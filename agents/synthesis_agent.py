"""
synthesis_agent.py — Sonnet 4.6, финальное сообщение в Telegram + сохранение анализа.

Вход: полный State после всех предыдущих агентов.
Выход: final_message (текст для Telegram) + analysis_json (для analyses/YYYY-MM-DD.json).

Стиль сообщения: тренер → атлет, русский, без воды, максимум 400 слов.
Структура: ✅/⚠/❌ статус → тренировка → гидрация → одна ключевая рекомендация.
"""

import json
import os
import sqlite3
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── System prompt ─────────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM = """
Ты тренер по бегу. Пишешь ежедневное сообщение атлету в Telegram.

АТЛЕТ: мужчина 58 лет, опытный, понимает спортивные термины (HRV, CTL, ACWR).

СТРУКТУРА СООБЩЕНИЯ (строго соблюдать):
1. Статус дня: одна строка с эмодзи (✅ готов / ⚠️ умеренно / 😴 отдых)
2. Твой статус: 2-3 предложения об HRV, восстановлении, ключевых метриках
3. ТРЕНИРОВКА СЕГОДНЯ: название, длительность, зоны, конкретное описание
4. Гидрация: 3-4 ключевых момента из расписания (не все, самые важные)
5. Одна рекомендация дня (жирным)

ПРИНЦИПЫ:
- Конкретно: "бег 50 мин в Z1-Z2, пульс 120-135", не "лёгкая пробежка"
- Без воды: убери все "отлично", "прекрасно", "молодец" — только факты
- Если есть аномалии в флагах — объясни кратко и понятно
- Если завтра гонка или ключевая тренировка — упомяни в конце
- Длина: 250-400 слов, не больше
- Если поле duration_note присутствует в данных тренировки — включи его дословно
  сразу после указания длительности (в скобках или отдельной строкой)

ФОРМАТ: обычный текст с эмодзи. Без markdown заголовков.
"""


# ── LangGraph node ────────────────────────────────────────────────────────────

def synthesis_fn(state: dict) -> dict:
    """Sonnet 4.6. Строит сообщение и сохраняет analysis_json."""

    rec      = state.get("recommendation") or {}
    hydration = state.get("hydration_schedule") or []

    # Добавляем дисклеймер детерминированно — LLM не должен угадывать источник
    rec_for_prompt = dict(rec)
    if rec.get("duration_estimated"):
        rec_for_prompt["duration_note"] = (
            f"⚠️ {rec.get('duration_min')} мин — оценка агента, "
            "Garmin Coach не вернул реальную длительность. "
            "Проверь план в приложении Garmin."
        )

    user_content = f"""
Дата: {state.get('date')}
Readiness: {state.get('readiness')} (score {state.get('readiness_score')})
Reasoning: {state.get('readiness_reasoning')}

Тренировка:
{json.dumps(rec_for_prompt, ensure_ascii=False, indent=2)}

Гидрация:
{chr(10).join(f'- {h}' for h in hydration)}

Ключевые метрики:
- HRV: {state.get('hrv_today')} (baseline {state.get('hrv_rolling_avg')}, deviation {state.get('hrv_deviation_pct')}%)
- ACWR: {state.get('acwr')} ({state.get('acwr_zone')})
- RHR тренд: {'+' if (state.get('rhr_trend') or 0) > 0 else ''}{state.get('rhr_trend')} bpm
- Form (CTL-ATL): {state.get('form_today', 'н/д')}

Флаги: {state.get('context_flags', [])}

Garmin real-time:
- Body Battery: {(state.get('garmin_rt') or {}).get('body_battery', 'н/д')}
- Training Readiness: {(state.get('garmin_rt') or {}).get('training_readiness', 'н/д')}

Сезонный контекст:
- Текущий блок: {state.get('current_block', 'н/д')} ({state.get('season_plan', {}).get('current_block_label', '')})
- До B-race ({state.get('season_plan', {}).get('b_race_date', '?')}): {state.get('days_to_b_race', 'н/д')} дн.
- До A-race ({state.get('season_plan', {}).get('a_race_date', '?')}): {state.get('days_to_a_race', 'н/д')} дн.
""".strip()

    print("[synthesis] запрос к Sonnet 4.6...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYNTHESIS_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    final_message = response.content[0].text.strip()

    # Структурированный анализ для analyses/YYYY-MM-DD.json
    analysis_json = {
        "date":               state.get("date"),
        "readiness":          state.get("readiness"),
        "readiness_score":    state.get("readiness_score"),
        "readiness_reasoning": state.get("readiness_reasoning"),
        "recommendation_type": rec.get("type"),
        "recommendation":     rec.get("description"),
        "hrv_today":          state.get("hrv_today"),
        "hrv_rolling_avg":    state.get("hrv_rolling_avg"),
        "hrv_deviation_pct":  state.get("hrv_deviation_pct"),
        "acwr":               state.get("acwr"),
        "acwr_zone":          state.get("acwr_zone"),
        "rhr_trend":          state.get("rhr_trend"),
        "mesocycle_week":     state.get("mesocycle_week"),
        "context_flags":      state.get("context_flags", []),
    }

    # Сохраняем анализ в JSON
    _save_analysis(state.get("date", ""), analysis_json)

    # Сохраняем в recommendation_log — единственное место где пишутся
    # readiness/score/type/text. telegram_bot допишет actual_rpe позже.
    _save_recommendation_log(state.get("date", ""), analysis_json)

    print(f"[synthesis] сообщение готово, {len(final_message)} символов")
    return {
        "final_message": final_message,
        "analysis_json": analysis_json,
    }


def _save_analysis(date_str: str, data: dict) -> None:
    Path("analyses").mkdir(exist_ok=True)
    path = f"analyses/{date_str}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[synthesis] сохранено: {path}")


