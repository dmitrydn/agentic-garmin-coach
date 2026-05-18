"""
memory_agent.py — Sonnet 4.6, раз в неделю (воскресенье вечером).

Читает: recommendation_log (последние 7 дней), wellness_cache,
        текущий ATHLETE_MEMORY.md.
Перезаписывает каждую секцию — не аппендит. Файл не должен расти.
Соблюдает лимиты токенов на секцию (указаны в заголовках).

Запуск: uv run agents/memory_agent.py
Или из pipeline.py при условии day_of_week == 6 (воскресенье).
"""

import json
import os
import sqlite3
from datetime import date, timedelta

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MEMORY_FILE = "ATHLETE_MEMORY.md"

# ── System prompt ─────────────────────────────────────────────────────────────

MEMORY_SYSTEM = """
Ты обновляешь долгосрочный профиль атлета в ATHLETE_MEMORY.md.

ПРАВИЛА (строго обязательны):
1. Перезаписывай каждую секцию полностью — не добавляй в конец.
2. Соблюдай лимиты токенов на секцию (указаны в заголовках).
3. Если нет новых данных по секции — сохраняй предыдущий текст без изменений.
4. Обновляй "Последнее обновление" датой сегодня.
5. Выводи ТОЛЬКО содержимое файла, без пояснений, без ```markdown.

СТРУКТУРА (сохранять точно):
## Текущая фаза [макс 150 токенов]
## HRV профиль [макс 100 токенов]
## Паттерны восстановления [макс 150 токенов]
## Ответ на нагрузку [макс 150 токенов]
## Гонки: целевой TSB [макс 100 токенов]
## Силовые [макс 100 токенов]
## Последнее обновление: YYYY-MM-DD

АНАЛИЗИРУЙ:
- Какие readiness_score соответствовали хорошему HRV назавтра?
- Есть ли паттерн: при каком ACWR атлет лучше восстанавливается?
- Изменился ли HRV baseline за неделю?
- Были ли признаки перегрузки или недовосстановления?
"""


# ── Data collection ───────────────────────────────────────────────────────────

def _collect_weekly_data() -> dict:
    """Собирает данные за последние 7 дней для анализа."""
    today    = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    con = sqlite3.connect("coach.db")

    wellness = con.execute("""
        SELECT date, ctl, atl, form, hrv, resting_hr, sleep_score
        FROM wellness_cache WHERE date >= ? ORDER BY date
    """, (week_ago,)).fetchall()

    # actual_hr  — из activity_cache за тот же день (telegram_bot не пишет это поле).
    # hrv_next_day — из wellness_cache следующего дня (никто не пишет это поле).
    # Оба получаем через JOIN, чтобы не зависеть от внешней записи.
    recommendations = con.execute("""
        SELECT r.date, r.readiness, r.readiness_score, r.recommendation_type,
               r.actual_rpe,
               a.avg_hr            AS actual_hr,
               w_next.hrv          AS hrv_next_day
        FROM recommendation_log r
        LEFT JOIN activity_cache a
            ON a.date = r.date
        LEFT JOIN wellness_cache w_next
            ON w_next.date = date(r.date, '+1 day')
        WHERE r.date >= ? ORDER BY r.date
    """, (week_ago,)).fetchall()

    con.close()

    return {
        "today":     today,
        "week_ago":  week_ago,
        "wellness":  [
            {"date": r[0], "ctl": r[1], "atl": r[2], "form": r[3],
             "hrv": r[4], "resting_hr": r[5], "sleep_score": r[6]}
            for r in wellness
        ],
        "recommendations": [
            {"date": r[0], "readiness": r[1], "readiness_score": r[2],
             "rec_type": r[3], "actual_rpe": r[4], "actual_hr": r[5],
             "hrv_next_day": r[6]}
            for r in recommendations
        ],
    }


def _read_current_memory() -> str:
    try:
        return open(MEMORY_FILE, encoding="utf-8").read()
    except FileNotFoundError:
        return _default_memory_template()


def _default_memory_template() -> str:
    return """## Текущая фаза [макс 150 токенов]
Данных нет. Мезоцикл: старт 2026-05-01. Фаза силовых: adaptation.
Ближайшая гонка: 23.05 C (trail 23km). Главная цель: 01.08 UTMB Gauja Trail 50км.

## HRV профиль [макс 100 токенов]
Rolling baseline: нет данных. Устройство: HRM-Pro (точный HRV с груди).

## Паттерны восстановления [макс 150 токенов]
Данных пока нет.

## Ответ на нагрузку [макс 150 токенов]
ACWR оптимум: 0.85-1.15. Рельеф Sūniši: terrain multiplier 1.1-1.2.

## Гонки: целевой TSB [макс 100 токенов]
Данных предыдущих гонок нет. Обновить после гонки 23.05.

## Силовые [макс 100 токенов]
Начало: 24.05 (после гонки C). Фаза: adaptation (bodyweight).

## Последнее обновление: """ + date.today().isoformat()


# ── LangGraph node ────────────────────────────────────────────────────────────

def memory_agent_fn(state: dict | None = None) -> dict:
    """
    Sonnet 4.6. Обновляет ATHLETE_MEMORY.md.
    Можно вызывать standalone или из pipeline при воскресенье.
    """
    weekly_data    = _collect_weekly_data()
    current_memory = _read_current_memory()

    user_content = f"""
Текущий ATHLETE_MEMORY.md:
{current_memory}

---
Данные за последние 7 дней ({weekly_data['week_ago']} → {weekly_data['today']}):

Wellness:
{json.dumps(weekly_data['wellness'], ensure_ascii=False, indent=2)}

Рекомендации и исходы:
{json.dumps(weekly_data['recommendations'], ensure_ascii=False, indent=2)}

Обнови файл, сохрани структуру и лимиты. Выведи только содержимое файла.
""".strip()

    print("[memory_agent] запрос к Sonnet 4.6...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=MEMORY_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    new_memory = response.content[0].text.strip()

    # Снять обёртки ```markdown если модель добавила
    if new_memory.startswith("```"):
        new_memory = "\n".join(new_memory.split("\n")[1:])
    if new_memory.endswith("```"):
        new_memory = "\n".join(new_memory.split("\n")[:-1])

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(new_memory)

    print(f"[memory_agent] ATHLETE_MEMORY.md обновлён ({len(new_memory)} символов)")
    return {"athlete_memory_updated": True}


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = memory_agent_fn()
    print("\nОбновлённый ATHLETE_MEMORY.md:")
    print(open(MEMORY_FILE, encoding="utf-8").read())
