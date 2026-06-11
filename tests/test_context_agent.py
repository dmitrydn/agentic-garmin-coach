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

from context_agent import _compute_flags, _parse_today_events, _read_log


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
