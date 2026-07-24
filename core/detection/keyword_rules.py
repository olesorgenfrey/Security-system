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
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

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
    return KeywordRule(
        id=data["id"],
        title=data["title"],
        description=data.get("description", "").strip(),
        mitre=data.get("mitre"),
        severity=int(data.get("severity", 50)),
        match_any=[list(group) for group in data.get("match_any", [])],
    )


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
