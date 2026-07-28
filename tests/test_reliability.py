from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import DateTime
from sqlalchemy.orm import Session

from core import maintenance, notification_worker
from core.config import HostAgentSettings, Settings
from core.ingestion import bus, consumer
from core.notify import queue_notification
from core.schemas.event import Event
from core.storage.models import (
    EventRecord,
    NotificationChannel,
    NotificationOutbox,
    NotificationStatus,
)


def _event_json(*, severity: int = 80) -> str:
    return json.dumps(
        {
            "@timestamp": "2026-07-28T12:00:00Z",
            "event": {"dataset": "test", "severity": severity},
            "host": {"name": "test-host"},
            "message": "test event",
        }
    )


def _settings(**values: Any) -> Settings:
    return Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://test:test@127.0.0.1:5432/aegis_test",
            "redis_url": "redis://127.0.0.1:6379/15",
            **values,
        }
    )


def test_event_timestamp_normalizes_naive_and_offset_to_utc() -> None:
    base = {"event": {"dataset": "test"}, "host": {"name": "host"}}
    naive = Event.model_validate({**base, "@timestamp": "2026-07-28T12:00:00"})
    offset = Event.model_validate({**base, "@timestamp": "2026-07-28T14:00:00+02:00"})

    assert naive.timestamp.tzinfo is UTC
    assert offset.timestamp == datetime(2026, 7, 28, 12, tzinfo=UTC)
    assert Event.model_validate(base).timestamp.tzinfo is UTC


def test_timestamp_columns_are_timezone_aware() -> None:
    event_timestamp_type = EventRecord.__table__.c.timestamp.type
    next_attempt_type = NotificationOutbox.__table__.c.next_attempt_at.type
    assert isinstance(event_timestamp_type, DateTime)
    assert isinstance(next_attempt_type, DateTime)
    assert event_timestamp_type.timezone is True
    assert next_attempt_type.timezone is True


def test_reliability_settings_reject_invalid_bounds() -> None:
    with pytest.raises(ValidationError):
        _settings(
            ingestion_max_delivery_attempts=0,
            notify_severity_threshold=101,
            event_retention_days=0,
        )


def test_host_agent_settings_do_not_require_database_credentials() -> None:
    settings = HostAgentSettings.model_validate({"redis_url": "redis://localhost:6379/0"})

    assert settings.redis_url == "redis://localhost:6379/0"
    assert not hasattr(settings, "database_url")


