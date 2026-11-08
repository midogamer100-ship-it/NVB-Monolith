"""Transaction history, details and CSV export (authenticated customer's data only)."""

# NOTE: no `from __future__ import annotations` here - FastAPI must resolve the
# class-based TxnFilters dependency's annotations at import time.
import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.db import as_utc
from app.deps import AuthContext, get_db, require_customer
from app.models import Account, LedgerEntry
from app.money import format_minor, mask_account_number
from app.serializers import TXN_TYPES, txn_out

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

MAX_EXPORT_ROWS = 10_000


class TxnFilters:
    def __init__(
        self,
        account_id: int | None = Query(default=None, ge=1),
        type: str | None = Query(default=None, max_length=24),
        direction: Literal["debit", "credit"] | None = None,
        q: str | None = Query(default=None, max_length=60),
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> None:
        if type is not None and type not in TXN_TYPES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"type must be one of {', '.join(TXN_TYPES)}")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from must be on or before date_to.")
        self.account_id = account_id
        self.type = type
        self.direction = direction
        self.q = q.strip() if q else None
        self.date_from = date_from
        self.date_to = date_to


def _scoped_query(db: Session, customer_id: int, f: TxnFilters) -> Select:
    stmt = select(LedgerEntry).join(Account, Account.id == LedgerEntry.account_id).where(Account.customer_id == customer_id)
    if f.account_id is not None:
        owned = db.scalar(select(Account.id).where(Account.id == f.account_id, Account.customer_id == customer_id))
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found.")
        stmt = stmt.where(LedgerEntry.account_id == f.account_id)
    if f.type:
        stmt = stmt.where(LedgerEntry.txn_type == f.type)
    if f.direction:
        stmt = stmt.where(LedgerEntry.direction == f.direction)
    if f.date_from:
        stmt = stmt.where(LedgerEntry.posted_at >= datetime.combine(f.date_from, time.min, tzinfo=UTC))
    if f.date_to:
        stmt = stmt.where(LedgerEntry.posted_at < datetime.combine(f.date_to + timedelta(days=1), time.min, tzinfo=UTC))
    if f.q:
        # Bound parameters only; escape LIKE wildcards supplied by the user.
        needle = "%" + f.q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(
            or_(
                func.lower(LedgerEntry.description).like(needle, escape="\\"),
                func.lower(LedgerEntry.counterparty).like(needle, escape="\\"),
                func.lower(LedgerEntry.reference).like(needle, escape="\\"),
            )
        )
    return stmt


@router.get("")
def list_transactions(
    filters: TxnFilters = Depends(),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_db),
):
    base = _scoped_query(db, auth.customer.id, filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(LedgerEntry.posted_at.desc(), LedgerEntry.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [txn_out(e) for e in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, -(-total // page_size)),
        "types": list(TXN_TYPES),
    }


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection."""
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@router.get("/export.csv")
def export_csv(
    request: Request,
    filters: TxnFilters = Depends(),
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        _scoped_query(db, auth.customer.id, filters)
        .order_by(LedgerEntry.posted_at.desc(), LedgerEntry.id.desc())
        .limit(MAX_EXPORT_ROWS)
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["posted_at_utc", "reference", "account", "type", "category", "direction", "amount_egp", "balance_after_egp", "description", "counterparty"])
    for e in rows:
        signed = e.amount_minor if e.direction == "credit" else -e.amount_minor
        writer.writerow([
            as_utc(e.posted_at).strftime("%Y-%m-%d %H:%M:%S"),
            e.reference,
            mask_account_number(e.account.account_number),
            e.txn_type,
            e.category,
            e.direction,
            format_minor(signed),
            format_minor(e.balance_after_minor),
            _csv_safe(e.description),
            _csv_safe(e.counterparty),
        ])
    audit.record(db, "transactions.export", "success", request=request, actor_user_id=auth.user.id,
                 actor_username=auth.user.username, details={"rows": len(rows)})
    db.commit()
    filename = f"nvb-transactions-{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/{entry_id}")
def get_transaction(entry_id: int, auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db)):
    entry = db.scalar(
        select(LedgerEntry)
        .join(Account, Account.id == LedgerEntry.account_id)
        .where(LedgerEntry.id == entry_id, Account.customer_id == auth.customer.id)
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found.")
    out = txn_out(entry)
    out["account"] = {"id": entry.account.id, "masked_number": mask_account_number(entry.account.account_number), "nickname": entry.account.nickname}
    return out