def _save_recommendation_log(date_str: str, data: dict) -> None:
    """Пишет readiness/score/type/text в recommendation_log.
    actual_rpe, actual_hr, hrv_next_day дописывает telegram_bot и memory_agent позже.
    ON CONFLICT DO UPDATE — не трогаем actual_rpe если атлет уже прислал фидбек."""
    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO recommendation_log
            (date, readiness, readiness_score, recommendation_type, recommendation_text)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            readiness=excluded.readiness,
            readiness_score=excluded.readiness_score,
            recommendation_type=excluded.recommendation_type,
            recommendation_text=excluded.recommendation_text
    """, (
        date_str,
        data.get("readiness"),
        data.get("readiness_score"),
        data.get("recommendation_type"),
        data.get("recommendation"),
    ))
    con.commit()
    con.close()
    print(f"[synthesis] recommendation_log обновлён: {date_str}")


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date

    mock_state = {
        "date":               date.today().isoformat(),
        "readiness":          "normal",
        "readiness_score":    6.5,
        "readiness_reasoning": "HRV в норме, ACWR оптимальный. Умеренный день.",
        "recommendation": {
            "type":         "easy",
            "title":        "Лёгкий бег в Z1-Z2",
            "duration_min": 50,
            "zones":        ["Z1", "Z2"],
            "description":  "50 минут по тропам, пульс 120-135. Первые 10 мин разминка Z1.",
            "cautions":     ["пульс не выше 140", "пить на 15-й и 35-й минуте"],
        },
        "hydration_schedule": [
            "07:00 — стакан воды (250мл)",
            "за 30 мин до бега — 350мл",
            "на 15-й мин — 200мл",
            "на 35-й мин — 200мл",
            "после бега — 500мл",
        ],
        "hrv_today":          60.0,
        "hrv_rolling_avg":    62.0,
        "hrv_deviation_pct":  -3.2,
        "acwr":               1.05,
        "acwr_zone":          "optimal",
        "rhr_trend":          0.5,
        "mesocycle_week":     2,
        "context_flags":      [],
        "garmin_rt":          {},
    }

    result = synthesis_fn(mock_state)
    print("\n" + "="*60)
    print(result["final_message"])
