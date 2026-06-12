"""
test_contracts.py — Layer I: LLM agent output schema validation.

LLM calls are mocked. Tests assert:
  - Required keys present in output
  - Value types correct
  - Fallback behavior on invalid JSON
  - Business shortcuts (readiness=rest → no LLM call)
"""

import json
from unittest.mock import patch

import pytest

from helpers import load_fixture, make_llm_msg
from coach_agent import coach_agent_fn
from memory_agent import memory_agent_fn
from plan_agent import plan_agent_fn
from synthesis_agent import synthesis_fn


TODAY = "2026-06-10"

_BASE_COACH_STATE = {
    "date": TODAY,
    "mesocycle_week": 2,
    "hrv_today": 60.0,
    "hrv_rolling_avg": 62.0,
    "hrv_deviation_pct": -3.2,
    "hrv_cv_week": 0.05,
    "hrv_garmin_today": None,
    "rhr_garmin_today": None,
    "acwr": 1.05,
    "acwr_zone": "optimal",
    "rhr_today": 47,
    "rhr_trend": 0.5,
    "rhr_rising": False,
    "days_since_quality": 2,
    "z1z2_ratio_week": 0.81,
    "z1z2_compliant": True,
    "strength_load_today": 0.0,
    "context_flags": [],
    "upcoming_plan": [{"date": TODAY, "type": "running",
                       "description": "Base Run", "duration_min": 44,
                       "duration_estimated": False}],
    "athlete_memory": "HRV baseline: 62. ACWR нормативный диапазон: 0.85-1.15.",
    "yesterday_analysis": "",
    "vo2max": 52.3,
    "vo2max_trend": "stable",
    "lt_hr": 154,
    "sleep_score": 75,
    "sleep_deep_min": 80,
    "sleep_rem_min": 90,
    "sleep_light_min": 150,
    "sleep_awake_min": 10,
    "garmin_rt": {},
    "season_plan": {"b_race_date": "2026-07-18", "a_race_date": "2026-08-01",
                    "b_race_distance_km": 50, "a_race_distance_km": 90,
                    "a_race_elevation_m": 2500, "b_race_strategy": "race_effort",
                    "current_block_label": "Foundation"},
    "current_block": "foundation",
    "days_to_b_race": 38,
    "days_to_a_race": 52,
    "events_context": "",
}


# ── coach_agent_fn ────────────────────────────────────────────────────────────

