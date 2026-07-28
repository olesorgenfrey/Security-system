"""Zuverlässiger Consumer für normalisierte Events aus Redis Streams.

Die Verarbeitung ist at-least-once: Erst nach dem gemeinsamen Commit von
Event, Alerts und Notification-Outbox wird die Redis-Nachricht bestätigt.
Die Event-UUID macht Wiederholungen nach einem Crash idempotent.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from typing import Any

import redis
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from core.config import get_settings
from core.detection.rules import evaluate as evaluate_detection_rules
from core.ingestion.bus import (
    CONSUMER_GROUP,
    ack_event,
    claim_stale_events,
    dead_letter_event,
    ensure_consumer_group,
    get_redis,
    read_events,
    start_delivery_attempt,
)
from core.ingestion.normalizer import normalize
from core.notify import queue_notification
from core.schemas.event import Event
from core.storage.database import SessionLocal
from core.storage.models import EventRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("aegis.consumer")


class InvalidEventError(ValueError):
    """Die Stream-Nachricht ist dauerhaft kein gültiges Aegis-Event."""


def _to_record(event: Event) -> EventRecord:
    host_ip = str(event.source.ip) if event.source and event.source.ip else None
    dest_ip = str(event.destination.ip) if event.destination and event.destination.ip else None
    return EventRecord(
        id=event.event.id,
        timestamp=event.timestamp,
        dataset=event.event.dataset,
        kind=event.event.kind.value,
        category=[category.value for category in event.event.category],
        type=[event_type.value for event_type in event.event.type],
        action=event.event.action,
        outcome=event.event.outcome.value,
        severity=event.event.severity,
        message=event.message,
        host_name=event.host.name,
        source_ip=host_ip,
        destination_ip=dest_ip,
        raw=json.loads(event.model_dump_json(by_alias=True)),
    )


def _parse_event(raw_json: str) -> Event:
    try:
        payload: Any = json.loads(raw_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidEventError(f"Ungültiges JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidEventError("Event-Payload muss ein JSON-Objekt sein")
    try:
        return normalize(payload)
    except ValidationError as exc:
        raise InvalidEventError(f"Schema-Validierung fehlgeschlagen: {exc}") from exc


def _event_notification_text(event: Event) -> str:
    return (
        f"Host: {event.host.name} | Dataset: {event.event.dataset} | "
        f"Severity: {event.event.severity} | {event.message or ''}"
    )


def _handle_message(raw_json: str) -> bool:
    """Persistiert ein Event vollständig; gibt False für ein bereits vorhandenes Event zurück."""
    event = _parse_event(raw_json)

    with SessionLocal() as session:
        if session.get(EventRecord, event.event.id) is not None:
            logger.info("Event %s bereits verarbeitet; ACK kann sicher erfolgen", event.event.id)
            return False

        try:
            record = _to_record(event)
            session.add(record)
            # Detection-Abfragen müssen das aktuelle Event bereits in ihrer Transaktion sehen.
            session.flush()

            alerts = evaluate_detection_rules(session, record)
            # UUID-Defaults der neuen Alerts materialisieren, bevor Dedupe-Keys entstehen.
            session.flush()

            settings = get_settings()
            if event.event.severity >= settings.notify_severity_threshold:
                queue_notification(
                    session,
                    title=event.message or event.event.action or event.event.dataset,
                    message=_event_notification_text(event),
                    severity=event.event.severity,
                    deduplication_key=f"event:{event.event.id}",
                    settings=settings,
                )

            for alert in alerts:
                queue_notification(
                    session,
                    title=alert.title,
                    message=alert.description or "",
                    severity=alert.severity,
                    deduplication_key=f"alert:{alert.id}",
                    settings=settings,
                )

            # Ein Commit umfasst Event, Detection-Ergebnisse und alle Outbox-Aufträge.
            session.commit()
            return True
        except IntegrityError:
            # Zwei Consumer können dieselbe Event-UUID parallel gesehen haben. Hat der
            # Gewinner committed, ist die Nachricht bereits vollständig verarbeitet.
            session.rollback()
            if session.get(EventRecord, event.event.id) is not None:
                logger.info("Event %s wurde parallel verarbeitet", event.event.id)
                return False
            raise


def _raw_data(fields: dict[str, Any]) -> str:
    data = fields.get("data")
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidEventError(f"Event-Daten sind nicht UTF-8: {exc}") from exc
    if not isinstance(data, str):
        raise InvalidEventError("Stream-Nachricht enthält kein String-Feld 'data'")
    return data


def process_message(
    client: redis.Redis,
    message_id: str,
    fields: dict[str, Any],
    *,
    max_attempts: int,
) -> bool:
    """Verarbeitet genau eine Nachricht und wahrt ACK-/DLQ-Reihenfolge.

    Rückgabewert True bedeutet ACK oder atomarer DLQ+ACK. False bedeutet,
    dass ein transienter Fehler die Nachricht absichtlich pending lässt.
    """
    attempt = start_delivery_attempt(client, message_id)
    try:
        raw_json = _raw_data(fields)
        _handle_message(raw_json)
    except InvalidEventError as exc:
        dead_letter_event(client, message_id, fields, str(exc), attempt)
        logger.warning("Ungültiges Event %s nach DLQ verschoben: %s", message_id, exc)
        return True
    except Exception as exc:
        if attempt >= max_attempts:
            reason = f"{type(exc).__name__}: {exc}"
            dead_letter_event(client, message_id, fields, reason, attempt)
            logger.exception(
                "Event %s nach %s transienten Fehlern in DLQ verschoben",
                message_id,
                attempt,
            )
            return True
        logger.exception(
            "Fehler beim Verarbeiten von %s (Versuch %s/%s); bleibt pending",
            message_id,
            attempt,
            max_attempts,
        )
        return False

    ack_event(client, message_id)
    return True


def _process_batch(
    client: redis.Redis,
    messages: list[tuple[str, dict[str, Any]]],
    *,
    max_attempts: int,
) -> None:
    for message_id, fields in messages:
        try:
            process_message(client, message_id, fields, max_attempts=max_attempts)
        except redis.exceptions.RedisError:
            # Wenn ACK oder DLQ fehlschlägt, bleibt die Nachricht in Redis pending.
            logger.exception("Redis-Fehler beim Abschluss von %s; bleibt pending", message_id)


def run() -> None:
    settings = get_settings()
    client = get_redis()
    ensure_consumer_group(client)
    consumer_name = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("Consumer '%s' gestartet, Gruppe '%s'", consumer_name, CONSUMER_GROUP)

    last_recovery = 0.0
    while True:
        try:
            monotonic_now = time.monotonic()
            if monotonic_now - last_recovery >= settings.ingestion_recovery_interval_seconds:
                recovered = claim_stale_events(
                    client,
                    consumer_name,
                    settings.ingestion_pending_idle_ms,
                    settings.ingestion_recovery_batch_size,
                )
                _process_batch(
                    client,
                    recovered,
                    max_attempts=settings.ingestion_max_delivery_attempts,
                )
                last_recovery = monotonic_now

            messages = read_events(client, consumer_name)
            _process_batch(
                client,
                messages,
                max_attempts=settings.ingestion_max_delivery_attempts,
            )
        except redis.exceptions.TimeoutError:
            continue
        except redis.exceptions.RedisError:
            logger.exception("Redis-Verbindung im Consumer fehlgeschlagen; neuer Versuch folgt")
            time.sleep(settings.ingestion_error_backoff_seconds)


if __name__ == "__main__":
    run()
