"""Shared input rules for sign-up, admin user creation and password reset."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.profile import CITIES, EMAIL_RE, PHONE_RE

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{3,31}$")
FULL_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-]+[^\W\d_]+)*$", re.UNICODE)


def check_password(password: str, username: str | None) -> str:
    if not 10 <= len(password) <= 128:
        raise ValueError("Password must be 10-128 characters long.")
    if not re.search(r"[^\W\d_]", password, re.UNICODE) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one number.")
    if username and username.lower() in password.lower():
        raise ValueError("Password must not contain your username.")
    return password


class NewCustomerFields(BaseModel):
    """Identity fields shared by self sign-up and admin-created users."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    phone: str = Field(min_length=3, max_length=20)
    city: str = Field(min_length=1, max_length=60)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 4-32 characters: lowercase letters, digits, '.', '_' or '-', "
                             "starting with a letter.")
        return v

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 3 <= len(v) <= 120 or not FULL_NAME_RE.match(v):
            raise ValueError("Full name must be 3-120 letters (spaces, hyphens and apostrophes allowed).")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = re.sub(r"[\s-]", "", v)
        if not PHONE_RE.match(v):
            raise ValueError("Enter an Egyptian mobile number in the format +201XXXXXXXXX.")
        return v

    @field_validator("city")
    @classmethod
    def _city(cls, v: str) -> str:
        if v not in CITIES:
            raise ValueError(f"City must be one of: {', '.join(CITIES)}.")
        return v


class RegisterRequest(NewCustomerFields):
    password: str = Field(min_length=1, max_length=256)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str, info) -> str:
        return check_password(v, info.data.get("username"))


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=1, max_length=256)


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
