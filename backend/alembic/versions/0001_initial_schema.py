"""Initial NVB schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_load_test", sa.Boolean(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("last_login_at", TZ),
        sa.CheckConstraint("role IN ('customer','admin','demo')", name="ck_users_role"),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("customer_number", sa.String(16), nullable=False, unique=True),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("preferred_name", sa.String(60)),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("city", sa.String(60), nullable=False),
        sa.Column("segment", sa.String(20), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_number", sa.String(20), nullable=False, unique=True),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("nickname", sa.String(60), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("balance_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("opened_at", TZ, nullable=False),
        sa.CheckConstraint("balance_minor >= 0", name="ck_accounts_non_negative"),
        sa.CheckConstraint("currency = 'EGP'", name="ck_accounts_currency"),
    )
    op.create_index("ix_accounts_customer_id", "accounts", ["customer_id"])
    op.create_table(
        "beneficiaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nickname", sa.String(60), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.UniqueConstraint("customer_id", "account_id", name="uq_beneficiary_customer_account"),
    )
    op.create_index("ix_beneficiaries_customer_id", "beneficiaries", ["customer_id"])
    op.create_table(
        "transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("initiated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("destination_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.String(140), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("failure_reason", sa.String(40)),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("completed_at", TZ),
        sa.UniqueConstraint("initiated_by_user_id", "idempotency_key", name="uq_transfers_idempotency"),
        sa.CheckConstraint("amount_minor > 0", name="ck_transfers_positive"),
        sa.CheckConstraint("status IN ('completed','failed')", name="ck_transfers_status"),
    )
    op.create_index("ix_transfers_source_account_id", "transfers", ["source_account_id"])
    op.create_index("ix_transfers_destination_account_id", "transfers", ["destination_account_id"])
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("transfers.id")),
        sa.Column("reference", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("txn_type", sa.String(24), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_minor", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(140), nullable=False),
        sa.Column("counterparty", sa.String(120), nullable=False),
        sa.Column("posted_at", TZ, nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_ledger_positive"),
        sa.CheckConstraint("direction IN ('debit','credit')", name="ck_ledger_direction"),
    )
    op.create_index("ix_ledger_account_posted", "ledger_entries", ["account_id", "posted_at"])
    op.create_index("ix_ledger_entries_transfer_id", "ledger_entries", ["transfer_id"])
    op.create_index("ix_ledger_entries_reference", "ledger_entries", ["reference"])
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("last_seen_at", TZ, nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("absolute_expires_at", TZ, nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_type", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("attempted_at", TZ, nullable=False),
    )
    op.create_index("ix_login_attempts_key_time", "login_attempts", ["key_type", "key_hash", "attempted_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(12), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_username", sa.String(64)),
        sa.Column("source_ip", sa.String(45)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    for table in ("audit_events", "login_attempts", "user_sessions", "ledger_entries", "transfers",
                  "beneficiaries", "accounts", "customers", "users"):
        op.drop_table(table)
