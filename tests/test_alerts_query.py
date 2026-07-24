from api.routes.alerts import build_alerts_query


def test_build_alerts_query_filters_status() -> None:
    stmt = build_alerts_query("open")
    assert "status" in str(stmt)


def test_build_alerts_query_no_filter() -> None:
    stmt = build_alerts_query(None)
    assert "alerts" in str(stmt).lower()
