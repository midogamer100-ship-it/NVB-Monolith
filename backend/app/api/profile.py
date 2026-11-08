"""Customer profile: read seeded details, update a limited set of fields."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app import audit
from app.db import as_utc, utcnow
from app.deps import AuthContext, get_db, require_customer

router = APIRouter(prefix="/api/profile", tags=["profile"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
PHONE_RE = re.compile(r"^\+20(10|11|12|15)\d{8}$")
NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$", re.UNICODE)
CITIES = ("Cairo", "Giza", "Alexandria", "Mansoura", "Tanta", "Aswan", "Luxor", "Ismailia", "Port Said", "Suez", "Hurghada", "Zagazig")


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_name: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=60)

    @field_validator("preferred_name")
    @classmethod
    def _name(cls, v):
        if v is None:
            return v
        v = v.strip()
        if v and (len(v) < 2 or not NAME_RE.match(v)):
            raise ValueError("Preferred name must be 2-60 letters (spaces, hyphens and apostrophes allowed).")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v is None:
            return v
        v = re.sub(r"[\s-]", "", v)
        if not PHONE_RE.match(v):
            raise ValueError("Enter an Egyptian mobile number in the format +201XXXXXXXXX.")
        return v

    @field_validator("city")
    @classmethod
    def _city(cls, v):
        if v is not None and v not in CITIES:
            raise ValueError(f"City must be one of: {', '.join(CITIES)}.")
        return v


def profile_out(auth: AuthContext) -> dict:
    c = auth.customer
    return {
        "customer_number": c.customer_number,
        "full_name": c.full_name,
        "preferred_name": c.preferred_name,
        "email": c.email,
        "phone": c.phone,
        "city": c.city,
        "segment": c.segment,
        "username": auth.user.username,
        "member_since": as_utc(c.created_at).date().isoformat(),
        "last_login_at": as_utc(auth.user.last_login_at).isoformat() if auth.user.last_login_at else None,
        "editable_fields": ["preferred_name", "email", "phone", "city"],
        "cities": list(CITIES),
    }


@router.get("")
def get_profile(auth: AuthContext = Depends(require_customer)):
    return profile_out(auth)


@router.patch("")
def update_profile(
    body: ProfileUpdate,
    request: Request,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_db),
):
    c = auth.customer
    changed = []
    for field in ("preferred_name", "email", "phone", "city"):
        value = getattr(body, field)
        if value is None:
            continue
        if field == "preferred_name" and value == "":
            value = None
        if getattr(c, field) != value:
            setattr(c, field, value)
            changed.append(field)
    if changed:
        c.updated_at = utcnow()
        # Field names only - never the values (personal data stays out of the audit log).
        audit.record(db, "profile.update", "success", request=request, actor_user_id=auth.user.id,
                     actor_username=auth.user.username, details={"fields": changed})
        db.commit()
    return {"profile": profile_out(auth), "changed": changed}
