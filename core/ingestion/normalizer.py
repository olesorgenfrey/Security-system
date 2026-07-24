"""Normalisiert rohe Collector-Payloads in das gemeinsame Event-Schema (ECS)."""

from __future__ import annotations

from typing import Any

from core.schemas.event import Event


def normalize(raw: dict[str, Any]) -> Event:
    """Validiert/parst ein rohes Dict (bereits ECS-förmig vom Collector) zu Event.

    Collectors sind "dumm" (architecture.md §3.1) — sie liefern schon
    ECS-strukturierte Dicts. Der Normalizer ist die Stelle, an der künftig
    Feldangleichung/Anreicherung für neue Collector-Typen ergänzt wird.
    """
    return Event.model_validate(raw)
