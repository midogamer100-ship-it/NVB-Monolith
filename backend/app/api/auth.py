"""Login, logout and current-user endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.db import as_utc, utcnow
from app.deps import AuthContext, get_auth, get_db, get_settings_dep
from app.metrics import LOGINS
from app.models import User
from app.security import (
    SESSION_COOKIE,
    clear_login_failures,
    create_session,
    destroy_session,
    is_login_throttled,
    record_login_failure,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Invalid username or password."
THROTTLED_ERROR = "Too many failed sign-in attempts. Please wait and try again."


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def user_payload(user: User) -> dict:
    customer = user.customer
    display = user.username
    if customer is not None:
        display = customer.preferred_name or customer.full_name.split(" ")[0]
    elif user.role == "admin":
        display = "Operations Admin"
    elif user.role == "demo":
        display = "Demo Operator"
    return {
        "username": user.username,
        "role": user.role,
        "display_name": display,
        "full_name": customer.full_name if customer else None,
        "customer_number": customer.customer_number if customer else None,
    }


def session_payload(auth_user: User, csrf_token: str, expires_at, settings: Settings) -> dict:
    return {
        "user": user_payload(auth_user),
        "csrf_token": csrf_token,
        "session_expires_at": as_utc(expires_at).isoformat(),
        "idle_timeout_minutes": settings.session_idle_timeout_minutes,
        "features": {"demo_workload": settings.demo_workload_enabled},
    }


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    username = body.username.strip().lower()
    ip = audit.client_ip(request)
    passwords = request.app.state.passwords

    if is_login_throttled(db, username, ip, settings):
        LOGINS.labels(outcome="throttled").inc()
        audit.record(db, "auth.login", "throttled", request=request, details={"reason": "rate_limited"})
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, THROTTLED_ERROR)

    user = db.scalar(select(User).where(User.username == username))
    valid = passwords.verify(user.password_hash if user else None, body.password)
    if not valid or user is None or not user.is_active:
        record_login_failure(db, username, ip)
        LOGINS.labels(outcome="failure").inc()
        audit.record(
            db,
            "auth.login",
            "failure",
            request=request,
            actor_user_id=user.id if user else None,
            actor_username=user.username if user else None,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    token, record = create_session(db, user, settings)
    user.last_login_at = utcnow()
    clear_login_failures(db, username)
    audit.record(db, "auth.login", "success", request=request, actor_user_id=user.id, actor_username=user.username)
    db.commit()
    LOGINS.labels(outcome="success").inc()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_absolute_timeout_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return session_payload(user, record.csrf_token, record.expires_at, settings)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    audit.record(db, "auth.logout", "success", request=request, actor_user_id=auth.user.id, actor_username=auth.user.username)
    db.commit()
    destroy_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    return {"status": "signed_out"}


@router.get("/me")
def me(auth: AuthContext = Depends(get_auth), settings: Settings = Depends(get_settings_dep)):
    return session_payload(auth.user, auth.session.csrf_token, auth.session.expires_at, settings)
