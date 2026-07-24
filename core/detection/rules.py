"""Detection Engine (Phase 2, docs/architecture.md §3.4): erste Regel.

Startet regelbasiert (wie in der Roadmap vorgesehen) mit einer einzelnen,
kuratierten Regel: Brute-Force-Erkennung über wiederholte fehlgeschlagene
Authentifizierungsversuche derselben Quell-IP. Weitere Regeln (Sigma-Import,
Anomalie-Detektoren) docken hier künftig als weitere `evaluate_*`-Funktionen an.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.detection.anomaly import evaluate_process_burst
from core.detection.keyword_rules import evaluate_keyword_rules
from core.storage.models import Alert, AlertStatus, EventRecord

RULE_BRUTE_FORCE = "brute_force_auth"
MITRE_BRUTE_FORCE = "T1110"


def _has_recent_open_alert(
    session: Session, rule_id: str, source_ip: str, cooldown_minutes: int
) -> bool:
    cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
    stmt = select(Alert.id).where(
        Alert.rule_id == rule_id,
        Alert.source_ip == source_ip,
        Alert.created_at >= cutoff,
    )
    return session.execute(stmt).first() is not None


def evaluate_brute_force(session: Session, record: EventRecord) -> Alert | None:
    """Prüft, ob die Fehlversuche von `record.source_ip` den Schwellwert erreichen."""
    is_failed_auth = "authentication" in record.category and record.outcome == "failure"
    if not is_failed_auth or not record.source_ip:
        return None

    settings = get_settings()
    window_minutes = settings.detection_brute_force_window_minutes
    window_start = datetime.utcnow() - timedelta(minutes=window_minutes)

    stmt = (
        select(EventRecord.id, EventRecord.timestamp)
        .where(
            EventRecord.source_ip == record.source_ip,
            EventRecord.outcome == "failure",
            EventRecord.category.contains(["authentication"]),
            EventRecord.timestamp >= window_start,
        )
        .order_by(EventRecord.timestamp.desc())
    )
    matches = session.execute(stmt).all()
    if len(matches) < settings.detection_brute_force_threshold:
        return None

    cooldown = settings.detection_brute_force_cooldown_minutes
    if _has_recent_open_alert(session, RULE_BRUTE_FORCE, record.source_ip, cooldown):
        return None

    alert = Alert(
        rule_id=RULE_BRUTE_FORCE,
        title=f"Brute-Force-Verdacht von {record.source_ip}",
        description=(
            f"{len(matches)} fehlgeschlagene Login-Versuche von {record.source_ip} "
            f"innerhalb von {window_minutes} Minuten (Host: {record.host_name})."
        ),
        severity=80,
        mitre_technique=MITRE_BRUTE_FORCE,
        status=AlertStatus.OPEN,
        host_name=record.host_name,
        source_ip=record.source_ip,
        event_ids=[str(event_id) for event_id, _ in matches],
    )
    session.add(alert)
    return alert


def evaluate(session: Session, record: EventRecord) -> list[Alert]:
    """Führt alle registrierten Detection-Regeln gegen das gespeicherte Event aus."""
    alerts = []
    for threshold_rule in (evaluate_brute_force, evaluate_process_burst):
        alert = threshold_rule(session, record)
        if alert is not None:
            alerts.append(alert)
    alerts.extend(evaluate_keyword_rules(session, record))
    return alerts
