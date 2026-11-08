"""Accounts and beneficiaries. Every query is scoped to the authenticated customer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import AuthContext, get_db, require_customer
from app.models import Account, Beneficiary
from app.money import format_minor
from app.serializers import account_out, beneficiary_out

router = APIRouter(prefix="/api", tags=["accounts"])


def owned_account(db: Session, customer_id: int, account_id: int) -> Account:
    """Return the account only if the customer owns it; otherwise 404 (no existence leak)."""
    acct = db.scalar(select(Account).where(Account.id == account_id, Account.customer_id == customer_id))
    if acct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found.")
    return acct


@router.get("/accounts")
def list_accounts(auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db)):
    accounts = db.scalars(
        select(Account).where(Account.customer_id == auth.customer.id).order_by(Account.id)
    ).all()
    total = sum(a.balance_minor for a in accounts if a.status == "active")
    return {"accounts": [account_out(a) for a in accounts], "total_balance": format_minor(total), "currency": "EGP"}


@router.get("/accounts/{account_id}")
def get_account(account_id: int, auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db)):
    return account_out(owned_account(db, auth.customer.id, account_id))


@router.get("/beneficiaries")
def list_beneficiaries(auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Beneficiary).where(Beneficiary.customer_id == auth.customer.id).order_by(Beneficiary.nickname)
    ).all()
    return {"beneficiaries": [beneficiary_out(b) for b in rows if b.account.status == "active"]}
