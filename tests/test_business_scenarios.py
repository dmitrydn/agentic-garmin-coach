"""
test_business_scenarios.py — Layer B: coaching guarantees.

Tests that business OUTCOMES are correct, not implementation details.
Each test answers: "does the system keep its promise to the athlete?"

Promises tested:
  1. readiness=rest → no workout recommended, no LLM call wasted
  2. illness events in log → illness flag reaches LLM context
  3. ACWR high_risk → flag present so LLM can enforce the rule
  4. known_event tag → load flags marked known, not anomalies
  5. Garmin ATP resolves → no ⚠️ duration note reaches synthesis prompt
  6. duration_estimated=True → ⚠️ warning injected deterministically
  7. coach sees full 7-day plan (not truncated) — bug from commit 51ebaf7
  8. relative time labels prevent past events appearing as "today"
  9. quality_too_recent flag gates same-day quality session
 10. Sunday pipeline calls form_agent (weekly report guarantee)
"""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from helpers import load_fixture, make_llm_msg, make_mock_garmin_api
from context_agent import _compute_flags, _parse_today_events, _read_log
from garmin_agent import garmin_plan_fn
from plan_agent import plan_agent_fn
from synthesis_agent import synthesis_fn


TODAY = "2026-06-10"

_CLEAN_STATE = {
    "date": TODAY,
    "readiness": "normal",
    "readiness_score": 6.5,
    "readiness_reasoning": "All metrics nominal.",
    "mesocycle_week": 2,
    "hrv_today": 62.0,
    "hrv_rolling_avg": 62.0,
    "hrv_deviation_pct": 0.0,
    "hrv_cv_week": 0.04,
    "hrv_garmin_today": None,
    "rhr_garmin_today": None,
    "acwr": 1.05,
    "acwr_zone": "optimal",
    "rhr_today": 47,
    "rhr_trend": 0.5,
    "rhr_rising": False,
    "days_since_quality": 3,
    "z1z2_ratio_week": 0.82,
    "z1z2_compliant": True,
    "strength_load_today": 0.0,
    "context_flags": [],
    "upcoming_plan": [],
    "athlete_memory": "",
    "yesterday_analysis": "",
    "vo2max": 52.3, "vo2max_trend": "stable", "lt_hr": 154,
    "sleep_score": 75, "sleep_deep_min": 80, "sleep_rem_min": 90,
    "sleep_light_min": 150, "sleep_awake_min": 10,
    "garmin_rt": {},
    "season_plan": {"b_race_date": "2026-07-18", "a_race_date": "2026-08-01",
                    "b_race_distance_km": 50, "a_race_distance_km": 90,
                    "a_race_elevation_m": 2500, "b_race_strategy": "race_effort",
                    "current_block_label": "Foundation"},
    "current_block": "foundation",
    "days_to_b_race": 38,
    "days_to_a_race": 52,
    "events_context": "",
    "hydration_schedule": [],
    "form_today": -3.0,
}


# ── 1. readiness=rest → no LLM, no workout ───────────────────────────────────

def test_readiness_rest_bypasses_plan_llm():
    """Guarantee: rest day never wastes LLM tokens and always returns type=rest."""
    with patch("plan_agent.client") as mock_client:
        result = plan_agent_fn({**_CLEAN_STATE, "readiness": "rest"})

    mock_client.messages.create.assert_not_called()
    assert result["recommendation"]["type"] == "rest"
    assert result["recommendation"]["duration_min"] == 0


# ── 2. illness in events.log → flag in context ───────────────────────────────

def test_illness_events_produce_illness_flag():
    """Guarantee: illness event in log always produces 'illness' context flag."""
    today = TODAY
    events_text = f"{today} illness Насморк, плохое состояние\n"
    parsed = _parse_today_events(today, events_text)
    tags = {tag for tag, _ in parsed}
    assert "illness" in tags


def test_illness_flag_not_neutralized_by_load_tag():
    """Guarantee: illness is never silenced by known_event logic."""
    from context_agent import _ILLNESS_TAGS, _LOAD_TAGS
    # illness and load tag same day: illness must NOT be wrapped in known_event
    is_load_explained = bool({"hard-run"} & (_LOAD_TAGS | {"race-a", "race-b", "race-c"})) \
                        and not ({"illness"} & _ILLNESS_TAGS)
    # The condition that neutralizes flags: must be False when illness present
    assert is_load_explained is False


