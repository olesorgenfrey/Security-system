"""Erste Alerting-Kanäle (docs/architecture.md §3.9): E-Mail + Webhook.

Beide sind konfigurationsgesteuert und no-op, solange nicht konfiguriert
(fail-safe: kein Ziel konfiguriert -> es wird nur geloggt, nichts geschickt).
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
from email.message import EmailMessage

from core.config import get_settings

logger = logging.getLogger("aegis.notify")


def notify_webhook(title: str, message: str, severity: int) -> None:
    url = get_settings().notify_webhook_url
    if not url:
        logger.info("Webhook nicht konfiguriert, überspringe Benachrichtigung: %s", title)
        return
    payload = json.dumps({"title": title, "message": message, "severity": severity}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        logger.exception("Webhook-Benachrichtigung fehlgeschlagen")


def notify_email(title: str, message: str) -> None:
    settings = get_settings()
    if not settings.notify_email_to or not settings.notify_smtp_host:
        logger.info("E-Mail nicht konfiguriert, überspringe Benachrichtigung: %s", title)
        return
    msg = EmailMessage()
    msg["Subject"] = f"[Aegis] {title}"
    msg["From"] = settings.notify_email_from
    msg["To"] = settings.notify_email_to
    msg.set_content(message)
    try:
        with smtplib.SMTP(settings.notify_smtp_host, settings.notify_smtp_port, timeout=5) as smtp:
            if settings.notify_smtp_user and settings.notify_smtp_password:
                smtp.starttls()
                smtp.login(settings.notify_smtp_user, settings.notify_smtp_password)
            smtp.send_message(msg)
    except Exception:
        logger.exception("E-Mail-Benachrichtigung fehlgeschlagen")


def notify(title: str, message: str, severity: int) -> None:
    """Löst alle konfigurierten Kanäle aus. Wird vom Consumer bei hoher Severity gerufen."""
    notify_webhook(title, message, severity)
    notify_email(title, message)
