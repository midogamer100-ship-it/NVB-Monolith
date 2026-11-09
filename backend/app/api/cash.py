"""Deposit and withdraw endpoints (simulated branch cash, synthetic demo)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app import audit
from app.api.transfers import DESCRIPTION_RE, IDEMPOTENCY_KEY_RE
from app.config import Settings
from app.db import as_utc
from app.deps import AuthContext, get_db, get_settings_dep, require_customer
from app.models import CashOperation
from app.money import MoneyError, format_minor, mask_account_number, parse_amount_to_minor
from app.services.cash import CashError, execute_cash_operation

router = APIRouter(prefix="/api/accounts", tags=["cash"])


class CashBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(min_length=1, max_length=20, description='Decimal string in EGP, e.g. "500.00"')
    description: str = Field(default="", max_length=140)

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str) -> str:
        v = v.strip()
        if not DESCRIPTION_RE.match(v):
            raise ValueError("Description contains unsupported characters.")
        return v


def cash_out(op: CashOperation) -> dict:
    acct = op.account
    out = {
        "reference": op.reference,
        "kind": op.kind,
        "status": op.status,
        "failure_reason": op.failure_reason,
        "amount": format_minor(op.amount_minor),
        "amount_minor": op.amount_minor,
        "description": op.description,
        "account": {"id": acct.id, "masked_number": mask_account_number(acct.account_number),
                    "nickname": acct.nickname, "balance": format_minor(acct.balance_minor),
                    "balance_minor": acct.balance_minor},
        "created_at": as_utc(op.created_at).isoformat(),
    }
    if op.status == "failed":
        out["message"] = ("Insufficient funds. No money was moved." if op.failure_reason == "insufficient_funds"
                          else "Operation failed.")
    return out


def _handle(kind: str, account_id: int, body: CashBody, request: Request, response: Response,
            idempotency_key: str | None, auth: AuthContext, db: Session, settings: Settings) -> dict:
    if not idempotency_key or not IDEMPOTENCY_KEY_RE.match(idempotency_key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {
            "code": "idempotency_key_required",
            "message": "An Idempotency-Key header (16-64 chars [A-Za-z0-9_-]) is required."})
    try:
        amount = parse_amount_to_minor(body.amount)
    except MoneyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    user_id, username, customer_id = auth.user.id, auth.user.username, auth.customer.id
    event = "account.deposit" if kind == "deposit" else "account.withdraw"
    limit = settings.max_deposit_minor if kind == "deposit" else settings.max_withdrawal_minor
    try:
        result = execute_cash_operation(db, user_id=user_id, customer_id=customer_id, account_id=account_id,
                                        kind=kind, amount_minor=amount, description=body.description,
                                        idempotency_key=idempotency_key, max_minor=limit)
    except CashError as exc:
        if exc.status_code != 404:
            audit.record(db, event, "rejected", request=request, actor_user_id=user_id, actor_username=username,
                         details={"code": exc.code})
            db.commit()
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc

    op = result.operation
    if not result.replayed:
        audit.record(db, event, op.status, request=request, actor_user_id=user_id, actor_username=username,
                     details={"reference": op.reference, "amount_minor": op.amount_minor,
                              "failure_reason": op.failure_reason})
        db.commit()
    db.refresh(op.account)
    response.headers["Idempotent-Replayed"] = "true" if result.replayed else "false"
    if op.status == "failed":
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        response.status_code = status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
    return cash_out(op)


@router.post("/{account_id}/deposit")
def deposit(account_id: int, body: CashBody, request: Request, response: Response,
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
            auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings_dep)):
    return _handle("deposit", account_id, body, request, response, idempotency_key, auth, db, settings)


@router.post("/{account_id}/withdraw")
def withdraw(account_id: int, body: CashBody, request: Request, response: Response,
             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
             auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db),
             settings: Settings = Depends(get_settings_dep)):
    return _handle("withdrawal", account_id, body, request, response, idempotency_key, auth, db, settings)
