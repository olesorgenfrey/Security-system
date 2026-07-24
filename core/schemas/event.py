"""Gemeinsames Event-Schema, angelehnt an das Elastic Common Schema (ECS).

Jede Komponente (Collector, Normalizer, Detection Engine, Storage) spricht
dieses Schema. Nur Felder, die die Roadmap-Phasen 1-4 tatsächlich brauchen,
sind modelliert — ECS selbst hat weit mehr Felder, die bei Bedarf ergänzt
werden können.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress


class EventKind(StrEnum):
    """ECS event.kind — grobe Klassifizierung des Events."""

    EVENT = "event"
    ALERT = "alert"
    METRIC = "metric"
    STATE = "state"


class EventCategory(StrEnum):
    """ECS event.category (Ausschnitt, passend zu Collectors/Detection-Scope)."""

    AUTHENTICATION = "authentication"
    PROCESS = "process"
    NETWORK = "network"
    FILE = "file"
    MALWARE = "malware"
    INTRUSION_DETECTION = "intrusion_detection"
    VULNERABILITY = "vulnerability"
    CONFIGURATION = "configuration"
    HOST = "host"
    WEB = "web"


class EventType(StrEnum):
    """ECS event.type — verfeinert die Kategorie."""

    START = "start"
    END = "end"
    INFO = "info"
    CONNECTION = "connection"
    DENIED = "denied"
    ALLOWED = "allowed"
    CREATION = "creation"
    DELETION = "deletion"
    CHANGE = "change"


class EventOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


class Host(BaseModel):
    name: str
    ip: list[IPvAnyAddress] = Field(default_factory=list)
    os: str | None = None


class Source(BaseModel):
    ip: IPvAnyAddress | None = None
    port: int | None = None
    user: str | None = None


class Destination(BaseModel):
    ip: IPvAnyAddress | None = None
    port: int | None = None


class Process(BaseModel):
    pid: int | None = None
    name: str | None = None
    command_line: str | None = None
    executable: str | None = None


class Network(BaseModel):
    protocol: str | None = None
    transport: str | None = None
    bytes: int | None = None


class FileInfo(BaseModel):
    path: str | None = None
    hash_sha256: str | None = None


class EventMeta(BaseModel):
    """ECS event.* — Metadaten über das Event selbst."""

    id: UUID = Field(default_factory=uuid4)
    kind: EventKind = EventKind.EVENT
    category: list[EventCategory] = Field(default_factory=list)
    type: list[EventType] = Field(default_factory=list)
    action: str | None = None
    outcome: EventOutcome = EventOutcome.UNKNOWN
    # 0-100, ECS-Konvention: höher = kritischer.
    severity: int = Field(default=0, ge=0, le=100)
    dataset: str
    """Welcher Collector/welche Quelle das Event erzeugt hat, z.B. 'host_agent.syslog'."""


class Event(BaseModel):
    """Ein einzelnes, normalisiertes Sicherheitsereignis."""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: datetime = Field(alias="@timestamp", default_factory=datetime.utcnow)
    event: EventMeta
    message: str | None = None

    host: Host
    source: Source | None = None
    destination: Destination | None = None
    process: Process | None = None
    network: Network | None = None
    file: FileInfo | None = None

    tags: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
