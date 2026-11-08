"""Deterministic synthetic seed data.

Everything is generated from a fixed PRNG seed, so two runs with the same
anchor date produce identical customers, accounts, balances and histories.
Transaction dates are relative to the anchor date (default: today, UTC) so
that the dashboard's "last six months" view always has data; set
NVB_SEED_ANCHOR_DATE=YYYY-MM-DD for byte-identical repeat runs.

All names, numbers and amounts are fictitious.
"""

from __future__ import annotations

import os
import random
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models import (
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_DEMO,
    Account,
    Beneficiary,
    Customer,
    LedgerEntry,
    User,
)
from app.security import PasswordService

SEED = 20261108
HISTORY_DAYS = 180
CUSTOMER_COUNT = 60
LOADTEST_COUNT = 100
DEMO_OPERATOR_COUNT = 10
ADMIN_USERNAME = "opsadmin"

FIRST = ["Ahmed", "Mohamed", "Omar", "Youssef", "Karim", "Mostafa", "Hassan", "Tarek", "Amr", "Khaled",
         "Nour", "Salma", "Mariam", "Farida", "Laila", "Hana", "Yasmin", "Dina", "Reem", "Aya",
         "Sherif", "Hesham", "Ziad", "Malak", "Habiba", "Rania", "Sara", "Ali", "Mahmoud", "Nada"]
LAST = ["Hassan", "Mansour", "El-Sayed", "Fathy", "Abdelrahman", "Saleh", "Kamel", "Naguib", "Farouk", "Shawky",
        "Ibrahim", "Zaki", "Ragab", "Soliman", "Hamdy", "Gaber", "Lotfy", "Barakat", "Fouad", "Rashad"]
CITIES = ["Cairo", "Giza", "Alexandria", "Mansoura", "Tanta", "Aswan", "Luxor", "Ismailia", "Port Said", "Suez",
          "Hurghada", "Zagazig"]
EMPLOYERS = ["Delta Valley Textiles", "Nile Horizon Logistics", "Pyramid Soft Systems", "Red Sea Hospitality Group",
             "Cairo Metro Pharma", "Alexandria Port Services", "Sinai Solar Works", "Giza Engineering Co."]
MERCHANTS = {
    "Groceries": ["Valley Fresh Market", "Nile Daily Grocer", "Green Basket"],
    "Dining": ["Koshary Corner", "Zamalek Cafe", "Felucca Grill", "Sun Bakery"],
    "Transport": ["Metro Card Top-up", "City Ride", "Fuel Station 24"],
    "Shopping": ["Khan Style Store", "Delta Electronics", "Book Haven"],
    "Health": ["Al-Shifa Pharmacy", "Care Clinic"],
    "Entertainment": ["Cinema Nile", "Stream Plus"],
}
BILLERS = {"Utilities": ["Cairo Electricity (synthetic)", "City Water (synthetic)", "Fiber Net Home"],
           "Telecom": ["Mobile Line Postpaid"], "Education": ["Valley Language School"]}

CREDENTIAL_ENV = {
    "customer": "NVB_SEED_CUSTOMER_PASSWORD",
    "loadtest": "NVB_SEED_LOADTEST_PASSWORD",
    "demo": "NVB_SEED_DEMO_PASSWORD",
    "admin": "NVB_SEED_ADMIN_PASSWORD",
}


class SeedError(RuntimeError):
    pass


@dataclass
class SeedReport:
    customers: int = 0
    accounts: int = 0
    ledger_entries: int = 0
    beneficiaries: int = 0
    users: int = 0
    generated_passwords: dict[str, str] = field(default_factory=dict)
    password_sources: dict[str, str] = field(default_factory=dict)


