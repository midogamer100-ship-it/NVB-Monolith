import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, select

from app.cli import alembic_config
from app.db import Base, build_sessionmaker
from app.models import Account, LedgerEntry, User
from app.security import PasswordService
from app.services.seed import SeedError, seed_database
from tests.conftest import PASSWORDS, make_settings

pytestmark = pytest.mark.skipif(bool(os.environ.get("NVB_TEST_DATABASE_URL")),
                                reason="uses its own SQLite files")


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'migr.db'}"
    cfg = alembic_config(url)
    cfg.attributes["configure_logging"] = False
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff
    command.downgrade(cfg, "base")


def _seed(tmp_path, name):
    url = f"sqlite:///{tmp_path / name}"
    settings = make_settings(url)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    db = build_sessionmaker(engine)()
    os.environ["NVB_SEED_ANCHOR_DATE"] = "2026-11-01"
    try:
        report = seed_database(db, PasswordService(settings), PASSWORDS, customer_count=60, loadtest_count=5,
                               demo_count=2)
    finally:
        del os.environ["NVB_SEED_ANCHOR_DATE"]
    return db, report


def test_seed_is_deterministic_and_consistent(tmp_path):
    db1, r1 = _seed(tmp_path, "a.db")
    db2, r2 = _seed(tmp_path, "b.db")
    assert r1.customers == 65 and r1.accounts >= 65
    snap = lambda db: db.execute(select(Account.account_number, Account.balance_minor).order_by(Account.id)).all()  # noqa: E731
    assert snap(db1) == snap(db2)
    # Each account's balance equals the last ledger balance and the sum of postings.
    for acct in db1.scalars(select(Account)).all():
        credits = db1.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_minor), 0)).where(
            LedgerEntry.account_id == acct.id, LedgerEntry.direction == "credit"))
        debits = db1.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_minor), 0)).where(
            LedgerEntry.account_id == acct.id, LedgerEntry.direction == "debit"))
        assert acct.balance_minor == credits - debits >= 0
    assert db1.scalar(select(func.count()).select_from(User).where(User.role == "admin")) == 1
    # Seeding twice is refused.
    with pytest.raises(SeedError):
        seed_database(db1, PasswordService(make_settings("sqlite://")), PASSWORDS)
    db1.close()
    db2.close()


def test_passwords_are_hashed(tmp_path):
    db, _ = _seed(tmp_path, "c.db")
    for u in db.scalars(select(User)).all():
        assert u.password_hash.startswith("$argon2")
        assert PASSWORDS["customer"] not in u.password_hash
    db.close()
