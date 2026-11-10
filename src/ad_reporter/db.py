"""SQLite storage for ad reports.

One connection per call, opened and closed around each statement — this
service has no long-lived request/response object to hang a shared
connection off of (plain WSGI, see wsgi.py), and SQLite's file-level
locking makes short-lived connections the simplest safe option under
gunicorn's multi-worker model.
"""

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = os.environ.get("AD_REPORTER_DB_PATH", "/data/ad-reporter.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution_note TEXT
);
"""

_SELECT_COLUMNS = "id, timestamp, client_ip, resolved, resolution_note"


@dataclass
class ReportRow:
    id: int
    timestamp: str
    client_ip: str
    resolved: bool
    resolution_note: str | None


def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(_SCHEMA)
    return connection


def _row_to_report(row: tuple[int, str, str, int, str | None]) -> ReportRow:
    return ReportRow(
        id=row[0],
        timestamp=row[1],
        client_ip=row[2],
        resolved=bool(row[3]),
        resolution_note=row[4],
    )


def insert_report(timestamp: str, client_ip: str) -> ReportRow:
    connection = _connect()
    try:
        cursor = connection.execute(
            "INSERT INTO reports (timestamp, client_ip, resolved) VALUES (?, ?, 0)",
            (timestamp, client_ip),
        )
        connection.commit()
        report_id = cursor.lastrowid
    finally:
        connection.close()
    assert report_id is not None
    report = get_report(report_id)
    assert report is not None
    return report


def get_report(report_id: int) -> ReportRow | None:
    connection = _connect()
    try:
        row = connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else _row_to_report(row)


def unresolved_reports(since: str | None = None) -> list[ReportRow]:
    query = f"SELECT {_SELECT_COLUMNS} FROM reports WHERE resolved = 0"
    params: tuple[str, ...] = ()
    if since is not None:
        query += " AND timestamp >= ?"
        params = (since,)
    query += " ORDER BY timestamp DESC"
    connection = _connect()
    try:
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()
    return [_row_to_report(row) for row in rows]


def resolve_report(report_id: int, resolution_note: str | None) -> ReportRow | None:
    connection = _connect()
    try:
        connection.execute(
            "UPDATE reports SET resolved = 1, resolution_note = ? WHERE id = ?",
            (resolution_note, report_id),
        )
        connection.commit()
    finally:
        connection.close()
    return get_report(report_id)
