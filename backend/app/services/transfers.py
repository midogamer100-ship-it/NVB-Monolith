"""Internal transfer execution.

Correctness guarantees
----------------------
* Amounts are integer minor units; no floating point.
* The debit, the credit, both ledger entries and the transfer record are
  written in ONE database transaction - all or nothing.
* Both account rows are locked with SELECT ... FOR UPDATE in ascending id
  order (deadlock-free ordering) before balances are read.
* The debit is a conditional UPDATE (``balance >= amount``) and the table has a
  CHECK (balance >= 0) constraint, so a negative balance is impossible even if
  application logic were bypassed.
* (initiated_by_user_id, idempotency_key) is UNIQUE. A retry with the same key
  and the same payload returns the original result; a different payload with
  the same key is rejected. Concurrent duplicates race on the unique index and
  only one can commit.
* A customer can only debit an account they own.
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
from app.metrics import TRANSFERS
from app.models import Account, Beneficiary, Customer, LedgerEntry, Transfer

log = logging.getLogger("nvb.transfers")


class TransferError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class TransferRequest:
    source_account_id: int
    amount_minor: int
    description: str
    beneficiary_id: int | None = None
    destination_account_id: int | None = None  # only the customer's own accounts


@dataclass
class TransferResult:
    transfer: Transfer
    replayed: bool


def new_reference() -> str:
    return "NVB" + utcnow().strftime("%y%m%d") + secrets.token_hex(5).upper()


def fingerprint(req: TransferRequest) -> str:
    payload = json.dumps(
        {
            "s": req.source_account_id,
            "b": req.beneficiary_id,
            "d": req.destination_account_id,
            "a": req.amount_minor,
            "m": req.description,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def resolve_destination(db: Session, customer: Customer, req: TransferRequest) -> Account:
    if (req.beneficiary_id is None) == (req.destination_account_id is None):
        raise TransferError(422, "invalid_destination", "Choose exactly one beneficiary or one of your own accounts.")
    if req.beneficiary_id is not None:
        ben = db.scalar(
            select(Beneficiary).where(Beneficiary.id == req.beneficiary_id, Beneficiary.customer_id == customer.id)
        )
        if ben is None:
            raise TransferError(404, "beneficiary_not_found", "Beneficiary not found.")
        dest = ben.account
    else:
        dest = db.scalar(
            select(Account).where(Account.id == req.destination_account_id, Account.customer_id == customer.id)
        )
        if dest is None:
            raise TransferError(404, "account_not_found", "Destination account not found.")
    if dest.status != "active":
        raise TransferError(422, "destination_inactive", "The destination account cannot receive transfers.")
    return dest


def validate(db: Session, customer: Customer, req: TransferRequest, max_minor: int) -> tuple[Account, Account]:
    """Read-only validation used by both preview and execution."""
    if req.amount_minor <= 0:
        raise TransferError(422, "invalid_amount", "Amount must be greater than zero.")
    if req.amount_minor > max_minor:
        raise TransferError(422, "limit_exceeded", "Amount exceeds the per-transfer limit.")
    source = db.scalar(
        select(Account).where(Account.id == req.source_account_id, Account.customer_id == customer.id)
    )
    if source is None:
        # Same response whether the account does not exist or belongs to someone else.
        raise TransferError(404, "account_not_found", "Source account not found.")
    if source.status != "active":
        raise TransferError(422, "source_inactive", "The source account cannot send transfers.")
    dest = resolve_destination(db, customer, req)
    if dest.id == source.id:
        raise TransferError(422, "same_account", "Source and destination must be different accounts.")
    return source, dest


def _find_existing(db: Session, user_id: int, key: str) -> Transfer | None:
    return db.scalar(
        select(Transfer).where(Transfer.initiated_by_user_id == user_id, Transfer.idempotency_key == key)
    )


def _replay(existing: Transfer, fp: str) -> TransferResult:
    if existing.request_fingerprint != fp:
        raise TransferError(
            409, "idempotency_conflict", "This idempotency key was already used for a different transfer request."
        )
    TRANSFERS.labels(outcome="replayed").inc()
    return TransferResult(existing, replayed=True)


def execute_transfer(
    db: Session,
    *,
    user_id: int,
    customer: Customer,
    req: TransferRequest,
    idempotency_key: str,
    max_minor: int,
) -> TransferResult:
    fp = fingerprint(req)

    existing = _find_existing(db, user_id, idempotency_key)
    if existing is not None:
        return _replay(existing, fp)

    try:
        source, dest = validate(db, customer, req, max_minor)
    except TransferError:
        TRANSFERS.labels(outcome="rejected").inc()
        db.rollback()
        raise

    try:
        result = _execute_locked(db, user_id, req, idempotency_key, fp, source.id, dest.id)
    except IntegrityError:
        # A concurrent request with the same idempotency key committed first.
        db.rollback()
        existing = _find_existing(db, user_id, idempotency_key)
        if existing is None:
            TRANSFERS.labels(outcome="error").inc()
            raise
        return _replay(existing, fp)
    except Exception:
        db.rollback()
        TRANSFERS.labels(outcome="error").inc()
        raise
    TRANSFERS.labels(outcome=result.transfer.status).inc()
    return result


def _post_credit(db: Session, dest_id: int, amount: int) -> int:
    """Credit an account and return its new balance (separate for fault-injection tests)."""
    db.execute(update(Account).where(Account.id == dest_id).values(balance_minor=Account.balance_minor + amount))
    return db.scalar(select(Account.balance_minor).where(Account.id == dest_id))


def _execute_locked(
    db: Session, user_id: int, req: TransferRequest, key: str, fp: str, source_id: int, dest_id: int
) -> TransferResult:
    # Discard anything read during validation; start the locking transaction fresh.
    db.rollback()
    now = utcnow()

    # Lock both rows in a deterministic order to avoid deadlocks between
    # transfers that touch the same pair of accounts in opposite directions.
    locked = {
        a.id: a
        for a in db.scalars(
            select(Account)
            .where(Account.id.in_(sorted({source_id, dest_id})))
            .order_by(Account.id)
            .with_for_update()
        ).all()
    }
    source, dest = locked[source_id], locked[dest_id]
    db.refresh(source)
    db.refresh(dest)

    transfer = Transfer(
        reference=new_reference(),
        idempotency_key=key,
        request_fingerprint=fp,
        initiated_by_user_id=user_id,
        source_account_id=source_id,
        destination_account_id=dest_id,
        amount_minor=req.amount_minor,
        description=req.description,
        created_at=now,
    )

    if source.balance_minor < req.amount_minor:
        transfer.status = "failed"
        transfer.failure_reason = "insufficient_funds"
        db.add(transfer)
        db.flush()  # raises IntegrityError on a concurrent duplicate key
        db.commit()
        return TransferResult(transfer, replayed=False)

    transfer.status = "completed"
    transfer.completed_at = now
    db.add(transfer)
    db.flush()

    debited = db.execute(
        update(Account)
        .where(Account.id == source_id, Account.balance_minor >= req.amount_minor)
        .values(balance_minor=Account.balance_minor - req.amount_minor)
    )
    if debited.rowcount != 1:
        # Should be unreachable while the row lock is held; fail closed.
        raise RuntimeError("Conditional debit did not apply")
    source_balance = db.scalar(select(Account.balance_minor).where(Account.id == source_id))
    dest_balance = _post_credit(db, dest_id, req.amount_minor)

    src_name = source.customer.full_name
    dst_name = dest.customer.full_name
    memo = req.description or "Internal transfer"
    db.add_all(
        [
            LedgerEntry(
                account_id=source_id, transfer_id=transfer.id, reference=transfer.reference, direction="debit",
                txn_type="transfer_out", category="Transfers", amount_minor=req.amount_minor,
                balance_after_minor=source_balance, description=memo, counterparty=dst_name, posted_at=now,
            ),
            LedgerEntry(
                account_id=dest_id, transfer_id=transfer.id, reference=transfer.reference, direction="credit",
                txn_type="transfer_in", category="Transfers", amount_minor=req.amount_minor,
                balance_after_minor=dest_balance, description=memo, counterparty=src_name, posted_at=now,
            ),
        ]
    )
    db.commit()
    log.info("transfer completed", extra={"transfer_ref": transfer.reference, "amount_minor": req.amount_minor})
    return TransferResult(transfer, replayed=False)
