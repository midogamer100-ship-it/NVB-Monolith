"""FastAPI dependencies: DB session, authentication, roles and CSRF."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_DEMO, Customer, User, UserSession
from app.security import CSRF_HEADER, SESSION_COOKIE, csrf_valid, load_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


@dataclass
class AuthContext:
    user: User
    session: UserSession

    @property
    def customer(self) -> Customer | None:
        return self.user.customer


def get_auth(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> AuthContext:
    record = load_session(db, request.cookies.get(SESSION_COOKIE), settings)
    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    if request.method not in SAFE_METHODS and not csrf_valid(record, request.headers.get(CSRF_HEADER)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token.")
    request.state.user_id = record.user_id
    user = record.user
    _ = user.customer  # load before ending the read transaction
    # End the authentication read transaction so no locks/snapshots are held
    # while the endpoint runs (matters for SQLite's database-level locking).
    db.commit()
    return AuthContext(user=user, session=record)


def require_customer(auth: AuthContext = Depends(get_auth)) -> AuthContext:
    if auth.user.role != ROLE_CUSTOMER or auth.customer is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer access only.")
    return auth


def require_admin(auth: AuthContext = Depends(get_auth)) -> AuthContext:
    if auth.user.role != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access only.")
    return auth


def require_demo(auth: AuthContext = Depends(get_auth)) -> AuthContext:
    if auth.user.role != ROLE_DEMO:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Demo operator access only.")
    return auth
