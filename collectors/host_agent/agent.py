"""Host-Agent (Phase 1, architecture.md §3.1): Log-Tailing + Prozess-/Netz-Snapshot.

Bewusst "dumm" — sammelt und normalisiert zu ECS-Events, trifft aber keine
Erkennungsentscheidungen (das macht Phase 2, die Detection Engine).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import psutil
import redis

from core.config import get_settings
from core.ingestion.bus import get_redis, publish_event
from core.schemas.event import (
    Event,
    EventCategory,
    EventKind,
    EventMeta,
    EventOutcome,
    EventType,
    Host,
    Process,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("aegis.host_agent")

_AUTH_FAIL_MARKERS = ("failed password", "authentication failure", "invalid user")
_AUTH_OK_MARKERS = ("accepted password", "accepted publickey", "session opened")


def _hostname() -> str:
    return get_settings().host_agent_hostname


def _emit(client: redis.Redis, event: Event) -> None:
    publish_event(client, event.model_dump_json(by_alias=True))


def _severity_for_log_line(line: str) -> tuple[int, EventOutcome]:
    lowered = line.lower()
    if any(marker in lowered for marker in _AUTH_FAIL_MARKERS):
        return 60, EventOutcome.FAILURE
    if any(marker in lowered for marker in _AUTH_OK_MARKERS):
        return 10, EventOutcome.SUCCESS
    return 20, EventOutcome.UNKNOWN


def tail_log(path: str, client: redis.Redis) -> None:
    """Folgt einer Log-Datei wie `tail -F` (übersteht Rotation via Inode-Check)."""
    file_path = Path(path)
    while not file_path.exists():
        logger.warning("Log-Datei %s existiert noch nicht, warte...", path)
        time.sleep(10)

    fh = file_path.open("r")
    fh.seek(0, os.SEEK_END)
    inode = file_path.stat().st_ino

    while True:
        line = fh.readline()
        if not line:
            time.sleep(1)
            try:
                if file_path.stat().st_ino != inode:
                    fh.close()
                    fh = file_path.open("r")
                    inode = file_path.stat().st_ino
            except FileNotFoundError:
                pass
            continue

        line = line.rstrip("\n")
        if not line:
            continue

        severity, outcome = _severity_for_log_line(line)
        event = Event(
            event=EventMeta(
                kind=EventKind.EVENT,
                category=[EventCategory.AUTHENTICATION],
                type=[EventType.INFO],
                outcome=outcome,
                severity=severity,
                dataset="host_agent.syslog",
            ),
            message=line,
            host=Host(name=_hostname()),
            tags=["host_agent", "log_tail"],
            labels={"source_file": path},
        )
        _emit(client, event)


def snapshot_processes(client: redis.Redis, known_pids: set[int]) -> set[int]:
    """Meldet neu aufgetauchte Prozesse als Creation-Events. Gibt aktualisierte PID-Menge zurück."""
    current: dict[int, psutil.Process] = {}
    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        current[proc.pid] = proc

    new_pids = set(current) - known_pids
    for pid in new_pids:
        proc = current[pid]
        try:
            info = proc.info
        except psutil.NoSuchProcess:
            continue
        event = Event(
            event=EventMeta(
                kind=EventKind.EVENT,
                category=[EventCategory.PROCESS],
                type=[EventType.CREATION],
                outcome=EventOutcome.SUCCESS,
                severity=5,
                dataset="host_agent.process",
            ),
            message=f"Neuer Prozess: {info.get('name')} (pid={pid})",
            host=Host(name=_hostname()),
            process=Process(
                pid=pid,
                name=info.get("name"),
                command_line=" ".join(info.get("cmdline") or []),
                executable=info.get("exe"),
            ),
            tags=["host_agent", "process_snapshot"],
        )
        _emit(client, event)

    return set(current)


def snapshot_network(client: redis.Redis) -> None:
    """Meldet eine Zusammenfassung aktiver Verbindungen (Metrik-Event)."""
    connections = psutil.net_connections(kind="inet")
    established = sum(1 for c in connections if c.status == psutil.CONN_ESTABLISHED)
    listening = sum(1 for c in connections if c.status == psutil.CONN_LISTEN)

    event = Event(
        event=EventMeta(
            kind=EventKind.METRIC,
            category=[EventCategory.NETWORK],
            type=[EventType.INFO],
            outcome=EventOutcome.SUCCESS,
            severity=0,
            dataset="host_agent.network",
        ),
        message=f"{established} aktive Verbindungen, {listening} lauschende Sockets",
        host=Host(name=_hostname()),
        labels={"established": str(established), "listening": str(listening)},
        tags=["host_agent", "network_snapshot"],
    )
    _emit(client, event)


def run_snapshots(client: redis.Redis) -> None:
    interval = get_settings().host_agent_snapshot_interval_seconds
    known_pids: set[int] = set(psutil.pids())
    logger.info("Prozess-/Netz-Snapshot alle %ss", interval)
    while True:
        try:
            known_pids = snapshot_processes(client, known_pids)
            snapshot_network(client)
        except Exception:
            logger.exception("Fehler beim Snapshot")
        time.sleep(interval)


def run() -> None:
    client = get_redis()
    log_paths = [p.strip() for p in get_settings().host_agent_log_paths.split(",") if p.strip()]

    threads = [
        threading.Thread(target=tail_log, args=(path, client), daemon=True) for path in log_paths
    ]
    for thread in threads:
        thread.start()

    run_snapshots(client)


if __name__ == "__main__":
    run()
