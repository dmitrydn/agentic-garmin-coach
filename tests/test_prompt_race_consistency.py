"""
test_prompt_race_consistency.py — Layer I: static prompt / source-of-truth drift guard.

Regression test for the 20.08.2026 incident: the rehab pivot (DNS Gauja 90k ->
Stirnu Buks Lūsis, commit e2f2cfa) updated plans/gauja_90k_2026.md and
context_agent.py, but left the static A-race prose hardcoded in
coach_agent/form_agent/plan_agent/memory_agent pointing at a race date three
weeks in the past. Nothing tied those prompt strings back to the single
source of truth, so they silently rotted — the contradiction between the
stale prompt and the correct dynamically-injected season_plan context is the
likely cause of coach_agent's Opus call returning unparseable JSON that day.

These tests read the current a_race out of plans/gauja_90k_2026.md and assert
each agent's system prompt references it, so the next time a_race changes and
a prompt isn't updated to match, this fails loudly here instead of confusing
the LLM in production.
"""

from datetime import date

from context_agent import load_plan_config

from coach_agent import COACH_SYSTEM
from form_agent import FORM_SYSTEM
from plan_agent import PLAN_SYSTEM
from memory_agent import _default_memory_template

_PROMPTS = {
    "coach_agent.COACH_SYSTEM":                  lambda: COACH_SYSTEM,
    "form_agent.FORM_SYSTEM":                    lambda: FORM_SYSTEM,
    "plan_agent.PLAN_SYSTEM":                    lambda: PLAN_SYSTEM,
    "memory_agent._default_memory_template()":   _default_memory_template,
}


def _current_a_race() -> dict:
    a_race = load_plan_config().get("a_race")
    assert a_race, "plans/gauja_90k_2026.md: a_race block missing or unparsable"
    return a_race


def test_a_race_date_matches_prompts():
    a_race = _current_a_race()
    race_day_month = date.fromisoformat(str(a_race["date"])).strftime("%d.%m")

    for name, get_text in _PROMPTS.items():
        text = get_text()
        assert race_day_month in text, (
            f"{name} does not mention current A-race date {race_day_month} "
            f"(plans/gauja_90k_2026.md a_race.date={a_race['date']}) — "
            "prompt likely still references a stale race, see incident 20.08.2026"
        )


def test_a_race_name_matches_prompts():
    a_race = _current_a_race()
    name = a_race["name"]

    for prompt_name, get_text in _PROMPTS.items():
        text = get_text()
        assert name in text, (
            f"{prompt_name} does not mention current A-race name '{name}' "
            f"(plans/gauja_90k_2026.md) — prompt likely still references a stale race"
        )
