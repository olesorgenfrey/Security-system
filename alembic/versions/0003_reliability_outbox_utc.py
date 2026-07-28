"""notification outbox and timezone-aware UTC timestamps

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28

Legacy timestamp-without-time-zone values are interpreted as UTC.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("events", "timestamp"),
    ("events", "created_at"),
    ("alerts", "created_at"),
    ("assets", "first_seen"),
    ("assets", "last_seen"),
    ("incidents", "created_at"),
    ("incidents", "updated_at"),
    ("incidents", "resolved_at"),
    ("audit_log", "timestamp"),
)


def upgrade() -> None:
    for table, column in TIMESTAMP_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"\"{column}\" AT TIME ZONE 'UTC'",
        )

    op.create_table(
        "notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deduplication_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "deduplication_key",
            name="uq_notification_outbox_deduplication_key",
        ),
    )
    op.create_index(
        "ix_notification_outbox_channel",
        "notification_outbox",
        ["channel"],
    )
    op.create_index(
        "ix_notification_outbox_status",
        "notification_outbox",
        ["status"],
    )
    op.create_index(
        "ix_notification_outbox_next_attempt_at",
        "notification_outbox",
        ["next_attempt_at"],
    )
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("notification_outbox")

    for table, column in TIMESTAMP_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            postgresql_using=f"\"{column}\" AT TIME ZONE 'UTC'",
        )
