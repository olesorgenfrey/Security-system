"""Benachrichtigungskanäle und transaktionale Outbox-Erzeugung.

Der Ingestion-Consumer führt keine Netzwerkzugriffe aus. Er schreibt je
konfiguriertem Kanal einen Auftrag in `notification_outbox`; der dedizierte
Worker in :mod:`core.notification_worker` übernimmt die Zustellung.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
import uuid
from email.message import EmailMessage

from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.storage.models import NotificationChannel, NotificationOutbox

logger = logging.getLogger("aegis.notify")


class NotificationDeliveryError(RuntimeError):
    """Ein konfigurierter Kanal konnte die Nachricht nicht zustellen."""


def configured_channels(settings: Settings | None = None) -> list[NotificationChannel]:
    """Ermittelt vollständig konfigurierte Kanäle für neue Outbox-Aufträge."""
    active_settings = settings or get_settings()
    channels: list[NotificationChannel] = []
    if active_settings.notify_webhook_url:
        channels.append(NotificationChannel.WEBHOOK)
    if active_settings.notify_email_to and active_settings.notify_smtp_host:
        channels.append(NotificationChannel.EMAIL)
    return channels


def queue_notification(
    session: Session,
    title: str,
    message: str,
    severity: int,
    *,
    deduplication_key: str | None = None,
    settings: Settings | None = None,
) -> list[NotificationOutbox]:
    """Legt pro aktivem Kanal einen persistenten Zustellauftrag an.

    Der Aufrufer kontrolliert die umgebende DB-Transaktion. So werden Event,
    Alerts und zugehörige Benachrichtigungen gemeinsam committed oder gemeinsam
    zurückgerollt.
    """
    active_settings = settings or get_settings()
    base_key = deduplication_key or f"notification:{uuid.uuid4()}"
    queued: list[NotificationOutbox] = []
    for channel in configured_channels(active_settings):
        item = NotificationOutbox(
            channel=channel.value,
            title=title,
            message=message,
            severity=severity,
            deduplication_key=f"{base_key}:{channel.value}",
            max_attempts=active_settings.notify_max_attempts,
        )
        session.add(item)
        queued.append(item)

    if not queued:
        logger.debug("Kein Benachrichtigungskanal konfiguriert: %s", title)
    return queued


def _deliver_webhook(
    title: str,
    message: str,
    severity: int,
    notification_id: uuid.UUID | None = None,
) -> None:
    url = get_settings().notify_webhook_url
    if not url:
        raise NotificationDeliveryError("Webhook ist nicht konfiguriert")
    payload = json.dumps({"title": title, "message": message, "severity": severity}).encode()
    headers = {"Content-Type": "application/json"}
    if notification_id is not None:
        headers["X-Aegis-Notification-ID"] = str(notification_id)
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise NotificationDeliveryError(f"Webhook antwortete mit HTTP {status}")
    except NotificationDeliveryError:
        raise
    except Exception as exc:
        raise NotificationDeliveryError(f"Webhook-Zustellung fehlgeschlagen: {exc}") from exc


def _deliver_email(
    title: str,
    message: str,
    notification_id: uuid.UUID | None = None,
) -> None:
    settings = get_settings()
    if not settings.notify_email_to or not settings.notify_smtp_host:
        raise NotificationDeliveryError("E-Mail ist nicht vollständig konfiguriert")

    email = EmailMessage()
    email["Subject"] = f"[Aegis] {title}"
    email["From"] = settings.notify_email_from
    email["To"] = settings.notify_email_to
    if notification_id is not None:
        email["Message-ID"] = f"<{notification_id}@aegis.local>"
    email.set_content(message)

    try:
        with smtplib.SMTP(settings.notify_smtp_host, settings.notify_smtp_port, timeout=5) as smtp:
            if settings.notify_smtp_user and settings.notify_smtp_password:
                smtp.starttls()
                smtp.login(
                    settings.notify_smtp_user,
                    settings.notify_smtp_password.get_secret_value(),
                )
            smtp.send_message(email)
    except Exception as exc:
        raise NotificationDeliveryError(f"E-Mail-Zustellung fehlgeschlagen: {exc}") from exc


def deliver_notification(item: NotificationOutbox) -> None:
    """Stellt genau einen Outbox-Auftrag zu und meldet Fehler an den Retry-Worker."""
    if item.channel == NotificationChannel.WEBHOOK:
        _deliver_webhook(item.title, item.message, item.severity, item.id)
    elif item.channel == NotificationChannel.EMAIL:
        _deliver_email(item.title, item.message, item.id)
    else:
        raise NotificationDeliveryError(f"Unbekannter Kanal: {item.channel}")


def notify_webhook(title: str, message: str, severity: int) -> None:
    """Kompatibler Best-Effort-Aufruf; neue Produktionpfade verwenden die Outbox."""
    if not get_settings().notify_webhook_url:
        logger.info("Webhook nicht konfiguriert, überspringe Benachrichtigung: %s", title)
        return
    try:
        _deliver_webhook(title, message, severity)
    except NotificationDeliveryError:
        logger.exception("Webhook-Benachrichtigung fehlgeschlagen")


def notify_email(title: str, message: str) -> None:
    """Kompatibler Best-Effort-Aufruf; neue Produktionpfade verwenden die Outbox."""
    settings = get_settings()
    if not settings.notify_email_to or not settings.notify_smtp_host:
        logger.info("E-Mail nicht konfiguriert, überspringe Benachrichtigung: %s", title)
        return
    try:
        _deliver_email(title, message)
    except NotificationDeliveryError:
        logger.exception("E-Mail-Benachrichtigung fehlgeschlagen")


def notify(title: str, message: str, severity: int) -> None:
    """Löst synchron beide Kanäle aus (Kompatibilität für bestehende Aufrufer)."""
    notify_webhook(title, message, severity)
    notify_email(title, message)
