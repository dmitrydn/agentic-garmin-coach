"""
conftest.py — pytest fixtures.

Shared helpers (load_fixture, make_llm_msg, make_mock_garmin_api) live in helpers.py.
"""

import pytest
from helpers import make_mock_garmin_api, load_fixture, make_llm_msg


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """
    Creates a temp SQLite DB with full schema at tmp_path/coach.db.
    Patches CWD to tmp_path so all agents that use relative sqlite3.connect("coach.db")
    and relative file paths (analyses/, events.log, etc.) resolve to tmp_path.
    """
    monkeypatch.chdir(tmp_path)
    from data_agent import init_db
    init_db()
    return tmp_path / "coach.db"


@pytest.fixture
def garmin_calendar_fixture():
    return load_fixture("garmin_calendar.json")


@pytest.fixture
def garmin_atp_fixture():
    return load_fixture("garmin_atp.json")


@pytest.fixture
def coach_llm_ok():
    return load_fixture("coach_llm_ok.json")


@pytest.fixture
def plan_llm_ok():
    return load_fixture("plan_llm_ok.json")
