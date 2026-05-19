"""
plan_agent.py — Sonnet 4.6, рекомендация тренировки дня.

Вход: readiness из coach_agent + upcoming_plan из garmin_agent + полный State.
Выход: dict с типом, описанием, зонами, длительностью, предостережениями.

Если readiness="rest" — возвращает день отдыха без LLM-вызова (экономия токенов).
"""

import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── System prompt ─────────────────────────────────────────────────────────────

PLAN_SYSTEM = """
Ты персональный тренер по бегу. Составь рекомендацию тренировки на сегодня.

АТЛЕТ: мужчина 58 лет, 9 лет бега, методология 80/20.
Покрытие: лесные тропы Sūniši (~100м/10км набора).
Цель сезона: UTMB Gauja Trail 50км (01.08.2026).

ПРИНЦИПЫ РЕКОМЕНДАЦИИ:
1. Приоритет Garmin Coach — если upcoming_plan содержит тренировку на сегодня,
   адаптируй её под текущий readiness, не заменяй полностью
2. При readiness="low" → снизить интенсивность, не объём (или оба если нужно)
3. При readiness="high" → можно добавить 10-15% к плановой интенсивности
4. Силовые не совмещать с качеством в один день
5. Взвешивание по ценности гонок: за 7 дней до C-гонки → tapering,
   за 14 до A-гонки → полный taper. C-гонка НЕ стоит риска для A-гонки —
   её ценность воспроизводима тренировочным длинным выходом.
6. При illness-флаге в context_flags — не рекомендовать нагрузку выше Z1
   до выполнения чек-листа возобновления. В поле description включить
   конкретные физиологические маркеры, при которых атлет может вернуться
   к нагрузке (RHR, температура, субъективное состояние, симптомы).

ЗОНЫ (Garmin / 5-zone):
Z1: очень лёгко, разговорный темп
Z2: аэробная база, можно разговаривать
Z3: марафонный темп, краткие фразы
Z4: пороговый, не можешь говорить
Z5: максимальный

ФОРМАТ ОТВЕТА — только JSON:
{
  "type": "easy|quality|long|back-to-back|strength|rest",
  "title": "Лёгкий бег в Z1-Z2",
  "duration_min": 50,
  "zones": ["Z1", "Z2"],
  "description": "детальное описание на русском, 3-5 предложений",
  "cautions": ["пить каждые 20 мин", "пульс не выше 145"],
  "garmin_plan_used": true,
  "return_protocol": null
}

Поле return_protocol: null при обычной тренировке.
При illness-флаге — объект с чек-листом допуска к нагрузке:
{
  "return_protocol": {
    "rhr_target": "вернуться к базовой ±1 bpm",
    "temp_free_hours": 48,
    "symptom_restriction": "только верхние ДП, грудные — абсолютный запрет",
    "subjective_min": "≥7/10",
    "sleep_nights": 2,
    "race_clearance": "описание условий допуска на ближайший старт или null если нет гонок"
  }
}
"""


# ── LangGraph node ────────────────────────────────────────────────────────────

