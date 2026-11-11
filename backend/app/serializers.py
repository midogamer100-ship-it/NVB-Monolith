"""Response shaping. Full account numbers are never returned by the API."""

from __future__ import annotations

from app.db import as_utc
from app.models import Account, Beneficiary, LedgerEntry, Transfer
from app.money import format_minor, mask_account_number

TXN_TYPES = (
    "salary",
    "deposit",
    "transfer_in",
    "transfer_out",
    "card_purchase",
    "bill_payment",
    "atm_withdrawal",
    "withdrawal",
)


def account_out(a: Account) -> dict:
    return {
        "id": a.id,
        "masked_number": mask_account_number(a.account_number),
        "last4": a.account_number[-4:],
        "type": a.account_type,
        "nickname": a.nickname,
        "currency": a.currency,
        "balance": format_minor(a.balance_minor),
        "balance_minor": a.balance_minor,
        "status": a.status,
        "opened_at": as_utc(a.opened_at).isoformat(),
    }


def txn_out(e: LedgerEntry) -> dict:
    return {
        "id": e.id,
        "account_id": e.account_id,
        "reference": e.reference,
        "direction": e.direction,
        "type": e.txn_type,
        "category": e.category,
        "amount": format_minor(e.amount_minor),
        "amount_minor": e.amount_minor,
        "signed_amount_minor": e.amount_minor if e.direction == "credit" else -e.amount_minor,
        "balance_after": format_minor(e.balance_after_minor),
        "description": e.description,
        "counterparty": e.counterparty,
        "posted_at": as_utc(e.posted_at).isoformat(),
        "transfer_reference": e.reference if e.transfer_id else None,
    }


def beneficiary_out(b: Beneficiary) -> dict:
    return {
        "id": b.id,
        "nickname": b.nickname,
        "holder_name": b.account.customer.full_name,
        "masked_number": mask_account_number(b.account.account_number),
        "bank": "R&D bank",
    }


def transfer_out(t: Transfer, *, viewer_customer_id: int) -> dict:
    src = t.source_account
    dst = t.destination_account
    return {
        "reference": t.reference,
        "status": t.status,
        "failure_reason": t.failure_reason,
        "amount": format_minor(t.amount_minor),
        "amount_minor": t.amount_minor,
        "currency": t.currency,
        "description": t.description,
        "source": {"id": src.id, "masked_number": mask_account_number(src.account_number), "nickname": src.nickname},
        "destination": {
            "masked_number": mask_account_number(dst.account_number),
            "holder_name": dst.customer.full_name,
            "is_own_account": dst.customer_id == viewer_customer_id,
        },
        "created_at": as_utc(t.created_at).isoformat(),
        "completed_at": as_utc(t.completed_at).isoformat() if t.completed_at else None,
    }
