"""
test_koop_plan_agent.py — Layer I: koop_plan_agent day-lookup correctness.

koop_plan_agent reads plans/gauja_90k_2026.md and must resolve the correct
day-by-day prescription for any date in the plan horizon (recovery/build_a/
build_b/build_c via weekly_templates, taper/race_day via explicit dates).
"""

from datetime import date

from koop_plan_agent import _entry_for_date, koop_plan_fn
from context_agent import load_plan_config


def _config():
    return load_plan_config()


def test_recovery_day_resolves_to_recovery_template():
    config = _config()
    # 2026-06-21 is a Sunday, inside the recovery block
    entry = _entry_for_date(config, date(2026, 6, 21))
    assert entry is not None
    assert entry["type"] == "rest"


def test_build_b_wednesday_resolves_to_hill_repeats():
    config = _config()
    # 2026-07-08 is a Wednesday, inside build_b (Sigulda hill repeats day)
    entry = _entry_for_date(config, date(2026, 7, 8))
    assert entry is not None
    assert entry["type"] == "quality"
    assert "Сигулда" in entry["description"] or "Sigulda" in entry.get("terrain", "")


def test_taper_day_resolves_to_explicit_date_entry():
    config = _config()
    entry = _entry_for_date(config, date(2026, 7, 19))
    assert entry is not None
    assert entry["type"] == "rest"
    assert "Фаза 1" in entry["description"]


def test_race_day_resolves_to_race_entry():
    config = _config()
    entry = _entry_for_date(config, date(2026, 8, 1))
    assert entry is not None
    assert entry["type"] == "race"


def test_date_beyond_horizon_returns_none():
    config = _config()
    entry = _entry_for_date(config, date(2026, 9, 1))
    assert entry is None


def test_koop_plan_fn_returns_seven_days_with_duration_estimated_false():
    result = koop_plan_fn({"date": "2026-06-21"})
    plan = result["upcoming_plan"]
    assert len(plan) == 7
    assert all(w["duration_estimated"] is False for w in plan)
    assert plan[0]["date"] == "2026-06-21"
    assert plan[0]["type"] == "rest"


def test_koop_plan_fn_lookahead_crosses_block_boundary():
    # 2026-06-26 + 6 days = 2026-07-02, crossing recovery -> build_a boundary
    result = koop_plan_fn({"date": "2026-06-26"})
    dates = [w["date"] for w in result["upcoming_plan"]]
    assert "2026-06-27" in dates  # last recovery day
    assert "2026-06-28" in dates  # first build_a day
    types_by_date = {w["date"]: w["type"] for w in result["upcoming_plan"]}
    assert types_by_date["2026-06-28"] == "easy"
