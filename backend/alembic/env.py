"""Alembic environment.

Migrations are an explicit, single operation (`python -m app.cli migrate`, the
VM install step, or the OpenShift migration Job) - never run automatically by
every replica on startup. On PostgreSQL a session-level advisory lock makes an
accidental concurrent run wait instead of racing.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from app import models  # noqa: F401  (registers tables)
from app.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
MIGRATION_LOCK_ID = 727_274_001


def run_migrations_offline() -> None:
    url = config.attributes.get("url") or get_settings().migration_sqlalchemy_url()
    context.configure(url=str(url), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = config.attributes.get("url") or get_settings().migration_sqlalchemy_url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        is_pg = conn.dialect.name == "postgresql"
        if is_pg:
            conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
            conn.commit()
        try:
            _run(conn)
        finally:
            if is_pg:
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})
                conn.commit()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
