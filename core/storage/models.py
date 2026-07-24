"""SQLAlchemy-Modelle für Events, Assets, Incidents und Audit-Log.

Deckt die in der Architektur (docs/architecture.md §3.3) genannten
Kernentitäten ab. Events werden sowohl in Kernspalten (für Filter/Index)
als auch vollständig als JSONB (`raw`) gespeichert, damit das ECS-Schema
(core/schemas/event.py) sich weiterentwickeln kann, ohne Migrationen für
jedes neue Feld zu erzwingen.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.storage.database import Base


class IncidentStatus(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    CONTAINED = "contained"
    RESOLVED = "resolved"


class AssetCriticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventRecord(Base):
    """Persistierte, normalisierte Events (siehe core/schemas/event.py)."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_timestamp_severity", "timestamp", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(index=True)
    dataset: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(default="event")
    category: Mapped[list[str]] = mapped_column(JSONB, default=list)
    type: Mapped[list[str]] = mapped_column(JSONB, default=list)
    action: Mapped[str | None]
    outcome: Mapped[str] = mapped_column(default="unknown")
    severity: Mapped[int] = mapped_column(default=0, index=True)
    message: Mapped[str | None]

    host_name: Mapped[str] = mapped_column(index=True)
    source_ip: Mapped[str | None] = mapped_column(INET, index=True)
    destination_ip: Mapped[str | None] = mapped_column(INET)

    raw: Mapped[dict[str, object]] = mapped_column(JSONB)
    """Vollständiges, normalisiertes Event (ECS-JSON) als Fallback/Detailquelle."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Asset(Base):
    """Bekannte Assets (Hosts, Services, Container, ...) im überwachten Scope."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(unique=True, index=True)
    asset_type: Mapped[str] = mapped_column(default="host")
    ip_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list)
    criticality: Mapped[str] = mapped_column(default=AssetCriticality.MEDIUM)
    in_scope: Mapped[bool] = mapped_column(default=False)
    """Nur Assets mit in_scope=True dürfen gescannt oder von SOAR angefasst werden."""
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)

    first_seen: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Incident(Base):
    """Aus korrelierten Alerts entstandene Vorfälle (Lifecycle siehe Roadmap Phase 2)."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str]
    description: Mapped[str | None]
    status: Mapped[str] = mapped_column(default=IncidentStatus.NEW, index=True)
    severity: Mapped[int] = mapped_column(default=0, index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None]

    events: Mapped[list[IncidentEvent]] = relationship(back_populates="incident")


class IncidentEvent(Base):
    """Verknüpft Events mit dem Incident, zu dem sie korreliert wurden."""

    __tablename__ = "incident_events"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), primary_key=True
    )

    incident: Mapped[Incident] = relationship(back_populates="events")


class AuditLogEntry(Base):
    """Lückenloses Audit-Log jeder System- und Response-Aktion (Architektur §3.7)."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    actor: Mapped[str]
    """z.B. 'system', 'user:<name>', 'playbook:<name>'."""
    action: Mapped[str]
    target: Mapped[str | None]
    outcome: Mapped[str] = mapped_column(default="success")
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
