"""Alert-API (Phase 2): Auflisten der von der Detection Engine erzeugten Alerts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.storage.database import get_session
from core.storage.models import Alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def build_alerts_query(status: str | None) -> Select[tuple[Alert]]:
    stmt = select(Alert).order_by(Alert.created_at.desc())
    if status:
        stmt = stmt.where(Alert.status == status)
    return stmt


@router.get("")
def list_alerts(
    session: Annotated[Session, Depends(get_session)],
    status: str | None = None,
    limit: int = Query(default=50, le=500),
) -> list[dict[str, object]]:
    stmt = build_alerts_query(status).limit(limit)
    records = session.execute(stmt).scalars().all()
    return [
        {
            "id": str(a.id),
            "created_at": a.created_at.isoformat(),
            "rule_id": a.rule_id,
            "title": a.title,
            "description": a.description,
            "severity": a.severity,
            "mitre_technique": a.mitre_technique,
            "status": a.status,
            "host_name": a.host_name,
            "source_ip": a.source_ip,
        }
        for a in records
    ]
