"""initial schema: events, assets, incidents, incident_events, audit_log

Revision ID: 0001
Revises:
Create Date: 2026-07-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("dataset", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="event"),
        sa.Column("category", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("type", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("host_name", sa.String(), nullable=False),
        sa.Column("source_ip", postgresql.INET(), nullable=True),
        sa.Column("destination_ip", postgresql.INET(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_events_timestamp_severity", "events", ["timestamp", "severity"])
    op.create_index("ix_events_dataset", "events", ["dataset"])
    op.create_index("ix_events_severity", "events", ["severity"])
    op.create_index("ix_events_host_name", "events", ["host_name"])
    op.create_index("ix_events_source_ip", "events", ["source_ip"])

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("asset_type", sa.String(), nullable=False, server_default="host"),
        sa.Column("ip_addresses", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("criticality", sa.String(), nullable=False, server_default="medium"),
        sa.Column("in_scope", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("first_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_assets_name", "assets", ["name"])

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])

    op.create_table(
        "incident_events",
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id"),
            primary_key=True,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id"),
            primary_key=True,
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False, server_default="success"),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("incident_events")
    op.drop_table("incidents")
    op.drop_table("assets")
    op.drop_table("events")
