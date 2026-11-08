"""Internal transfer endpoints: preview (validation only), execute, receipt, history."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.deps import AuthContext, get_db, get_settings_dep, require_customer
from app.models import Account, Transfer
from app.money import MoneyError, format_minor, mask_account_number, parse_amount_to_minor
from app.serializers import transfer_out
from app.services.transfers import TransferError, TransferRequest, execute_transfer, validate

router = APIRouter(prefix="/api/transfers", tags=["transfers"])

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
DESCRIPTION_RE = re.compile(r"^[\w\s.,'()/#&:-]*$", re.UNICODE)


class TransferBody(BaseModel):
    source_account_id: int = Field(ge=1)
    beneficiary_id: int | None = Field(default=None, ge=1)
    destination_account_id: int | None = Field(default=None, ge=1)
    amount: str = Field(min_length=1, max_length=20, description='Decimal string in EGP, e.g. "1250.50"')
    description: str = Field(default="", max_length=140)

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str) -> str:
        v = v.strip()
        if not DESCRIPTION_RE.match(v):
            raise ValueError("Description contains unsupported characters.")
        return v

    def to_request(self) -> TransferRequest:
        try:
            minor = parse_amount_to_minor(self.amount)
        except MoneyError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return TransferRequest(
            source_account_id=self.source_account_id,
            beneficiary_id=self.beneficiary_id,
            destination_account_id=self.destination_account_id,
            amount_minor=minor,
            description=self.description,
        )


def _error(exc: TransferError) -> HTTPException:
    return HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})


@router.post("/preview")
def preview(
    body: TransferBody,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    """Server-side validation for the confirmation screen. Moves no money."""
    req = body.to_request()
    try:
        source, dest = validate(db, auth.customer, req, settings.max_transfer_minor)
    except TransferError as exc:
        raise _error(exc) from exc
    return {
        "source": {"id": source.id, "masked_number": mask_account_number(source.account_number), "nickname": source.nickname,
                   "balance": format_minor(source.balance_minor)},
        "destination": {"masked_number": mask_account_number(dest.account_number), "holder_name": dest.customer.full_name,
                        "is_own_account": dest.customer_id == auth.customer.id},
        "amount": format_minor(req.amount_minor),
        "fee": "0.00",
        "currency": "EGP",
        "description": req.description,
        "sufficient_funds": source.balance_minor >= req.amount_minor,
        "balance_after": format_minor(source.balance_minor - req.amount_minor) if source.balance_minor >= req.amount_minor else None,
    }


@router.post("")
def create_transfer(
    body: TransferBody,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    if not idempotency_key or not IDEMPOTENCY_KEY_RE.match(idempotency_key):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "idempotency_key_required", "message": "An Idempotency-Key header (16-64 chars [A-Za-z0-9_-]) is required."},
        )
    req = body.to_request()
    user_id, username, customer_id = auth.user.id, auth.user.username, auth.customer.id
    try:
        result = execute_transfer(
            db, user_id=user_id, customer=auth.customer, req=req,
            idempotency_key=idempotency_key, max_minor=settings.max_transfer_minor,
        )
    except TransferError as exc:
        audit.record(db, "transfer.create", "rejected", request=request, actor_user_id=user_id,
                     actor_username=username, details={"code": exc.code})
        db.commit()
        raise _error(exc) from exc

    t = result.transfer
    if not result.replayed:
        audit.record(db, "transfer.create", t.status, request=request, actor_user_id=user_id, actor_username=username,
                     details={"reference": t.reference, "amount_minor": t.amount_minor, "failure_reason": t.failure_reason})
        db.commit()
    response.headers["Idempotent-Replayed"] = "true" if result.replayed else "false"
    payload = transfer_out(t, viewer_customer_id=customer_id)
    if t.status == "failed":
        # The attempt is persisted (and replayable) but money did not move.
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        payload["message"] = "Insufficient funds. No money was moved." if t.failure_reason == "insufficient_funds" else "Transfer failed."
    else:
        response.status_code = status.HTTP_201_CREATED if not result.replayed else status.HTTP_200_OK
    return payload


@router.get("")
def list_transfers(
    limit: int = Query(default=10, ge=1, le=50),
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Transfer).where(Transfer.initiated_by_user_id == auth.user.id).order_by(Transfer.id.desc()).limit(limit)
    ).all()
    return {"items": [transfer_out(t, viewer_customer_id=auth.customer.id) for t in rows]}


@router.get("/{reference}")
def get_transfer(reference: str, auth: AuthContext = Depends(require_customer), db: Session = Depends(get_db)):
    if len(reference) > 32:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer not found.")
    own_accounts = select(Account.id).where(Account.customer_id == auth.customer.id)
    t = db.scalar(
        select(Transfer).where(
            Transfer.reference == reference,
            or_(Transfer.source_account_id.in_(own_accounts), Transfer.destination_account_id.in_(own_accounts)),
        )
    )
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer not found.")
    return transfer_out(t, viewer_customer_id=auth.customer.id)
