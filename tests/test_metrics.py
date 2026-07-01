"""
test_metrics.py — Layer I: pure math validation for metrics.py.

No I/O, no mocks. Every function is deterministic — tests assert
float precision, boundary zones, and edge-case guards.
"""

import pytest
from datetime import date, timedelta

from metrics import (
    adjusted_training_load,
    calculate_acwr,
    days_since_last_quality,
    format_recent_activities,
    hrv_analysis,
    mesocycle_week,
    rhr_trend_analysis,
    strength_load_today,
    weekly_volume_status,
    weekly_zone_ratio,
)


# ── HRV Analysis ──────────────────────────────────────────────────────────────

def _hrv_history(values: list[float]) -> list[dict]:
    """Build minimal wellness history list from a list of HRV floats."""
    return [{"hrv": v, "resting_hr": 47} for v in values]


def test_hrv_deviation_positive():
    # 8 values: baseline avg = 60.0, today = 66
    # deviation = (66 - 60) / 60 * 100 = +10.0%
    hist = _hrv_history([60, 60, 60, 60, 60, 60, 60, 66])
    result = hrv_analysis(hist)
    assert result["hrv_today"] == 66
    assert result["hrv_rolling_avg"] == 60.0
    assert abs(result["hrv_deviation_pct"] - 10.0) < 0.1


def test_hrv_deviation_negative_critical():
    # baseline avg from first 7 = 62, today = 54
    # deviation = (54 - 62) / 62 * 100 = -12.9%
    hist = _hrv_history([62, 62, 62, 62, 62, 62, 62, 54])
    result = hrv_analysis(hist)
    assert result["hrv_deviation_pct"] < -10.0  # below -10% threshold


def test_hrv_rolling_excludes_today():
    # Plews 2017: today's HRV must NOT be part of its own 7-day baseline.
    # If today=100 were included in avg, deviation would be artificially low.
    hist = _hrv_history([50, 50, 50, 50, 50, 50, 50, 100])
    result = hrv_analysis(hist)
    # rolling_avg must be 50.0 (only the 7 prior values)
    assert result["hrv_rolling_avg"] == 50.0
    # deviation = (100 - 50) / 50 * 100 = +100%
    assert abs(result["hrv_deviation_pct"] - 100.0) < 0.1


def test_hrv_insufficient_data_returns_safe_defaults():
    # < 3 values → all zeroed, no crash
    result = hrv_analysis(_hrv_history([60, 55]))
    assert result["hrv_today"] is None
    assert result["hrv_rolling_avg"] == 0.0
    assert result["hrv_deviation_pct"] == 0.0


def test_hrv_cv_measures_week_variability():
    # High-variance week: std_dev is large relative to mean
    hist = _hrv_history([40, 60, 40, 60, 40, 60, 40, 55])  # last 7 prev = stdev ~10
    result = hrv_analysis(hist)
    assert result["hrv_cv_week"] > 0.10  # flagged as unstable


def test_hrv_stable_week_low_cv():
    hist = _hrv_history([60, 61, 60, 60, 61, 60, 60, 62])
    result = hrv_analysis(hist)
    assert result["hrv_cv_week"] < 0.05


# ── ACWR Zones ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("atl,ctl,expected_zone", [
    (79, 100, "underload"),    # 0.79 < 0.80
    (80, 100, "optimal"),      # 0.80 boundary
    (130, 100, "optimal"),     # 1.30 boundary
    (131, 100, "caution"),     # 1.31 just above
    (150, 100, "caution"),     # 1.50 boundary
    (151, 100, "high_risk"),   # 1.51 just above
    (200, 100, "high_risk"),
])
def test_acwr_zone_boundaries(atl, ctl, expected_zone):
    result = calculate_acwr(ctl=float(ctl), atl=float(atl))
    assert result["acwr_zone"] == expected_zone


def test_acwr_zero_ctl_returns_unknown():
    result = calculate_acwr(ctl=0, atl=80)
    assert result["acwr_zone"] == "unknown"
    assert result["acwr"] == 1.0


# ── RHR Trend ─────────────────────────────────────────────────────────────────

def test_rhr_rising_flag_triggered_above_3bpm():
    hist = [{"resting_hr": 46}, {"resting_hr": 47}, {"resting_hr": 48}, {"resting_hr": 52}]
    result = rhr_trend_analysis(hist)
    assert result["rhr_rising"] is True
    assert result["rhr_trend"] > 3.0


def test_rhr_rising_not_triggered_small_increase():
    hist = [{"resting_hr": 46}, {"resting_hr": 47}, {"resting_hr": 47}, {"resting_hr": 48}]
    result = rhr_trend_analysis(hist)
    assert result["rhr_rising"] is False


def test_rhr_insufficient_data():
    result = rhr_trend_analysis([{"resting_hr": 47}])
    assert result["rhr_today"] is None
    assert result["rhr_rising"] is False


# ── Terrain Load Multiplier ───────────────────────────────────────────────────

