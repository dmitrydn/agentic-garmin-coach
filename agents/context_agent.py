"""
context_agent.py — чистый Python, ноль токенов.

Читает: events.log, feedback.log, analyses/вчера.json, ATHLETE_MEMORY.md.
Вычисляет context_flags из метрик, разрешает аномалии через events.log.

Соглашение events.log:
  YYYY-MM-DD [тег] описание
  Пример: 2026-05-10 [sleep] ночной переезд, sleep_score=20 — не аномалия

Соглашение feedback.log:
  YYYY-MM-DD rpe=N notes=текст
"""

import json
import os
from datetime import date, timedelta

# Теги, которые объясняют нагрузку/усталость → флаги помечаются known_event
_LOAD_TAGS    = {"hard-run", "camp-start", "camp-end", "no-sleep", "travel", "heat", "rest-day", "strength"}
_RACE_TAGS    = {"race-a", "race-b", "race-c"}
# Теги болезни → добавляют флаг illness, НЕ нейтрализуют метрические флаги
_ILLNESS_TAGS = {"illness"}


# ── LangGraph node ────────────────────────────────────────────────────────────

def context_agent_fn(state: dict) -> dict:
    """Читает файлы, строит флаги. Ноль токенов."""
    today = state["date"]

    events             = _read_log("events.log",  days=14)
    feedback           = _read_log("feedback.log", days=7)
    yesterday_analysis = _read_analysis(today, offset=-1)
    athlete_memory     = _read_file("ATHLETE_MEMORY.md")

    flags        = _compute_flags(state)
    today_events = _parse_today_events(today, events)
    today_tags   = {tag for tag, _ in today_events}

    # Illness: добавляем флаг, метрические флаги остаются как есть
    # Load/race events: метрические флаги помечаются known_event (объяснены)
    is_load_explained = bool(today_tags & (_LOAD_TAGS | _RACE_TAGS)) \
                        and not (today_tags & _ILLNESS_TAGS)

    resolved_flags = [
        f"known_event|{f}" if is_load_explained else f
        for f in flags
    ]

    for tag, desc in today_events:
        if tag in _ILLNESS_TAGS:
            resolved_flags.append(f"illness:{desc}" if desc else "illness")

    print(f"[context_agent] flags: {resolved_flags}")
    return {
        "context_flags":      resolved_flags,
        "athlete_memory":     athlete_memory,
        "events_context":     events,
        "feedback_context":   feedback,
        "yesterday_analysis": yesterday_analysis,
    }


# ── Flag computation ──────────────────────────────────────────────────────────

def _compute_flags(state: dict) -> list[str]:
    """
    Все пороги — на основе метрик из metrics_fn.
    Не использует абсолютные значения (ATL > 80 и т.п.) — только тренды.
    """
    flags = []

    acwr = state.get("acwr", 1.0) or 1.0
    zone = state.get("acwr_zone", "optimal") or "optimal"
    if zone == "high_risk":
        flags.append(f"acwr_high_risk:{acwr}")
    elif zone == "caution":
        flags.append(f"acwr_caution:{acwr}")

    hrv_dev = state.get("hrv_deviation_pct", 0.0) or 0.0
    hrv_cv  = state.get("hrv_cv_week", 0.0) or 0.0
    if hrv_dev < -10:
        flags.append(f"hrv_critical_low:{hrv_dev}%")
    elif hrv_dev < -5:
        flags.append(f"hrv_below_baseline:{hrv_dev}%")
    if hrv_cv > 0.10:
        flags.append("hrv_unstable_week")

    if state.get("rhr_rising"):
        flags.append(f"rhr_rising_trend:+{state.get('rhr_trend')}bpm")

    dsq = state.get("days_since_quality", 99)
    if dsq < 2:
        flags.append(f"quality_too_recent:{dsq}d")

    if state.get("z1z2_compliant") is False:
        flags.append(f"8020_violation:{state.get('z1z2_ratio_week')}")

    if state.get("mesocycle_week") == 4:
        flags.append("mesocycle_recovery_week")

    return flags


# ── File helpers ──────────────────────────────────────────────────────────────

def _read_log(path: str, days: int) -> str:
    """Возвращает строки лога за последние N дней. Макс 30 строк."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        lines = open(path, encoding="utf-8").readlines()
        relevant = [
            l for l in lines
            if not l.startswith("#") and l.strip() and l.strip()[:10] >= cutoff
        ]
        return "".join(relevant[-30:])
    except FileNotFoundError:
        return ""


def _read_analysis(today: str, offset: int = -1) -> str:
    """Читает analyses/YYYY-MM-DD.json со смещением offset дней."""
    target = (date.fromisoformat(today) + timedelta(days=offset)).isoformat()
    path   = f"analyses/{target}.json"
    try:
        return json.dumps(json.load(open(path, encoding="utf-8")), ensure_ascii=False)
    except FileNotFoundError:
        return ""


def _read_file(path: str) -> str:
    try:
        return open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return ""


def _parse_today_events(today: str, events_text: str) -> list[tuple[str, str]]:
    """Возвращает [(тег, описание)] из строк events.log за сегодня."""
    result = []
    for line in events_text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) >= 2 and parts[0] == today:
            result.append((parts[1], parts[2] if len(parts) > 2 else ""))
    return result


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date

    mock_state = {
        "date":               date.today().isoformat(),
        "acwr":               1.4,
        "acwr_zone":          "caution",
        "hrv_deviation_pct":  -7.0,
        "hrv_cv_week":        0.09,
        "rhr_rising":         False,
        "rhr_trend":          1.5,
        "days_since_quality": 1,
        "z1z2_compliant":     True,
        "z1z2_ratio_week":    0.82,
        "mesocycle_week":     2,
    }

    result = context_agent_fn(mock_state)
    print("\nFlags:", result["context_flags"])
    print("Memory (первые 200 символов):", result["athlete_memory"][:200])
    print("Yesterday analysis:", result["yesterday_analysis"][:200] or "нет данных")
