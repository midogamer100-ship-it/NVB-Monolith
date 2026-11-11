"""Creating customer users, password-reset tokens and demo-mailbox messages."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import as_utc, utcnow
from app.models import ROLE_CUSTOMER, Account, Customer, OutboxMessage, PasswordResetToken, User
from app.security import sha256_hex

RESET_SUBJECT = "Reset your R&D bank password"
SETUP_SUBJECT = "Set up your R&D bank sign-in"


class UsernameTaken(Exception):
    pass


@dataclass
class NewCustomer:
    user: User
    customer: Customer
    account: Account


def _new_account_number(db: Session) -> str:
    while True:
        number = "1007" + "".join(str(secrets.randbelow(10)) for _ in range(12))
        if db.scalar(select(Account.id).where(Account.account_number == number)) is None:
            return number


def create_customer_user(db: Session, *, username: str, password_hash: str, full_name: str, email: str,
                         phone: str, city: str) -> NewCustomer:
    """Create user + customer + one 0.00 current account in the caller's transaction."""
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise UsernameTaken(username)
    now = utcnow()
    user = User(username=username, password_hash=password_hash, role=ROLE_CUSTOMER, is_active=True,
                is_load_test=False, created_at=now)
    db.add(user)
    db.flush()
    customer = Customer(user_id=user.id, customer_number="TMP" + secrets.token_hex(6), full_name=full_name,
                        preferred_name=None, email=email, phone=phone, city=city, segment="Retail",
                        created_at=now, updated_at=now)
    db.add(customer)
    db.flush()
    customer.customer_number = f"C{customer.id:06d}"
    account = Account(customer_id=customer.id, account_number=_new_account_number(db), account_type="current",
                      nickname="Everyday Current", currency="EGP", balance_minor=0, status="active",
                      opened_at=now)
    db.add(account)
    db.flush()
    return NewCustomer(user, customer, account)


def mailbox_address(user: User) -> str:
    if user.customer is not None:
        return user.customer.email
    return f"{user.username}@nvb-demo.invalid"


def issue_token(db: Session, user: User, kind: str, ttl: timedelta) -> str:
    """Invalidate the user's unused tokens, create a new one and put the email in the demo mailbox."""
    now = utcnow()
    db.execute(update(PasswordResetToken)
               .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
               .values(used_at=now))
    raw = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(user_id=user.id, token_hash=sha256_hex(raw), kind=kind, created_at=now,
                              expires_at=now + ttl))
    link = f"/reset-password?token={raw}"
    if kind == "account_setup":
        subject = SETUP_SUBJECT
        body = (f"Hello {user.username},\n\nAn account has been created for you at R&D bank (demo).\n"
                f"Choose your password here (valid for {int(ttl.total_seconds() // 3600)} hours):\n{link}\n\n"
                "Synthetic demo message - no real email was sent.")
    else:
        subject = RESET_SUBJECT
        body = (f"Hello {user.username},\n\nWe received a request to reset your password.\n"
                f"Use this link within {int(ttl.total_seconds() // 60)} minutes:\n{link}\n\n"
                "If you did not ask for this, ignore this message.\nSynthetic demo message - no real email was sent.")
    db.add(OutboxMessage(user_id=user.id, username=user.username, to_address=mailbox_address(user), kind=kind,
                         subject=subject, body=body, created_at=now))
    return raw


def find_valid_token(db: Session, raw: str) -> PasswordResetToken | None:
    token = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256_hex(raw)))
    if token is None or token.used_at is not None or as_utc(token.expires_at) <= utcnow():
        return None
    if not token.user.is_active:
        return None
    return token
