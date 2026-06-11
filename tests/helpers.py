"""
helpers.py — shared test utilities (not pytest fixtures).

Imported directly by test files: `from helpers import load_fixture, make_llm_msg, ...`
Fixtures in conftest.py delegate to these functions.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def make_llm_msg(text: str) -> MagicMock:
    """Fake anthropic.messages.create return value."""
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


def make_mock_garmin_api(
    calendar: dict | None = None,
    atp: dict | None = None,
    vo2max_data: list | None = None,
    lt_data: dict | None = None,
) -> MagicMock:
    api = MagicMock()

    _calendar = calendar or {"calendarItems": []}
    api.get_scheduled_workouts.return_value = _calendar

    if atp is not None:
        api.get_adaptive_training_plan_by_id.return_value = atp
    else:
        api.get_adaptive_training_plan_by_id.side_effect = Exception("ATP not available")

    _vo2max = vo2max_data if vo2max_data is not None else [
        {"generic": {"vo2MaxPreciseValue": 52.3}}
    ]
    api.get_max_metrics.return_value = _vo2max

    _lt = lt_data or {"speed_and_heart_rate": {"heartRate": 154, "speed": 0.00347}}
    api.get_lactate_threshold.return_value = _lt

    api.get_sleep_data.return_value = {
        "dailySleepDTO": {
            "deepSleepSeconds": 4800, "remSleepSeconds": 5400,
            "lightSleepSeconds": 9000, "awakeSleepSeconds": 600,
        }
    }
    api.get_hrv_data.return_value = {"hrvSummary": {"lastNightAvg": 61}}
    api.get_stats.return_value = {"restingHeartRate": 47}
    api.get_body_battery.return_value = [
        {"date": "2026-06-10", "bodyBatteryValuesArray": [[0, 85], [3600, 72]]}
    ]
    api.get_training_readiness.return_value = [
        {"calendarDate": "2026-06-10", "score": 68}
    ]
    api.get_training_status.return_value = {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "device1": {"trainingStatusFeedbackPhrase": "PRODUCTIVE_1"}
            }
        }
    }
    return api
