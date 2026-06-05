"""011_create_notifications

Revision ID: 011
Revises: 010
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Enum(name="notification_type_enum", create_type=False), nullable=False),
        sa.Column("channel", sa.Enum(name="notification_channel_type", create_type=False), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("is_sent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("retry_count >= 0", name="notifications_retry_non_negative"),
        sa.CheckConstraint("sent_at IS NULL OR sent_at >= created_at", name="notifications_sent_at_after_created"),
    )
    op.create_index("idx_notifications_pending", "notifications", ["created_at"],
                    postgresql_where=sa.text("is_sent = FALSE AND (next_retry_at IS NULL OR next_retry_at <= NOW())"))
    op.create_index("idx_notifications_retry", "notifications", ["next_retry_at"],
                    postgresql_where=sa.text("is_sent = FALSE AND retry_count > 0 AND retry_count < 3"))
    op.create_index("idx_notifications_user_created", "notifications", ["user_id", "created_at"],
                    postgresql_where=sa.text("channel = 'web_push'"))
    op.create_index("idx_notifications_unread", "notifications", ["user_id"],
                    postgresql_where=sa.text("channel = 'web_push' AND read_at IS NULL AND is_sent = TRUE"))
    op.create_index("idx_notifications_user_type", "notifications", ["user_id", "type", "created_at"])


def downgrade() -> None:
    for idx in ["idx_notifications_user_type", "idx_notifications_unread",
                "idx_notifications_user_created", "idx_notifications_retry",
                "idx_notifications_pending"]:
        op.drop_index(idx, table_name="notifications")
    op.drop_table("notifications")
