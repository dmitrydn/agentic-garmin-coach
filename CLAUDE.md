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

*Детали API, схема БД, промпты агентов, LangGraph граф → `agents/CLAUDE.md`*

*Май 2026 · обновлять при изменении архитектуры*
