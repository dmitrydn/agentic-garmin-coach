"""
garmin_agent.py — Garmin Connect, два режима, чистый Python.

Использует python-garminconnect (garth не используется напрямую).
Токены хранятся в .garmin_session/ — после первого запуска garmin_auth.py
повторный логин и MFA не нужны.

garmin_plan_fn  → план Coach (fbtAdaptiveWorkout) на 7 дней, TTL 12ч
garmin_rt_fn    → Body Battery, Readiness, Status, TTL 24ч

Graceful degradation: если Garmin недоступен — пустой dict/список,
пайплайн продолжается без Garmin-данных.
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import garminconnect
from dotenv import load_dotenv

load_dotenv()

_SESSION_DIR = Path(__file__).parent.parent / ".garmin_session"


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_api() -> garminconnect.Garmin:
    """Загружает сохранённые токены. Credentials используются только как fallback."""
    api = garminconnect.Garmin(
        os.getenv("GARMIN_EMAIL", ""),
        os.getenv("GARMIN_PASSWORD", ""),
    )
    api.login(tokenstore=str(_SESSION_DIR))
    return api


# ── Cache helpers ─────────────────────────────────────────────────────────────

def get_garmin_cache(today: str) -> dict | None:
    con = sqlite3.connect("coach.db")
    row = con.execute(
        "SELECT body_battery_morning, training_readiness, training_status, "
        "upcoming_plan_json, fetched_at FROM garmin_cache WHERE date=?",
        (today,)
    ).fetchone()
    con.close()
    if not row or not row[4]:
        return None
    age_hours = (datetime.now() - datetime.fromisoformat(row[4])).total_seconds() / 3600
    return {
        "body_battery":        row[0],
        "training_readiness":  row[1],
        "training_status":     row[2],
        "upcoming_plan_json":  row[3],
        "age_hours":           age_hours,
    }


def _save_garmin_plan(date_str: str, plan: list) -> None:
    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO garmin_cache (date, upcoming_plan_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            upcoming_plan_json=excluded.upcoming_plan_json,
            fetched_at=excluded.fetched_at
    """, (date_str, json.dumps(plan, ensure_ascii=False), datetime.now().isoformat()))
    con.commit()
    con.close()


