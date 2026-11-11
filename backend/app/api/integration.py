"""Extension integration API (``/internal/v1``). Registered only when
``NVB_INTEGRATION_ENABLED=true``.

Security model
--------------
* Every request needs ``Authorization: Bearer <client token>``. The core stores
  only SHA-256 digests in a JSON file mounted from a Secret
  (``NVB_INTEGRATION_CLIENTS_FILE``); the file is re-read when it changes, so a
  credential rotation does not need a core restart. Missing/invalid configuration
  fails closed (401 for every request).
* Each client has explicit scopes; each endpoint requires one of them.
* Network placement is NOT the control: these checks run on every request.
* Customer routes, ``require_customer`` and ``owned_account`` are untouched. This
  router never returns full account numbers and never writes financial data.

File format::

    {"clients": [{"client_id": "nvb-core-adapter",
                  "token_sha256": ["<hex digest>", "<next digest during rotation>"],
                  "scopes": ["identity:introspect", "accounts:read", "statements:extract"]}]}
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.db import as_utc, utcnow
from app.models import ROLE_CUSTOMER
from app.security import csrf_valid, load_session
from app.services import integration_exports as ix

log = logging.getLogger("nvb.integration")
router = APIRouter(prefix="/internal/v1", tags=["integration"])

SCOPES = {
    "identity:introspect",
    "accounts:read",
    "statements:extract",
    "summaries:read",
    "accounts:discover",
}
MIN_TOKEN_LENGTH = 32
RELOAD_CHECK_SECONDS = 15

INTEGRATION_REQUESTS = Counter(
    "nvb_integration_requests_total", "Integration API requests", ["endpoint", "outcome"]
)


# --- Client registry ------------------------------------------------------------------


@dataclass
class Client:
    client_id: str
    digests: list[str]
    scopes: set[str]


@dataclass
class ClientRegistry:
    path: str | None
    clients: list[Client] = field(default_factory=list)
    _mtime: float | None = None
    _checked: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _load(self) -> None:
        if not self.path:
            self.clients = []
            return
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            log.error("integration clients file not readable; failing closed")
            self.clients, self._mtime = [], None
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
            clients = []
            for item in raw.get("clients", []):
                scopes = set(item.get("scopes", []))
                unknown = scopes - SCOPES
                digests = [d.lower() for d in item.get("token_sha256", [])]
                if unknown or not digests or not all(len(d) == 64 for d in digests):
                    raise ValueError(f"invalid client entry {item.get('client_id')!r}")
                clients.append(Client(str(item["client_id"]), digests, scopes))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.error("integration clients file invalid; failing closed", extra={"error": str(exc)})
            self.clients, self._mtime = [], mtime
            return
        self.clients, self._mtime = clients, mtime
        log.info("integration clients loaded", extra={"clients": [c.client_id for c in clients]})

    def authenticate(self, token: str | None) -> Client | None:
        now = time.monotonic()
        with self._lock:
            if now - self._checked >= RELOAD_CHECK_SECONDS or self._mtime is None:
                self._checked = now
                self._load()
            clients = list(self.clients)
        if not token or len(token) < MIN_TOKEN_LENGTH or len(token) > 512:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        match = None
        for c in clients:
            for d in c.digests:
                if hmac.compare_digest(d, digest):
                    match = c
        return match


@dataclass
class IntegrationState:
    registry: ClientRegistry
    exports: threading.BoundedSemaphore
    queue_timeout: float


def configure(app: FastAPI, settings: Settings) -> None:
    app.state.integration = IntegrationState(
        registry=ClientRegistry(settings.integration_clients_file),
        exports=threading.BoundedSemaphore(settings.integration_max_concurrent_exports),
        queue_timeout=settings.integration_export_queue_timeout_seconds,
    )
    install_error_handlers(app)
    if not settings.integration_clients_file:
        log.error("integration enabled without NVB_INTEGRATION_CLIENTS_FILE; all requests will be rejected")


# --- Dependencies ---------------------------------------------------------------------


class IntegrationHTTPError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None) -> None:
        self.status_code, self.code, self.message, self.headers = status_code, code, message, headers or {}


def _error(status_code: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code,
                        headers=headers or {})


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def require_scope(*accepted: str):
    def dep(request: Request) -> Client:
        state: IntegrationState = request.app.state.integration
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else None
        client = state.registry.authenticate(token)
        if client is None:
            raise IntegrationHTTPError(401, "invalid_client", "Client authentication failed.",
                                       {"WWW-Authenticate": "Bearer"})
        if not client.scopes.intersection(accepted):
            raise IntegrationHTTPError(403, "insufficient_scope", "Client is not permitted to call this endpoint.")
        request.state.integration_client = client.client_id
        return client

    return dep


class _ExportSlot:
    """Bounded concurrency for expensive extraction queries (per core process)."""

    def __init__(self, state: IntegrationState) -> None:
        self.state = state

    def __enter__(self):
        if not self.state.exports.acquire(timeout=self.state.queue_timeout):
            raise IntegrationHTTPError(429, "export_capacity", "Export capacity is busy; retry later.",
                                       {"Retry-After": "2"})
        return self

    def __exit__(self, *exc):
        self.state.exports.release()
        return False


def _settings(request: Request) -> Settings:
    return request.app.state.settings


# --- Endpoints ------------------------------------------------------------------------


class IntrospectRequest(BaseModel):
    session_token: str = Field(min_length=1, max_length=128)
    csrf_token: str | None = Field(default=None, max_length=128)
    include_accounts: bool = False


@router.post("/sessions/introspect")
def introspect(body: IntrospectRequest, request: Request, client: Client = Depends(require_scope("identity:introspect")),
               db: Session = Depends(get_db)):
    """RFC 7662-style introspection of a browser session token.

    Uses the same ``load_session`` as the customer API, so idle/absolute expiry,
    logout (row deleted), password reset (sessions deleted) and user suspension
    behave identically. Introspection counts as session activity (slides idle expiry)
    exactly like a direct API call would.
    """
    record = load_session(db, body.session_token, _settings(request))
    if record is None:
        INTEGRATION_REQUESTS.labels("introspect", "inactive").inc()
        return {"active": False}
    user = record.user
    customer = user.customer
    out = {
        "active": True,
        "subject": ix.subject_for(user),
        "username": user.username,
        "role": user.role,
        "display_name": (customer.preferred_name or customer.full_name.split(" ")[0]) if customer else user.username,
        "full_name": customer.full_name if customer else None,
        "customer_number": customer.customer_number if customer else None,
        "session_expires_at": as_utc(record.expires_at).isoformat(),
        "csrf_valid": csrf_valid(record, body.csrf_token) if body.csrf_token is not None else None,
    }
    if body.include_accounts:
        if "accounts:read" not in client.scopes:
            raise IntegrationHTTPError(403, "insufficient_scope", "include_accounts requires accounts:read.")
        out["accounts"] = ix.accounts_for_customer(db, customer) if (customer and user.role == ROLE_CUSTOMER) else []
    db.commit()
    INTEGRATION_REQUESTS.labels("introspect", "active").inc()
    return out


@router.get("/subjects/{subject}/accounts")
def subject_accounts(subject: str, request: Request, _c: Client = Depends(require_scope("accounts:read")),
                     db: Session = Depends(get_db)):
    _user, customer = ix.customer_for_subject(db, subject)
    INTEGRATION_REQUESTS.labels("subject_accounts", "ok").inc()
    return {"subject": subject, "accounts": ix.accounts_for_customer(db, customer)}


def _period(request: Request, start: datetime, end: datetime) -> ix.Period:
    s = _settings(request)
    return ix.validate_period(start, end, now=utcnow(), settle_seconds=s.integration_settle_seconds,
                              max_days=s.integration_max_period_days)


@router.get("/accounts/{account_id}/statement-manifest")
def statement_manifest(
    account_id: int,
    request: Request,
    subject: str = Query(min_length=1, max_length=64),
    period_start: datetime = Query(),
    period_end: datetime = Query(),
    client: Client = Depends(require_scope("statements:extract", "summaries:read")),
    db: Session = Depends(get_db),
):
    period = _period(request, period_start, period_end)
    with _ExportSlot(request.app.state.integration):
        ix.begin_snapshot(db)
        _user, customer = ix.customer_for_subject(db, subject)
        account = ix.owned_account(db, customer, account_id)
        manifest = ix.statement_manifest(db, customer, account, period, now=utcnow(),
                                         max_entries=_settings(request).integration_max_statement_entries)
        db.rollback()  # end the read-only snapshot before writing the audit row
    audit.record(db, "integration.statement_manifest", "success", request=request,
                 details={"client_id": client.client_id, "account_id": account_id,
                          "period_start": manifest["period_start"], "period_end": manifest["period_end"],
                          "entry_count": manifest["entry_count"]})
    db.commit()
    INTEGRATION_REQUESTS.labels("statement_manifest", "ok").inc()
    return manifest


@router.get("/accounts/{account_id}/statement-entries")
def statement_entries(
    account_id: int,
    request: Request,
    subject: str = Query(min_length=1, max_length=64),
    period_start: datetime = Query(),
    period_end: datetime = Query(),
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=500, ge=1),
    _c: Client = Depends(require_scope("statements:extract")),
    db: Session = Depends(get_db),
):
    period = _period(request, period_start, period_end)
    limit = min(limit, _settings(request).integration_max_page_size)
    with _ExportSlot(request.app.state.integration):
        ix.begin_snapshot(db)
        _user, customer = ix.customer_for_subject(db, subject)
        account = ix.owned_account(db, customer, account_id)
        page = ix.statement_entries(db, account, period, cursor=cursor, limit=limit)
        db.rollback()
    INTEGRATION_REQUESTS.labels("statement_entries", "ok").inc()
    return page


@router.get("/discovery/statement-accounts")
def discovery(
    request: Request,
    after_account_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1),
    include_load_test: bool = False,
    client: Client = Depends(require_scope("accounts:discover")),
    db: Session = Depends(get_db),
):
    limit = min(limit, _settings(request).integration_discovery_max_page_size)
    page = ix.discover_statement_accounts(db, after_account_id=after_account_id, limit=limit,
                                          include_load_test=include_load_test)
    db.rollback()
    audit.record(db, "integration.discovery", "success", request=request,
                 details={"client_id": client.client_id, "after_account_id": after_account_id,
                          "returned": len(page["items"])})
    db.commit()
    INTEGRATION_REQUESTS.labels("discovery", "ok").inc()
    return page


@router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def not_found(rest: str):
    raise IntegrationHTTPError(404, "not_found", "Not found.")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(IntegrationHTTPError)
    async def _h1(_request: Request, exc: IntegrationHTTPError):
        return _error(exc.status_code, exc.code, exc.message, exc.headers)

    @app.exception_handler(ix.IntegrationError)
    async def _h2(request: Request, exc: ix.IntegrationError):
        if exc.status_code >= 500:
            log.error("integration error", extra={"code": exc.code, "path": request.url.path})
        INTEGRATION_REQUESTS.labels("any", exc.code).inc()
        return _error(exc.status_code, exc.code, exc.message)
