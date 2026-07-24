"""Event Bus auf Basis von Redis Streams (docs/architecture.md §3.2).

Collectors schreiben rohe, aber schon ECS-normalisierte Events (als JSON) in
den Stream `STREAM_KEY`. Der Consumer-Worker (core/ingestion/consumer.py)
liest daraus und persistiert nach Postgres.
"""

from __future__ import annotations

from typing import Any

import redis

from core.config import get_settings

STREAM_KEY = "aegis:events"
CONSUMER_GROUP = "aegis:storage"


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def publish_event(client: redis.Redis, event_json: str) -> str:
    """Schreibt ein normalisiertes Event (JSON-String) in den Stream. Gibt die Stream-ID zurück."""
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


def ack_event(client: redis.Redis, message_id: str) -> None:
    client.xack(STREAM_KEY, CONSUMER_GROUP, message_id)
