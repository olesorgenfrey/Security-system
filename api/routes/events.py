"""Event-API (Phase 1): Auflisten/Filtern der gespeicherten Events."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.schemas.event import EventCategory
from core.storage.database import get_session
from core.storage.models import EventRecord

router = APIRouter(prefix="/api/events", tags=["events"])


def build_events_query(
    host: str | None,
    category: str | None,
    min_severity: int,
    search: str | None,
) -> Select[tuple[EventRecord]]:
    stmt = select(EventRecord).order_by(EventRecord.timestamp.desc())
    if host:
        stmt = stmt.where(EventRecord.host_name == host)
    if category:
        stmt = stmt.where(EventRecord.category.contains([category]))
    if min_severity:
        stmt = stmt.where(EventRecord.severity >= min_severity)
    if search:
        stmt = stmt.where(EventRecord.message.ilike(f"%{search}%"))
    return stmt


@router.get("")
def list_events(
    session: Annotated[Session, Depends(get_session)],
    host: Annotated[str | None, Query(max_length=255)] = None,
    category: EventCategory | None = None,
    min_severity: Annotated[int, Query(ge=0, le=100)] = 0,
    search: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[dict[str, object]]:
    stmt = build_events_query(host, category, min_severity, search).limit(limit)
    records = session.execute(stmt).scalars().all()
    return [
        {
            "id": str(r.id),
            "timestamp": r.timestamp.isoformat(),
            "dataset": r.dataset,
            "category": r.category,
            "severity": r.severity,
            "outcome": r.outcome,
            "message": r.message,
            "host_name": r.host_name,
            "source_ip": r.source_ip,
        }
        for r in records
    ]
