"""
test_graph.py — graph wiring and compilation smoke tests.

build_graph() is never exercised by other test files. A deleted node,
a miswired edge, or a broken conditional branch would produce a silent
runtime failure that no other test layer catches.

These tests verify:
  1. The graph compiles without error.
  2. The conditional edge routes correctly based on readiness_score.
     (route_garmin_rt is tested in isolation by test_routing.py;
      here we verify the edge is actually wired into the live graph.)
"""

from unittest.mock import patch

import pytest

from pipeline import build_graph


# ── Compilation ───────────────────────────────────────────────────────────────

def test_build_graph_compiles_without_error():
    """build_graph() must assemble all nodes and compile without exception."""
    graph = build_graph()
    assert graph is not None


# ── Conditional edge via live graph invocation ────────────────────────────────

_PASS = lambda s: s


def _invoke_with_mocked_nodes(coach_score: float) -> list[bool]:
    """
    Invoke the full graph with all real nodes replaced by passthroughs.
    Returns a list that records whether node_garmin_rt was visited.
    """
    garmin_rt_visited: list[bool] = []

    def spy_garmin_rt(s):
        garmin_rt_visited.append(True)
        return s

    def mock_coach(s):
        return {**s, "readiness_score": coach_score, "readiness": "normal"}

    def mock_plan(s):
        return {**s, "recommendation": {"type": "easy", "duration_min": 30}}

    def mock_hydration(s):
        return {**s, "hydration_schedule": []}

    def mock_synthesis(s):
        return {**s, "final_message": "OK"}

    with patch("pipeline.node_data", _PASS), \
         patch("pipeline.node_metrics", _PASS), \
         patch("pipeline.node_garmin_plan", _PASS), \
         patch("pipeline.node_garmin_performance", _PASS), \
         patch("pipeline.node_context", _PASS), \
         patch("pipeline.node_coach", mock_coach), \
         patch("pipeline.node_garmin_rt", spy_garmin_rt), \
         patch("pipeline.node_plan", mock_plan), \
         patch("pipeline.node_hydration", mock_hydration), \
         patch("pipeline.node_synthesis", mock_synthesis), \
         patch("pipeline.node_telegram", _PASS):
        graph = build_graph()
        graph.invoke({"date": "2026-06-10"})

    return garmin_rt_visited


def test_graph_high_score_bypasses_garmin_rt():
    """readiness_score > 5.0 → garmin_rt node must NOT be visited."""
    visited = _invoke_with_mocked_nodes(coach_score=7.0)
    assert visited == []


def test_graph_boundary_score_routes_through_garmin_rt():
    """readiness_score == 5.0 (inclusive boundary) → garmin_rt MUST be visited."""
    visited = _invoke_with_mocked_nodes(coach_score=5.0)
    assert len(visited) == 1


def test_graph_low_score_routes_through_garmin_rt():
    """readiness_score < 5.0 → garmin_rt MUST be visited before plan."""
    visited = _invoke_with_mocked_nodes(coach_score=3.5)
    assert len(visited) == 1
