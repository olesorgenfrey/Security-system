from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from core.config import get_settings
from core.ingestion.bus import (
    CONSUMER_GROUP,
    DEAD_LETTER_STREAM_KEY,
    DELIVERY_ATTEMPTS_KEY,
    STREAM_KEY,
    ensure_consumer_group,
    get_redis,
    publish_event,
    read_events,
)
from core.ingestion.consumer import _handle_message, process_message
from core.schemas.event import Event, EventCategory, EventMeta, EventOutcome, EventType
from core.storage.database import SessionLocal
from core.storage.models import EventRecord, NotificationOutbox

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_SERVICE_TESTS") != "1",
        reason="requires explicitly enabled PostgreSQL and Redis services",
    ),
]


def test_redis_to_postgres_pipeline_is_idempotent_and_acks_after_commit() -> None:
    event_id = uuid4()
    event = Event.model_validate(
        {
            "@timestamp": datetime.now(UTC),
            "event": EventMeta(
                id=event_id,
                dataset="integration.pipeline",
                category=[EventCategory.AUTHENTICATION],
                type=[EventType.INFO],
                outcome=EventOutcome.FAILURE,
                severity=80,
            ),
            "message": "Integration pipeline delivery",
            "host": {"name": "integration-host"},
        }
    )
    raw_json = event.model_dump_json(by_alias=True)
    client = get_redis()

    # CI provides a dedicated Redis instance. Reset only Aegis transport keys so
    # the assertion is deterministic and never flush unrelated Redis data.
    client.delete(STREAM_KEY, DEAD_LETTER_STREAM_KEY, DELIVERY_ATTEMPTS_KEY)
    ensure_consumer_group(client)

    try:
        publish_event(client, raw_json)
        messages = read_events(client, "integration-test", count=1, block_ms=100)
        assert len(messages) == 1
        message_id, fields = messages[0]

        assert process_message(client, message_id, fields, max_attempts=3)
        assert client.xlen(STREAM_KEY) == 0
        assert client.xpending(STREAM_KEY, CONSUMER_GROUP)["pending"] == 0

        with SessionLocal() as session:
            assert session.get(EventRecord, event_id) is not None
            outbox_count = session.scalar(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(NotificationOutbox.deduplication_key == f"event:{event_id}:webhook")
            )
            assert outbox_count == 1

        # Simulate a consumer crash after DB commit but before its Redis ACK.
        # Replaying the same UUID must neither duplicate the event nor its outbox row.
        assert _handle_message(raw_json) is False
        with SessionLocal() as session:
            event_count = session.scalar(
                select(func.count()).select_from(EventRecord).where(EventRecord.id == event_id)
            )
            outbox_count = session.scalar(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(NotificationOutbox.deduplication_key == f"event:{event_id}:webhook")
            )
            assert event_count == 1
            assert outbox_count == 1
    finally:
        with SessionLocal() as session:
            session.execute(
                delete(NotificationOutbox).where(
                    NotificationOutbox.deduplication_key.like(f"event:{event_id}:%")
                )
            )
            session.execute(delete(EventRecord).where(EventRecord.id == event_id))
            session.commit()
        client.delete(STREAM_KEY, DEAD_LETTER_STREAM_KEY, DELIVERY_ATTEMPTS_KEY)
        get_settings.cache_clear()
