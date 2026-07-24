"""Einfacher Anomalie-Detektor (Phase 2, architecture.md §3.4): Z-Score auf

Prozess-Erstellungsrate pro Host. Bewusst simpel gehalten (Schwellwert +
Z-Score über gleitende Zeitfenster), wie in der Roadmap für den Start
vorgesehen — ML-basierte Verfahren (Isolation Forest o.ä.) sind spätere
Ausbaustufen (Phase 6).
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.storage.models import Alert, AlertStatus, EventRecord

RULE_PROCESS_BURST = "process_creation_anomaly"
MITRE_DISCOVERY = "T1057"


def _count_process_creations(
    session: Session, host_name: str, start: datetime, end: datetime
) -> int:
    stmt = select(EventRecord.id).where(
        EventRecord.host_name == host_name,
        EventRecord.dataset == "host_agent.process",
        EventRecord.type.contains(["creation"]),
        EventRecord.timestamp >= start,
        EventRecord.timestamp < end,
    )
    return len(session.execute(stmt).all())


def _zscore(current: int, baseline: list[int]) -> float:
    mean = statistics.mean(baseline)
    stdev = statistics.pstdev(baseline) or 1.0
    return (current - mean) / stdev


def _has_recent_open_alert_for_host(
    session: Session, rule_id: str, host_name: str, cooldown_minutes: int
) -> bool:
    cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
    stmt = select(Alert.id).where(
        Alert.rule_id == rule_id,
        Alert.host_name == host_name,
        Alert.created_at >= cutoff,
    )
    return session.execute(stmt).first() is not None


def evaluate_process_burst(session: Session, record: EventRecord) -> Alert | None:
    """Erkennt ungewöhnlich viele neue Prozesse auf einem Host (Z-Score gegen Baseline)."""
    is_process_creation = record.dataset == "host_agent.process" and "creation" in record.type
    if not is_process_creation:
        return None

    settings = get_settings()
    window = timedelta(seconds=settings.anomaly_window_seconds)
    now = datetime.utcnow()

    current_count = _count_process_creations(session, record.host_name, now - window, now)
    if current_count < settings.anomaly_min_count:
        return None

    baseline_counts = [
        _count_process_creations(
            session,
            record.host_name,
            now - (i + 1) * window,
            now - i * window,
        )
        for i in range(1, settings.anomaly_baseline_windows + 1)
    ]
    if len(baseline_counts) < 3:
        return None

    z_score = _zscore(current_count, baseline_counts)
    if z_score < settings.anomaly_z_threshold:
        return None

    if _has_recent_open_alert_for_host(
        session, RULE_PROCESS_BURST, record.host_name, settings.anomaly_cooldown_minutes
    ):
        return None

    baseline_mean = statistics.mean(baseline_counts)
    alert = Alert(
        rule_id=RULE_PROCESS_BURST,
        title=f"Ungewöhnlich viele neue Prozesse auf {record.host_name}",
        description=(
            f"{current_count} neue Prozesse in {settings.anomaly_window_seconds}s "
            f"(Baseline-Mittel: {baseline_mean:.1f}, Z-Score: {z_score:.1f})."
        ),
        severity=65,
        mitre_technique=MITRE_DISCOVERY,
        status=AlertStatus.OPEN,
        host_name=record.host_name,
        source_ip=None,
        event_ids=[str(record.id)],
    )
    session.add(alert)
    return alert
