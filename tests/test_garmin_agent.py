"""
test_garmin_agent.py — Layer I: Garmin API parsing with mocked garminconnect.

Covers the three historical duration bugs:
- fbtAdaptiveWorkout has workoutId=None, get_scheduled_workout_by_id(id) → 404
- get_adaptive_training_plan_by_id is the correct path (current fix)
- VO2max returned as list, not scalar (commit fa79744)
- VO2max not always on today's date (commit c866baf)
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from helpers import load_fixture, make_mock_garmin_api
from garmin_agent import (
    _compute_vo2max_trend,
    _extract_morning_battery,
    _fetch_lt,
    _fetch_vo2max,
    _steps_duration_s,
    garmin_performance_fn,
    garmin_plan_fn,
)


TODAY = "2026-06-10"


# ── ATP duration resolution ───────────────────────────────────────────────────

def test_atp_lookup_produces_duration_not_estimated(tmp_db):
    calendar = load_fixture("garmin_calendar.json")
    atp = load_fixture("garmin_atp.json")
    mock_api = make_mock_garmin_api(calendar=calendar, atp=atp)

    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_plan_fn({"date": TODAY})

    plan = result["upcoming_plan"]
    assert len(plan) == 3
    for item in plan:
        assert item["duration_estimated"] is False, (
            f"{item['description']} still has duration_estimated=True"
        )


def test_atp_lookup_maps_workout_detail(tmp_db):
    calendar = load_fixture("garmin_calendar.json")
    atp = load_fixture("garmin_atp.json")
    mock_api = make_mock_garmin_api(calendar=calendar, atp=atp)

    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_plan_fn({"date": TODAY})

    by_title = {w["description"]: w for w in result["upcoming_plan"]}
    assert by_title["Base Run"]["workout_detail"] == "131bpm"
    assert by_title["VO2 Max"]["workout_detail"] == "5x3:00@166bpm"


def test_atp_duration_values_correct(tmp_db):
    calendar = load_fixture("garmin_calendar.json")
    atp = load_fixture("garmin_atp.json")
    mock_api = make_mock_garmin_api(calendar=calendar, atp=atp)

    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_plan_fn({"date": TODAY})

    by_title = {w["description"]: w for w in result["upcoming_plan"]}
    assert by_title["Base Run"]["duration_min"] == 44   # 2640s / 60
    assert by_title["VO2 Max"]["duration_min"] == 43    # 2580s / 60
    assert by_title["Long Run"]["duration_min"] == 153  # 9180s / 60


def test_no_atp_plan_id_falls_back_to_heuristic(tmp_db):
    # Calendar items without trainingPlanId → no ATP call → heuristic
    calendar = {
        "calendarItems": [{
            "itemType": "fbtAdaptiveWorkout",
            "date": TODAY,
            "title": "Base Run",
            "sportTypeKey": "running",
            "workoutUuid": "uuid-xxx",
            "workoutId": None,
            "id": 1781076593000,
        }]
    }
    mock_api = make_mock_garmin_api(calendar=calendar, atp=None)
    mock_api.get_scheduled_workout_by_id.side_effect = Exception("404")

    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_plan_fn({"date": TODAY})

    item = result["upcoming_plan"][0]
    assert item["duration_estimated"] is True


def test_uuid_not_in_atp_falls_back_per_item(tmp_db):
    # Two items: one has matching UUID, one does not.
    calendar = {
        "calendarItems": [
            {"itemType": "fbtAdaptiveWorkout", "date": TODAY, "title": "Base Run",
             "sportTypeKey": "running", "workoutUuid": "uuid-base-001",
             "trainingPlanId": "plan-abc-123", "workoutId": None, "id": 111},
            {"itemType": "fbtAdaptiveWorkout", "date": TODAY, "title": "Mystery Run",
             "sportTypeKey": "running", "workoutUuid": "uuid-unknown-999",
             "trainingPlanId": "plan-abc-123", "workoutId": None, "id": 222},
        ]
    }
    atp = {"planId": "plan-abc-123", "taskList": [
        {"taskWorkout": {"workoutUuid": "uuid-base-001",
                         "estimatedDurationInSecs": 2640, "workoutDescription": "131bpm"}}
    ]}
    mock_api = make_mock_garmin_api(calendar=calendar, atp=atp)
    mock_api.get_scheduled_workout_by_id.side_effect = Exception("404")

    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_plan_fn({"date": TODAY})

    by_title = {w["description"]: w for w in result["upcoming_plan"]}
    assert by_title["Base Run"]["duration_estimated"] is False
    assert by_title["Mystery Run"]["duration_estimated"] is True


def test_cache_hit_skips_garmin_api(tmp_db):
    # Pre-populate the cache with a fresh entry
    con = sqlite3.connect(str(tmp_db))
    plan_json = json.dumps([{"date": TODAY, "type": "running", "description": "Cached Run",
                              "duration_min": 50, "duration_estimated": False}])
    con.execute(
        "INSERT INTO garmin_cache (date, upcoming_plan_json, fetched_at) VALUES (?,?,?)",
        (TODAY, plan_json, datetime.now().isoformat())
    )
    con.commit()
    con.close()

    mock_api = make_mock_garmin_api()
    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_plan_fn({"date": TODAY})

    mock_api.get_scheduled_workouts.assert_not_called()
    assert result["upcoming_plan"][0]["description"] == "Cached Run"


# ── VO2max parsing (commits fa79744 + c866baf) ────────────────────────────────

def test_vo2max_extracted_from_list_format(tmp_db):
    # Bug: API returns a list, not a scalar
    mock_api = make_mock_garmin_api(
        vo2max_data=[{"generic": {"vo2MaxPreciseValue": 52.3, "vo2MaxValue": 52.0}}]
    )
    with patch("garmin_agent._get_api", return_value=mock_api):
        val = _fetch_vo2max(mock_api, TODAY)
    assert val == 52.3  # prefers vo2MaxPreciseValue


def test_vo2max_fallback_when_today_returns_empty(tmp_db):
    # Bug: VO2max not on today, need to search by recent activity date
    call_count = {"n": 0}
    def patched_get_max_metrics(date_str):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []  # today returns empty
        return [{"generic": {"vo2MaxPreciseValue": 51.5}}]  # second call succeeds

    mock_api = make_mock_garmin_api()
    mock_api.get_max_metrics.side_effect = patched_get_max_metrics

    val = _fetch_vo2max(mock_api, TODAY)
    assert val == 51.5
    assert call_count["n"] >= 2


# ── Helper function unit tests ────────────────────────────────────────────────

def test_steps_duration_flat_steps():
    steps = [
        {"type": "WorkoutStep", "endCondition": {"conditionTypeKey": "time"},
         "endConditionValue": 600},
        {"type": "WorkoutStep", "endCondition": {"conditionTypeKey": "time"},
         "endConditionValue": 1200},
    ]
    assert _steps_duration_s(steps) == 1800


def test_steps_duration_repeat_group():
    # 3 × (2 steps × 180s each) = 1080s
    steps = [{
        "type": "RepeatGroupDTO",
        "numberOfIterations": 3,
        "workoutSteps": [
            {"endCondition": {"conditionTypeKey": "time"}, "endConditionValue": 180},
            {"endCondition": {"conditionTypeKey": "time"}, "endConditionValue": 180},
        ],
    }]
    assert _steps_duration_s(steps) == 1080


def test_extract_morning_battery_picks_max():
    bb_list = [{"date": TODAY, "bodyBatteryValuesArray": [[0, 85], [3600, 72], [7200, 60]]}]
    result = _extract_morning_battery(bb_list, TODAY)
    assert result == 85


def test_lt_parsing_nested_speed_and_heart_rate():
    mock_api = make_mock_garmin_api(
        lt_data={"speed_and_heart_rate": {"heartRate": 154, "speed": 0.00347}}
    )
    hr, pace_s = _fetch_lt(mock_api)
    assert hr == 154
    assert pace_s == 3   # round(0.00347 * 1000)


# ── _compute_vo2max_trend ─────────────────────────────────────────────────────

def _insert_prior_vo2max(tmp_db, prior_date: str, vo2max: float) -> None:
    con = sqlite3.connect(str(tmp_db))
    con.execute(
        "INSERT INTO performance_cache (date, vo2max, fetched_at) VALUES (?,?,?)",
        (prior_date, vo2max, datetime.now().isoformat()),
    )
    con.commit()
    con.close()


def test_vo2max_trend_rising(tmp_db):
    # diff = 51.0 - 50.0 = +1.0 > 0.5 → "rising"
    prior = (date.fromisoformat(TODAY) - timedelta(days=7)).isoformat()
    _insert_prior_vo2max(tmp_db, prior, 50.0)
    assert _compute_vo2max_trend(51.0, TODAY) == "rising"


def test_vo2max_trend_falling(tmp_db):
    # diff = 51.0 - 52.0 = -1.0 < -0.5 → "falling"
    prior = (date.fromisoformat(TODAY) - timedelta(days=7)).isoformat()
    _insert_prior_vo2max(tmp_db, prior, 52.0)
    assert _compute_vo2max_trend(51.0, TODAY) == "falling"


def test_vo2max_trend_stable(tmp_db):
    # diff = 52.3 - 52.0 = +0.3  within ±0.5 → "stable"
    prior = (date.fromisoformat(TODAY) - timedelta(days=7)).isoformat()
    _insert_prior_vo2max(tmp_db, prior, 52.0)
    assert _compute_vo2max_trend(52.3, TODAY) == "stable"


def test_vo2max_trend_stable_boundary_exact_threshold(tmp_db):
    # diff = exactly 0.5 — NOT > 0.5 → "stable"
    prior = (date.fromisoformat(TODAY) - timedelta(days=7)).isoformat()
    _insert_prior_vo2max(tmp_db, prior, 52.0)
    assert _compute_vo2max_trend(52.5, TODAY) == "stable"


def test_vo2max_trend_unknown_when_current_none(tmp_db):
    assert _compute_vo2max_trend(None, TODAY) == "unknown"


def test_vo2max_trend_unknown_when_no_prior_row(tmp_db):
    # Empty performance_cache → no prior → "unknown"
    assert _compute_vo2max_trend(52.3, TODAY) == "unknown"


# ── garmin_performance_fn node ────────────────────────────────────────────────

def test_garmin_performance_fn_returns_all_expected_keys(tmp_db):
    """garmin_performance_fn must return all keys that downstream agents read."""
    mock_api = make_mock_garmin_api()
    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_performance_fn({"date": TODAY})

    expected_keys = {
        "vo2max", "vo2max_trend",
        "lt_hr", "lt_pace_s",
        "sleep_deep_min", "sleep_rem_min", "sleep_light_min", "sleep_awake_min",
        "hrv_garmin_today", "rhr_garmin_today",
    }
    assert expected_keys.issubset(result.keys()), (
        f"Missing: {expected_keys - result.keys()}"
    )


def test_garmin_performance_fn_parses_mock_values(tmp_db):
    """Node must correctly parse each sub-API response from the mock."""
    mock_api = make_mock_garmin_api()
    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_performance_fn({"date": TODAY})

    assert abs(result["vo2max"] - 52.3) < 0.01
    assert result["lt_hr"] == 154
    assert result["sleep_deep_min"] == 80    # 4800s / 60
    assert result["sleep_rem_min"] == 90     # 5400s / 60
    assert result["sleep_light_min"] == 150  # 9000s / 60
    assert result["sleep_awake_min"] == 10   # 600s / 60
    assert result["hrv_garmin_today"] == 61
    assert result["rhr_garmin_today"] == 47


def test_garmin_performance_fn_saves_to_performance_cache(tmp_db):
    """Fetched values must be persisted in performance_cache for TTL caching."""
    mock_api = make_mock_garmin_api()
    with patch("garmin_agent._get_api", return_value=mock_api):
        garmin_performance_fn({"date": TODAY})

    con = sqlite3.connect(str(tmp_db))
    row = con.execute(
        "SELECT vo2max, lt_hr, hrv_garmin, rhr_garmin FROM performance_cache WHERE date=?",
        (TODAY,),
    ).fetchone()
    con.close()
    assert row is not None, "performance_cache row not written"
    assert abs(row[0] - 52.3) < 0.01
    assert row[1] == 154
    assert row[2] == 61
    assert row[3] == 47


def test_garmin_performance_fn_cache_hit_skips_api(tmp_db):
    """A fresh performance_cache row must bypass all live API calls."""
    con = sqlite3.connect(str(tmp_db))
    con.execute(
        """INSERT INTO performance_cache
               (date, vo2max, lt_hr, lt_pace_s,
                sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
                hrv_garmin, rhr_garmin, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (TODAY, 51.0, 152, 340, 70, 80, 120, 10, 58, 46, datetime.now().isoformat()),
    )
    con.commit()
    con.close()

    mock_api = make_mock_garmin_api()
    with patch("garmin_agent._get_api", return_value=mock_api):
        result = garmin_performance_fn({"date": TODAY})

    mock_api.get_max_metrics.assert_not_called()
    mock_api.get_lactate_threshold.assert_not_called()
    assert result["vo2max"] == 51.0
    assert result["hrv_garmin_today"] == 58
    assert result["rhr_garmin_today"] == 46
