"""Audit trail for authentication, transfers and administrative actions.

Audit details must never contain passwords, tokens or full account numbers.
"""

from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from app.logging_config import request_id_var
from app.models import AuditEvent

log = logging.getLogger("nvb.audit")


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host[:45]


def record(
    db: Session,
    event_type: str,
    outcome: str,
    *,
    request: Request | None = None,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    details: dict | None = None,
) -> None:
    """Add an audit event to the current DB transaction (caller commits)."""
    event = AuditEvent(
        event_type=event_type,
        outcome=outcome,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        source_ip=client_ip(request),
        request_id=request_id_var.get(),
        details=details or {},
    )
    db.add(event)
    log.info(
        "audit",
        extra={"event_type": event_type, "outcome": outcome, "actor": actor_username, "details": details or {}},
    )
