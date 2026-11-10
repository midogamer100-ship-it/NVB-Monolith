"""Read-only data extraction for the extension integration API.

Nothing in this module changes balances, ledger rows or ownership rules. It only
reads, and it never returns full account numbers.

Subjects
--------
``users.id`` is immutable, but a demo reset (TRUNCATE ... RESTART IDENTITY) reuses
ids. The subject therefore binds the id to the user's creation instant:
``nvb-user:<id>:<created_at unix seconds>``. A subject that no longer matches the
current row is rejected. A reset that recreates a user with the same id and the
same created_at second is still indistinguishable, so a core reset must be paired
with an extension data reset (documented in the extension runbook).

Statement dataset contract (version ``statement-v1``)
---------------------------------------------------
* Period boundaries are UTC instants, half-open: ``start <= posted_at < end``.
  This is exactly what the existing /api/transactions date filters do (UTC days).
  Callers convert local calendar periods (e.g. Africa/Cairo) to UTC instants.
* Ordering is ``posted_at ASC, id ASC`` - deterministic for tied timestamps.
* opening = sum of signed amounts with posted_at < start (accounts start at 0 and
  every balance change writes a ledger entry; this is verified, see below).
  closing = opening + credits - debits within the period. The current balance is
  never substituted for a historical closing balance.
* The manifest is computed in one REPEATABLE READ, READ ONLY snapshot on PostgreSQL
  and includes a reconciliation check: sum(all signed entries) == accounts.balance.
* Entries are fetched with keyset pagination (no offsets) and no row cap.
* Consistency: postings take ``posted_at = now()`` *before* waiting for the account
  row lock, so a transaction can commit a row whose posted_at is slightly in the
  past. A maximum id or timestamp alone is therefore not a completeness guarantee.
  We only serve periods with ``end <= now - settle_seconds`` (default 300 s; the
  core's statement_timeout is 10 s), and the caller must verify that the entries
  it received reproduce the manifest's count/totals and that the manifest's
  ``dataset_id`` is unchanged after paging. Any mismatch means "retry later".
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.db import as_utc
from app.models import ROLE_CUSTOMER, Account, Customer, LedgerEntry, User
from app.money import mask_account_number

DATASET_VERSION = "statement-v1"
SUBJECT_PREFIX = "nvb-user"


class IntegrationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# --- Subjects -------------------------------------------------------------------------


def subject_for(user: User) -> str:
    return f"{SUBJECT_PREFIX}:{user.id}:{int(as_utc(user.created_at).timestamp())}"


def _parse_subject(subject: str) -> tuple[int, int]:
    parts = subject.split(":")
    if len(parts) != 3 or parts[0] != SUBJECT_PREFIX or not parts[1].isdigit() or not parts[2].isdigit():
        raise IntegrationError(422, "invalid_subject", "Subject is not valid.")
    return int(parts[1]), int(parts[2])


def customer_for_subject(db: Session, subject: str) -> tuple[User, Customer]:
    """Return the active customer behind a subject, or fail closed with 404."""
    user_id, created = _parse_subject(subject)
    user = db.get(User, user_id)
    if user is None or int(as_utc(user.created_at).timestamp()) != created:
        raise IntegrationError(404, "subject_not_found", "Subject not found.")
    if not user.is_active or user.role != ROLE_CUSTOMER or user.customer is None:
        # Suspended users and non-customers are not eligible for customer data.
        raise IntegrationError(404, "subject_not_found", "Subject not found.")
    return user, user.customer


def owned_account(db: Session, customer: Customer, account_id: int) -> Account:
    acct = db.scalar(select(Account).where(Account.id == account_id, Account.customer_id == customer.id))
    if acct is None:
        raise IntegrationError(404, "account_not_found", "Account not found.")
    return acct


def account_summary(a: Account) -> dict:
    return {
        "account_id": a.id,
        "masked_number": mask_account_number(a.account_number),
        "type": a.account_type,
        "nickname": a.nickname,
        "currency": a.currency,
        "status": a.status,
        "opened_at": as_utc(a.opened_at).isoformat(),
    }


def accounts_for_customer(db: Session, customer: Customer) -> list[dict]:
    rows = db.scalars(select(Account).where(Account.customer_id == customer.id).order_by(Account.id)).all()
    return [account_summary(a) for a in rows]


# --- Periods --------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime


def validate_period(start: datetime, end: datetime, *, now: datetime, settle_seconds: int,
                    max_days: int) -> Period:
    if start.tzinfo is None or end.tzinfo is None:
        raise IntegrationError(422, "naive_datetime", "Period boundaries must include a UTC offset.")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if start >= end:
        raise IntegrationError(422, "invalid_period", "period_start must be before period_end.")
    if end - start > timedelta(days=max_days):
        raise IntegrationError(422, "period_too_long", f"Period must be at most {max_days} days.")
    if end > now - timedelta(seconds=settle_seconds):
        raise IntegrationError(409, "period_not_settled",
                               "Period end is too recent to guarantee a complete dataset; retry later.")
    return Period(start, end)


# --- Snapshot helper ------------------------------------------------------------------


def begin_snapshot(db: Session) -> None:
    """Start a REPEATABLE READ READ ONLY transaction on PostgreSQL.

    SQLite (tests only) already serialises transactions with BEGIN IMMEDIATE.
    Must be called before the session has started a transaction.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.connection(execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True})