@pytest.mark.parametrize("gain_m,dist_m,expected_multiplier", [
    (0,    10000, 1.00),   # flat road
    (80,   10000, 1.00),   # exactly 8 m/km — code uses > 8 (strict), stays flat
    (81,   10000, 1.10),   # 8.1 m/km — just above threshold → moderate
    (140,  10000, 1.10),   # 14 m/km — still moderate
    (150,  10000, 1.10),   # exactly 15 m/km — code uses > 15 (strict), stays moderate
    (151,  10000, 1.20),   # 15.1 m/km — just above steep threshold
    (300,  10000, 1.20),   # very steep
])
def test_terrain_multiplier(gain_m, dist_m, expected_multiplier):
    activity = {
        "training_load": 100.0,
        "distance_m": dist_m,
        "elevation_gain_m": gain_m,
    }
    result = adjusted_training_load(activity)
    assert abs(result - 100.0 * expected_multiplier) < 0.01


def test_terrain_multiplier_zero_distance():
    result = adjusted_training_load({"training_load": 50.0, "distance_m": 0})
    assert result == 50.0  # no crash, returns base_load


# ── 80/20 Zone Ratio ─────────────────────────────────────────────────────────

def test_zone_ratio_exactly_75pct_is_compliant():
    acts = [{"duration_s": 3600, "time_in_z1": 1800, "time_in_z2": 900}]  # 75%
    result = weekly_zone_ratio(acts)
    assert result["z1z2_compliant"] is True


def test_zone_ratio_below_75pct_not_compliant():
    acts = [{"duration_s": 3600, "time_in_z1": 1200, "time_in_z2": 480}]  # 46.7%
    result = weekly_zone_ratio(acts)
    assert result["z1z2_compliant"] is False


def test_zone_ratio_missing_z1z2_returns_none_not_false():
    # Bug from history: z1=z2=0 with activities present must return None,
    # not 0% — avoids spurious 8020_violation flag.
    acts = [{"duration_s": 3600, "time_in_z1": 0, "time_in_z2": 0}]
    result = weekly_zone_ratio(acts)
    assert result["z1z2_ratio"] is None
    assert result["z1z2_compliant"] is None


def test_zone_ratio_empty_activities():
    result = weekly_zone_ratio([])
    assert result["z1z2_ratio"] is None
    assert result["total_minutes"] == 0


# ── Mesocycle 3+1 ─────────────────────────────────────────────────────────────

def test_mesocycle_four_week_rotation():
    # mesocycle_week(start) returns the week number relative to today.
    # If start = today → 0 days elapsed → week 1.
    # If start = today - 7  → 7 days → week 2.
    # If start = today - 14 → 14 days → week 3.
    # If start = today - 21 → 21 days → week 4.
    # If start = today - 28 → 28 days → week 1 again (full cycle).
    from datetime import date, timedelta
    today = date.today()
    assert mesocycle_week(today.isoformat()) == 1
    assert mesocycle_week((today - timedelta(days=7)).isoformat())  == 2
    assert mesocycle_week((today - timedelta(days=14)).isoformat()) == 3
    assert mesocycle_week((today - timedelta(days=21)).isoformat()) == 4
    assert mesocycle_week((today - timedelta(days=28)).isoformat()) == 1  # cycle resets


# ── Strength Load ─────────────────────────────────────────────────────────────

def test_strength_load_not_completed_returns_zero():
    assert strength_load_today("build", completed=False) == 0.0
    assert strength_load_today("adaptation", completed=False) == 0.0


def test_strength_load_build_phase():
    assert strength_load_today("build", completed=True) == 50.0


def test_strength_load_unknown_phase_returns_zero():
    assert strength_load_today("unknown_phase", completed=True) == 0.0


# ── Days Since Quality ────────────────────────────────────────────────────────

def test_days_since_quality_no_activities_returns_99():
    assert days_since_last_quality([]) == 99


def test_days_since_quality_detects_high_load():
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    acts = [{"date": yesterday, "training_load": 80, "name": "Tempo Run"}]
    result = days_since_last_quality(acts)
    assert result == 1


def test_days_since_quality_ignores_easy_run():
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    acts = [{"date": yesterday, "training_load": 40, "name": "Easy Run"}]
    result = days_since_last_quality(acts)
    assert result == 99  # no quality found


# ── format_recent_activities: factual grounding vs hallucination ──────────────

def test_recent_activities_empty_states_no_data_explicitly():
    """No activities → explicit 'none' text so LLM won't invent history."""
    out = format_recent_activities([])
    assert out["days_since_last_activity"] is None
    assert "нет" in out["summary"].lower()
    assert "не придумывай" in out["summary"].lower()


def test_recent_activities_stale_data_carries_warning():
    """Last activity ≥2 days old → explicit staleness marker for the LLM."""
    old = (date.today() - timedelta(days=7)).isoformat()
    acts = [{"date": old, "name": "Base", "duration_s": 3600,
             "training_load": 60, "time_in_z1": 3000, "time_in_z2": 600}]
    out = format_recent_activities(acts)
    assert out["days_since_last_activity"] == 7
    assert "⚠" in out["summary"]
    assert "НЕТ" in out["summary"]


