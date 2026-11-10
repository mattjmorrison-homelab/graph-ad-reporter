from ad_reporter import db


def test_insert_report_creates_unresolved_row_with_given_fields() -> None:
    report = db.insert_report(
        timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
    )

    assert report.client_ip == "192.168.1.5"
    assert report.timestamp == "2026-11-10T00:00:00+00:00"
    assert report.resolved is False
    assert report.resolution_note is None
    assert report.id > 0


def test_get_report_returns_none_for_missing_id() -> None:
    assert db.get_report(999) is None


def test_unresolved_reports_excludes_resolved_rows() -> None:
    unresolved = db.insert_report(
        timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
    )
    resolved = db.insert_report(
        timestamp="2026-11-10T00:01:00+00:00", client_ip="192.168.1.6"
    )
    db.resolve_report(resolved.id, "handled")

    reports = db.unresolved_reports()

    assert [row.id for row in reports] == [unresolved.id]


def test_unresolved_reports_filters_by_since() -> None:
    db.insert_report(timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5")
    new = db.insert_report(
        timestamp="2026-11-10T01:00:00+00:00", client_ip="192.168.1.6"
    )

    reports = db.unresolved_reports(since="2026-11-10T00:30:00+00:00")

    assert [row.id for row in reports] == [new.id]


def test_unresolved_reports_orders_newest_first() -> None:
    first = db.insert_report(
        timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
    )
    second = db.insert_report(
        timestamp="2026-11-10T01:00:00+00:00", client_ip="192.168.1.6"
    )

    reports = db.unresolved_reports()

    assert [row.id for row in reports] == [second.id, first.id]


def test_resolve_report_sets_resolved_and_note() -> None:
    report = db.insert_report(
        timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
    )

    resolved = db.resolve_report(report.id, "example.com blocked")

    assert resolved is not None
    assert resolved.resolved is True
    assert resolved.resolution_note == "example.com blocked"


def test_resolve_report_returns_none_for_missing_id() -> None:
    assert db.resolve_report(999, "note") is None
