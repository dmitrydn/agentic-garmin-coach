"""
test_koop_plan_agent.py — Layer I: koop_plan_agent day-lookup correctness.

koop_plan_agent reads plans/season_plan_2026.md and must resolve the correct
day-by-day prescription for any date in the plan horizon. As of v3 (2026-07-29)
the plan is an Achilles rehab → return-to-run block (Gauja 90k DNS'd), anchored
to the conditional comeback race Stirnu Buks Lūsis on 2026-09-12:

  rehab      (29.07–03.08)
  montenegro (04.08–18.08)
  rebuild1   (19.08–24.08)
  rebuild2   (25.08–31.08)
  sharpen    (01.09–11.09)
  Final 18 days 26.08–11.09 encoded as explicit dated overrides
  (taper_days key); 09-12 via race_day.
"""

from datetime import date

from koop_plan_agent import entry_for_date, koop_plan_fn
from context_agent import load_plan_config


def _config():
    return load_plan_config()


def test_rehab_friday_resolves_to_strength_template():
    config = _config()
    # 2026-07-31 is a Friday inside the rehab block (Achilles-safe gym day)
    entry = entry_for_date(config, date(2026, 7, 31))
    assert entry is not None
    assert entry["type"] == "strength"


def test_montenegro_wednesday_resolves_to_hike():
    config = _config()
    # 2026-08-05 is a Wednesday inside the montenegro block (hiking day)
    entry = entry_for_date(config, date(2026, 8, 5))
    assert entry is not None
    assert entry["type"] == "easy"
    assert entry.get("terrain") == "hike"


def test_rebuild_saturday_resolves_to_long_run():
    config = _config()
    # 2026-08-22 is a Saturday inside rebuild1 (first return long run, flat)
    entry = entry_for_date(config, date(2026, 8, 22))
    assert entry is not None
    assert entry["type"] == "long"


def test_taper_day_resolves_to_explicit_date_entry():
    config = _config()
    # 2026-09-10 is an explicit dated rest override (peak-taper before the race)
    entry = entry_for_date(config, date(2026, 9, 10))
    assert entry is not None
    assert entry["type"] == "rest"


def test_key_race_sim_resolves_on_course_2908():
    config = _config()
    # 2026-08-29: single key race-sim on the actual Lūsis course (athlete decision 25.08)
    entry = entry_for_date(config, date(2026, 8, 29))
    assert entry is not None
    assert entry["type"] == "long"
    assert entry.get("terrain") == "trail"
    assert entry["duration_min"] == 120


def test_race_day_resolves_to_race_entry():
    config = _config()
    entry = entry_for_date(config, date(2026, 9, 12))
    assert entry is not None
    assert entry["type"] == "race"


def test_date_beyond_horizon_returns_none():
    config = _config()
    entry = entry_for_date(config, date(2026, 10, 1))
    assert entry is None


def test_koop_plan_fn_returns_seven_days_with_duration_estimated_false():
    result = koop_plan_fn({"date": "2026-08-04"})
    plan = result["upcoming_plan"]
    assert len(plan) == 7
    assert all(w["duration_estimated"] is False for w in plan)
    assert plan[0]["date"] == "2026-08-04"
    assert plan[0]["type"] == "easy"   # montenegro tue (flat run)


def test_koop_plan_fn_lookahead_crosses_rehab_to_montenegro_boundary():
    # 2026-07-30 + 6 days = 2026-08-05, crossing rehab -> montenegro (08-03 -> 08-04)
    result = koop_plan_fn({"date": "2026-07-30"})
    types_by_date = {w["date"]: w["type"] for w in result["upcoming_plan"]}
    assert types_by_date["2026-08-03"] == "rest"   # rehab's mon entry
    assert types_by_date["2026-08-04"] == "easy"   # montenegro's tue entry


def test_koop_plan_fn_lookahead_resolves_taper_days_and_race():
    # explicit dated entries (taper_days) and race_day must resolve in the lookahead
    result = koop_plan_fn({"date": "2026-09-08"})
    types_by_date = {w["date"]: w["type"] for w in result["upcoming_plan"]}
    assert types_by_date["2026-09-10"] == "rest"   # explicit dated rest override
    assert types_by_date["2026-09-12"] == "race"   # race day
