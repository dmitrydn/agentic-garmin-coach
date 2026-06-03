"""
context_agent.py — чистый Python, ноль токенов.

Читает: events.log, feedback.log, analyses/вчера.json, ATHLETE_MEMORY.md,
        plans/gauja_90k_2026.md (YAML-блок с расписанием сезона).
Вычисляет context_flags из метрик, разрешает аномалии через events.log.
Автоматически определяет current_block и дни до B/A-race по датам.

Источники фидбека (оба читаются, оба поддерживаются):
  Вариант А — Telegram-опрос (feedback.log):
    YYYY-MM-DDThh:mm:ss | TYPE: TELEGRAM_POLL | RPE: N | LEGS_HEAVINESS: N
  Вариант Б — Ручной ввод в events.log или текстом в бот:
    YYYY-MM-DD rpe=N notes=текст   (feedback.log)
    YYYY-MM-DD тег описание        (events.log)

Приоритет: events.log всегда участвует в flag-resolution (known_event/illness).
  Telegram-poll дополняет флаги числовыми значениями RPE и усталости ног.
  Если poll отсутствует — система работает только на events.log, не падает.
"""

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import yaml

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

    # Вариант А: Telegram-опрос — забираем из очереди getUpdates
    poll = _collect_telegram_poll(today)

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

    # Добавляем флаги из Telegram-опроса (высокая субъективная усталость)
    if poll:
        if poll.get("rpe") is not None and poll["rpe"] >= 8:
            resolved_flags.append(f"poll_high_rpe:{poll['rpe']}")
        if poll.get("legs") is not None and poll["legs"] >= 4:
            resolved_flags.append(f"poll_heavy_legs:{poll['legs']}")

    season = _read_season_plan(today)

    feedback_source = "poll+events" if poll else "events_only"
    print(f"[context_agent] feedback_source={feedback_source} poll={poll}")
    print(f"[context_agent] flags: {resolved_flags}")
    print(f"[context_agent] block={season.get('current_block')} "
          f"B-race={season.get('days_to_b_race')}д "
          f"A-race={season.get('days_to_a_race')}д")
    return {
        "context_flags":        resolved_flags,
        "athlete_memory":       athlete_memory,
        "events_context":       events,
        "feedback_context":     feedback,
        "yesterday_analysis":   yesterday_analysis,
        "season_plan":          season,
        "current_block":        season.get("current_block", "unknown"),
        "days_to_b_race":       season.get("days_to_b_race"),
        "days_to_a_race":       season.get("days_to_a_race"),
        "poll_rpe":             poll["rpe"]  if poll else None,
        "poll_legs_heaviness":  poll["legs"] if poll else None,
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

def _collect_telegram_poll(today: str) -> dict | None:
    """
    Вариант А: забирает ответы на вечерний опрос из очереди Telegram getUpdates.
    Lazy-import telegram_bot чтобы не тянуть зависимости при standalone-запуске.
    При любой ошибке возвращает None — пайплайн продолжает работу без poll-данных.
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from telegram_bot import collect_poll_response
        return collect_poll_response(today)
    except Exception as e:
        print(f"[context_agent] poll fetch failed: {e}")
        return None


def _read_log(path: str, days: int) -> str:
    """Возвращает строки лога за последние N дней с относительными метками времени."""
    today  = date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    try:
        result = []
        for line in open(path, encoding="utf-8"):
            if line.startswith("#") or not line.strip():
                continue
            date_str = line.strip()[:10]
            if date_str < cutoff:
                continue
            try:
                delta = (today - date.fromisoformat(date_str)).days
                if delta == 0:
                    label = "[сегодня, ещё не выполнено]"
                elif delta == 1:
                    label = "[вчера]"
                elif delta > 0:
                    label = f"[{delta}д назад]"
                else:
                    label = f"[через {-delta}д]"
                line = line[:10] + f" {label}" + line[10:]
            except ValueError:
                pass
            result.append(line)
        return "".join(result[-30:])
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


_BLOCK_LABELS = {
    "recovery":    "Восстановление",
    "re_entry":    "Re-entry / Аэробный ребилд",
    "foundation":  "Foundation (LT/VO2)",
    "specific":    "Specific (вертикаль + объём)",
    "pre_b_taper": "Pre-B мини-тейпер",
    "b_race":      "B-RACE день",
    "a_race_prep": "Recovery + A-race prep",
    "a_race":      "A-RACE день",
}


def _to_date_str(val) -> str:
    """Конвертирует datetime.date или строку в ISO-формат."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _read_season_plan(today: str) -> dict:
    """
    Читает plans/gauja_90k_2026.md, парсит yaml-блок.
    Вычисляет current_block, days_to_b_race, days_to_a_race автоматически.
    Возвращает пустой dict при любой ошибке (graceful degradation).
    """
    plan_path = Path(__file__).parent.parent / "plans" / "gauja_90k_2026.md"
    try:
        content = plan_path.read_text(encoding="utf-8")
        match = re.search(r"```yaml\n(.*?)```", content, re.DOTALL)
        if not match:
            print("[context_agent] season plan: yaml-блок не найден")
            return {}

        config = yaml.safe_load(match.group(1))
        today_date = date.fromisoformat(today)

        # Определяем текущий блок по датам
        schedule = config.get("block_schedule", {})
        current_block = "unknown"
        for name, info in schedule.items():
            if "date" in info:
                if _to_date_str(info["date"]) == today:
                    current_block = name
                    break
            elif "start" in info and "end" in info:
                start = date.fromisoformat(_to_date_str(info["start"]))
                end   = date.fromisoformat(_to_date_str(info["end"]))
                if start <= today_date <= end:
                    current_block = name
                    break

        # Дни до гонок
        b_date = date.fromisoformat(_to_date_str(config["b_race"]["date"]))
        a_date = date.fromisoformat(_to_date_str(config["a_race"]["date"]))
        days_to_b = (b_date - today_date).days
        days_to_a = (a_date - today_date).days

        return {
            "current_block":        current_block,
            "current_block_label":  _BLOCK_LABELS.get(current_block, current_block),
            "days_to_b_race":       days_to_b,
            "days_to_a_race":       days_to_a,
            "b_race_date":          _to_date_str(config["b_race"]["date"]),
            "b_race_distance_km":   config["b_race"].get("distance_km"),
            "b_race_strategy":      config["b_race"].get("strategy"),
            "a_race_date":          _to_date_str(config["a_race"]["date"]),
            "a_race_distance_km":   config["a_race"].get("distance_km"),
            "a_race_elevation_m":   config["a_race"].get("elevation_gain_m"),
            "peak_weekly_tss":      config.get("peak_weekly_tss"),
            "taper_start":          _to_date_str(config["taper_start_final"]) if config.get("taper_start_final") else None,
        }
    except Exception as e:
        print(f"[context_agent] season plan error: {e}")
        return {}


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
