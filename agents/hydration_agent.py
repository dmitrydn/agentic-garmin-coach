"""
hydration_agent.py — правила гидрации, чистый Python, ноль токенов.

Расписание строится по типу и длительности тренировки.
Атлет исторически пьёт мало — поэтому напоминания обязательны.

Нормы (Burke & Deakin, Clinical Sports Nutrition):
- До: 300-400мл за 30 мин
- Во время: 150-200мл каждые 20 мин при длительности > 60 мин
- После: 500мл в первые 30 мин
"""

from datetime import date


# ── LangGraph node ────────────────────────────────────────────────────────────

def hydration_fn(state: dict) -> dict:
    """Rule-based расписание. Ноль токенов."""
    rec      = state.get("recommendation") or {}
    rec_type = rec.get("type", "easy")
    duration = rec.get("duration_min", 45) or 45

    schedule = _build_schedule(rec_type, duration)
    print(f"[hydration] тип={rec_type}, {len(schedule)} напоминаний")
    return {"hydration_schedule": schedule}


def _build_schedule(rec_type: str, duration_min: int) -> list[str]:
    schedule = []

    # Всегда: утро
    schedule.append("07:00 — стакан воды сразу после пробуждения (250мл)")

    if rec_type == "rest":
        schedule.append("в течение дня — не менее 2л воды небольшими порциями")
        return schedule

    # До тренировки
    schedule.append("за 30 мин до бега — 300-400мл воды или изотоника")

    # Во время (если > 60 мин)
    if duration_min > 60:
        first_drink = 15       # первый глоток через 15 мин
        interval    = 20       # каждые 20 мин
        t = first_drink
        while t < duration_min - 5:
            schedule.append(f"на {t}-й мин бега — 150-200мл")
            t += interval

    # После
    schedule.append("в первые 30 мин после бега — 500мл")

    # Если длинная тренировка — изотоник
    if duration_min >= 90:
        schedule.append("после бега — 500мл изотоника для восстановления электролитов")

    # Ужин
    schedule.append("ужин — 300-400мл воды с едой")

    return schedule


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        ("rest",   0),
        ("easy",   45),
        ("easy",   90),
        ("long",   120),
        ("quality", 75),
    ]

    for rec_type, duration in test_cases:
        print(f"\n=== {rec_type} {duration}мин ===")
        schedule = _build_schedule(rec_type, duration)
        for item in schedule:
            print(f"  {item}")
