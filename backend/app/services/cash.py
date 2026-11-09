"""Simulated branch cash operations: deposit and withdrawal.

Same guarantees as transfers (see services/transfers.py):
* integer minor units only;
* the account row is locked (SELECT ... FOR UPDATE) before the balance is read;
* the withdrawal debit is a conditional UPDATE (balance >= amount) backed by the
  CHECK (balance_minor >= 0) constraint;
* operation record + ledger entry + balance change commit together or not at all;
* UNIQUE (user_id, idempotency_key): a retry with the same payload replays the original
  result, a different payload is rejected with 409, concurrent duplicates collide.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import utcnow
from app.metrics import CASH_OPERATIONS
from app.models import Account, CashOperation, LedgerEntry

log = logging.getLogger("nvb.cash")
COUNTERPARTY = "NVB Branch (demo)"
KINDS = {
    "deposit": {"direction": "credit", "txn_type": "deposit", "category": "Cash deposit", "default": "Cash deposit"},
    "withdrawal": {"direction": "debit", "txn_type": "withdrawal", "category": "Cash", "default": "Cash withdrawal"},
}


class CashError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class CashResult:
    operation: CashOperation
    replayed: bool


def _fingerprint(kind: str, account_id: int, amount_minor: int, description: str) -> str:
    raw = json.dumps({"k": kind, "a": account_id, "m": amount_minor, "d": description}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _existing(db: Session, user_id: int, key: str) -> CashOperation | None:
    return db.scalar(select(CashOperation).where(CashOperation.user_id == user_id,
                                                 CashOperation.idempotency_key == key))


def _replay(op: CashOperation, fp: str) -> CashResult:
    if op.request_fingerprint != fp:
        raise CashError(409, "idempotency_conflict",
                        "This idempotency key was already used for a different request.")
    CASH_OPERATIONS.labels(kind=op.kind, outcome="replayed").inc()
    return CashResult(op, replayed=True)


def execute_cash_operation(db: Session, *, user_id: int, customer_id: int, account_id: int, kind: str,
                           amount_minor: int, description: str, idempotency_key: str, max_minor: int) -> CashResult:
    if kind not in KINDS:
        raise ValueError("unknown kind")
    description = description or KINDS[kind]["default"]
    fp = _fingerprint(kind, account_id, amount_minor, description)

    existing = _existing(db, user_id, idempotency_key)
    if existing is not None:
        return _replay(existing, fp)

    try:
        account = db.scalar(select(Account).where(Account.id == account_id, Account.customer_id == customer_id))
        if account is None:
            raise CashError(404, "account_not_found", "Account not found.")
        if account.status != "active":
            raise CashError(422, "account_inactive", "This account cannot be used for cash operations.")
        if amount_minor <= 0:
            raise CashError(422, "invalid_amount", "Amount must be greater than zero.")
        if amount_minor > max_minor:
            raise CashError(422, "limit_exceeded", "Amount exceeds the per-operation limit.")
    except CashError:
        CASH_OPERATIONS.labels(kind=kind, outcome="rejected").inc()
        db.rollback()
        raise

    try:
        result = _execute_locked(db, user_id, account_id, kind, amount_minor, description, idempotency_key, fp)
    except IntegrityError:
        db.rollback()
        existing = _existing(db, user_id, idempotency_key)
        if existing is None:
            CASH_OPERATIONS.labels(kind=kind, outcome="error").inc()
            raise
        return _replay(existing, fp)
    except Exception:
        db.rollback()
        CASH_OPERATIONS.labels(kind=kind, outcome="error").inc()
        raise
    CASH_OPERATIONS.labels(kind=kind, outcome=result.operation.status).inc()
    return result


def _execute_locked(db: Session, user_id: int, account_id: int, kind: str, amount: int, description: str,
                    key: str, fp: str) -> CashResult:
    db.rollback()  # start the locking transaction fresh
    now = utcnow()
    account = db.scalar(select(Account).where(Account.id == account_id).with_for_update())
    db.refresh(account)
    op = CashOperation(reference="CSH" + now.strftime("%y%m%d") + secrets.token_hex(5).upper(),
                       idempotency_key=key, request_fingerprint=fp, user_id=user_id, account_id=account_id,
                       kind=kind, amount_minor=amount, description=description, created_at=now)

    if kind == "withdrawal" and account.balance_minor < amount:
        op.status, op.failure_reason = "failed", "insufficient_funds"
        db.add(op)
        db.flush()  # IntegrityError on a concurrent duplicate key
        db.commit()
        return CashResult(op, replayed=False)

    op.status, op.completed_at = "completed", now
    db.add(op)
    db.flush()
    if kind == "deposit":
        changed = db.execute(update(Account).where(Account.id == account_id)
                             .values(balance_minor=Account.balance_minor + amount))
    else:
        changed = db.execute(update(Account).where(Account.id == account_id, Account.balance_minor >= amount)
                             .values(balance_minor=Account.balance_minor - amount))
    if changed.rowcount != 1:
        raise RuntimeError("Cash operation balance update did not apply")
    balance = db.scalar(select(Account.balance_minor).where(Account.id == account_id))
    spec = KINDS[kind]
    db.add(LedgerEntry(account_id=account_id, transfer_id=None, reference=op.reference, direction=spec["direction"],
                       txn_type=spec["txn_type"], category=spec["category"], amount_minor=amount,
                       balance_after_minor=balance, description=description, counterparty=COUNTERPARTY,
                       posted_at=now))
    db.commit()
    log.info("cash operation completed", extra={"kind": kind, "cash_ref": op.reference, "amount_minor": amount})
    return CashResult(op, replayed=False)
