from api.routes.events import build_events_query


def test_build_events_query_applies_filters() -> None:
    stmt = build_events_query("myhost", "authentication", 50, "failed")
    compiled = str(stmt)
    assert "host_name" in compiled
    assert "severity" in compiled
    assert "message" in compiled


def test_build_events_query_no_filters() -> None:
    stmt = build_events_query(None, None, 0, None)
    compiled = str(stmt)
    assert "events" in compiled.lower()
