"""
test_context_agent.py — Layer I: flag logic and log parsing.

Covers the three historical bug categories:
1. illness flag not reaching agents (commit ff893f0)
2. load events not neutralising metric flags (known_event prefix)
3. Raw dates causing LLM hallucination (commit fd4d00d, relative labels)

Pure function calls only — no DB, no Garmin, no LLM.
"""

import textwrap
from datetime import date, timedelta

import pytest

from context_agent import _compute_flags, _parse_today_events, _parse_race_dates_from_log, _read_log


# ── _compute_flags ────────────────────────────────────────────────────────────

def test_flags_acwr_high_risk():
    state = {"acwr": 1.6, "acwr_zone": "high_risk", "hrv_deviation_pct": 0, "hrv_cv_week": 0,
             "rhr_rising": False, "days_since_quality": 3, "z1z2_compliant": True, "mesocycle_week": 2}
    flags = _compute_flags(state)
    assert any("acwr_high_risk" in f for f in flags)


def test_flags_acwr_caution():
    state = {"acwr": 1.4, "acwr_zone": "caution", "hrv_deviation_pct": 0, "hrv_cv_week": 0,
             "rhr_rising": False, "days_since_quality": 3, "z1z2_compliant": True, "mesocycle_week": 2}
    flags = _compute_flags(state)
    assert any("acwr_caution" in f for f in flags)


def test_flags_hrv_critical_low():
    state = {"acwr": 1.0, "acwr_zone": "optimal", "hrv_deviation_pct": -11.0, "hrv_cv_week": 0,
             "rhr_rising": False, "days_since_quality": 3, "z1z2_compliant": True, "mesocycle_week": 2}
    flags = _compute_flags(state)
    assert any("hrv_critical_low" in f for f in flags)


def test_flags_hrv_below_baseline_not_critical():
    state = {"acwr": 1.0, "acwr_zone": "optimal", "hrv_deviation_pct": -7.0, "hrv_cv_week": 0,
             "rhr_rising": False, "days_since_quality": 3, "z1z2_compliant": True, "mesocycle_week": 2}
    flags = _compute_flags(state)
    flag_names = [f.split(":")[0] for f in flags]
    assert "hrv_below_baseline" in flag_names
    assert "hrv_critical_low" not in flag_names


def test_flags_quality_too_recent():
    state = {"acwr": 1.0, "acwr_zone": "optimal", "hrv_deviation_pct": 0, "hrv_cv_week": 0,
             "rhr_rising": False, "days_since_quality": 1, "z1z2_compliant": True, "mesocycle_week": 2}
    flags = _compute_flags(state)
    assert any("quality_too_recent" in f for f in flags)


def test_flags_8020_violation():
    state = {"acwr": 1.0, "acwr_zone": "optimal", "hrv_deviation_pct": 0, "hrv_cv_week": 0,
             "rhr_rising": False, "days_since_quality": 3, "z1z2_compliant": False,
             "z1z2_ratio_week": 0.65, "mesocycle_week": 2}
    flags = _compute_flags(state)
    assert any("8020_violation" in f for f in flags)


def test_flags_mesocycle_recovery_week():
    state = {"acwr": 1.0, "acwr_zone": "optimal", "hrv_deviation_pct": 0, "hrv_cv_week": 0,
             "rhr_rising": False, "days_since_quality": 3, "z1z2_compliant": True, "mesocycle_week": 4}
    flags = _compute_flags(state)
    assert "mesocycle_recovery_week" in flags


def test_flags_clean_state_no_flags():
    state = {"acwr": 1.05, "acwr_zone": "optimal", "hrv_deviation_pct": -2.0, "hrv_cv_week": 0.04,
             "rhr_rising": False, "days_since_quality": 3, "z1z2_compliant": True, "mesocycle_week": 2}
    flags = _compute_flags(state)
    assert flags == []


# ── _parse_today_events ───────────────────────────────────────────────────────

