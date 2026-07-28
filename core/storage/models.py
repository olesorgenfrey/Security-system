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

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
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
    __table_args__ = (Index("ix_events_timestamp_severity", "timestamp", "severity"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


class Alert(Base):
    """Von der Detection Engine (Phase 2) erzeugte Alerts aus verdächtigen Event-Mustern."""

    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_created_at_severity", "created_at", "severity"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[str] = mapped_column(index=True)
    """z.B. 'brute_force_ssh' — eindeutiger Name der auslösenden Detection-Regel."""
    title: Mapped[str]
    description: Mapped[str | None]
    severity: Mapped[int] = mapped_column(default=0, index=True)
    mitre_technique: Mapped[str | None]
    """MITRE-ATT&CK-Technik-ID, z.B. 'T1110' (Brute Force)."""
    status: Mapped[str] = mapped_column(default=AlertStatus.OPEN, index=True)

    host_name: Mapped[str | None] = mapped_column(index=True)
    source_ip: Mapped[str | None] = mapped_column(INET, index=True)
    event_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    """IDs der Events, die diesen Alert ausgelöst haben."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Asset(Base):
    """Bekannte Assets (Hosts, Services, Container, ...) im überwachten Scope."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    asset_type: Mapped[str] = mapped_column(default="host")
    ip_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list)
    criticality: Mapped[str] = mapped_column(default=AssetCriticality.MEDIUM)
    in_scope: Mapped[bool] = mapped_column(default=False)
    """Nur Assets mit in_scope=True dürfen gescannt oder von SOAR angefasst werden."""
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Incident(Base):
    """Aus korrelierten Alerts entstandene Vorfälle (Lifecycle siehe Roadmap Phase 2)."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str]
    description: Mapped[str | None]
    status: Mapped[str] = mapped_column(default=IncidentStatus.NEW, index=True)
    severity: Mapped[int] = mapped_column(default=0, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor: Mapped[str]
    """z.B. 'system', 'user:<name>', 'playbook:<name>'."""
    action: Mapped[str]
    target: Mapped[str | None]
    outcome: Mapped[str] = mapped_column(default="success")
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class NotificationChannel(StrEnum):
    WEBHOOK = "webhook"
    EMAIL = "email"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class NotificationOutbox(Base):
    """Persistenter, kanalweiser Zustellauftrag für Benachrichtigungen."""

    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_notification_outbox_due", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(index=True)
    title: Mapped[str]
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[int] = mapped_column(default=0)
    deduplication_key: Mapped[str] = mapped_column(unique=True)

    status: Mapped[str] = mapped_column(default=NotificationStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
