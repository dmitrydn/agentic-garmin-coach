# CLAUDE.md — Инструкции для Claude Code

Персональный AI беговой тренер для атлета 58 лет.
Оркестратор: LangGraph. LLM: Opus 4.8 (coach) + Sonnet 4.6 (plan, synthesis, memory).

→ Стек, структура проекта, переменные окружения, статус агентов: `README.md`

---

## Запуск

```bash
uv run agents/data_agent.py   # любой агент standalone
uv run agents/pipeline.py     # полный пайплайн
uv run agents/pipeline.py --dry  # без отправки в Telegram
```

**Никогда не использовать `python` напрямую — только `uv run`.**

---

## Какие агенты вызывают LLM

Большинство агентов — чистый Python, ноль токенов.
LLM вызывают только четыре агента:

| Агент | Модель | Задача |
|---|---|---|
| `coach_agent` | `claude-opus-4-8` | Оценка readiness из HRV, ACWR, флагов, памяти тренера |
| `plan_agent` | `claude-sonnet-4-6` | Адаптация Garmin-плана под текущий readiness |
| `synthesis_agent` | `claude-sonnet-4-6` | Финальное сообщение в Telegram |
| `memory_agent` | `claude-sonnet-4-6` | Еженедельная перезапись ATHLETE_MEMORY.md |

Остальные агенты (`data`, `metrics`, `garmin`, `context`, `hydration`) — детерминированная логика, Python.

```python
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def call_sonnet(system: str, user: str, max_tokens: int = 1000) -> str:
    r = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=max_tokens,
        system=system, messages=[{"role": "user", "content": user}]
    )
    return r.content[0].text
```

---

## Запрещено

- Не использовать `python` — только `uv run`
- Не читать всю историю wellness — только delta с `last_sync`
- Не дёргать Garmin API если кеш свежее TTL (plan: 12ч / rt: 24ч)
- Не вызывать LLM там где достаточно Python-логики
- Не хранить секреты в коде — только через `.env`
- Не использовать синхронный httpx — только async
- Не игнорировать аномалии — всегда объяснять через events.log

---

## Verification Protocol

**Обязательно после каждого изменения кода:**

```bash
uv run pytest tests/ -x --tb=short
```

### Правила

1. **Задача не считается выполненной, пока хотя бы один тест падает.**
   Исправить регрессию до отчёта пользователю — не после.

2. **При падении теста**: найти root cause в коде, не в тесте.
   Удалять или скипать тесты запрещено без явной просьбы пользователя.

3. **При добавлении новой функциональности**: добавить хотя бы один тест
   в соответствующий слой (Layer I — реализация, Layer B — бизнес-гарантия).

4. **Слои тестов**:
   - `test_metrics.py` — математика метрик (HRV, ACWR, зоны)
   - `test_routing.py` — маршрутизация LangGraph графа
   - `test_hydration_agent.py` — правила гидрации
   - `test_context_agent.py` — флаги и парсинг событий
   - `test_garmin_agent.py` — парсинг Garmin API, ATP длительности
   - `test_data_agent.py` — дельта-синхронизация, SQLite
   - `test_contracts.py` — схемы выходных данных LLM-агентов
   - `test_business_scenarios.py` — гарантии тренера атлету

### Что проверяет Layer B (бизнес-гарантии)

| Гарантия | Тест |
|---|---|
| `readiness=rest` → no LLM call, type=rest | `test_readiness_rest_bypasses_plan_llm` |
| illness в events.log → illness flag в контексте | `test_illness_events_produce_illness_flag` |
| ACWR > 1.5 → acwr_high_risk flag | `test_acwr_high_risk_flag_always_present` |
| ATP resolves → no ⚠️ в Telegram | `test_garmin_atp_no_duration_warning_in_synthesis_prompt` |
| duration_estimated=True → ⚠️ инжектится | `test_duration_estimated_true_always_injects_warning` |
| Coach видит все 7 дней плана | `test_coach_prompt_contains_all_7_plan_days` |
| events.log → относительные метки времени | `test_past_events_carry_relative_labels` |
| days_since_quality < 2 → quality_too_recent flag | `test_quality_too_recent_flag_present_when_dsq_is_1` |

---

*Детали API, схема БД, промпты агентов, LangGraph граф → `agents/CLAUDE.md`*

*Май 2026 · обновлять при изменении архитектуры*
