"""Helpers for the extension integration API tests (test-only credentials)."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from sqlalchemy import select

from app.models import Account, Customer, User

ALL_SCOPES = ["identity:introspect", "accounts:read", "statements:extract", "summaries:read", "accounts:discover"]


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def write_clients(path: Path, clients: dict[str, tuple[list[str], list[str]]]) -> None:
    """clients: client_id -> (tokens, scopes)."""
    payload = {"clients": [{"client_id": cid, "token_sha256": [digest(t) for t in tokens], "scopes": scopes}
                           for cid, (tokens, scopes) in clients.items()]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def user_row(app, username: str) -> User:
    db = app.state.sessionmaker()
    user = db.scalar(select(User).where(User.username == username))
    db.close()
    return user


def first_account_id(app, username: str) -> int:
    db = app.state.sessionmaker()
    acct_id = db.scalar(select(Account.id).join(Customer).join(User).where(User.username == username)
                        .order_by(Account.id))
    db.close()
    return acct_id
