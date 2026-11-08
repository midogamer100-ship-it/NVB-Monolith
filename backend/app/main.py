"""FastAPI application factory. One artifact: API + built React frontend."""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.api import accounts, auth, dashboard, demo, health, ops, profile, transactions, transfers
from app.config import Settings, get_settings
from app.db import build_engine, build_sessionmaker
from app.logging_config import configure_logging, request_id_var
from app.metrics import HTTP_DURATION, HTTP_ERRORS, HTTP_IN_FLIGHT, HTTP_REQUESTS, LocalStats, update_pool_metrics
from app.security import PasswordService
from app.services.workload import WorkloadLimits, WorkloadRunner

log = logging.getLogger("nvb.http")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
DEFAULT_STATIC = Path(__file__).resolve().parent / "static"
NOT_LOGGED_PATHS = {"/health/live", "/health/ready", "/metrics"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path == "/{full_path:path}":
        return "spa"
    if path == "/api/{rest:path}":
        return "api_not_found"
    return path or "unmatched"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.resolved_instance_id)

    app = FastAPI(
        title="Nova Valley Bank (NVB) demo API",
        version=settings.app_version,
        description="Synthetic data only. Demonstration system - no real banking.",
        docs_url=None,  # no public interactive docs in the demo deployment
        redoc_url=None,
        openapi_url=None,
    )
    engine = build_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = build_sessionmaker(engine)
    app.state.passwords = PasswordService(settings)
    app.state.local_stats = LocalStats()
    app.state.workload = WorkloadRunner(
        WorkloadLimits(
            max_concurrency=settings.demo_workload_max_concurrency,
            queue_timeout_seconds=settings.demo_workload_queue_timeout_seconds,
            max_seconds=settings.demo_workload_max_seconds,
            simulations=settings.demo_workload_simulations,
        )
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Request-ID"],
        )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        HTTP_IN_FLIGHT.inc()
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            log.exception("unhandled error", extra={"path": request.url.path})
            response = JSONResponse({"detail": "Internal server error.", "request_id": rid}, status_code=500)
        finally:
            elapsed = time.perf_counter() - started
            HTTP_IN_FLIGHT.dec()
            route = _route_label(request)
            HTTP_REQUESTS.labels(request.method, route, f"{status_code // 100}xx").inc()
            HTTP_DURATION.labels(request.method, route).observe(elapsed)
            if status_code >= 500:
                HTTP_ERRORS.labels(route).inc()
            if request.url.path not in NOT_LOGGED_PATHS:
                app.state.local_stats.observe(elapsed, status_code >= 500)
                update_pool_metrics(engine)
                log.info(
                    "request",
                    extra={"method": request.method, "route": route, "status": status_code,
                           "duration_ms": round(elapsed * 1000, 1)},
                )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-NVB-Instance"] = settings.resolved_instance_id
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if settings.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for module in (health, auth, accounts, transactions, transfers, dashboard, profile, ops):
        app.include_router(module.router)
    if settings.demo_workload_enabled:
        app.include_router(demo.router)

    @app.get("/api/info", tags=["meta"])
    def info():
        """Public, non-sensitive metadata used by the login page footer."""
        return {"app": "Nova Valley Bank demo", "version": settings.app_version, "synthetic_data": True}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str):
        raise HTTPException(404, "Not found.")

    static_dir = Path(settings.static_dir) if settings.static_dir else DEFAULT_STATIC
    static_root = static_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "health/")) or full_path in ("api", "metrics"):
            raise HTTPException(404, "Not found.")
        index = static_root / "index.html"
        if not index.is_file():
            return PlainTextResponse(
                "NVB API is running, but the frontend has not been built. Run `npm run build` in frontend/.",
                status_code=503,
            )
        if full_path:
            candidate = (static_root / full_path).resolve()
            if candidate.is_file() and static_root in candidate.parents:
                cache = "public, max-age=31536000, immutable" if full_path.startswith("assets/") else "no-cache"
                return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    log.info("application configured", extra={"environment": settings.environment_label,
                                               "version": settings.app_version,
                                               "demo_workload": settings.demo_workload_enabled})
    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn: ``uvicorn --factory app.main:app_factory``."""
    return create_app()