def test_coach_output_has_required_keys():
    resp = load_fixture("coach_llm_ok.json")
    with patch("coach_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = coach_agent_fn(_BASE_COACH_STATE)

    assert set(result.keys()) >= {"readiness", "readiness_score", "readiness_reasoning"}


def test_coach_readiness_is_valid_value():
    resp = load_fixture("coach_llm_ok.json")
    with patch("coach_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = coach_agent_fn(_BASE_COACH_STATE)

    assert result["readiness"] in {"high", "normal", "low", "rest"}


def test_coach_score_is_float_in_range():
    resp = load_fixture("coach_llm_ok.json")
    with patch("coach_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = coach_agent_fn(_BASE_COACH_STATE)

    score = result["readiness_score"]
    assert isinstance(score, float)
    assert 1.0 <= score <= 10.0


def test_coach_uses_opus_4_8_model():
    resp = load_fixture("coach_llm_ok.json")
    with patch("coach_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        coach_agent_fn(_BASE_COACH_STATE)

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-opus-4-8"


def test_coach_fallback_on_invalid_json():
    with patch("coach_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg("This is not JSON at all")
        result = coach_agent_fn(_BASE_COACH_STATE)

    # Fallback must provide safe defaults
    assert result["readiness"] == "normal"
    assert result["readiness_score"] == 5.0
    assert "readiness_reasoning" in result


# ── plan_agent_fn ─────────────────────────────────────────────────────────────

_BASE_PLAN_STATE = {
    **_BASE_COACH_STATE,
    "readiness": "normal",
    "readiness_score": 6.5,
    "readiness_reasoning": "HRV в норме, ACWR оптимальный.",
}


def test_plan_output_has_required_keys():
    resp = load_fixture("plan_llm_ok.json")
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = plan_agent_fn(_BASE_PLAN_STATE)

    rec = result["recommendation"]
    required = {"type", "title", "duration_min", "zones", "description", "cautions", "garmin_plan_used"}
    assert required.issubset(rec.keys())


def test_plan_type_is_valid_value():
    resp = load_fixture("plan_llm_ok.json")
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = plan_agent_fn(_BASE_PLAN_STATE)

    valid_types = {"easy", "quality", "long", "back-to-back", "strength", "rest"}
    assert result["recommendation"]["type"] in valid_types


def test_plan_rest_shortcircuits_without_llm():
    with patch("plan_agent.client") as mock_client:
        result = plan_agent_fn({**_BASE_PLAN_STATE, "readiness": "rest"})

    mock_client.messages.create.assert_not_called()
    rec = result["recommendation"]
    assert rec["type"] == "rest"
    assert rec["duration_min"] == 0


def test_plan_duration_estimated_propagated_from_garmin():
    # When Garmin plan has duration_estimated=True, plan_agent must echo it
    resp = {**load_fixture("plan_llm_ok.json"), "duration_estimated": True}
    state = {
        **_BASE_PLAN_STATE,
        "upcoming_plan": [{"date": TODAY, "type": "running", "description": "Base Run",
                           "duration_min": 45, "duration_estimated": True}],
    }
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = plan_agent_fn(state)

    # The LLM echoed duration_estimated=True from the system prompt instruction
    assert result["recommendation"]["duration_estimated"] is True


def test_plan_fallback_on_invalid_json():
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg("{ broken json }")
        result = plan_agent_fn(_BASE_PLAN_STATE)

    rec = result["recommendation"]
    assert "type" in rec
    assert "duration_min" in rec


# ── synthesis_fn ──────────────────────────────────────────────────────────────

_BASE_SYNTHESIS_STATE = {
    **_BASE_PLAN_STATE,
    "recommendation": {
        "type": "easy", "title": "Лёгкий бег", "duration_min": 44,
        "duration_estimated": False, "zones": ["Z1", "Z2"],
        "description": "44 мин Z1-Z2.", "cautions": [], "garmin_plan_used": True,
    },
    "hydration_schedule": ["07:00 — 250мл", "за 30 мин — 350мл"],
    "form_today": -5.0,
}


def test_synthesis_duration_estimated_false_no_warning_note(tmp_db):
    captured = {}
    def capture_create(**kwargs):
        captured["user"] = kwargs["messages"][0]["content"]
        return make_llm_msg("Всё хорошо. Бегом!")
    with patch("synthesis_agent.client") as mock_client:
        mock_client.messages.create.side_effect = lambda **kw: capture_create(**kw)
        synthesis_fn(_BASE_SYNTHESIS_STATE)

    assert "duration_note" not in captured.get("user", "")


def test_synthesis_duration_estimated_true_injects_warning(tmp_db):
    state = {
        **_BASE_SYNTHESIS_STATE,
        "recommendation": {
            **_BASE_SYNTHESIS_STATE["recommendation"],
            "duration_estimated": True,
            "duration_min": 45,
        },
    }
    captured = {}
    def capture_create(**kwargs):
        captured["user"] = kwargs["messages"][0]["content"]
        return make_llm_msg("Предупреждение.")
    with patch("synthesis_agent.client") as mock_client:
        mock_client.messages.create.side_effect = lambda **kw: capture_create(**kw)
        synthesis_fn(state)

    assert "duration_note" in captured.get("user", "")
    assert "⚠️" in captured["user"]


# ── memory_agent_fn ───────────────────────────────────────────────────────────

def test_memory_agent_calls_sonnet_4_6_model(tmp_db):
    """memory_agent must use claude-sonnet-4-6, not the Opus model."""
    with patch("memory_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(
            "## Профиль атлета\nUpdated content."
        )
        memory_agent_fn({})

    model_used = mock_client.messages.create.call_args.kwargs["model"]
    assert model_used == "claude-sonnet-4-6"


def test_memory_agent_writes_athlete_memory_file(tmp_db):
    """memory_agent must write ATHLETE_MEMORY.md to the working directory."""
    new_content = "## Профиль атлета\nWeekly update complete."
    with patch("memory_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(new_content)
        memory_agent_fn({})

    memory_path = tmp_db.parent / "ATHLETE_MEMORY.md"
    assert memory_path.exists(), "ATHLETE_MEMORY.md was not created"
    written = memory_path.read_text(encoding="utf-8")
    assert "Профиль атлета" in written


def test_memory_agent_returns_updated_flag(tmp_db):
    """memory_agent must return {'athlete_memory_updated': True}."""
    with patch("memory_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg("## Updated memory")
        result = memory_agent_fn({})

    assert result == {"athlete_memory_updated": True}


# ── plan_agent output range validation ────────────────────────────────────────

def test_plan_duration_min_positive_for_non_rest():
    """Any non-rest recommendation must have duration_min > 0."""
    resp = load_fixture("plan_llm_ok.json")
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = plan_agent_fn(_BASE_PLAN_STATE)

    rec = result["recommendation"]
    assert rec["type"] != "rest"
    assert rec["duration_min"] > 0, (
        f"Non-rest recommendation has duration_min={rec['duration_min']}"
    )


def test_plan_zones_non_empty_for_non_rest():
    """Non-rest recommendation must include at least one zone."""
    resp = load_fixture("plan_llm_ok.json")
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = plan_agent_fn(_BASE_PLAN_STATE)

    rec = result["recommendation"]
    assert rec["type"] != "rest"
    assert isinstance(rec["zones"], list) and len(rec["zones"]) > 0, (
        f"Expected non-empty zones list, got: {rec['zones']}"
    )


def test_plan_zones_are_valid_garmin_zones():
    """Every zone in the recommendation must be one of Z1-Z5."""
    resp = load_fixture("plan_llm_ok.json")
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = plan_agent_fn(_BASE_PLAN_STATE)

    valid = {"Z1", "Z2", "Z3", "Z4", "Z5"}
    for z in result["recommendation"]["zones"]:
        assert z in valid, f"Invalid zone '{z}' in recommendation"


# ── plan_agent illness return_protocol ────────────────────────────────────────

def test_plan_illness_return_protocol_has_required_keys():
    """
    When illness flag is in context_flags, the LLM must return a return_protocol
    with all six required keys. This test verifies plan_agent propagates the
    return_protocol dict from the LLM response unchanged.
    """
    resp = load_fixture("plan_llm_illness.json")
    illness_state = {
        **_BASE_PLAN_STATE,
        "context_flags": ["illness"],
    }
    with patch("plan_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(json.dumps(resp))
        result = plan_agent_fn(illness_state)

    protocol = result["recommendation"].get("return_protocol")
    assert protocol is not None, "return_protocol must not be null when illness flag is set"

    required_keys = {
        "rhr_target", "temp_free_hours", "symptom_restriction",
        "subjective_min", "sleep_nights", "race_clearance",
    }
    assert required_keys.issubset(protocol.keys()), (
        f"Missing keys in return_protocol: {required_keys - protocol.keys()}"
    )


# ── synthesis_fn output length guard ─────────────────────────────────────────

def test_synthesis_final_message_is_non_empty(tmp_db):
    """synthesis_fn must return a non-empty final_message string."""
    expected = "✅ Готов. Бег 44 мин Z1-Z2, пульс 120-135."
    with patch("synthesis_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(expected)
        result = synthesis_fn(_BASE_SYNTHESIS_STATE)

    assert isinstance(result["final_message"], str)
    assert len(result["final_message"]) > 0


def test_synthesis_final_message_within_telegram_limit(tmp_db):
    """
    Telegram silently truncates messages > 4096 chars. Synthesis prompt
    asks for 250-400 words; guard ensures the contract is not violated.
    """
    long_msg = "Тренер говорит: " + "х" * 4000  # ~4016 chars, within limit
    with patch("synthesis_agent.client") as mock_client:
        mock_client.messages.create.return_value = make_llm_msg(long_msg)
        result = synthesis_fn(_BASE_SYNTHESIS_STATE)

    assert len(result["final_message"]) <= 4096, (
        f"final_message length {len(result['final_message'])} exceeds Telegram 4096-char limit"
    )


def test_synthesis_prompt_includes_tomorrow_workout(tmp_db):
    """When upcoming_plan has tomorrow's workout, synthesis prompt must include its date and duration."""
    from datetime import date, timedelta
    tomorrow = (date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()
    state = {
        **_BASE_SYNTHESIS_STATE,
        "upcoming_plan": [
            {"date": tomorrow, "type": "long", "description": "Long Run", "duration_min": 153},
        ],
    }
    captured = {}
    def capture_create(**kwargs):
        captured["user"] = kwargs["messages"][0]["content"]
        return make_llm_msg("Хорошо.")
    with patch("synthesis_agent.client") as mock_client:
        mock_client.messages.create.side_effect = lambda **kw: capture_create(**kw)
        synthesis_fn(state)

    assert tomorrow in captured.get("user", ""), "tomorrow date must appear in synthesis prompt"
    assert "153" in captured["user"], "tomorrow workout duration must appear in synthesis prompt"


def test_synthesis_prompt_no_tomorrow_data_when_plan_empty(tmp_db):
    """When upcoming_plan is empty, synthesis prompt must say 'нет данных' for tomorrow."""
    captured = {}
    def capture_create(**kwargs):
        captured["user"] = kwargs["messages"][0]["content"]
        return make_llm_msg("Хорошо.")
    state = {**_BASE_SYNTHESIS_STATE, "upcoming_plan": []}
    with patch("synthesis_agent.client") as mock_client:
        mock_client.messages.create.side_effect = lambda **kw: capture_create(**kw)
        synthesis_fn(state)

    assert "нет данных" in captured.get("user", ""), "prompt must say 'нет данных' when no upcoming workout"
