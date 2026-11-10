from pathlib import Path

import pytest

from ad_reporter import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every test at its own throwaway SQLite file instead of the
    real AD_REPORTER_DB_PATH default, so tests never share or pollute state.
    """
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
