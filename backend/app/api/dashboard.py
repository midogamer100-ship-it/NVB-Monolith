"""Customer dashboard summary."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.deps import AuthContext, get_db, require_customer
from app.models import Account, LedgerEntry
from app.money import format_minor
from app.serializers import account_out, txn_out

router = APIRouter(prefix="/api", tags=["dashboard"])

MONTHS = 6


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


@router.get("/dashboard")
def dashboard(auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db)):
    customer = auth.customer
    accounts = db.scalars(select(Account).where(Account.customer_id == customer.id).order_by(Account.id)).all()
    account_ids = [a.id for a in accounts]
    total = sum(a.balance_minor for a in accounts if a.status == "active")

    recent = db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.account_id.in_(account_ids))
        .order_by(LedgerEntry.posted_at.desc(), LedgerEntry.id.desc())
        .limit(8)
    ).all() if account_ids else []

    now = datetime.now(UTC)
    months = []
    for i in range(MONTHS - 1, -1, -1):
        y, m = _shift(now.year, now.month, -i)
        ny, nm = _shift(y, m, 1)
        months.append((y, m, _month_start(y, m), _month_start(ny, nm)))

    # Internal transfers between the customer's own accounts are excluded so that
    # moving money between own accounts does not inflate income or spending.
    own_transfer = (LedgerEntry.txn_type.in_(("transfer_in", "transfer_out"))) & (
        LedgerEntry.counterparty == customer.full_name
    )
    monthly = []
    for y, m, start, end in months:
        row = db.execute(
            select(
                func.coalesce(func.sum(case((LedgerEntry.direction == "credit", LedgerEntry.amount_minor), else_=0)), 0),
                func.coalesce(func.sum(case((LedgerEntry.direction == "debit", LedgerEntry.amount_minor), else_=0)), 0),
            ).where(
                LedgerEntry.account_id.in_(account_ids),
                LedgerEntry.posted_at >= start,
                LedgerEntry.posted_at < end,
                ~own_transfer,
            )
        ).one() if account_ids else (0, 0)
        monthly.append({
            "month": f"{y:04d}-{m:02d}",
            "income": format_minor(int(row[0])),
            "income_minor": int(row[0]),
            "spending": format_minor(int(row[1])),
            "spending_minor": int(row[1]),
        })

    cur_start, cur_end = months[-1][2], months[-1][3]
    categories = db.execute(
        select(LedgerEntry.category, func.sum(LedgerEntry.amount_minor))
        .where(
            LedgerEntry.account_id.in_(account_ids),
            LedgerEntry.direction == "debit",
            LedgerEntry.posted_at >= cur_start,
            LedgerEntry.posted_at < cur_end,
            ~own_transfer,
        )
        .group_by(LedgerEntry.category)
        .order_by(func.sum(LedgerEntry.amount_minor).desc())
    ).all() if account_ids else []

    return {
        "greeting_name": customer.preferred_name or customer.full_name.split(" ")[0],
        "customer_number": customer.customer_number,
        "accounts": [account_out(a) for a in accounts],
        "total_balance": format_minor(total),
        "total_balance_minor": total,
        "currency": "EGP",
        "recent_transactions": [txn_out(e) for e in recent],
        "monthly": monthly,
        "spending_by_category": [
            {"category": c, "amount": format_minor(int(v)), "amount_minor": int(v)} for c, v in categories
        ],
    }
