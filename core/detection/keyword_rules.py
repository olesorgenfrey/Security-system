"""Leichtgewichtige, Sigma-inspirierte Keyword-Regeln (Phase 2).

Kein vollständiger Sigma-Parser (pySigma) — für den MVP reicht ein einfaches,
deklaratives YAML-Format (`rules/*.yml`): eine Regel feuert, wenn mindestens
eine ihrer `match_any`-Gruppen vollständig (alle Keywords, case-insensitiv als
Teilstring) im Event-Text vorkommt. Das deckt die in der Roadmap genannten
"kuratierten Startregeln" (Brute-Force ist als eigene Threshold-Regel in
rules.py gelöst, hier kommen musterbasierte Regeln wie "neues Admin-Konto"
oder "Reverse-Shell-Muster" dazu). Ein Umstieg auf echtes Sigma (pySigma) ist
später möglich, ohne den Aufrufer (core/detection/rules.py) zu ändern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.storage.models import Alert, AlertStatus, EventRecord

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


@dataclass
class KeywordRule:
    id: str
    title: str
    description: str
    mitre: str | None
    severity: int
    match_any: list[list[str]]

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        return any(all(kw.lower() in lowered for kw in group) for group in self.match_any)


def _load_rule(path: Path) -> KeywordRule:
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    rule = KeywordRule(
        id=data["id"],
        title=data["title"],
        description=data.get("description", "").strip(),
        mitre=data.get("mitre"),
        severity=int(data.get("severity", 50)),
        match_any=[list(group) for group in data.get("match_any", [])],
    )
    if not rule.id.strip():
        raise ValueError(f"Regel {path} hat keine ID")
    if not 0 <= rule.severity <= 100:
        raise ValueError(f"Regel {path} hat eine Severity ausserhalb 0..100")
    if not rule.match_any or any(
        not group or any(not isinstance(keyword, str) or not keyword.strip() for keyword in group)
        for group in rule.match_any
    ):
        raise ValueError(f"Regel {path} enthaelt eine leere match_any-Gruppe")
    return rule


def load_rules(rules_dir: Path = RULES_DIR) -> list[KeywordRule]:
    if not rules_dir.exists():
        return []
    return [_load_rule(p) for p in sorted(rules_dir.glob("*.yml"))]


def _searchable_text(record: EventRecord) -> str:
    parts = [record.message or ""]
    process = record.raw.get("process") if isinstance(record.raw, dict) else None
    if isinstance(process, dict):
        parts.append(str(process.get("command_line") or ""))
        parts.append(str(process.get("name") or ""))
    return " ".join(parts)


def _has_recent_alert(session: Session, rule_id: str, host_name: str, minutes: int) -> bool:
    """Suppress repeated matches for the same rule and host during a short cooldown."""
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    stmt = select(Alert.id).where(
        Alert.rule_id == rule_id,
        Alert.host_name == host_name,
        Alert.created_at >= cutoff,
    )
    return session.execute(stmt).first() is not None


def evaluate_keyword_rules(
    session: Session, record: EventRecord, rules: list[KeywordRule] | None = None
) -> list[Alert]:
    """Prüft alle geladenen Keyword-Regeln gegen ein einzelnes Event."""
    active_rules = load_rules() if rules is None else rules
    text = _searchable_text(record)
    alerts: list[Alert] = []

    for rule in active_rules:
        if not rule.matches(text):
            continue
        if _has_recent_alert(
            session,
            rule.id,
            record.host_name,
            get_settings().detection_keyword_cooldown_minutes,
        ):
            continue
        alert = Alert(
            rule_id=rule.id,
            title=rule.title,
            description=rule.description or None,
            severity=rule.severity,
            mitre_technique=rule.mitre,
            status=AlertStatus.OPEN,
            host_name=record.host_name,
            source_ip=record.source_ip,
            event_ids=[str(record.id)],
        )
        session.add(alert)
        alerts.append(alert)

    return alerts
