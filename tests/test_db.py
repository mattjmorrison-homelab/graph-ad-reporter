import sqlite3
from unittest.mock import patch

import pytest

from ad_reporter import db


def test_insert_report_creates_unresolved_row_with_given_fields() -> None:
    report = db.insert_report(
        timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
    )

    assert report.client_ip == "192.168.1.5"
    assert report.timestamp == "2026-11-10T00:00:00+00:00"
    assert report.resolved is False
    assert report.resolution_note is None
    assert report.candidate_domains is None
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


def test_record_candidate_domains_stores_json_encoded_list() -> None:
    report = db.insert_report(
        timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
    )

    updated = db.record_candidate_domains(
        report.id, ["a.example.com", "b.example.com"]
    )

    assert updated is not None
    assert updated.candidate_domains == '["a.example.com", "b.example.com"]'


def test_record_candidate_domains_with_empty_list_is_distinct_from_null() -> None:
    report = db.insert_report(
        timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
    )

    updated = db.record_candidate_domains(report.id, [])

    assert updated is not None
    assert updated.candidate_domains == "[]"


class _FlakyAlterConnection:
    """Wraps a real sqlite3.Connection, raising a non-"duplicate column"
    OperationalError on ALTER TABLE so _connect()'s migration re-raise path
    can be exercised.
    """

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> sqlite3.Cursor:
        if "ALTER TABLE" in sql:
            raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


def test_connect_reraises_non_duplicate_column_operational_errors() -> None:
    original_connect = sqlite3.connect

    def flaky_connect(database: str) -> _FlakyAlterConnection:
        return _FlakyAlterConnection(original_connect(database))

    with patch("ad_reporter.db.sqlite3.connect", flaky_connect):
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            db.insert_report(
                timestamp="2026-11-10T00:00:00+00:00", client_ip="192.168.1.5"
            )
