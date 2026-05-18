# agents/CLAUDE.md — Архитектура пайплайна

*Код реализации → в `.py` файлах (docstring + комментарии со ссылками на источники).
Здесь: граф, State, routing, таблица агентов, порядок разработки, запреты.*

---

## LLM vs Python

| Компонент         | Тип             | Модель              | Обоснование                        |
|-------------------|-----------------|---------------------|------------------------------------|
| `data_agent`      | Python-функция  | —                   | fetch → parse → SQLite             |
| `metrics`         | Python-модуль   | —                   | HRV rolling, ACWR, RHR, 80/20      |
| `garmin_agent`    | Python-функция  | —                   | cache check → API → parse          |
| `context_agent`   | Python-функция  | —                   | чтение файлов, флаги               |
| `hydration_agent` | Python-функция  | —                   | rule-based расписание              |
| `coach_agent`     | LLM             | `claude-sonnet-4-6` | readiness, интерпретация метрик    |
| `plan_agent`      | LLM             | `claude-sonnet-4-6` | рекомендация тренировки дня        |
| `synthesis_agent` | LLM             | `claude-sonnet-4-6` | Telegram-сообщение                 |
| `memory_agent`    | LLM             | `claude-sonnet-4-6` | обновление ATHLETE_MEMORY.md       |

**Правило:** LLM — только для рассуждений на естественном языке.
Детерминированные вычисления — чистый Python, ноль токенов.

---

## LangGraph State и граф

```python
class CoachState(TypedDict):
    date: str
    # data_agent
    wellness_delta: list[dict]
    activities_delta: list[dict]
    # metrics (Python)
    hrv_today: float;  hrv_rolling_avg: float;  hrv_deviation_pct: float;  hrv_cv_week: float
    acwr: float;  acwr_zone: str
    rhr_trend: float;  rhr_rising: bool
    adjusted_loads: list[dict]
    days_since_quality: int
    z1z2_ratio_week: float;  z1z2_compliant: bool
    mesocycle_week: int          # 1-3 = нагрузка / 4 = восстановление
    strength_load_today: float
    # garmin_agent (Python)
    upcoming_plan: list[dict]    # план на 7 дней, TTL 12ч
    garmin_rt: dict              # Body Battery, Readiness, Status; TTL 24ч
    # context_agent (Python)
    context_flags: list[str]
    athlete_memory: str
    yesterday_analysis: str
    # coach_agent (Sonnet)
    readiness: str               # "high" / "normal" / "low" / "rest"
    readiness_score: float       # 1–10
    readiness_reasoning: str
    # plan_agent (Sonnet)
    recommendation: dict
    # hydration_agent (Python)
    hydration_schedule: list[str]
    # synthesis_agent (Sonnet)
    final_message: str
    analysis_json: dict          # сохраняется в analyses/YYYY-MM-DD.json
```

```
data → metrics → garmin_plan → context → coach ──┬── [score ≤ 5] → garmin_rt → plan
                                                  └── [score > 5] ──────────────→ plan
                                                                    plan → hydration → synthesis → END
```

`route_garmin_rt`: Garmin real-time только при пограничном `readiness_score ≤ 5.0`.

---

## Порядок разработки

```
1. data_agent.py       — init_db + delta fetch wellness/activities + save → SQLite
2. metrics.py          — HRV rolling, ACWR, RHR trend, terrain multiplier, 80/20, мезоцикл
3. garmin_agent.py     — два режима: plan 7д (TTL 12ч) + realtime (TTL 24ч)
4. context_agent.py    — events.log, feedback.log, вчерашний analyses/JSON, ATHLETE_MEMORY.md
5. coach_agent.py      — Sonnet → readiness JSON {readiness, readiness_score, reasoning}
6. plan_agent.py       — Sonnet → рекомендация тренировки с учётом upcoming_plan
7. hydration_agent.py  — rule-based расписание по типу и длительности тренировки
8. telegram_bot.py     — отправка synthesis + получение RPE-фидбека
9. memory_agent.py     — Sonnet, раз в неделю, перезапись секций ATHLETE_MEMORY.md
10. pipeline.py        — LangGraph граф + lock + feedback_loop (оценка вчерашней рекоменд.)
```

Каждый агент: `if __name__ == "__main__"` standalone-тест, `print`-логирование, не падает молча.

---

## Запреты

- Не использовать `python` — только `uv run`
- Не читать всю историю wellness — только delta с `last_sync`
- Не вызывать Garmin API если кеш свежее TTL (plan: 12ч / rt: 24ч)
- Не вызывать Sonnet там где достаточно Python-логики
- Не хранить секреты в коде — только через `.env`
- Не использовать синхронный httpx — только async
- Не игнорировать аномалии — всегда писать в events.log

---

*Детали реализации: docstring и комментарии в каждом `.py` файле.*
*Научные источники метрик: комментарии в `metrics.py`.*
*Май 2026 · обновлять при изменении архитектуры*