def test_parse_illness_tag():
    today = date.today().isoformat()
    events_text = f"{today} illness Насморк, плохое самочувствие\n"
    result = _parse_today_events(today, events_text)
    assert len(result) == 1
    tag, desc = result[0]
    assert tag == "illness"
    assert "Насморк" in desc


def test_parse_ignores_other_dates():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    events_text = f"{yesterday} hard-run Load 101\n{today} illness Температура\n"
    result = _parse_today_events(today, events_text)
    assert len(result) == 1
    assert result[0][0] == "illness"


def test_parse_tag_only_no_description():
    today = date.today().isoformat()
    events_text = f"{today} race-c\n"
    result = _parse_today_events(today, events_text)
    assert len(result) == 1
    assert result[0][0] == "race-c"
    assert result[0][1] == ""


# ── _read_log relative time labels (commit fd4d00d fix) ───────────────────────

def _write_log(path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_log_labels_past_event(tmp_path):
    log_file = tmp_path / "events.log"
    three_days_ago = (date.today() - timedelta(days=3)).isoformat()
    _write_log(log_file, [f"{three_days_ago} hard-run Load 101"])
    result = _read_log(str(log_file), days=14)
    assert "[3д назад]" in result


def test_log_labels_today_event(tmp_path):
    log_file = tmp_path / "events.log"
    today = date.today().isoformat()
    _write_log(log_file, [f"{today} race-c тренировочный старт"])
    result = _read_log(str(log_file), days=14)
    assert "[сегодня, ещё не выполнено]" in result


def test_log_labels_future_event(tmp_path):
    log_file = tmp_path / "events.log"
    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    _write_log(log_file, [f"{tomorrow} race-b B-гонка"])
    result = _read_log(str(log_file), days=14)
    assert "[через 2д]" in result


def test_log_missing_file_returns_empty(tmp_path):
    result = _read_log(str(tmp_path / "nonexistent.log"), days=14)
    assert result == ""


# ── _parse_race_dates_from_log ────────────────────────────────────────────────

def test_race_dates_from_log_overrides_yaml(tmp_path):
    """Future race-b and race-a entries in events.log must be extracted correctly."""
    log = tmp_path / "events.log"
    log.write_text(
        "2026-06-20 race-b 59km trail, грунт\n"
        "2026-08-01 race-a 90km UTMB Gauja\n",
        encoding="utf-8",
    )
    result = _parse_race_dates_from_log("2026-06-12", str(log))
    assert result["b_race_date"] == "2026-06-20"
    assert result["a_race_date"] == "2026-08-01"


def test_race_dates_past_events_ignored(tmp_path):
    """Race events before today must not be returned."""
    log = tmp_path / "events.log"
    log.write_text(
        "2026-05-23 race-c 23km тренировочный\n"
        "2026-08-01 race-a 90km UTMB Gauja\n",
        encoding="utf-8",
    )
    result = _parse_race_dates_from_log("2026-06-12", str(log))
    assert "b_race_date" not in result
    assert result["a_race_date"] == "2026-08-01"


def test_race_dates_missing_log_returns_empty(tmp_path):
    """Missing events.log must return empty dict, not raise."""
    result = _parse_race_dates_from_log("2026-06-12", str(tmp_path / "nonexistent.log"))
    assert result == {}


# ── _read_season_plan: b_race retired (cancelled 2026-06-21) ──────────────────

def test_read_season_plan_without_b_race_key_does_not_crash():
    """
    plans/gauja_90k_2026.md v2 has no `b_race` key (retired — see §1 of the
    plan). _read_season_plan must not KeyError, and must omit b_race_* /
    days_to_b_race from the result rather than inventing stale values.
    """
    from context_agent import _read_season_plan
    result = _read_season_plan("2026-06-21")
    assert result  # plan loaded successfully
    assert "days_to_b_race" not in result
    assert "b_race_date" not in result
    assert result["days_to_a_race"] == 41  # 2026-08-01 - 2026-06-21
