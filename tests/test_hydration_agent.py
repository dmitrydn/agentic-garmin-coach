"""
test_hydration_agent.py — Layer I: hydration schedule rule logic.

_build_schedule is pure Python — no DB, no LLM, no Garmin.
Tests cover all branching: rest, short run, >60 min, >=90 min.
"""

import pytest
from hydration_agent import _build_schedule


def test_rest_type_returns_minimal_no_pre_run_item():
    schedule = _build_schedule("rest", 0)
    texts = " ".join(schedule)
    assert "за 30 мин до бега" not in texts
    assert "на" not in texts or "мин бега" not in texts
    assert len(schedule) == 2  # morning + day total


def test_short_run_no_mid_run_drinks():
    # 45 min: below the 60-min threshold for mid-run reminders
    schedule = _build_schedule("easy", 45)
    mid_run_items = [s for s in schedule if "мин бега" in s]
    assert mid_run_items == []


def test_long_run_has_mid_run_drink_at_15_min():
    # 75 min: first drink at 15 min
    schedule = _build_schedule("long", 75)
    texts = " ".join(schedule)
    assert "на 15-й мин бега" in texts


def test_long_run_drink_intervals_every_20_min():
    # 90 min: drinks at 15, 35, 55, 75 (75 < 90-5=85 → included)
    schedule = _build_schedule("long", 90)
    mid_items = [s for s in schedule if "мин бега" in s]
    assert len(mid_items) == 4
    assert any("15" in s for s in mid_items)
    assert any("35" in s for s in mid_items)
    assert any("55" in s for s in mid_items)
    assert any("75" in s for s in mid_items)


def test_very_long_run_includes_electrolyte_reminder():
    # >= 90 min → extra electrolyte reminder for sodium/potassium replenishment
    schedule = _build_schedule("long", 120)
    texts = " ".join(schedule)
    assert "электролитов" in texts


def test_short_run_no_electrolyte_reminder():
    # < 90 min → no extra electrolyte reminder (base post-run item is fine)
    schedule = _build_schedule("easy", 50)
    electrolyte_items = [s for s in schedule if "электролитов" in s]
    assert electrolyte_items == []