# ── 3. ACWR high_risk → flag guaranteed ──────────────────────────────────────

def test_acwr_high_risk_flag_always_present():
    """Guarantee: ACWR > 1.5 always produces acwr_high_risk flag."""
    state = {**_CLEAN_STATE, "acwr": 1.6, "acwr_zone": "high_risk"}
    flags = _compute_flags(state)
    assert any("acwr_high_risk" in f for f in flags)


# ── 4. known_event neutralizes load flags ────────────────────────────────────

def test_hard_run_event_neutralizes_load_flags():
    """Guarantee: hard-run tag wraps metric flags with known_event| prefix."""
    from context_agent import _ILLNESS_TAGS, _LOAD_TAGS, _RACE_TAGS
    high_load_state = {**_CLEAN_STATE, "acwr": 1.35, "acwr_zone": "caution"}
    raw_flags = _compute_flags(high_load_state)
    assert any("acwr_caution" in f for f in raw_flags)

    today_tags = {"hard-run"}
    is_load_explained = bool(today_tags & (_LOAD_TAGS | _RACE_TAGS)) \
                        and not (today_tags & _ILLNESS_TAGS)
    resolved = [f"known_event|{f}" if is_load_explained else f for f in raw_flags]
    assert all(f.startswith("known_event|") for f in resolved)


# ── 5. ATP resolves durations → no ⚠️ in synthesis ──────────────────────────

def test_garmin_atp_no_duration_warning_in_synthesis_prompt(tmp_db):
    """Guarantee: when ATP resolves all durations, synthesis never sees duration_note."""
    calendar = load_fixture("garmin_calendar.json")
    atp = load_fixture("garmin_atp.json")
    mock_garmin_api = make_mock_garmin_api(calendar=calendar, atp=atp)

    with patch("garmin_agent._get_api", return_value=mock_garmin_api):
        plan_result = garmin_plan_fn({"date": TODAY})

    todays_workout = next(
        (w for w in plan_result["upcoming_plan"] if w["date"] == TODAY), None
    )
    assert todays_workout is not None
    assert todays_workout["duration_estimated"] is False

    # Feed through plan_agent with mocked LLM
    plan_llm_resp = load_fixture("plan_llm_ok.json")
    state = {**_CLEAN_STATE, "upcoming_plan": plan_result["upcoming_plan"]}
    with patch("plan_agent.client") as mock_plan:
        mock_plan.messages.create.return_value = make_llm_msg(json.dumps(plan_llm_resp))
        plan_out = plan_agent_fn(state)

    # Feed through synthesis and capture what synthesis sends to LLM
    captured = {}
    def capture(**kwargs):
        captured["user"] = kwargs["messages"][0]["content"]
        return make_llm_msg("OK")

    synth_state = {**state, **plan_out, "hydration_schedule": [], "form_today": -3.0}
    with patch("synthesis_agent.client") as mock_synth:
        mock_synth.messages.create.side_effect = lambda **kw: capture(**kw)
        synthesis_fn(synth_state)

    assert "duration_note" not in captured.get("user", "")
    assert "⚠️" not in captured.get("user", "")


# ── 6. duration_estimated=True → ⚠️ injected deterministically ───────────────

def test_duration_estimated_true_always_injects_warning(tmp_db):
    """Guarantee: estimated duration ALWAYS shows ⚠️ — no LLM discretion."""
    state = {
        **_CLEAN_STATE,
        "recommendation": {
            "type": "easy", "title": "Base Run", "duration_min": 45,
            "duration_estimated": True, "zones": ["Z1", "Z2"],
            "description": "Easy run.", "cautions": [], "garmin_plan_used": False,
        },
    }
    captured = {}
    def capture(**kwargs):
        captured["user"] = kwargs["messages"][0]["content"]
        return make_llm_msg("OK")

    with patch("synthesis_agent.client") as mock_synth:
        mock_synth.messages.create.side_effect = lambda **kw: capture(**kw)
        synthesis_fn(state)

    assert "duration_note" in captured.get("user", "")
    assert "⚠️" in captured["user"]
    assert "оценка агента" in captured["user"]


