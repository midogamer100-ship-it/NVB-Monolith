"""Health probes and the Prometheus metrics endpoint."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.metrics import render_metrics

router = APIRouter(tags=["health"])


@router.get("/health/live", include_in_schema=False)
def live():
    """Process liveness only. Deliberately does NOT touch the database, so a
    database outage does not cause OpenShift to restart healthy pods."""
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
def ready(request: Request):
    """Ready to serve: the DB answers a trivial query within a short timeout."""
    engine = request.app.state.engine
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("SET LOCAL statement_timeout = 2000"))
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"status": "unavailable", "checks": {"database": "unavailable"}, "error": type(exc).__name__},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return {"status": "ok", "checks": {"database": "ok"}}


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    settings = request.app.state.settings
    if settings.metrics_token:
        supplied = request.headers.get("authorization", "")
        expected = "Bearer " + settings.metrics_token
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return Response("Unauthorized\n", status_code=401, media_type="text/plain")
    elif not settings.metrics_allow_unauthenticated:
        return Response("Metrics require NVB_METRICS_TOKEN or NVB_METRICS_ALLOW_UNAUTHENTICATED=true\n",
                        status_code=403, media_type="text/plain")
    body, content_type = render_metrics()
    return Response(body, media_type=content_type)
