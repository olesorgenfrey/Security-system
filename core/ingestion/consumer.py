"""Consumer-Worker: liest normalisierte Events vom Bus und persistiert sie.

Läuft als eigener Dauerprozess (siehe deploy/docker-compose.yml, Service
`worker`). Trennung von API und Ingestion hält beide Seiten unabhängig
skalierbar (architecture.md Designprinzip 1).
"""

from __future__ import annotations

import json
import logging
import os
import socket

import redis
from pydantic import ValidationError

from core.ingestion.bus import (
    CONSUMER_GROUP,
    ack_event,
    ensure_consumer_group,
    get_redis,
    read_events,
)
from core.ingestion.normalizer import normalize
from core.notify import notify
from core.schemas.event import Event
from core.storage.database import SessionLocal
from core.storage.models import EventRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("aegis.consumer")


def _to_record(event: Event) -> EventRecord:
    host_ip = str(event.source.ip) if event.source and event.source.ip else None
    dest_ip = str(event.destination.ip) if event.destination and event.destination.ip else None
    return EventRecord(
        id=event.event.id,
        timestamp=event.timestamp,
        dataset=event.event.dataset,
        kind=event.event.kind.value,
        category=[c.value for c in event.event.category],
        type=[t.value for t in event.event.type],
        action=event.event.action,
        outcome=event.event.outcome.value,
        severity=event.event.severity,
        message=event.message,
        host_name=event.host.name,
        source_ip=host_ip,
        destination_ip=dest_ip,
        raw=json.loads(event.model_dump_json(by_alias=True)),
    )


def _handle_message(raw_json: str) -> None:
    payload = json.loads(raw_json)
    try:
        event = normalize(payload)
    except ValidationError:
        logger.exception("Ungültiges Event verworfen: %s", raw_json[:200])
        return

    with SessionLocal() as session:
        session.add(_to_record(event))
        session.commit()

    from core.config import get_settings

    threshold = get_settings().notify_severity_threshold
    if event.event.severity >= threshold:
        notify(
            title=event.message or event.event.action or event.event.dataset,
            message=(
                f"Host: {event.host.name} | Dataset: {event.event.dataset} | "
                f"Severity: {event.event.severity} | {event.message or ''}"
            ),
            severity=event.event.severity,
        )


def run() -> None:
    client = get_redis()
    ensure_consumer_group(client)
    consumer_name = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("Consumer '%s' gestartet, Gruppe '%s'", consumer_name, CONSUMER_GROUP)

    while True:
        try:
            messages = read_events(client, consumer_name)
        except redis.exceptions.TimeoutError:
            # Erwartbar bei blockierendem XREADGROUP ohne neue Nachrichten; erneut versuchen.
            continue

        for message_id, fields in messages:
            try:
                _handle_message(fields["data"])
            except Exception:
                logger.exception("Fehler beim Verarbeiten von %s", message_id)
            finally:
                ack_event(client, message_id)


if __name__ == "__main__":
    run()
