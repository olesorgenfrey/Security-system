from core.ingestion.normalizer import normalize
from core.schemas.event import EventOutcome


def test_normalize_roundtrip() -> None:
    raw = {
        "event": {
            "dataset": "host_agent.syslog",
            "category": ["authentication"],
            "type": ["info"],
            "outcome": "failure",
            "severity": 60,
        },
        "message": "Failed password for root from 1.2.3.4",
        "host": {"name": "test-host"},
    }
    event = normalize(raw)
    assert event.host.name == "test-host"
    assert event.event.severity == 60
    assert event.event.outcome == EventOutcome.FAILURE
    assert event.model_dump_json(by_alias=True)
