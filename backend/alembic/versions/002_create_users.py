"""002_create_users

Revision ID: 002
Revises: 001
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgENUM
from sqlalchemy.dialects.postgresql import ARRAY, INET

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("plan", PgENUM(name="plan_type", create_type=False), nullable=False, server_default="free"),
        sa.Column("risk_profile", PgENUM(name="risk_profile_type", create_type=False), nullable=False, server_default="moderate"),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Seoul"),
        sa.Column("is_email_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("email_verify_token", sa.String(64), nullable=True),
        sa.Column("email_verify_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_2fa_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("totp_secret_encrypted", sa.Text, nullable=True),
        sa.Column("totp_backup_codes", ARRAY(sa.Text()), nullable=True),
        sa.Column("login_attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_login_ip", INET(), nullable=True),
        sa.Column("password_changed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            r"email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'",
            name="users_email_format",
        ),
        sa.CheckConstraint(
            "login_attempts >= 0 AND login_attempts <= 10",
            name="users_login_attempts_range",
        ),
    )
    op.create_index(
        "idx_users_email_active", "users", ["email"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_users_deleted_at", "users", ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index(
        "idx_users_plan", "users", ["plan"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_users_plan", table_name="users")
    op.drop_index("idx_users_deleted_at", table_name="users")
    op.drop_index("idx_users_email_active", table_name="users")
    op.drop_table("users")
