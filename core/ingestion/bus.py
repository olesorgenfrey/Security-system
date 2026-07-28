"""Event Bus auf Basis von Redis Streams (docs/architecture.md §3.2).

Collectors schreiben rohe, aber schon ECS-normalisierte Events (als JSON) in
den Stream `STREAM_KEY`. Der Consumer-Worker (core/ingestion/consumer.py)
liest daraus und persistiert nach Postgres. Aegis verwendet genau eine
Consumer-Gruppe; nach deren ACK wird der Quell-Eintrag atomar gelöscht.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import redis

from core.config import get_settings

STREAM_KEY = "aegis:events"
CONSUMER_GROUP = "aegis:storage"
DEAD_LETTER_STREAM_KEY = "aegis:events:dead-letter"
DELIVERY_ATTEMPTS_KEY = "aegis:events:delivery-attempts"


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def publish_event(client: redis.Redis, event_json: str) -> str:
    """Schreibt ein normalisiertes Event (JSON-String) in den Stream. Gibt die Stream-ID zurück."""
    # Kein blindes MAXLEN: Das könnte bei Rückstau noch nicht bestätigte Events
    # abschneiden. Erfolgreiche Einträge werden stattdessen bei ACK gezielt gelöscht.
    return str(client.xadd(STREAM_KEY, {"data": event_json}))


def ensure_consumer_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def read_events(
    client: redis.Redis, consumer_name: str, count: int = 50, block_ms: int = 5000
) -> list[tuple[str, dict[str, Any]]]:
    """Liest neue Nachrichten für einen Consumer innerhalb der Gruppe (blockierend)."""
    resp: Any = client.xreadgroup(
        CONSUMER_GROUP, consumer_name, {STREAM_KEY: ">"}, count=count, block=block_ms
    )
    if not resp:
        return []
    _, messages = resp[0]
    return [(str(message_id), dict(fields)) for message_id, fields in messages]


def claim_stale_events(
    client: redis.Redis,
    consumer_name: str,
    min_idle_ms: int,
    count: int = 50,
) -> list[tuple[str, dict[str, Any]]]:
    """Übernimmt verwaiste Pending-Nachrichten eines ausgefallenen Consumers.

    `XAUTOCLAIM` ändert nur den Besitzer der Nachricht; die Nachricht bleibt bis
    zum expliziten ACK in der Pending Entries List der Consumer-Gruppe.
    """
    response: Any = client.xautoclaim(
        STREAM_KEY,
        CONSUMER_GROUP,
        consumer_name,
        min_idle_ms,
        start_id="0-0",
        count=count,
    )
    if not response or len(response) < 2:
        return []
    messages: Any = response[1]
    return [(str(message_id), dict(fields)) for message_id, fields in messages]


def start_delivery_attempt(client: redis.Redis, message_id: str) -> int:
    """Zählt persistente Zustellversuche unabhängig vom Consumer-Prozess."""
    return int(client.hincrby(DELIVERY_ATTEMPTS_KEY, message_id, 1))


def ack_event(client: redis.Redis, message_id: str) -> None:
    """ACKt und löscht die Nachricht für die einzige Aegis-Gruppe atomar."""
    pipeline = client.pipeline(transaction=True)
    pipeline.xack(STREAM_KEY, CONSUMER_GROUP, message_id)
    pipeline.xdel(STREAM_KEY, message_id)
    pipeline.hdel(DELIVERY_ATTEMPTS_KEY, message_id)
    pipeline.execute()


def dead_letter_event(
    client: redis.Redis,
    message_id: str,
    fields: dict[str, Any],
    reason: str,
    attempts: int,
) -> str:
    """Persistiert eine nicht verarbeitbare Nachricht im DLQ-Stream und ACKt atomar."""
    dead_letter: dict[Any, Any] = {
        "source_stream": STREAM_KEY,
        "source_group": CONSUMER_GROUP,
        "source_message_id": message_id,
        "attempts": str(attempts),
        "failed_at": datetime.now(UTC).isoformat(),
        "reason": reason[:2000],
        "fields": json.dumps(fields, ensure_ascii=False, default=str),
    }
    pipeline = client.pipeline(transaction=True)
    pipeline.xadd(
        DEAD_LETTER_STREAM_KEY,
        dead_letter,
        maxlen=get_settings().ingestion_dlq_maxlen,
        approximate=True,
    )
    pipeline.xack(STREAM_KEY, CONSUMER_GROUP, message_id)
    pipeline.xdel(STREAM_KEY, message_id)
    pipeline.hdel(DELIVERY_ATTEMPTS_KEY, message_id)
    results: list[Any] = pipeline.execute()
    return str(results[0])
