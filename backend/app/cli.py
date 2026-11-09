"""Operator CLI: ``python -m app.cli <command>`` (run from the backend/ directory).

Commands
  migrate           Apply Alembic migrations (single explicit operation).
  seed              Load deterministic synthetic demo data into an empty database.
  reset-demo-data   Guarded: wipe ALL demo data and re-seed.
  check-db          Verify connectivity with the application credentials.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text

from app import audit
from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.models import (
    Account,
    AuditEvent,
    Beneficiary,
    CashOperation,
    Customer,
    LedgerEntry,
    LoginAttempt,
    OutboxMessage,
    PasswordResetToken,
    Transfer,
    User,
    UserSession,
)
from app.security import PasswordService
from app.services.seed import SeedError, resolve_passwords, seed_database

BACKEND_DIR = Path(__file__).resolve().parent.parent
RESET_PHRASE = "RESET NVB DEMO DATA"


def alembic_config(url) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["url"] = url
    return cfg


def cmd_migrate(_args) -> int:
    settings = get_settings()
    url = settings.migration_sqlalchemy_url()
    print(f"Applying migrations to {url.render_as_string(hide_password=True)}")
    command.upgrade(alembic_config(url), "head")
    print("Migrations complete.")
    return 0


def _write_credentials(path: Path, generated: dict[str, str], sources: dict[str, str]) -> None:
    lines = [
        "# NVB demo credentials - SYNTHETIC DEMO ONLY. Do not commit. Delete after the demo.",
        "# Usernames: customer001..customer060, loadtest001..loadtest100, demoload01..demoload10, opsadmin",
    ]
    groups = {"customer": "customer001..customer060", "loadtest": "loadtest001..loadtest100",
              "demo": "demoload01..demoload10 (demo role)", "admin": "opsadmin (admin role)"}
    for group, users in groups.items():
        if group in generated:
            lines.append(f"{users}: {generated[group]}")
        else:
            lines.append(f"{users}: <from {sources[group]}>")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _seed(db, settings, credentials_file: Path) -> int:
    passwords, generated, sources = resolve_passwords()
    report = seed_database(db, PasswordService(settings), passwords)
    audit.record(db, "admin.seed", "success", actor_username="cli",
                 details={"customers": report.customers, "accounts": report.accounts})
    db.commit()
    print(f"Seeded {report.users} users, {report.customers} customers, {report.accounts} accounts, "
          f"{report.ledger_entries} ledger entries, {report.beneficiaries} beneficiaries.")
    for group, source in sources.items():
        print(f"  {group:9s} password: {source}")
    if generated:
        _write_credentials(credentials_file, generated, sources)
        print(f"Generated passwords were written to {credentials_file} (mode 0600). They are not printed.")
    return 0


def cmd_seed(args) -> int:
    settings = get_settings()
    engine = build_engine(settings, settings.migration_sqlalchemy_url())
    db = build_sessionmaker(engine)()
    try:
        return _seed(db, settings, Path(args.credentials_file))
    except SeedError as exc:
        print(f"Seed refused: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


def cmd_reset(args) -> int:
    settings = get_settings()
    if not settings.allow_demo_reset:
        print("Refused: set NVB_ALLOW_DEMO_RESET=true for this one command to allow a reset.", file=sys.stderr)
        return 2
    if args.confirm != RESET_PHRASE:
        print(f'Refused: pass --confirm "{RESET_PHRASE}" exactly.', file=sys.stderr)
        return 2
    engine = build_engine(settings, settings.migration_sqlalchemy_url())
    db = build_sessionmaker(engine)()
    try:
        if engine.dialect.name == "postgresql":
            db.execute(text(
                "TRUNCATE ledger_entries, cash_operations, transfers, beneficiaries, accounts, customers, "
                "password_reset_tokens, outbox_messages, user_sessions, login_attempts, audit_events, users "
                "RESTART IDENTITY CASCADE"))
        else:
            for model in (LedgerEntry, CashOperation, Transfer, Beneficiary, Account, Customer, PasswordResetToken,
                          OutboxMessage, UserSession, LoginAttempt, AuditEvent, User):
                db.execute(delete(model))
        db.commit()
        print("All demo data deleted. Re-seeding...")
        audit.record(db, "admin.reset_demo_data", "success", actor_username="cli")
        db.commit()
        return _seed(db, settings, Path(args.credentials_file))
    finally:
        db.close()


def cmd_check_db(_args) -> int:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()" if engine.dialect.name == "postgresql" else "SELECT sqlite_version()")).scalar()
        print(f"OK: connected to {engine.url.render_as_string(hide_password=True)} ({version})")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="NVB demo operator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    p_seed = sub.add_parser("seed", help="load deterministic synthetic data")
    p_seed.add_argument("--credentials-file", default="nvb-demo-credentials.txt")
    p_seed.set_defaults(func=cmd_seed)
    p_reset = sub.add_parser("reset-demo-data", help="DANGER: delete all data and re-seed")
    p_reset.add_argument("--confirm", required=True)
    p_reset.add_argument("--credentials-file", default="nvb-demo-credentials.txt")
    p_reset.set_defaults(func=cmd_reset)
    sub.add_parser("check-db", help="check database connectivity").set_defaults(func=cmd_check_db)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
