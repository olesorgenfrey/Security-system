from datetime import UTC, datetime
from unittest.mock import MagicMock

from core.detection.rules import evaluate_brute_force
from core.storage.models import EventRecord


def _failed_auth(host: str = "srv-a") -> EventRecord:
    return EventRecord(
        timestamp=datetime.now(UTC),
        dataset="host_agent.syslog",
        kind="event",
        category=["authentication"],
        type=["info"],
        action=None,
        outcome="failure",
        severity=60,
        message="Failed password",
        host_name=host,
        source_ip="203.0.113.9",
        destination_ip=None,
        raw={},
    )


def test_brute_force_query_is_scoped_to_target_host() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = []

    assert evaluate_brute_force(session, _failed_auth()) is None

    compiled = str(session.execute.call_args.args[0])
    assert "events.host_name" in compiled
    assert "events.source_ip" in compiled
