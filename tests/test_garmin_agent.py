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

from unittest.mock import MagicMock

from helpers import load_fixture, make_mock_garmin_api
from garmin_agent import (
    _compute_vo2max_trend,
    _extract_morning_battery,
    _fetch_lt,
    _fetch_vo2max,
    _steps_duration_s,
    backfill_running_dynamics_fn,
    fetch_running_dynamics,
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


# ── Running Dynamics backfill (GCT, vertical oscillation, vertical ratio) ────
#
# intervals.icu doesn't expose these fields at all (verified against live API
# response). Garmin Connect's get_activity_details() has them as per-sample
# time-series, keyed by metricDescriptors — index position is NOT stable
# across activities, so fetch_running_dynamics must resolve it dynamically.

def _activity_details_fixture(gct_vals, vo_vals, vr_vals, balance_vals=None):
    """Builds a minimal get_activity_details()-shaped dict with 4 metrics:
    directGroundContactTime, directVerticalOscillation, directVerticalRatio,
    directGroundContactBalanceLeft — deliberately at non-zero, non-sequential
    metricsIndex positions to catch any code that assumes a fixed array layout.
    balance_vals=None means "chest strap not worn" (no balance samples at all),
    matching a wrist-estimated (Coros / no HRM) activity."""
    descriptors = [
        {"key": "directVerticalRatio", "metricsIndex": 0},
        {"key": "directGroundContactTime", "metricsIndex": 2},
        {"key": "directVerticalOscillation", "metricsIndex": 5},
        {"key": "directGroundContactBalanceLeft", "metricsIndex": 7},
    ]
    if balance_vals is None:
        balance_vals = [None] * len(gct_vals)
    rows = []
    for vr, gct, vo, bal in zip(vr_vals, gct_vals, vo_vals, balance_vals):
        metrics = [None] * 8
        metrics[0] = vr
        metrics[2] = gct
        metrics[5] = vo
        metrics[7] = bal
        rows.append({"metrics": metrics})
    return {"metricDescriptors": descriptors, "activityDetailMetrics": rows}


def test_fetch_running_dynamics_averages_and_converts_units():
    # GCT ms as-is; VO cm -> mm (x10); VR dimensionless as-is.
    # Zeros and None must be excluded from the average.
    detail = _activity_details_fixture(
        gct_vals=[250, 260, 0, None, 270],
        vo_vals=[7.0, 7.5, 0, None, 8.0],
        vr_vals=[9.0, 9.5, 0, None, 10.0],
    )
    mock_api = MagicMock()
    mock_api.get_activity_details.return_value = detail

    result = fetch_running_dynamics(mock_api, "12345")

    assert result["avg_gct_ms"] == 260.0
    assert result["avg_vertical_osc_mm"] == 75.0   # 7.5cm avg -> 75.0mm
    assert result["avg_vertical_ratio"] == 9.5


def test_fetch_running_dynamics_returns_none_when_all_values_missing():
    detail = _activity_details_fixture(
        gct_vals=[0, None], vo_vals=[0, None], vr_vals=[0, None],
    )
    mock_api = MagicMock()
    mock_api.get_activity_details.return_value = detail

    assert fetch_running_dynamics(mock_api, "12345") is None


# ── Sensor source detection (HRM-Pro chest strap vs Coros/wrist-estimated) ──

def test_fetch_running_dynamics_detects_chest_strap_via_balance():
    # Real left/right Ground Contact Balance present on most samples → chest strap.
    detail = _activity_details_fixture(
        gct_vals=[260, 270, 265, 268],
        vo_vals=[7.0, 7.5, 7.2, 7.3],
        vr_vals=[9.0, 9.5, 9.2, 9.3],
        balance_vals=[49.0, 49.5, 50.0, 50.2],
    )
    mock_api = MagicMock()
    mock_api.get_activity_details.return_value = detail

    result = fetch_running_dynamics(mock_api, "12345")
    assert result["rd_sensor_source"] == "chest_strap"


def test_fetch_running_dynamics_detects_wrist_estimated_without_balance():
    # GCT/VO/VR present (wrist can estimate these) but no balance samples
    # at all → Coros or no HRM, wrist-only estimation.
    detail = _activity_details_fixture(
        gct_vals=[260, 270, 265, 268],
        vo_vals=[7.0, 7.5, 7.2, 7.3],
        vr_vals=[9.0, 9.5, 9.2, 9.3],
        balance_vals=None,
    )
    mock_api = MagicMock()
    mock_api.get_activity_details.return_value = detail

    result = fetch_running_dynamics(mock_api, "12345")
    assert result["rd_sensor_source"] == "wrist_estimated"


def test_fetch_running_dynamics_sparse_balance_below_threshold_is_wrist_estimated():
    # A couple of stray non-zero balance samples (sensor noise/brief reconnect)
    # below the 10% threshold must NOT be classified as chest_strap.
    n = 20
    detail = _activity_details_fixture(
        gct_vals=[260] * n,
        vo_vals=[7.0] * n,
        vr_vals=[9.0] * n,
        balance_vals=[50.0, 50.0] + [None] * (n - 2),  # 2/20 = 10% exactly... use 1 to go below
    )
    detail["activityDetailMetrics"][1]["metrics"][7] = None  # drop to 1/20 = 5%, below threshold
    mock_api = MagicMock()
    mock_api.get_activity_details.return_value = detail

    result = fetch_running_dynamics(mock_api, "12345")
    assert result["rd_sensor_source"] == "wrist_estimated"


def test_fetch_running_dynamics_handles_api_error_gracefully():
    mock_api = MagicMock()
    mock_api.get_activity_details.side_effect = Exception("network error")

    assert fetch_running_dynamics(mock_api, "12345") is None


def _insert_activity(con, activity_id, garmin_id, gct=None):
    con.execute("""
        INSERT INTO activity_cache
            (id, date, name, distance_m, duration_s, avg_hr, training_load,
             adjusted_load, avg_pace_s, elevation_gain_m, time_in_z1, time_in_z2,
             surface, rpe, synced_at, avg_cadence, avg_gct_ms, avg_vertical_osc_mm,
             avg_vertical_ratio, avg_stride_length_m, efficiency_factor, garmin_activity_id)
        VALUES (?,'2026-06-10','Run',10000,3600,140,80,NULL,360,100,1000,1000,
                NULL,NULL,'2026-06-10T08:00:00',175,?,NULL,NULL,0.9,1.3,?)
    """, (activity_id, gct, garmin_id))


def test_backfill_running_dynamics_updates_missing_rows(tmp_db):
    con = sqlite3.connect("coach.db")
    _insert_activity(con, "act-rd-1", "999111")
    con.commit()
    con.close()

    detail = _activity_details_fixture(
        gct_vals=[260, 270], vo_vals=[7.0, 8.0], vr_vals=[9.0, 10.0],
        balance_vals=[49.0, 50.0],
    )
    mock_api = MagicMock()
    mock_api.get_activity_details.return_value = detail

    with patch("garmin_agent._get_api", return_value=mock_api):
        backfill_running_dynamics_fn({})

    con = sqlite3.connect("coach.db")
    row = con.execute(
        "SELECT avg_gct_ms, avg_vertical_osc_mm, avg_vertical_ratio, rd_sensor_source "
        "FROM activity_cache WHERE id='act-rd-1'"
    ).fetchone()
    con.close()
    assert row[0] == 265.0
    assert row[1] == 75.0
    assert row[2] == 9.5
    assert row[3] == "chest_strap"


def test_backfill_running_dynamics_skips_rows_already_filled(tmp_db):
    con = sqlite3.connect("coach.db")
    _insert_activity(con, "act-rd-2", "999222", gct=300.0)  # already backfilled
    con.commit()
    con.close()

    mock_api = MagicMock()
    with patch("garmin_agent._get_api", return_value=mock_api):
        backfill_running_dynamics_fn({})

    mock_api.get_activity_details.assert_not_called()


def test_backfill_running_dynamics_no_network_call_when_nothing_missing(tmp_db):
    # Empty activity_cache → no rows need backfill → _get_api must never be called
    with patch("garmin_agent._get_api") as mock_get_api:
        backfill_running_dynamics_fn({})
    mock_get_api.assert_not_called()
