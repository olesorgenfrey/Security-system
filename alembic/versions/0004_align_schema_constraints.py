"""align model nullability and indexes with the database schema

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29

Existing nullable timestamp values are backfilled before the constraints are
tightened so upgrades remain safe for databases created by earlier releases.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_NULL_TIMESTAMPS: tuple[tuple[str, str], ...] = (
    ("events", "created_at"),
    ("alerts", "created_at"),
    ("assets", "first_seen"),
    ("assets", "last_seen"),
    ("incidents", "created_at"),
    ("incidents", "updated_at"),
    ("audit_log", "timestamp"),
)


def upgrade() -> None:
    for table, column in _NON_NULL_TIMESTAMPS:
        op.execute(
            sa.text(f'UPDATE "{table}" SET "{column}" = CURRENT_TIMESTAMP WHERE "{column}" IS NULL')
        )
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    # Keep uniqueness enforced while replacing the redundant constraint/index pair
    # with the single unique index represented by Asset.name in SQLAlchemy.
    op.drop_index("ix_assets_name", table_name="assets")
    op.create_index("ix_assets_name", "assets", ["name"], unique=True)
    op.drop_constraint("assets_name_key", "assets", type_="unique")

    op.create_index("ix_events_timestamp", "events", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_events_timestamp", table_name="events")

    op.create_unique_constraint("assets_name_key", "assets", ["name"])
    op.drop_index("ix_assets_name", table_name="assets")
    op.create_index("ix_assets_name", "assets", ["name"])

    for table, column in reversed(_NON_NULL_TIMESTAMPS):
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