# --- Statement manifest and entries -----------------------------------------------------


def _signed():
    return case((LedgerEntry.direction == "credit", LedgerEntry.amount_minor), else_=-LedgerEntry.amount_minor)


def statement_manifest(db: Session, customer: Customer, account: Account, period: Period,
                       *, now: datetime) -> dict:
    acct_filter = LedgerEntry.account_id == account.id
    in_period = and_(acct_filter, LedgerEntry.posted_at >= period.start, LedgerEntry.posted_at < period.end)

    opening = db.scalar(
        select(func.coalesce(func.sum(_signed()), 0)).where(acct_filter, LedgerEntry.posted_at < period.start)
    )
    credit_total, debit_total, count, first_id, last_id = db.execute(
        select(
            func.coalesce(func.sum(case((LedgerEntry.direction == "credit", LedgerEntry.amount_minor), else_=0)), 0),
            func.coalesce(func.sum(case((LedgerEntry.direction == "debit", LedgerEntry.amount_minor), else_=0)), 0),
            func.count(LedgerEntry.id),
            func.min(LedgerEntry.id),
            func.max(LedgerEntry.id),
        ).where(in_period)
    ).one()
    ledger_total = db.scalar(select(func.coalesce(func.sum(_signed()), 0)).where(acct_filter))
    balance_now = db.scalar(select(Account.balance_minor).where(Account.id == account.id))
    if int(ledger_total) != int(balance_now):
        raise IntegrationError(500, "ledger_reconciliation_failed",
                               "Ledger does not reconcile with the account balance.")

    opening, credit_total, debit_total = int(opening), int(credit_total), int(debit_total)
    closing = opening + credit_total - debit_total
    opened_at = as_utc(account.opened_at)
    core = {
        "dataset_version": DATASET_VERSION,
        "account_id": account.id,
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "opening_balance_minor": opening,
        "closing_balance_minor": closing,
        "credit_total_minor": credit_total,
        "debit_total_minor": debit_total,
        "entry_count": int(count),
        "first_entry_id": first_id,
        "last_entry_id": last_id,
    }
    dataset_id = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    holder = customer.full_name if isinstance(customer, Customer) else None
    return {
        **core,
        "dataset_id": dataset_id,
        "boundary": "[start,end) UTC",
        "ordering": "posted_at ASC, id ASC",
        "currency": account.currency,
        "account": {**account_summary(account), "holder_name": holder},
        "account_opened_in_period": period.start <= opened_at < period.end,
        "account_opened_after_period": opened_at >= period.end,
        "generated_at": now.isoformat(),
    }


def encode_cursor(posted_at: datetime, entry_id: int) -> str:
    raw = f"{as_utc(posted_at).isoformat()}|{entry_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        posted, entry_id = base64.urlsafe_b64decode(padded.encode()).decode().split("|")
        dt = datetime.fromisoformat(posted)
        if dt.tzinfo is None:
            raise ValueError
        return dt.astimezone(UTC), int(entry_id)
    except (ValueError, UnicodeDecodeError):
        raise IntegrationError(422, "invalid_cursor", "Cursor is not valid.") from None


def entry_out(e: LedgerEntry) -> dict:
    return {
        "entry_id": e.id,
        "posted_at": as_utc(e.posted_at).isoformat(),
        "reference": e.reference,
        "direction": e.direction,
        "type": e.txn_type,
        "category": e.category,
        "amount_minor": e.amount_minor,
        "signed_amount_minor": e.amount_minor if e.direction == "credit" else -e.amount_minor,
        "balance_after_minor": e.balance_after_minor,
        "description": e.description,
        "counterparty": e.counterparty,
    }


def statement_entries(db: Session, account: Account, period: Period, *, cursor: str | None,
                      limit: int) -> dict:
    stmt = select(LedgerEntry).where(
        LedgerEntry.account_id == account.id,
        LedgerEntry.posted_at >= period.start,
        LedgerEntry.posted_at < period.end,
    )
    if cursor:
        after_posted, after_id = decode_cursor(cursor)
        stmt = stmt.where(or_(LedgerEntry.posted_at > after_posted,
                              and_(LedgerEntry.posted_at == after_posted, LedgerEntry.id > after_id)))
    rows = db.scalars(stmt.order_by(LedgerEntry.posted_at.asc(), LedgerEntry.id.asc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [entry_out(e) for e in rows],
        "has_more": has_more,
        "next_cursor": encode_cursor(rows[-1].posted_at, rows[-1].id) if has_more else None,
    }


# --- Batch discovery ------------------------------------------------------------------


def discover_statement_accounts(db: Session, *, after_account_id: int, limit: int,
                                include_load_test: bool) -> dict:
    """Active accounts of active customers, keyset-paginated by account id."""
    stmt = (
        select(Account, User)
        .join(Customer, Customer.id == Account.customer_id)
        .join(User, User.id == Customer.user_id)
        .where(Account.id > after_account_id, Account.status == "active", User.is_active.is_(True),
               User.role == ROLE_CUSTOMER)
    )
    if not include_load_test:
        stmt = stmt.where(User.is_load_test.is_(False))
    rows = db.execute(stmt.order_by(Account.id).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [{"subject": subject_for(u), **account_summary(a)} for a, u in rows],
        "has_more": has_more,
        "next_after_account_id": rows[-1][0].id if has_more else None,
    }
