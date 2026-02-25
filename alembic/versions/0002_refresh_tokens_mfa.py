"""refresh tokens rotation + MFA fields

Revision ID: 0002_refresh_tokens_mfa
Revises: 0001_init
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_refresh_tokens_mfa"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade():
    # accounts: MFA fields
    op.add_column("accounts", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("accounts", sa.Column("mfa_secret", sa.String(length=64), nullable=True))
    op.add_column("accounts", sa.Column("mfa_verified_at", sa.DateTime(), nullable=True))

    # refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False, index=True),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("replaced_by_jti", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(length=300), nullable=False, server_default=""),
    )
    op.create_index("ix_refresh_tokens_account_id", "refresh_tokens", ["account_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True)
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])


def downgrade():
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_account_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_column("accounts", "mfa_verified_at")
    op.drop_column("accounts", "mfa_secret")
    op.drop_column("accounts", "mfa_enabled")