def plan_agent_fn(state: dict) -> dict:
    """
    Sonnet 4.6. Если readiness=rest — возвращает без LLM-вызова.
    """
    if state.get("readiness") == "rest":
        print("[plan_agent] readiness=rest — день отдыха без LLM")
        return {"recommendation": {
            "type":         "rest",
            "title":        "День отдыха",
            "duration_min": 0,
            "zones":        [],
            "description":  "Полный отдых. Лёгкая прогулка 15-20 мин по желанию. Гидрация, сон, растяжка.",
            "cautions":     ["не планировать тренировки", "спать не менее 8 часов"],
            "garmin_plan_used": False,
        }}

    # Тренировка Garmin Coach на сегодня (если есть)
    today = state.get("date", "")
    todays_workout = next(
        (w for w in (state.get("upcoming_plan") or []) if w.get("date") == today),
        None
    )

    user_content = f"""
Дата: {today}
Readiness: {state.get('readiness')} (score: {state.get('readiness_score')})
Reasoning тренера: {state.get('readiness_reasoning')}

Garmin Coach на сегодня: {json.dumps(todays_workout, ensure_ascii=False) if todays_workout else 'нет данных'}
Garmin Plan на неделю: {json.dumps((state.get('upcoming_plan') or [])[:7], ensure_ascii=False)}

Текущие метрики:
- ACWR: {state.get('acwr')} ({state.get('acwr_zone')})
- HRV deviation: {state.get('hrv_deviation_pct')}%
- Дней с качества: {state.get('days_since_quality')}
- 80/20 за неделю: {state.get('z1z2_ratio_week')} ({'OK' if state.get('z1z2_compliant') else '⚠ нарушение'})
- Мезоцикл неделя: {state.get('mesocycle_week')}/4
- Силовая нагрузка сегодня: {state.get('strength_load_today', 0)} усл.ед.

Garmin real-time (если доступен):
- Body Battery утром: {(state.get('garmin_rt') or {}).get('body_battery', 'н/д')}
- Training Readiness: {(state.get('garmin_rt') or {}).get('training_readiness', 'н/д')}
- Training Status: {(state.get('garmin_rt') or {}).get('training_status', 'н/д')}

Флаги контекста: {state.get('context_flags', [])}

Сезонный план:
- Текущий блок: {state.get('current_block', 'н/д')} ({state.get('season_plan', {}).get('current_block_label', '')})
- Дней до B-race ({state.get('season_plan', {}).get('b_race_distance_km', '?')} km, {state.get('season_plan', {}).get('b_race_date', '?')}): {state.get('days_to_b_race', 'н/д')}
- Дней до A-race ({state.get('season_plan', {}).get('a_race_distance_km', '?')} km / {state.get('season_plan', {}).get('a_race_elevation_m', '?')} m D+, {state.get('season_plan', {}).get('a_race_date', '?')}): {state.get('days_to_a_race', 'н/д')}
- B-race стратегия: {state.get('season_plan', {}).get('b_race_strategy', 'н/д')}

События (events.log, последние 14 дней):
{state.get('events_context') or 'нет событий'}
""".strip()

    print("[plan_agent] запрос к Sonnet 4.6...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=PLAN_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines()
            if not line.startswith("```")
        ).strip()

    try:
        recommendation = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[plan_agent] ошибка парсинга JSON: {raw[:200]}")
        recommendation = {
            "type":         "easy",
            "title":        "Лёгкий бег (fallback)",
            "duration_min": 45,
            "zones":        ["Z1", "Z2"],
            "description":  "Лёгкий восстановительный бег. Ошибка парсинга — применяю безопасный fallback.",
            "cautions":     ["пульс не выше 140"],
            "garmin_plan_used": False,
        }

    print(f"[plan_agent] тип={recommendation.get('type')} длительность={recommendation.get('duration_min')}мин")
    return {"recommendation": recommendation}


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date

    mock_state = {
        "date":               date.today().isoformat(),
        "readiness":          "normal",
        "readiness_score":    6.5,
        "readiness_reasoning": "HRV чуть ниже baseline, ACWR оптимальный. Умеренная тренировка по плану.",
        "upcoming_plan":      [
            {"date": date.today().isoformat(), "type": "running",
             "description": "Easy Run", "duration_min": 50}
        ],
        "acwr":               1.05,
        "acwr_zone":          "optimal",
        "hrv_deviation_pct":  -3.0,
        "days_since_quality": 2,
        "z1z2_ratio_week":    0.80,
        "z1z2_compliant":     True,
        "mesocycle_week":     2,
        "strength_load_today": 0.0,
        "garmin_rt":          {},
        "context_flags":      [],
    }

    result = plan_agent_fn(mock_state)
    rec = result["recommendation"]
    print(f"\nТип: {rec['type']}")
    print(f"Название: {rec['title']}")
    print(f"Длительность: {rec['duration_min']} мин")
    print(f"Зоны: {rec['zones']}")
    print(f"Описание: {rec['description']}")
    print(f"Предостережения: {rec['cautions']}")
