"""
coach_agent.py — Sonnet 4.6, оценка readiness атлета.

Вход: метрики из metrics_fn + контекст из context_agent_fn.
Выход: JSON {readiness, readiness_score, reasoning}.

Системный промпт содержит всю доменную логику интерпретации.
Не пересчитывает метрики — использует готовые значения из State.
"""

import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── System prompt ─────────────────────────────────────────────────────────────
# {mesocycle_week} подставляется динамически в coach_agent_fn

COACH_SYSTEM = """
Ты персональный тренер по бегу. Анализируй данные и определи readiness атлета.

АТЛЕТ:
- Мужчина, 58 лет, 9 лет бега, 4 марафона, 1 ультра (77км)
- Методология: 80/20 + Garmin Coach Personal Plan 2026
- Устройство: Garmin Epix Gen 2 + HRM-Pro (точный HRV с груди)
- Покрытие: лесные тропы, гравий/песок, ~100м набора на 10км в Sūniši
- Гидрация: пьёт мало — критично напоминать
- Силовые: начинает с нуля, первые 4 недели = bodyweight only (DOMS-риск)
- Восстановление после качественной сессии: 48-72ч (возраст 58)

ИНТЕРПРЕТАЦИЯ HRV (7-дневная rolling mean, HRM-Pro, Plews et al. 2017):
- deviation > +5%    → высокая готовность, можно интенсивнее
- deviation -5%..+5% → норма, по плану
- deviation < -5%    → снизить интенсивность
- deviation < -10%   → только восстановительное
- cv > 0.10          → нестабильная неделя, консервативнее

ACWR зоны (ATL/CTL, Gabbett 2016):
- < 0.8   → underload
- 0.8-1.3 → optimal
- 1.3-1.5 → caution (повышенный риск)
- > 1.5   → high_risk → обязательное снижение

ГОНКИ 2026:
- 23.05 (C, trail 23км), 18.07 (B), 01.08 (A — главная, UTMB Gauja Trail 50км)

МЕЗОЦИКЛ (3+1 периодизация):
Текущая неделя: {mesocycle_week}/4.
Недели 1-3 = нагрузка, неделя 4 = восстановление.
Form=-15 на неделе 3 — НОРМА накопленной усталости, не аномалия.
Form=-15 на неделе 1 — сигнал перегрузки.

ЖЁСТКИЕ ПРАВИЛА:
- Если days_since_quality < 2 → качество запрещено независимо от readiness
- Если acwr_zone = "high_risk" → readiness не может быть выше "low"
- Если upcoming_plan пуст → используй структуру: Пн=силовая, Вт=Z1,
  Ср=качество, Чт=Z1, Пт=силовая, Сб=длинный, Вс=back-to-back Z1
- Флаги с префиксом "known_event|" — это известные события из events.log,
  учитывай их как смягчающий контекст, не как аномалии

Отвечай ТОЛЬКО JSON, без преамбулы:
{
  "readiness": "high|normal|low|rest",
  "readiness_score": 7.5,
  "reasoning": "краткое объяснение на русском, 2-3 предложения"
}
"""


# ── LangGraph node ────────────────────────────────────────────────────────────

def coach_agent_fn(state: dict) -> dict:
    """Sonnet 4.6. Единственный вызов LLM в первой половине пайплайна."""

    user_content = f"""
Дата: {state.get('date')}
Мезоцикл неделя: {state.get('mesocycle_week', '?')}

HRV сегодня: {state.get('hrv_today')}
HRV 7д rolling avg: {state.get('hrv_rolling_avg')}
HRV отклонение: {state.get('hrv_deviation_pct')}%
HRV CV недели: {state.get('hrv_cv_week')}

ACWR: {state.get('acwr')} ({state.get('acwr_zone')})
RHR сегодня: {state.get('rhr_today')} bpm
RHR тренд: {'+' if (state.get('rhr_trend') or 0) > 0 else ''}{state.get('rhr_trend')} bpm {'⚠ растёт' if state.get('rhr_rising') else ''}

Дней с последней качественной сессии: {state.get('days_since_quality')}
80/20 за неделю: {state.get('z1z2_ratio_week')} ({'OK' if state.get('z1z2_compliant') else '⚠ нарушение'})
Силовая нагрузка сегодня: {state.get('strength_load_today', 0)} усл.ед.

Флаги контекста: {state.get('context_flags', [])}
Garmin Coach план (ближайшие 3 тренировки): {state.get('upcoming_plan', [])[:3]}

Долгосрочная память тренера:
{state.get('athlete_memory', 'нет данных')}

Вчерашний анализ: {state.get('yesterday_analysis', 'нет данных')}
""".strip()

    system = COACH_SYSTEM.replace(
        "{mesocycle_week}", str(state.get("mesocycle_week", 1))
    )

    print("[coach_agent] запрос к Sonnet 4.6...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines()
            if not line.startswith("```")
        ).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[coach_agent] ошибка парсинга JSON: {raw[:200]}")
        result = {
            "readiness":       "normal",
            "readiness_score": 5.0,
            "reasoning":       "Ошибка парсинга — применяю нейтральную оценку",
        }

    print(f"[coach_agent] readiness={result['readiness']} score={result['readiness_score']}")
    return {
        "readiness":           result["readiness"],
        "readiness_score":     float(result["readiness_score"]),
        "readiness_reasoning": result["reasoning"],
    }


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date

    mock_state = {
        "date":               date.today().isoformat(),
        "mesocycle_week":     2,
        "hrv_today":          58.0,
        "hrv_rolling_avg":    62.0,
        "hrv_deviation_pct":  -6.5,
        "hrv_cv_week":        0.07,
        "acwr":               1.05,
        "acwr_zone":          "optimal",
        "rhr_today":          48,
        "rhr_trend":          1.0,
        "rhr_rising":         False,
        "days_since_quality": 2,
        "z1z2_ratio_week":    0.81,
        "z1z2_compliant":     True,
        "strength_load_today": 0.0,
        "context_flags":      [],
        "upcoming_plan":      [{"date": date.today().isoformat(), "type": "running", "description": "Easy run 45min"}],
        "athlete_memory":     "Текущий мезоцикл: неделя 2/4. HRV baseline: 62. ACWR оптимум: 0.85-1.15.",
        "yesterday_analysis": "",
    }

    result = coach_agent_fn(mock_state)
    print(f"\nReadiness: {result['readiness']} ({result['readiness_score']})")
    print(f"Reasoning: {result['readiness_reasoning']}")
