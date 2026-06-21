"""
koop_plan_agent.py — персональный периодизированный план (Jason Koop / CTS),
заменяет Garmin Coach (garmin_plan_fn) как основу ежедневной рекомендации.

Читает день-в-день календарь из plans/gauja_90k_2026.md (weekly_templates по
блокам + явные taper_days/race_day) и отдаёт upcoming_plan в ТОМ ЖЕ формате,
что раньше отдавал garmin_plan_fn — coach_agent/plan_agent/synthesis_agent
не меняются структурно, меняется только источник данных.

Чистый Python, ноль LLM-токенов, без сети, без кеша/TTL — файл маленький,
читается заново на каждый запуск пайплайна.

Garmin (garmin_rt_fn, garmin_performance_fn) продолжает поставлять
readiness-сигналы (Body Battery, Training Readiness, VO2max, LT, сон) —
только адаптивный план тренировок (garmin_plan_fn/upcoming_plan) заменён.
"""

from datetime import date, timedelta

from context_agent import block_for_date, load_plan_config, to_date_str

_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _entry_for_date(config: dict, d: date) -> dict | None:
    """Возвращает прескрипцию дня d из koop-календаря или None вне горизонта плана."""
    date_str = d.isoformat()

    race_day = config.get("race_day") or {}
    if date_str in race_day:
        return race_day[date_str]

    taper_days = config.get("taper_days") or {}
    if date_str in taper_days:
        return taper_days[date_str]

    block = block_for_date(config, d)
    if not block:
        return None

    template = (config.get("weekly_templates") or {}).get(block)
    if not template:
        return None

    return template.get(_WEEKDAY_KEYS[d.weekday()])


def koop_plan_fn(state: dict) -> dict:
    """
    LangGraph node. upcoming_plan = сегодня + 6 дней вперёд.
    duration_estimated всегда False — план полностью авторский, не оценка.
    """
    today_str = state.get("date") or date.today().isoformat()
    today     = date.fromisoformat(today_str)
    config    = load_plan_config()

    plan = []
    for i in range(7):
        d     = today + timedelta(days=i)
        entry = _entry_for_date(config, d)
        if not entry:
            continue
        plan.append({
            "date":               d.isoformat(),
            "type":               entry.get("type"),
            "description":        entry.get("description"),
            "duration_min":       entry.get("duration_min"),
            "duration_estimated": False,
            "zones":              entry.get("zones", []),
            "terrain":            entry.get("terrain"),
        })

    today_type = plan[0]["type"] if plan else "нет данных"
    print(f"[koop_plan] {today_str}: {len(plan)} дней вперёд, сегодня={today_type}")
    return {"upcoming_plan": plan}


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = koop_plan_fn({"date": date.today().isoformat()})
    for w in result["upcoming_plan"]:
        desc = (w["description"] or "")[:70]
        print(f"  {w['date']} {w['type']:9s} {str(w['duration_min']):>4s}мин  {desc}")
