from collectors.host_agent.agent import _extract_source, _severity_for_log_line
from core.schemas.event import EventOutcome


def test_failed_login_is_high_severity() -> None:
    line = "Failed password for invalid user admin from 1.2.3.4"
    severity, outcome = _severity_for_log_line(line)
    assert severity == 60
    assert outcome == EventOutcome.FAILURE


def test_successful_login_is_low_severity() -> None:
    severity, outcome = _severity_for_log_line("Accepted publickey for ole from 10.0.0.5")
    assert severity == 10
    assert outcome == EventOutcome.SUCCESS


def test_unrelated_line_is_default_severity() -> None:
    severity, outcome = _severity_for_log_line("systemd started service X")
    assert severity == 20
    assert outcome == EventOutcome.UNKNOWN


def test_extract_source_parses_ip_and_user() -> None:
    line = "Failed password for invalid user admin from 203.0.113.5 port 51234 ssh2"
    source = _extract_source(line)
    assert source is not None
    assert str(source.ip) == "203.0.113.5"
    assert source.user == "admin"


def test_extract_source_returns_none_without_ip() -> None:
    assert _extract_source("systemd started service X") is None