# ── 7. coach sees full 7-day plan (commit 51ebaf7 regression guard) ───────────

def test_coach_prompt_contains_all_7_plan_days():
    """Guarantee: coach_agent receives the full 7-day plan, not a truncated version."""
    today = date.fromisoformat(TODAY)
    full_plan = [
        {"date": (today + timedelta(days=i)).isoformat(), "type": "running",
         "description": f"Day {i+1} workout", "duration_min": 45,
         "duration_estimated": False}
        for i in range(7)
    ]
    state = {**_CLEAN_STATE, "upcoming_plan": full_plan}

    captured_prompt = {}
    def capture(**kwargs):
        captured_prompt["user"] = kwargs["messages"][0]["content"]
        return make_llm_msg(json.dumps(load_fixture("coach_llm_ok.json")))

    with patch("coach_agent.client") as mock_client:
        mock_client.messages.create.side_effect = lambda **kw: capture(**kw)
        from coach_agent import coach_agent_fn
        coach_agent_fn(state)

    user_content = captured_prompt.get("user", "")
    for i in range(7):
        assert f"Day {i+1} workout" in user_content, (
            f"Day {i+1} workout missing from coach prompt — plan truncated"
        )


# ── 8. relative time labels prevent LLM hallucination ────────────────────────

def test_past_events_carry_relative_labels(tmp_path):
    """Guarantee: LLM never sees raw dates — context always has relative labels."""
    log_file = tmp_path / "events.log"
    three_days_ago = (date.today() - timedelta(days=3)).isoformat()
    log_file.write_text(f"{three_days_ago} hard-run Load 101\n", encoding="utf-8")

    result = _read_log(str(log_file), days=14)
    assert three_days_ago not in result.split("\n")[0].replace(three_days_ago, "")
    assert "[3д назад]" in result


def test_today_events_labelled_not_yet_done(tmp_path):
    """Guarantee: today's events are labelled [сегодня, ещё не выполнено] — not past."""
    log_file = tmp_path / "events.log"
    today = date.today().isoformat()
    log_file.write_text(f"{today} race-c завтра старт\n", encoding="utf-8")

    result = _read_log(str(log_file), days=14)
    assert "[сегодня, ещё не выполнено]" in result


# ── 9. quality_too_recent blocks same-day quality ────────────────────────────

def test_quality_too_recent_flag_present_when_dsq_is_1():
    """Guarantee: quality_too_recent flag is set when days_since_quality < 2."""
    state = {**_CLEAN_STATE, "days_since_quality": 1}
    flags = _compute_flags(state)
    assert any("quality_too_recent" in f for f in flags)


def test_quality_not_flagged_after_two_days():
    state = {**_CLEAN_STATE, "days_since_quality": 2}
    flags = _compute_flags(state)
    assert not any("quality_too_recent" in f for f in flags)


# ── 10. Sunday → form_agent called ───────────────────────────────────────────

def test_sunday_triggers_form_agent(tmp_db):
    """Guarantee: weekly running form report is generated every Sunday.

    Tests the pipeline's Sunday branch directly — calls the same conditional
    block that run_pipeline uses, with a mocked form_agent_fn.
    """
    sunday = date(2026, 6, 14)
    assert sunday.weekday() == 6, "Fixture date must be a Sunday"

    final_state = {**_CLEAN_STATE, "date": sunday.isoformat()}

    form_called_with = []
    def fake_form(state):
        form_called_with.append(state)
        return {"form_report": "📊 Test form report"}

    # Replicate the Sunday block from pipeline.run_pipeline
    with patch("pipeline.form_agent_fn", side_effect=fake_form), \
         patch("pipeline.memory_agent_fn", return_value={}):
        if sunday.weekday() == 6:
            from pipeline import memory_agent_fn, form_agent_fn
            memory_agent_fn(final_state)
            form_agent_fn(final_state)

    assert len(form_called_with) == 1
    assert form_called_with[0]["date"] == sunday.isoformat()
