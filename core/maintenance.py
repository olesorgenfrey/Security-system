"""Gebündelte Datenpflege für Aegis.

``python -m core.maintenance`` startet den periodischen Dienst;
``python -m core.maintenance --once`` führt genau einen Retention-Lauf aus.
Events, die als Incident-Evidenz referenziert sind, werden nie automatisch
gelöscht.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.storage.database import SessionLocal
from core.storage.models import EventRecord, IncidentEvent

logger = logging.getLogger("aegis.maintenance")


def delete_expired_events_batch(
    session: Session,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
    batch_size: int | None = None,
) -> int:
    """Löscht und committed höchstens eine Charge nicht referenzierter alter Events."""
    settings = get_settings()
    days = settings.event_retention_days if retention_days is None else retention_days
    limit = settings.event_retention_batch_size if batch_size is None else batch_size
    if days <= 0:
        raise ValueError("event_retention_days muss größer als 0 sein")
    if limit <= 0:
        raise ValueError("event_retention_batch_size muss größer als 0 sein")

    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    else:
        reference_time = reference_time.astimezone(UTC)
    cutoff = reference_time - timedelta(days=days)

    incident_reference = select(IncidentEvent.event_id).where(
        IncidentEvent.event_id == EventRecord.id
    )
    id_statement = (
        select(EventRecord.id)
        .where(
            EventRecord.timestamp < cutoff,
            ~exists(incident_reference),
        )
        .order_by(EventRecord.timestamp)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    event_ids = list(session.scalars(id_statement))
    if not event_ids:
        session.rollback()
        return 0

    session.execute(delete(EventRecord).where(EventRecord.id.in_(event_ids)))
    session.commit()
    return len(event_ids)


def run_retention_once() -> int:
    """Leert alle fälligen Events in begrenzten Einzeltransaktionen."""
    deleted_total = 0
    while True:
        with SessionLocal() as session:
            deleted = delete_expired_events_batch(session)
        deleted_total += deleted
        if deleted == 0:
            logger.info("Event-Retention beendet: %s Events gelöscht", deleted_total)
            return deleted_total


def run() -> None:
    """Startet Retention sofort und danach im konfigurierten Intervall."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Maintenance-Worker gestartet")
    while True:
        try:
            run_retention_once()
        except Exception:
            logger.exception("Event-Retention fehlgeschlagen")
        time.sleep(settings.maintenance_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis-Datenpflege")
    parser.add_argument("--once", action="store_true", help="Retention einmal ausführen")
    args = parser.parse_args()
    if args.once:
        run_retention_once()
    else:
        run()


if __name__ == "__main__":
    main()
