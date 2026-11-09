"""Admin-only operations page API. Shows only measured or configured values."""

from __future__ import annotations

import secrets
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.db import as_utc, utcnow
from app.deps import AuthContext, get_db, get_settings_dep, require_admin
from app.api.auth import new_customer_payload
from app.models import AuditEvent, OutboxMessage, User
from app.security import clear_login_failures
from app.services.monitoring import cluster_metrics
from app.services.onboarding import UsernameTaken, create_customer_user, issue_token
from app.validation import NewCustomerFields

router = APIRouter(prefix="/api/ops", tags=["operations"])


def db_check(request: Request) -> dict:
    engine = request.app.state.engine
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "connected", "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "backend": engine.url.get_backend_name(), "host": engine.url.host or "local"}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the ops page
        return {"status": "unavailable", "error": type(exc).__name__}


def pool_info(request: Request) -> dict:
    pool = request.app.state.engine.pool
    try:
        return {"size": pool.size(), "checked_out": pool.checkedout(), "overflow": max(pool.overflow(), 0)}
    except AttributeError:
        return {"status": "not_applicable"}


@router.get("/status")
def ops_status(
    request: Request,
    auth: AuthContext = Depends(require_admin),
    settings: Settings = Depends(get_settings_dep),
):
    return {
        "environment_label": settings.environment_label,
        "app_version": settings.app_version,
        "instance_id": settings.resolved_instance_id,
        "database": db_check(request),
        "db_pool": pool_info(request),
        "this_instance": request.app.state.local_stats.snapshot(),
        "cluster": cluster_metrics(settings),
        "demo_workload_enabled": settings.demo_workload_enabled,
        "server_time": utcnow().isoformat(),
    }


@router.get("/audit")
def audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = Query(default=None, max_length=40),
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    return {
        "items": [
            {
                "id": e.id, "event_type": e.event_type, "outcome": e.outcome, "actor": e.actor_username,
                "source_ip": e.source_ip, "request_id": e.request_id, "details": e.details,
                "created_at": as_utc(e.created_at).isoformat(),
            }
            for e in db.scalars(stmt).all()
        ]
    }


@router.post("/users/{username}/unlock")
def unlock_user(
    username: str,
    request: Request,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Clear the failed-login counter for a username (administrative change, audited)."""
    username = username.strip().lower()
    if not 1 <= len(username) <= 64:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid username.")
    exists = db.scalar(select(User.id).where(User.username == username)) is not None
    cleared = clear_login_failures(db, username) if exists else 0
    audit.record(db, "admin.unlock_user", "success" if exists else "not_found", request=request,
                 actor_user_id=auth.user.id, actor_username=auth.user.username,
                 details={"target": username if exists else None, "cleared": cleared})
    db.commit()
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return {"username": username, "cleared_failures": cleared}


# --- Admin-created users and the demo mailbox ---------------------------------------


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: NewCustomerFields,
    request: Request,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    """Create a customer user without a password; a set-password link goes to the demo mailbox."""
    unusable = request.app.state.passwords.hash(secrets.token_urlsafe(32))
    try:
        created = create_customer_user(db, username=body.username, password_hash=unusable,
                                       full_name=body.full_name, email=body.email, phone=body.phone, city=body.city)
    except UsernameTaken:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "username_taken", "message": "That username is not available."}) from None
    db.refresh(created.user)
    issue_token(db, created.user, "account_setup", timedelta(hours=settings.account_setup_ttl_hours))
    audit.record(db, "admin.create_user", "success", request=request, actor_user_id=auth.user.id,
                 actor_username=auth.user.username,
                 details={"target": created.user.username, "customer_number": created.customer.customer_number})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "username_taken", "message": "That username is not available."}) from None
    return new_customer_payload(created, "User created. A set-password link was sent to the demo mailbox.")


@router.get("/mailbox")
def mailbox(
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Demo-only stand-in for an email provider. Admin-readable only."""
    rows = db.scalars(select(OutboxMessage).order_by(OutboxMessage.id.desc()).limit(limit)).all()
    return {
        "demo_only": True,
        "items": [{"id": m.id, "to": m.to_address, "username": m.username, "subject": m.subject, "body": m.body,
                   "kind": m.kind, "created_at": as_utc(m.created_at).isoformat()} for m in rows],
    }
