"""Exact money handling. Amounts cross the API as decimal strings ("1250.50")."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

MINOR_PER_MAJOR = 100


class MoneyError(ValueError):
    pass


def parse_amount_to_minor(value: str | int | Decimal) -> int:
    """Parse a user-supplied EGP amount into integer piastres.

    Rejects floats, NaN/Infinity, more than two decimal places and non-positive
    values. Accepts str (preferred) and int.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise MoneyError("Amount must be a decimal string, e.g. \"1250.50\".")
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError("Amount is not a valid number.") from exc
    if not dec.is_finite():
        raise MoneyError("Amount is not a valid number.")
    if dec <= 0:
        raise MoneyError("Amount must be greater than zero.")
    if dec > Decimal("1e15"):
        raise MoneyError("Amount is too large.")
    if dec.as_tuple().exponent < -2 and dec != dec.quantize(Decimal("0.01")):
        raise MoneyError("Amount can have at most two decimal places.")
    return int(dec * MINOR_PER_MAJOR)


def format_minor(minor: int) -> str:
    """Return a plain decimal string such as "1250.50" (no thousands separators)."""
    sign = "-" if minor < 0 else ""
    minor = abs(int(minor))
    return f"{sign}{minor // MINOR_PER_MAJOR}.{minor % MINOR_PER_MAJOR:02d}"


def mask_account_number(account_number: str) -> str:
    return f"•••• {account_number[-4:]}"
