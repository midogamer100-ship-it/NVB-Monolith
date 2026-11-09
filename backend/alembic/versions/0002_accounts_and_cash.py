"""Sign-up / password reset / demo mailbox / cash operations.

Revision ID: 0002_accounts_and_cash
Revises: 0001_initial
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_accounts_and_cash"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("used_at", TZ),
        sa.CheckConstraint("kind IN ('password_reset','account_setup')", name="ck_reset_tokens_kind"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("to_address", sa.String(254), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_outbox_messages_created_at", "outbox_messages", ["created_at"])
    op.create_table(
        "cash_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(140), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("failure_reason", sa.String(40)),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("completed_at", TZ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_cash_idempotency"),
        sa.CheckConstraint("kind IN ('deposit','withdrawal')", name="ck_cash_kind"),
        sa.CheckConstraint("amount_minor > 0", name="ck_cash_positive"),
        sa.CheckConstraint("status IN ('completed','failed')", name="ck_cash_status"),
    )
    op.create_index("ix_cash_operations_account_id", "cash_operations", ["account_id"])


def downgrade() -> None:
    op.drop_table("cash_operations")
    op.drop_table("outbox_messages")
    op.drop_table("password_reset_tokens")