def test_recent_activities_lists_actual_sessions_sorted_desc():
    """Real sessions are listed newest-first with duration and load."""
    today = date.today()
    acts = [
        {"date": (today - timedelta(days=3)).isoformat(), "name": "Intervals",
         "duration_s": 3000, "training_load": 95, "time_in_z1": 600,
         "time_in_z2": 1200, "rpe": 7},
        {"date": (today - timedelta(days=1)).isoformat(), "name": "Easy",
         "duration_s": 2400, "training_load": 40, "time_in_z1": 2000,
         "time_in_z2": 200},
    ]
    out = format_recent_activities(acts)
    lines = [l for l in out["summary"].splitlines() if "—" in l]
    # newest (Easy, -1d) must appear before older (Intervals, -3d)
    assert lines[0].index("Easy") >= 0
    assert "Intervals" in lines[1]
    assert "RPE 7" in out["summary"]


# ── metrics_fn LangGraph node integration ─────────────────────────────────────

def test_metrics_fn_integration_reads_db_and_returns_all_keys(tmp_db):
    """
    metrics_fn must read wellness_cache + activity_cache from SQLite and
    return all keys required by downstream agents.

    Pure functions are unit-tested above. This test guards the SQL queries,
    column ordering, and dict-assembly in metrics_fn itself — none of which
    pure-function tests can catch.
    """
    import sqlite3
    from datetime import date, timedelta
    from metrics import metrics_fn

    today = date.today()
    con = sqlite3.connect(str(tmp_db))

    # Insert 14 days of wellness (oldest → newest)
    for i in range(14):
        d = (today - timedelta(days=13 - i)).isoformat()
        con.execute(
            "INSERT INTO wellness_cache VALUES (?,?,?,?,?,?,?,?)",
            (d, 50.0 + i * 0.5, 48.0 + i * 0.5, 2.0,
             60.0 + i * 0.2, 47, 75.0, d + "T06:00:00"),
        )

    # Insert one activity this week (low load → days_since_quality = 99)
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    con.execute(
        """INSERT INTO activity_cache
           (id, date, name, distance_m, duration_s, avg_hr, training_load,
            adjusted_load, avg_pace_s, elevation_gain_m, time_in_z1, time_in_z2,
            surface, rpe, synced_at, avg_cadence, avg_gct_ms, avg_vertical_osc_mm,
            avg_vertical_ratio, avg_stride_length_m, efficiency_factor)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("act-metrics-test", week_start, "Easy Run", 10000, 3600, 130, 45.0,
         None, 360.0, 80.0, 1800, 900, None, None, week_start + "T07:00:00",
         None, None, None, None, None, None),
    )

    # Set mesocycle_start so mesocycle_week is deterministic
    con.execute(
        "INSERT OR REPLACE INTO pipeline_meta VALUES ('mesocycle_start', ?)",
        (today.isoformat(),),  # today → week 1
    )
    con.commit()
    con.close()

    result = metrics_fn({"activities_delta": []})

    expected_keys = {
        "hrv_today", "hrv_rolling_avg", "hrv_deviation_pct", "hrv_cv_week",
        "acwr", "acwr_zone",
        "rhr_today", "rhr_trend", "rhr_rising",
        "form_today", "sleep_score",
        "z1z2_ratio_week", "z1z2_compliant",
        "days_since_quality", "mesocycle_week",
        "adjusted_loads", "strength_load_today",
    }
    assert expected_keys.issubset(result.keys()), (
        f"Missing keys: {expected_keys - result.keys()}"
    )

    # Type sanity checks: verify SQL column order did not silently shift
    assert isinstance(result["acwr"], float)
    assert result["acwr_zone"] in {"underload", "optimal", "caution", "high_risk", "unknown"}
    assert isinstance(result["mesocycle_week"], int)
    assert result["mesocycle_week"] == 1   # mesocycle_start = today → week 1
    assert isinstance(result["adjusted_loads"], list)
    assert result["strength_load_today"] == 0.0  # no strength_log row


# ── weekly_volume_status (koop-plan volume control) ───────────────────────────

def test_volume_status_on_track_within_tolerance():
    # target 260, actual 280 → +7.7%, within ±15%
    result = weekly_volume_status(280, 260)
    assert result["volume_status"] == "on_track"


def test_volume_status_over_above_tolerance():
    # target 260, actual 320 → +23%, above +15%
    result = weekly_volume_status(320, 260)
    assert result["volume_status"] == "over"
    assert result["volume_pct"] > 15


def test_volume_status_under_below_tolerance():
    # target 260, actual 180 → -30.8%, below -15%
    result = weekly_volume_status(180, 260)
    assert result["volume_status"] == "under"
    assert result["volume_pct"] < -15


def test_volume_status_unknown_when_no_target():
    result = weekly_volume_status(200, None)
    assert result["volume_status"] == "unknown"
    assert result["volume_pct"] is None


def test_volume_status_unknown_when_actual_missing():
    result = weekly_volume_status(None, 260)
    assert result["volume_status"] == "unknown"
