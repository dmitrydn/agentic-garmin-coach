"""
test_routing.py — Layer I: LangGraph conditional edge routing.

route_garmin_rt decides whether to fetch real-time Garmin data.
Rule: score <= 5.0 → "garmin_rt", score > 5.0 → "plan".
The boundary (5.0) must go to garmin_rt (≤ is inclusive).
"""

import pytest
from pipeline import route_garmin_rt


@pytest.mark.parametrize("score,expected_route", [
    (1.0,  "garmin_rt"),   # clearly low
    (5.0,  "garmin_rt"),   # exact boundary — must be garmin_rt
    (5.1,  "plan"),        # just above — skip RT fetch
    (6.5,  "plan"),        # normal readiness
    (9.0,  "plan"),        # high readiness
])
def test_route_garmin_rt_boundary(score, expected_route):
    state = {"readiness_score": score}
    assert route_garmin_rt(state) == expected_route


def test_route_defaults_to_plan_when_score_missing():
    # Missing score → default 6.0 in route_garmin_rt → "plan"
    assert route_garmin_rt({}) == "plan"
