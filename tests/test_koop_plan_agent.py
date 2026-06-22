"""
test_koop_plan_agent.py — Layer I: koop_plan_agent day-lookup correctness.

koop_plan_agent reads plans/gauja_90k_2026.md and must resolve the correct
day-by-day prescription for any date in the plan horizon (recovery/build_a/
build_b/build_c via weekly_templates, taper/race_day via explicit dates).

Blocks run Mon-Sun (v2.1, 2026-06-22) to match metrics.py's Monday-anchored
weekly volume window — build_c is the one exception (Mon-Fri, 5 days),
since Saturday is already the first day of taper.
"""

from datetime import date

from koop_plan_agent import entry_for_date, koop_plan_fn
from context_agent import load_plan_config


def _config():
    return load_plan_config()


def test_recovery_day_resolves_to_recovery_template():
    config = _config()
    # 2026-06-22 is a Monday, the first day of the recovery block
    entry = entry_for_date(config, date(2026, 6, 22))
    assert entry is not None
    assert entry["type"] == "rest"


def test_build_b_wednesday_resolves_to_hill_repeats():
    config = _config()
    # 2026-07-08 is a Wednesday, inside build_b (Sigulda hill repeats day)
    entry = entry_for_date(config, date(2026, 7, 8))
    assert entry is not None
    assert entry["type"] == "quality"
    assert "Сигулда" in entry["description"] or "Sigulda" in entry.get("terrain", "")


def test_taper_day_resolves_to_explicit_date_entry():
    config = _config()
    entry = entry_for_date(config, date(2026, 7, 19))
    assert entry is not None
    assert entry["type"] == "rest"
    assert "Фаза 1" in entry["description"]


def test_race_day_resolves_to_race_entry():
    config = _config()
    entry = entry_for_date(config, date(2026, 8, 1))
    assert entry is not None
    assert entry["type"] == "race"


def test_date_beyond_horizon_returns_none():
    config = _config()
    entry = entry_for_date(config, date(2026, 9, 1))
    assert entry is None


def test_koop_plan_fn_returns_seven_days_with_duration_estimated_false():
    result = koop_plan_fn({"date": "2026-06-22"})
    plan = result["upcoming_plan"]
    assert len(plan) == 7
    assert all(w["duration_estimated"] is False for w in plan)
    assert plan[0]["date"] == "2026-06-22"
    assert plan[0]["type"] == "rest"


def test_koop_plan_fn_lookahead_crosses_recovery_to_build_a_boundary():
    # 2026-06-25 + 6 days = 2026-07-01, crossing recovery -> build_a (Sun 06-28 -> Mon 06-29)
    result = koop_plan_fn({"date": "2026-06-25"})
    dates = [w["date"] for w in result["upcoming_plan"]]
    assert "2026-06-28" in dates  # last recovery day (Sunday)
    assert "2026-06-29" in dates  # first build_a day (Monday)
    types_by_date = {w["date"]: w["type"] for w in result["upcoming_plan"]}
    assert types_by_date["2026-06-28"] == "rest"   # recovery's sun entry
    assert types_by_date["2026-06-29"] == "rest"   # build_a's mon entry


def test_koop_plan_fn_lookahead_crosses_build_b_to_build_c_boundary():
    # build_b's peak long run (Sat 07-11) and its back-to-back (Sun 07-12) must
    # both stay inside build_b — that's the whole point of the Mon-Sun realignment.
    result = koop_plan_fn({"date": "2026-07-09"})
    types_by_date = {w["date"]: w["type"] for w in result["upcoming_plan"]}
    assert types_by_date["2026-07-11"] == "long"
    assert types_by_date["2026-07-12"] == "easy"
    assert types_by_date["2026-07-13"] == "rest"   # first build_c day (Monday)


def test_koop_plan_fn_lookahead_crosses_build_c_to_taper_boundary():
    # build_c ends Fri 07-17; Sat 07-18 is taper's own explicit "soft start" day,
    # not build_c's old Saturday rest entry.
    result = koop_plan_fn({"date": "2026-07-16"})
    types_by_date = {w["date"]: w["type"] for w in result["upcoming_plan"]}
    assert types_by_date["2026-07-17"] == "strength"  # last build_c day
    assert types_by_date["2026-07-18"] == "rest"       # taper day 1
