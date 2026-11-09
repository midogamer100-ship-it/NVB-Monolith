"""Login, logout and current-user endpoints."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.db import as_utc, utcnow
from app.deps import AuthContext, get_auth, get_db, get_settings_dep
from app.metrics import LOGINS
from app.models import User
from app.money import format_minor, mask_account_number
from app.security import (
    SESSION_COOKIE,
    attempt_count,
    clear_login_failures,
    create_session,
    delete_user_sessions,
    destroy_session,
    is_login_throttled,
    record_attempt,
    record_login_failure,
)
from app.services.onboarding import UsernameTaken, create_customer_user, find_valid_token, issue_token
from app.validation import ForgotPasswordRequest, RegisterRequest, ResetPasswordRequest, check_password

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


# --- Self sign-up, forgot password, reset password ----------------------------------

FORGOT_MESSAGE = "If that account exists, we've sent password reset instructions to its registered email."
RESET_WINDOW = timedelta(minutes=15)


def new_customer_payload(created, message: str) -> dict:
    acct = created.account
    return {
        "username": created.user.username,
        "customer_number": created.customer.customer_number,
        "account": {"masked_number": mask_account_number(acct.account_number), "type": acct.account_type,
                    "nickname": acct.nickname, "balance": format_minor(acct.balance_minor)},
        "message": message,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    if not settings.self_registration_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    ip = audit.client_ip(request) or "unknown"
    if attempt_count(db, "reg", ip, timedelta(hours=1)) >= settings.registration_max_per_ip_per_hour:
        audit.record(db, "auth.register", "throttled", request=request)
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many sign-up attempts. Please try again later.")
    record_attempt(db, "reg", ip)
    db.commit()
    passwords = request.app.state.passwords
    try:
        created = create_customer_user(
            db, username=body.username, password_hash=passwords.hash(body.password), full_name=body.full_name,
            email=body.email, phone=body.phone, city=body.city,
        )
    except UsernameTaken:
        db.rollback()
        audit.record(db, "auth.register", "duplicate", request=request)
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "username_taken", "message": "That username is not available."}) from None
    audit.record(db, "auth.register", "success", request=request, actor_user_id=created.user.id,
                 actor_username=created.user.username, details={"customer_number": created.customer.customer_number})
    try:
        db.commit()
    except IntegrityError:  # concurrent registration of the same username hit the unique constraint
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "username_taken", "message": "That username is not available."}) from None
    return new_customer_payload(created, "Your account is ready. Please sign in.")


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    username = body.username.strip().lower()
    ip = audit.client_ip(request) or "unknown"
    throttled = (attempt_count(db, "pwr_u", username, RESET_WINDOW) >= 3
                 or attempt_count(db, "pwr_ip", ip, RESET_WINDOW) >= 20)
    record_attempt(db, "pwr_u", username)
    record_attempt(db, "pwr_ip", ip)
    if throttled:
        outcome = "throttled"
    else:
        user = db.scalar(select(User).where(User.username == username))
        if user is not None and user.is_active:
            issue_token(db, user, "password_reset", timedelta(minutes=settings.password_reset_ttl_minutes))
            outcome = "issued"
        else:
            outcome = "ignored"
    # The username is only recorded when the account exists (no enumeration via audit log).
    audit.record(db, "auth.password_reset_requested", outcome, request=request,
                 actor_username=username if outcome == "issued" else None)
    db.commit()
    return {"message": FORGOT_MESSAGE}


@router.post("/password/reset")
def reset_password(body: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    token = find_valid_token(db, body.token)
    if token is None:
        audit.record(db, "auth.password_reset", "failure", request=request, details={"reason": "invalid_token"})
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {
            "code": "invalid_or_expired_token",
            "message": "This link is invalid or has expired. Request a new one."})
    user = token.user
    try:
        check_password(body.new_password, user.username)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    user.password_hash = request.app.state.passwords.hash(body.new_password)
    token.used_at = utcnow()
    ended = delete_user_sessions(db, user.id)
    clear_login_failures(db, user.username)
    audit.record(db, "auth.password_reset", "success", request=request, actor_user_id=user.id,
                 actor_username=user.username, details={"kind": token.kind, "sessions_ended": ended})
    db.commit()
    return {"message": "Your password has been updated. Please sign in."}
