"""Password hashing, database-backed sessions, CSRF and login-abuse protection."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import as_utc, utcnow
from app.models import LoginAttempt, User, UserSession

SESSION_COOKIE = "nvb_session"
CSRF_COOKIE = "nvb_csrf"
CSRF_HEADER = "X-CSRF-Token"
LAST_SEEN_UPDATE_INTERVAL = timedelta(seconds=60)


class PasswordService:
    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
        )
        # Used to equalise timing when the username does not exist.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash or self._dummy_hash, password) and password_hash is not None
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# --- Sessions --------------------------------------------------------------------


def create_session(db: Session, user: User, settings: Settings) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    record = UserSession(
        token_hash=_sha256(token),
        csrf_token=secrets.token_urlsafe(32),
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.session_idle_timeout_minutes),
        absolute_expires_at=now + timedelta(minutes=settings.session_absolute_timeout_minutes),
    )
    db.add(record)
    # Opportunistic cleanup keeps the table small without a background job.
    db.execute(delete(UserSession).where(UserSession.absolute_expires_at < now - timedelta(days=1)))
    return token, record


def load_session(db: Session, token: str | None, settings: Settings) -> UserSession | None:
    """Return the live session for a raw cookie token, sliding the idle expiry."""
    if not token or len(token) > 128:
        return None
    record = db.scalar(select(UserSession).where(UserSession.token_hash == _sha256(token)))
    if record is None:
        return None
    now = utcnow()
    if as_utc(record.expires_at) <= now or as_utc(record.absolute_expires_at) <= now:
        db.delete(record)
        db.commit()
        return None
    if not record.user.is_active:
        return None
    if now - as_utc(record.last_seen_at) >= LAST_SEEN_UPDATE_INTERVAL:
        record.last_seen_at = now
        record.expires_at = min(
            now + timedelta(minutes=settings.session_idle_timeout_minutes),
            as_utc(record.absolute_expires_at),
        )
        db.commit()
    return record


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _sha256(token)))
        db.commit()


def csrf_valid(session: UserSession, header_value: str | None) -> bool:
    return bool(header_value) and hmac.compare_digest(session.csrf_token, header_value)


# --- Login abuse protection (shared across replicas via the database) ---------------


def _attempt_keys(username: str, ip: str | None) -> list[tuple[str, str]]:
    keys = [("user", _sha256("u:" + username.strip().lower()))]
    if ip:
        keys.append(("ip", _sha256("i:" + ip)))
    return keys


def is_login_throttled(db: Session, username: str, ip: str | None, settings: Settings) -> bool:
    since = utcnow() - timedelta(minutes=settings.login_window_minutes)
    limits = {"user": settings.login_max_failures_per_user, "ip": settings.login_max_failures_per_ip}
    for key_type, key_hash in _attempt_keys(username, ip):
        count = db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.key_type == key_type,
                LoginAttempt.key_hash == key_hash,
                LoginAttempt.attempted_at >= since,
            )
        )
        if (count or 0) >= limits[key_type]:
            return True
    return False


def record_login_failure(db: Session, username: str, ip: str | None) -> None:
    now = utcnow()
    for key_type, key_hash in _attempt_keys(username, ip):
        db.add(LoginAttempt(key_type=key_type, key_hash=key_hash, attempted_at=now))


def clear_login_failures(db: Session, username: str) -> int:
    key_type, key_hash = _attempt_keys(username, None)[0]
    result = db.execute(
        delete(LoginAttempt).where(LoginAttempt.key_type == key_type, LoginAttempt.key_hash == key_hash)
    )
    return result.rowcount or 0