@pytest.mark.parametrize(
    "invalid_auth",
    [
        {"api_username": "   "},
        {"api_password": "too-short"},
    ],
)
def test_settings_reject_weak_api_credentials(invalid_auth: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _settings(**invalid_auth)


def test_ack_atomically_removes_source_and_attempt_counter() -> None:
    client = MagicMock()
    pipeline = client.pipeline.return_value
    pipeline.execute.return_value = [1, 1, 1]

    bus.ack_event(client, "1-0")

    client.pipeline.assert_called_once_with(transaction=True)
    pipeline.xack.assert_called_once_with(bus.STREAM_KEY, bus.CONSUMER_GROUP, "1-0")
    pipeline.xdel.assert_called_once_with(bus.STREAM_KEY, "1-0")
    pipeline.hdel.assert_called_once_with(bus.DELIVERY_ATTEMPTS_KEY, "1-0")
    pipeline.execute.assert_called_once_with()


def test_dead_letter_is_written_before_atomic_ack_and_is_bounded() -> None:
    client = MagicMock()
    pipeline = client.pipeline.return_value
    pipeline.execute.return_value = ["2-0", 1, 1, 1]

    result = bus.dead_letter_event(client, "1-0", {"data": "bad"}, "invalid", 2)

    assert result == "2-0"
    pipeline.xadd.assert_called_once()
    xadd_args = pipeline.xadd.call_args
    assert xadd_args.args[0] == bus.DEAD_LETTER_STREAM_KEY
    assert xadd_args.kwargs["maxlen"] == 10_000
    assert xadd_args.kwargs["approximate"] is True
    pipeline.xack.assert_called_once_with(bus.STREAM_KEY, bus.CONSUMER_GROUP, "1-0")
    pipeline.xdel.assert_called_once_with(bus.STREAM_KEY, "1-0")


def test_claim_stale_events_uses_xautoclaim() -> None:
    client = MagicMock()
    client.xautoclaim.return_value = ["0-0", [("1-0", {"data": "{}"})], []]

    claimed = bus.claim_stale_events(client, "worker-1", 60_000, count=12)

    assert claimed == [("1-0", {"data": "{}"})]
    client.xautoclaim.assert_called_once_with(
        bus.STREAM_KEY,
        bus.CONSUMER_GROUP,
        "worker-1",
        60_000,
        start_id="0-0",
        count=12,
    )


def test_process_message_acks_only_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    handled: list[str] = []
    acked: list[str] = []

    def handle(raw_json: str) -> bool:
        handled.append(raw_json)
        return True

    def ack(_client: Any, message_id: str) -> None:
        acked.append(message_id)

    monkeypatch.setattr(consumer, "start_delivery_attempt", lambda *_args: 1)
    monkeypatch.setattr(consumer, "_handle_message", handle)
    monkeypatch.setattr(consumer, "ack_event", ack)

    assert consumer.process_message(
        client,
        "1-0",
        {"data": _event_json()},
        max_attempts=5,
    )
    assert handled == [_event_json()]
    assert acked == ["1-0"]


def test_transient_error_stays_pending_until_attempt_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    ack = MagicMock()
    dead_letter = MagicMock()

    def fail(_raw_json: str) -> bool:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(consumer, "start_delivery_attempt", lambda *_args: 2)
    monkeypatch.setattr(consumer, "_handle_message", fail)
    monkeypatch.setattr(consumer, "ack_event", ack)
    monkeypatch.setattr(consumer, "dead_letter_event", dead_letter)

    assert not consumer.process_message(
        client,
        "1-0",
        {"data": _event_json()},
        max_attempts=3,
    )
    ack.assert_not_called()
    dead_letter.assert_not_called()

    monkeypatch.setattr(consumer, "start_delivery_attempt", lambda *_args: 3)
    assert consumer.process_message(
        client,
        "1-0",
        {"data": _event_json()},
        max_attempts=3,
    )
    ack.assert_not_called()
    dead_letter.assert_called_once()


def test_invalid_payload_moves_directly_to_dead_letter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    ack = MagicMock()
    dead_letter = MagicMock()
    monkeypatch.setattr(consumer, "start_delivery_attempt", lambda *_args: 1)
    monkeypatch.setattr(consumer, "ack_event", ack)
    monkeypatch.setattr(consumer, "dead_letter_event", dead_letter)

    assert consumer.process_message(
        client,
        "1-0",
        {"data": "not-json"},
        max_attempts=5,
    )
    dead_letter.assert_called_once()
    ack.assert_not_called()


def test_existing_event_is_an_idempotent_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock(spec=Session)
    session.get.return_value = object()
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    monkeypatch.setattr(consumer, "SessionLocal", MagicMock(return_value=context))

    assert consumer._handle_message(_event_json()) is False
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_queue_notification_creates_one_deduplicated_row_per_channel() -> None:
    session = MagicMock(spec=Session)
    settings = _settings(
        notify_webhook_url="https://example.invalid/hook",
        notify_email_to="ops@example.invalid",
        notify_smtp_host="smtp.example.invalid",
        notify_max_attempts=7,
    )

    queued = queue_notification(
        session,
        "Alert",
        "Details",
        90,
        deduplication_key="alert:123",
        settings=settings,
    )

    assert {item.channel for item in queued} == {
        NotificationChannel.WEBHOOK,
        NotificationChannel.EMAIL,
    }
    assert {item.deduplication_key for item in queued} == {
        "alert:123:webhook",
        "alert:123:email",
    }
    assert all(item.max_attempts == 7 for item in queued)
    assert session.add.call_count == 2


def _outbox_item(*, attempts: int = 0, max_attempts: int = 3) -> NotificationOutbox:
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    return NotificationOutbox(
        id=uuid.uuid4(),
        channel=NotificationChannel.WEBHOOK,
        title="Alert",
        message="Details",
        severity=90,
        deduplication_key=f"test:{uuid.uuid4()}",
        status=NotificationStatus.PENDING,
        attempts=attempts,
        max_attempts=max_attempts,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )


def test_outbox_failure_records_error_and_exponential_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        notify_retry_base_seconds=10,
        notify_retry_max_seconds=60,
    )
    monkeypatch.setattr(notification_worker, "get_settings", lambda: settings)
    item = _outbox_item()
    session = MagicMock(spec=Session)
    session.scalars.return_value = [item]
    attempted_at = datetime(2026, 7, 28, 13, tzinfo=UTC)

    def fail_delivery(_item: NotificationOutbox) -> None:
        raise RuntimeError("timeout")

    processed = notification_worker.process_outbox_batch(
        session,
        now=attempted_at,
        delivery=fail_delivery,
    )

    assert processed == 1
    assert item.attempts == 1
    assert item.status == NotificationStatus.PENDING
    assert item.next_attempt_at == attempted_at + timedelta(seconds=10)
    assert item.last_error == "RuntimeError: timeout"
    session.commit.assert_called_once_with()


def test_outbox_marks_terminal_failure_at_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(notification_worker, "get_settings", lambda: settings)
    item = _outbox_item(attempts=2, max_attempts=3)
    session = MagicMock(spec=Session)
    session.scalars.return_value = [item]

    def fail_delivery(_item: NotificationOutbox) -> None:
        raise RuntimeError("still down")

    notification_worker.process_outbox_batch(session, delivery=fail_delivery)

    assert item.attempts == 3
    assert item.status == NotificationStatus.FAILED
    assert item.last_error == "RuntimeError: still down"


def test_retention_excludes_incident_evidence_and_rolls_back_empty_batch() -> None:
    session = MagicMock(spec=Session)
    session.scalars.return_value = []

    deleted = maintenance.delete_expired_events_batch(
        session,
        now=datetime(2026, 7, 28, tzinfo=UTC),
        retention_days=30,
        batch_size=25,
    )

    assert deleted == 0
    statement = session.scalars.call_args.args[0]
    sql = str(statement)
    assert "incident_events" in sql
    assert "NOT (EXISTS" in sql
    assert "LIMIT" in sql
    session.rollback.assert_called_once_with()
    session.execute.assert_not_called()
