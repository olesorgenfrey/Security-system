"""Retry-Worker für die persistente Notification-Outbox.

Start als eigener Dienst mit ``python -m core.notification_worker``.
Zustellungen sind mindestens einmal; die stabile Outbox-UUID wird bei Webhooks
als Idempotency-Header und bei E-Mails als Message-ID mitgesendet.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.notify import deliver_notification
from core.storage.database import SessionLocal
from core.storage.models import NotificationOutbox, NotificationStatus

logger = logging.getLogger("aegis.notification_worker")

DeliveryFunction = Callable[[NotificationOutbox], None]


def retry_delay_seconds(attempt: int, base_seconds: int, max_seconds: int) -> int:
    """Berechnet einen gedeckelten exponentiellen Backoff."""
    exponent = max(0, attempt - 1)
    multiplier: int = 1 << exponent
    return min(max_seconds, base_seconds * multiplier)


def process_outbox_batch(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int | None = None,
    delivery: DeliveryFunction = deliver_notification,
) -> int:
    """Sperrt und verarbeitet eine fällige Charge; committed Status und Fehler."""
    settings = get_settings()
    attempted_at = now or datetime.now(UTC)
    batch_size = limit or settings.notify_worker_batch_size
    statement = (
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status == NotificationStatus.PENDING,
            NotificationOutbox.next_attempt_at <= attempted_at,
        )
        .order_by(NotificationOutbox.next_attempt_at, NotificationOutbox.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    items = list(session.scalars(statement))

    for item in items:
        item.attempts += 1
        item.last_attempt_at = attempted_at
        item.updated_at = attempted_at
        try:
            delivery(item)
        except Exception as exc:
            item.last_error = f"{type(exc).__name__}: {exc}"[:4000]
            if item.attempts >= item.max_attempts:
                item.status = NotificationStatus.FAILED
                logger.error(
                    "Benachrichtigung %s nach %s Versuchen endgültig fehlgeschlagen: %s",
                    item.id,
                    item.attempts,
                    item.last_error,
                )
            else:
                delay = retry_delay_seconds(
                    item.attempts,
                    settings.notify_retry_base_seconds,
                    settings.notify_retry_max_seconds,
                )
                item.next_attempt_at = attempted_at + timedelta(seconds=delay)
                logger.warning(
                    "Benachrichtigung %s fehlgeschlagen; Retry in %ss: %s",
                    item.id,
                    delay,
                    item.last_error,
                )
        else:
            item.status = NotificationStatus.DELIVERED
            item.delivered_at = attempted_at
            item.last_error = None

    session.commit()
    return len(items)


def run_once() -> int:
    """Service-freundlicher Einstiegspunkt für genau eine fällige Charge."""
    with SessionLocal() as session:
        return process_outbox_batch(session)


def run() -> None:
    """Verarbeitet die Outbox fortlaufend; leere Queues werden gepollt."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Notification-Outbox-Worker gestartet")
    while True:
        try:
            processed = run_once()
        except Exception:
            logger.exception("Outbox-Verarbeitung fehlgeschlagen")
            processed = 0
        if processed == 0:
            time.sleep(settings.notify_worker_poll_seconds)


if __name__ == "__main__":
    run()