def _save_garmin_rt(date_str: str, data: dict) -> None:
    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO garmin_cache
            (date, body_battery_morning, training_readiness, training_status, fetched_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            body_battery_morning=excluded.body_battery_morning,
            training_readiness=excluded.training_readiness,
            training_status=excluded.training_status,
            fetched_at=excluded.fetched_at
    """, (
        date_str,
        data.get("body_battery"),
        data.get("training_readiness"),
        data.get("training_status"),
        datetime.now().isoformat(),
    ))
    con.commit()
    con.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_morning_battery(bb_list: list, target_date: str) -> int | None:
    """
    Пик Body Battery за день = максимум из bodyBatteryValuesArray.
    Пик всегда утром после сна, потом Battery снижается.
    """
    for entry in bb_list:
        if entry.get("date") != target_date:
            continue
        values = entry.get("bodyBatteryValuesArray") or []
        if values:
            levels = [v[1] for v in values if len(v) >= 2 and v[1] > 0]
            return max(levels) if levels else None
        return entry.get("charged")  # fallback: суммарный заряд за ночь
    return None


# ── LangGraph nodes ───────────────────────────────────────────────────────────

def garmin_plan_fn(state: dict) -> dict:
    """
    TTL 12ч. Garmin Coach план (fbtAdaptiveWorkout) на 7 дней вперёд.
    Если Garmin недоступен → upcoming_plan=[], Coach Agent использует
    стандартную недельную структуру (Пн=силовая, Ср=качество, Сб=длинный...).
    """
    today_str = state["date"]

    cached = get_garmin_cache(today_str)
    if cached and cached["age_hours"] < 12 and cached.get("upcoming_plan_json"):
        plan = json.loads(cached["upcoming_plan_json"])
        print(f"[garmin_plan] кеш ({cached['age_hours']:.1f}ч), {len(plan)} тренировок")
        return {"upcoming_plan": plan}

    try:
        api      = _get_api()
        today    = date.fromisoformat(today_str)
        end_date = today + timedelta(days=6)

        # 7-дневное окно может пересекать границу месяца
        months = {(today.year, today.month)}
        if (end_date.year, end_date.month) != (today.year, today.month):
            months.add((end_date.year, end_date.month))

        all_items: list = []
        for yr, mo in months:
            r = api.get_scheduled_workouts(yr, mo)
            all_items.extend(r.get("calendarItems", []))

        plan = [
            {
                "date":         w["date"],
                "type":         w.get("sportTypeKey") or "running",
                "description":  w.get("title"),
                "duration_min": 0,  # недоступно в calendar API; уточняется через workout details
            }
            for w in all_items
            if w.get("itemType") == "fbtAdaptiveWorkout"
            and w.get("date")
            and today_str <= w["date"] <= end_date.isoformat()
        ]

        _save_garmin_plan(today_str, plan)
        print(f"[garmin_plan] загружен из Garmin, {len(plan)} тренировок")
        return {"upcoming_plan": plan}

    except Exception as e:
        print(f"[garmin_plan] недоступен: {e} — продолжаем без плана")
        return {"upcoming_plan": []}


def garmin_rt_fn(state: dict) -> dict:
    """
    TTL 24ч. Вызывается только при readiness_score <= 5.0 (route_garmin_rt).
    Body Battery + Training Readiness (score 0-100) + Training Status.
    """
    today_str = state["date"]

    cached = get_garmin_cache(today_str)
    if cached and cached["age_hours"] < 24 and cached.get("body_battery") is not None:
        print(f"[garmin_rt] кеш ({cached['age_hours']:.1f}ч)")
        return {"garmin_rt": {
            "body_battery":        cached["body_battery"],
            "training_readiness":  cached["training_readiness"],
            "training_status":     cached["training_status"],
        }}

    try:
        api = _get_api()

        # Body Battery: пик за день = значение после сна
        bb_list    = api.get_body_battery(today_str)
        bb_morning = _extract_morning_battery(bb_list, today_str)

        # Training Readiness: score 0-100, level HIGH/MEDIUM/LOW
        tr_list  = api.get_training_readiness(today_str)
        tr_today = next(
            (r for r in tr_list if r.get("calendarDate") == today_str), {}
        ) if isinstance(tr_list, list) else {}
        readiness = tr_today.get("score")

        # Training Status: PEAKING_1, MAINTAINING_1, PRODUCTIVE_1 и т.д.
        ts_data     = api.get_training_status(today_str)
        device_data = next(
            iter(
                ts_data.get("mostRecentTrainingStatus", {})
                       .get("latestTrainingStatusData", {}).values()
            ),
            {},
        )
        status = device_data.get("trainingStatusFeedbackPhrase")

        result = {
            "body_battery":       bb_morning,
            "training_readiness": readiness,
            "training_status":    status,
        }
        _save_garmin_rt(today_str, result)
        print(f"[garmin_rt] BB={bb_morning}, Readiness={readiness}, Status={status}")
        return {"garmin_rt": result}

    except Exception as e:
        print(f"[garmin_rt] недоступен: {e}")
        return {"garmin_rt": {}}


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    today = date.today().isoformat()
    state = {"date": today}

    print("=== garmin_plan_fn ===")
    result = garmin_plan_fn(state)
    for w in result.get("upcoming_plan", []):
        print(f"  {w}")

    print("\n=== garmin_rt_fn ===")
    result2 = garmin_rt_fn({**state, "readiness_score": 4.0})
    print(f"  {result2.get('garmin_rt')}")