def resolve_passwords(overrides: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (passwords, generated, sources). Never uses built-in defaults."""
    passwords, generated, sources = {}, {}, {}
    for group, env in CREDENTIAL_ENV.items():
        value = (overrides or {}).get(group) or os.environ.get(env)
        if value:
            if len(value) < 12:
                raise SeedError(f"{env} must be at least 12 characters.")
            passwords[group] = value
            sources[group] = f"environment ({env})"
        else:
            value = secrets.token_urlsafe(12)
            passwords[group] = value
            generated[group] = value
            sources[group] = "generated"
    return passwords, generated, sources


def anchor_date() -> date:
    raw = os.environ.get("NVB_SEED_ANCHOR_DATE")
    return date.fromisoformat(raw) if raw else datetime.now(UTC).date()


def _at(d: date, rng: random.Random) -> datetime:
    return datetime.combine(d, time(rng.randint(7, 21), rng.randint(0, 59), rng.randint(0, 59)), tzinfo=UTC)


def _account_number(rng: random.Random, used: set[str]) -> str:
    while True:
        num = "1007" + "".join(str(rng.randint(0, 9)) for _ in range(12))
        if num not in used:
            used.add(num)
            return num


def _history(rng: random.Random, kind: str, start: date, end: date, opening: int, salary: int,
             employer: str) -> list[dict]:
    """Build a chronologically consistent history; never lets the balance go negative."""
    events: list[tuple[datetime, str, str, str, int, str, str]] = []
    events.append((_at(start, rng), "credit", "deposit", "Deposits", opening, "Account opening deposit", "NVB Branch"))
    day = start + timedelta(days=1)
    while day <= end:
        if kind == "current":
            if day.day == 25:
                events.append((_at(day, rng), "credit", "salary", "Salary", salary, f"Salary - {employer}", employer))
            if day.day in (3, 4) and rng.random() < 0.6:
                cat = rng.choice(list(BILLERS))
                biller = rng.choice(BILLERS[cat])
                events.append((_at(day, rng), "debit", "bill_payment", cat, rng.randint(15_000, 120_000),
                               f"Bill payment - {biller}", biller))
            for _ in range(rng.choices([0, 1, 2], weights=[45, 40, 15])[0]):
                cat = rng.choice(list(MERCHANTS))
                merchant = rng.choice(MERCHANTS[cat])
                events.append((_at(day, rng), "debit", "card_purchase", cat, rng.randint(2_500, 180_000),
                               f"Card purchase - {merchant}", merchant))
            if rng.random() < 0.05:
                events.append((_at(day, rng), "debit", "atm_withdrawal", "Cash", rng.choice([50_000, 100_000, 200_000]),
                               "ATM withdrawal", "NVB ATM"))
        elif kind == "savings":
            if day.day == 1 and rng.random() < 0.7:
                events.append((_at(day, rng), "credit", "deposit", "Savings", rng.randint(100_000, 500_000),
                               "Monthly savings deposit", "Self"))
        day += timedelta(days=1)
    events.sort(key=lambda e: e[0])
    balance = 0
    rows = []
    for posted, direction, ttype, cat, amount, desc, cp in events:
        if direction == "debit":
            if balance - amount < 0:
                continue
            balance -= amount
        else:
            balance += amount
        rows.append({"posted_at": posted, "direction": direction, "txn_type": ttype, "category": cat,
                     "amount_minor": amount, "balance_after_minor": balance, "description": desc,
                     "counterparty": cp})
    return rows


def database_has_data(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(User)) or 0) > 0


def seed_database(db: Session, passwords_svc: PasswordService, passwords: dict[str, str],
                  *, customer_count: int = CUSTOMER_COUNT, loadtest_count: int = LOADTEST_COUNT,
                  demo_count: int = DEMO_OPERATOR_COUNT) -> SeedReport:
    if database_has_data(db):
        raise SeedError("Database already contains data. Use `reset-demo-data` to start over.")
    rng = random.Random(SEED)
    end = anchor_date()
    start = end - timedelta(days=HISTORY_DAYS)
    report = SeedReport()
    used_numbers: set[str] = set()
    used_names: set[str] = set()
    ref_counter = 0

    def next_ref() -> str:
        nonlocal ref_counter
        ref_counter += 1
        return f"TXN{ref_counter:09d}"

    def make_user(username: str, group: str, role: str, load_test: bool = False) -> User:
        u = User(username=username, password_hash=passwords_svc.hash(passwords[group]), role=role,
                 is_load_test=load_test, created_at=datetime.combine(start, time(9), tzinfo=UTC))
        db.add(u)
        report.users += 1
        return u

    current_accounts: list[Account] = []
    ledger_rows: list[dict] = []

    def add_customer(index: int, username: str, group: str, load_test: bool) -> Customer:
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if load_test:
                name = f"Load Test {index:03d}"
            if name not in used_names:
                used_names.add(name)
                break
        user = make_user(username, group, ROLE_CUSTOMER, load_test)
        db.flush()
        first = name.split(" ")[0].lower()
        cust = Customer(
            user_id=user.id,
            customer_number=f"{'LT' if load_test else 'C'}{index:06d}",
            full_name=name,
            email=f"{username}@example.test",
            phone=f"+2010{rng.randint(10_000_000, 99_999_999)}",
            city=rng.choice(CITIES),
            segment="Load test" if load_test else rng.choice(["Retail", "Retail", "Premier", "Youth"]),
            preferred_name=None if rng.random() < 0.7 else first.capitalize(),
            created_at=datetime.combine(start, time(9), tzinfo=UTC),
            updated_at=datetime.combine(start, time(9), tzinfo=UTC),
        )
        db.add(cust)
        db.flush()
        report.customers += 1

        kinds = ["current"] if load_test else ["current"] + (["savings"] if rng.random() < 0.6 else []) + (
            ["current"] if rng.random() < 0.15 else [])
        employer = rng.choice(EMPLOYERS)
        salary = rng.randint(800_000, 6_500_000)
        for n, kind in enumerate(kinds):
            opening = 100_000_000 if load_test else (
                rng.randint(500_000, 15_000_000) if kind == "current" else rng.randint(1_000_000, 80_000_000))
            history = _history(rng, kind, start, end, opening, salary if n == 0 else salary // 3, employer)
            if load_test:
                history = history[:40]
            acct = Account(
                customer_id=cust.id, account_number=_account_number(rng, used_numbers), account_type=kind,
                nickname={"current": "Everyday Current", "savings": "Smart Savings"}[kind]
                + (f" {kinds[:n + 1].count(kind)}" if kinds[:n].count(kind) else ""),
                balance_minor=history[-1]["balance_after_minor"],
                opened_at=datetime.combine(start, time(9), tzinfo=UTC),
            )
            db.add(acct)
            db.flush()
            report.accounts += 1
            for row in history:
                ledger_rows.append({**row, "account_id": acct.id, "reference": next_ref(), "transfer_id": None})
            if kind == "current" and n == 0:
                current_accounts.append(acct)
        return cust

    customers = [add_customer(i, f"customer{i:03d}", "customer", False) for i in range(1, customer_count + 1)]
    loadtesters = [add_customer(i, f"loadtest{i:03d}", "loadtest", True) for i in range(1, loadtest_count + 1)]

    for i in range(1, demo_count + 1):
        make_user(f"demoload{i:02d}", "demo", ROLE_DEMO)
    make_user(ADMIN_USERNAME, "admin", ROLE_ADMIN)

    # Beneficiaries: regular customers get 3-5 other customers; load-test users get the next one (ring).
    regular_accounts = current_accounts[: len(customers)]
    for cust in customers:
        others = [a for a in regular_accounts if a.customer_id != cust.id]
        for acct in rng.sample(others, k=min(len(others), rng.randint(3, 5))):
            db.add(Beneficiary(customer_id=cust.id, account_id=acct.id, nickname=acct.customer.full_name))
            report.beneficiaries += 1
    lt_accounts = current_accounts[len(customers):]
    for idx, cust in enumerate(loadtesters):
        if len(lt_accounts) > 1:
            target = lt_accounts[(idx + 1) % len(lt_accounts)]
            db.add(Beneficiary(customer_id=cust.id, account_id=target.id, nickname=target.customer.full_name))
            report.beneficiaries += 1

    if ledger_rows:
        for i in range(0, len(ledger_rows), 2000):
            db.execute(insert(LedgerEntry), ledger_rows[i:i + 2000])
    report.ledger_entries = len(ledger_rows)
    db.commit()
    return report
