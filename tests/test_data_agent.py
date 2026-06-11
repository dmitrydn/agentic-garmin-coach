"""
test_data_agent.py — Layer I: SQLite save/load and delta logic.

Uses a temp DB (no live API). httpx calls are mocked via unittest.mock.
"""

import asyncio
import sqlite3
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_agent import (
    data_agent_fn,
    get_last_sync,
    init_db,
    save_activities,
    save_wellness,
    set_last_sync,
)
from helpers import load_fixture


# ── Schema and sync state ─────────────────────────────────────────────────────

def test_init_db_creates_all_tables(tmp_db):
    con = sqlite3.connect(str(tmp_db))
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    con.close()
    expected = {
        "wellness_cache", "activity_cache", "garmin_cache",
        "performance_cache", "strength_log", "recommendation_log", "pipeline_meta"
    }
    assert expected.issubset(tables)


def test_last_sync_default_is_90_days_ago(tmp_db):
    from datetime import date, timedelta
    result = get_last_sync()
    expected_approx = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    assert result == expected_approx


def test_set_and_get_last_sync(tmp_db):
    set_last_sync("2026-05-01")
    assert get_last_sync() == "2026-05-01"


# ── save_activities ───────────────────────────────────────────────────────────

def test_save_activity_ef_computed_from_watts_hr(tmp_db):
    activities = [{
        "id": "act-001",
        "start_date_local": "2026-06-10T07:00:00",
        "name": "Easy Run",
        "distance": 10000,
        "elapsed_time": 3600,
        "average_heartrate": 130,
        "icu_training_load": 45.0,
        "total_elevation_gain": 80,
        "time_in_z1": 1800,
        "time_in_z2": 1200,
        "average_cadence": 175,
        "icu_average_watts": 182,         # EF = 182 / 130 = 1.4
        "efficiency_factor": None,
    }]
    save_activities(activities)

    con = sqlite3.connect("coach.db")
    row = con.execute("SELECT efficiency_factor FROM activity_cache WHERE id='act-001'").fetchone()
    con.close()
    assert row is not None
    assert abs(row[0] - 1.4) < 0.01


def test_save_activity_conflict_does_not_overwrite_rpe(tmp_db):
    # First insert with rpe=8 via direct SQL
    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO activity_cache
            (id, date, name, distance_m, duration_s, avg_hr, training_load,
             adjusted_load, avg_pace_s, elevation_gain_m,
             time_in_z1, time_in_z2, surface, rpe, synced_at,
             avg_cadence, avg_gct_ms, avg_vertical_osc_mm,
             avg_vertical_ratio, avg_stride_length_m, efficiency_factor)
        VALUES ('act-002','2026-06-10','Tempo',10000,3600,140,80,
                NULL,360,100,1000,1000,NULL,8,'2026-06-10T08:00:00',
                NULL,NULL,NULL,NULL,NULL,NULL)
    """)
    con.commit()
    con.close()

    # Now re-save same activity via data_agent (simulates delta re-sync)
    activities = [{
        "id": "act-002",
        "start_date_local": "2026-06-10T07:00:00",
        "name": "Tempo Run Updated",
        "distance": 10000,
        "elapsed_time": 3600,
        "average_heartrate": 145,
        "icu_training_load": 85.0,
        "total_elevation_gain": 100,
        "time_in_z1": 500,
        "time_in_z2": 1000,
        "average_cadence": 180,
        "efficiency_factor": None,
        "icu_average_watts": None,
    }]
    save_activities(activities)

    con = sqlite3.connect("coach.db")
    row = con.execute("SELECT rpe, name FROM activity_cache WHERE id='act-002'").fetchone()
    con.close()

    # rpe must be preserved (ON CONFLICT keeps existing rpe)
    assert row[0] == 8
    # name is updated (it's in the DO UPDATE SET list)
    assert row[1] == "Tempo Run Updated"


# ── data_agent_fn: full async delta flow ─────────────────────────────────────

async def test_data_agent_fn_returns_correct_state_keys(tmp_db):
    """data_agent_fn must return the three keys LangGraph expects."""
    with patch("data_agent.fetch_wellness_delta", new_callable=AsyncMock, return_value=[]), \
         patch("data_agent.fetch_activities_delta", new_callable=AsyncMock, return_value=[]):
        result = await data_agent_fn({})

    assert set(result.keys()) >= {"date", "wellness_delta", "activities_delta"}
    assert result["date"] == date.today().isoformat()
    assert result["wellness_delta"] == []
    assert result["activities_delta"] == []


async def test_data_agent_fn_saves_wellness_to_db(tmp_db):
    """Fetched wellness records must be persisted in wellness_cache."""
    wellness = load_fixture("intervals_wellness.json")
    activities = load_fixture("intervals_activities.json")

    with patch("data_agent.fetch_wellness_delta", new_callable=AsyncMock, return_value=wellness), \
         patch("data_agent.fetch_activities_delta", new_callable=AsyncMock, return_value=activities):
        result = await data_agent_fn({})

    con = sqlite3.connect(str(tmp_db))
    rows = con.execute("SELECT date FROM wellness_cache ORDER BY date").fetchall()
    con.close()
    assert len(rows) == len(wellness)
    assert result["wellness_delta"] == wellness


async def test_data_agent_fn_saves_activities_to_db(tmp_db):
    """Fetched activities must be persisted in activity_cache."""
    wellness = load_fixture("intervals_wellness.json")
    activities = load_fixture("intervals_activities.json")

    with patch("data_agent.fetch_wellness_delta", new_callable=AsyncMock, return_value=wellness), \
         patch("data_agent.fetch_activities_delta", new_callable=AsyncMock, return_value=activities):
        await data_agent_fn({})

    con = sqlite3.connect(str(tmp_db))
    rows = con.execute("SELECT id FROM activity_cache").fetchall()
    ef_row = con.execute(
        "SELECT efficiency_factor FROM activity_cache WHERE id='act-fixture-001'"
    ).fetchone()
    con.close()

    assert len(rows) == len(activities)
    # EF must be computed from icu_average_watts / average_heartrate = 165/128 ≈ 1.289
    assert ef_row is not None
    assert abs(ef_row[0] - (165.0 / 128.0)) < 0.01


async def test_data_agent_fn_updates_last_sync_on_success(tmp_db):
    """last_sync must be advanced to today after a successful delta fetch."""
    wellness = load_fixture("intervals_wellness.json")

    with patch("data_agent.fetch_wellness_delta", new_callable=AsyncMock, return_value=wellness), \
         patch("data_agent.fetch_activities_delta", new_callable=AsyncMock, return_value=[]):
        await data_agent_fn({})

    assert get_last_sync() == date.today().isoformat()


async def test_data_agent_fn_http_error_returns_empty_delta_and_does_not_advance_sync(tmp_db):
    """Pipeline must not crash on HTTP failure — empty deltas returned, last_sync unchanged."""
    with patch("data_agent.fetch_wellness_delta", new_callable=AsyncMock,
               side_effect=Exception("connection timeout")), \
         patch("data_agent.fetch_activities_delta", new_callable=AsyncMock,
               side_effect=Exception("connection timeout")):
        result = await data_agent_fn({})

    assert result["wellness_delta"] == []
    assert result["activities_delta"] == []
    # last_sync must NOT advance — still the default 90-days-ago value
    assert get_last_sync() != date.today().isoformat()
