# Agentic Garmin Coach

Персональный AI беговой тренер на базе multi-agent системы.
Основной источник данных — intervals.icu API. Garmin Connect — источник проприетарных метрик.
Интерфейс — Telegram-бот.

---

## Стек

| Компонент | Инструмент | Роль |
|---|---|---|
| Данные primary | intervals.icu API | CTL/ATL/Form, HRV, сон, активности, зоны темпа |
| Данные Garmin-only | Garmin Connect (garth) | Body Battery, Training Readiness, Training Status, Garmin Coach план |
| Оркестратор | LangGraph | Stateful multi-agent pipeline с checkpointing |
| LLM агенты | Claude Sonnet 4.6 | Coach, Plan, Synthesis, Memory — только 4 агента |
| Python агенты | чистый Python, 0 токенов | Data, Metrics, Garmin, Context, Hydration |
| Разработка | Claude Code CLI | Написание и обслуживание агентного кода |
| Интерфейс | Telegram-бот | Утренний брифинг, фидбек, напоминания |
| Кеш / структура | SQLite (coach.db) | Metrics cache, Garmin cache с TTL |
| Сессионная память | JSON files (analyses/) | Аналитика сессий, гибкая схема |
| Долгосрочная память | ATHLETE_MEMORY.md | Профиль тренера, ~800 токенов |
| Пакеты | uv | Python окружение |

**Бюджет:** ~$28–32/мес
(`$4` intervals.icu · `$20` Claude Pro/Code · `~$4–8` Anthropic API)

## Технический стек

```
Python 3.12+ · uv · LangGraph · httpx (async) · anthropic
python-telegram-bot · garth · sqlite3 · python-dotenv
```
---

## Переменные окружения (.env)

```
INTERVALS_ATHLETE_ID=      # числовой ID атлета
INTERVALS_API_KEY=         # из Settings → API
ANTHROPIC_API_KEY=         # sk-ant-...
TELEGRAM_BOT_TOKEN=        # от @BotFather
TELEGRAM_CHAT_ID=          # ID чата атлета
GARMIN_EMAIL=
GARMIN_PASSWORD=
```

---

## Профиль атлета

```yaml
возраст:     58 лет
опыт:        9 лет бега
марафоны:    4 финиша
ультра:      1 финиш (77 km)
методология: 80/20 + Garmin Coach Personal Plan (2026)
устройство:  Garmin Epix Gen 2 (24/7) + HRM-Pro (точный HRV с груди)
локация:     Sūniši, Garkalnes novads (~20 мин от Риги)
покрытие:    лесные тропы + гравий/песок, сосновый лес
рельеф:      холмистый, ~100m набора на 10 km
гидрация:    пьёт мало — напоминания критичны
силовые:     начинает с нуля (май 2026)
```

---

## Календарь гонок 2026

| Дата | Дистанция | Приоритет | Гонка |
|---|---|---|---|
| 23.05.2026 | 23 km | **C** | Trail |
| 18.07.2026 | 50 km | **B** | Trail |
| 01.08.2026 | 50 km | **A** | UTMB Gauja Trail |

---

## Недельная структура

| День | Тип | Содержание |
|---|---|---|
| Пн | 💪 Силовая (основная) | 45–60 мин · Bulgarian split squat · RDL · hip thrust · calf raise |
| Вт | 🏃 Лёгкий бег | Зона 1–2 · 50–60 мин · лес |
| Ср | ⚡ Качество | Зона 3–4 · порог/интервалы · единственная тяжёлая в неделю |
| Чт | 🏃 Восстановительный | Строго Зона 1 · 40–50 мин |
| Пт | 💪 Силовая (профилактика) | 40–50 мин · step-up · lateral band · eccentric calf · core |
| Сб | 🏔 Длинный бег | Зона 1–2 · главная сессия недели · рельеф + трейл |
| Вс | 🏃 Back-to-back | Зона 1 · 40–60 мин · усталые ноги |

---

## Фазы силовых тренировок

| Период | Фаза | Содержание |
|---|---|---|
| до 23.05 | `pre-race-c` | силовых нет |
| 24.05 – 11.07 | `adaptation` | bodyweight + резинки · 2×/нед · 35 мин |
| 12.07 – 17.07 | `taper-b` | силовых нет |
| 18.07 – 24.07 | `between-races` | 1× лёгкая по самочувствию |
| 25.07 – 01.08 | `taper-a` | силовых нет |
| после 01.08 | `build` | полноценные 2×/нед с весами |

---

## Архитектура пайплайна

```
Триггер: cron 07:00
         │
         ▼
[1] data_agent · Python
    intervals.icu /wellness + /activities
    читает только DELTA (новее last_sync из SQLite)
    пишет в: wellness_cache, activity_cache
         │
         ▼
[2] metrics · Python
    HRV rolling 7д, ACWR, RHR trend, terrain multiplier
    80/20 compliance, days_since_quality, мезоцикл
         │
         ▼
[3] garmin_plan · Python (TTL 12ч)
    Garmin Coach план на 7 дней → upcoming_plan
         │
         ▼
[4] context_agent · Python
    events.log (14 дней) + feedback.log (7 дней) + analyses/вчера.json
    вычисляет context_flags, разрешает аномалии через events.log
         │
         ▼
[5] coach_agent · Sonnet 4.6
    ATHLETE_MEMORY.md + метрики + флаги + upcoming_plan
    → readiness: high / normal / low / rest  +  readiness_score 1–10
         │
         ├─── score > 5 ───────────────────────────────────┐
         │                                                  │ score ≤ 5
         │                                         [6] garmin_rt · Python (TTL 24ч)
         │                                             Body Battery, Training Readiness,
         │                                             Training Status → доп. контекст
         │                                                  │
         └──────────────────────┬───────────────────────────┘
                                ▼
                       [7] plan_agent · Sonnet 4.6
                           адаптирует Garmin-план под readiness
                           тип / зоны / длительность / предостережения
                           (при readiness=rest — без LLM-вызова)
                                │
                                ▼
                       [8] hydration_agent · Python
                           rule-based расписание по типу и длительности
                                │
                                ▼
                       [9] synthesis_agent · Sonnet 4.6
                           → Telegram: брифинг 250-400 слов
                           → сохраняет analyses/YYYY-MM-DD.json

─────────────── раз в неделю, воскресенье ───────────────
                       [10] memory_agent · Sonnet 4.6
                            читает recommendation_log + wellness_cache за 7 дней
                            → перезаписывает секции ATHLETE_MEMORY.md
```

---

## Архитектура памяти (3 слоя)

### Слой 1 — SQLite `coach.db`

```sql
CREATE TABLE wellness_cache (
    date        TEXT PRIMARY KEY,
    ctl         REAL,
    atl         REAL,
    form        REAL,          -- вычисляется как ctl - atl
    hrv         REAL,
    resting_hr  INTEGER,
    sleep_score REAL,
    synced_at   TEXT
);

CREATE TABLE activity_cache (
    id               TEXT PRIMARY KEY,
    date             TEXT,
    name             TEXT,
    distance_m       REAL,
    duration_s       INTEGER,
    avg_hr           REAL,
    training_load    REAL,
    adjusted_load    REAL,     -- с terrain multiplier, заполняет metrics_fn
    avg_pace_s       REAL,
    elevation_gain_m REAL,
    surface          TEXT,
    rpe              INTEGER,  -- пишет Telegram-бот после тренировки
    synced_at        TEXT
);

CREATE TABLE garmin_cache (
    date                      TEXT PRIMARY KEY,
    body_battery_morning      INTEGER,
    training_readiness        INTEGER,
    training_status           TEXT,
    coach_workout_description TEXT,
    upcoming_plan_json        TEXT,   -- план Coach на 7 дней, TTL 12ч
    fetched_at                TEXT    -- TTL: plan 12ч / rt 24ч
);

CREATE TABLE strength_log (
    date                     TEXT PRIMARY KEY,
    phase                    TEXT,
    completed                BOOLEAN,
    perceived_difficulty     INTEGER,   -- 1-5
    legs_heaviness_next_day  INTEGER,   -- 1-5
    notes                    TEXT
);

CREATE TABLE recommendation_log (
    date                 TEXT PRIMARY KEY,
    readiness            TEXT,
    readiness_score      REAL,
    recommendation_type  TEXT,
    recommendation_text  TEXT,
    actual_rpe           INTEGER,   -- из Telegram-фидбека
    actual_hr            REAL,
    hrv_next_day         REAL,
    outcome              TEXT       -- читает memory_agent еженедельно
);

CREATE TABLE pipeline_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
    -- ключи: last_sync, mesocycle_start, last_memory_update
);
```

### Слой 2 — JSON сессии `analyses/YYYY-MM-DD.json`

Создаётся автоматически `synthesis_agent.py`. Поля фиксированы:

```json
{
  "date": "2026-05-16",
  "readiness": "normal",
  "readiness_score": 6.5,
  "readiness_reasoning": "HRV чуть ниже baseline, ACWR оптимальный. Умеренный день.",
  "recommendation_type": "easy",
  "recommendation": "Лёгкий бег 50 мин в Z1-Z2, пульс 120-135",
  "hrv_today": 60.0,
  "hrv_rolling_avg": 62.0,
  "hrv_deviation_pct": -3.2,
  "acwr": 1.05,
  "acwr_zone": "optimal",
  "rhr_trend": 0.5,
  "mesocycle_week": 2,
  "context_flags": []
}
```

Схема гибкая — добавляй поля без миграций.

### Слой 3 — `ATHLETE_MEMORY.md`

Обновляется `memory_agent` каждое воскресенье. ~800 токенов.
Читается `coach_agent` вместо сырой истории wellness (экономия ~96% токенов).
При первом запуске создаётся автоматически из шаблона по умолчанию.

Секции: Текущая фаза · HRV профиль · Паттерны восстановления ·
Ответ на нагрузку · Гонки: целевой TSB · Силовые · Последнее обновление.

---

## Правила: возраст и нагрузка

```python
# context_agent.py — флаги на основе относительных метрик (не абсолютных порогов):
#   hrv_deviation < -10%        → hrv_critical_low
#   hrv_deviation < -5%         → hrv_below_baseline
#   hrv_cv_week  > 0.10         → hrv_unstable_week
#   acwr_zone == "high_risk"    → acwr_high_risk   (acwr > 1.5)
#   acwr_zone == "caution"      → acwr_caution     (acwr 1.3–1.5)
#   rhr_trend > 3 bpm за 3 дня → rhr_rising_trend
#   days_since_quality < 2      → quality_too_recent
#   z1z2_ratio < 0.75           → 8020_violation
#   mesocycle_week == 4         → mesocycle_recovery_week

# Жёсткие правила coach_agent.py:
#   days_since_quality < 2      → качество запрещено независимо от readiness
#   acwr_zone == "high_risk"    → readiness не может быть выше "low"

# Правила возраст 58 лет:
#   восстановление 48-72ч после качественной сессии
#   силовые первые 4 нед: DOMS-риск, мониторить legs_heaviness
#   если legs_heaviness >= 4 два раза подряд → снизить силовые
#   перед A/B: силовые отменить за 7 дней
#   перед C: силовые отменить за 5 дней
```

---

## Telegram-бот: форматы сообщений

### Утренний брифинг (генерирует synthesis_agent)

```
⚠️ Умеренная готовность

HRV 60 (baseline 62, -3%). ACWR 1.05 — оптимальный. RHR стабилен.
Восстановление в норме, можно тренироваться по плану.

ТРЕНИРОВКА СЕГОДНЯ: лёгкий бег в Z1-Z2, 50 мин
Garmin Coach: Easy Run 50 min. Пульс 120-135, первые 10 мин разминка Z1,
основная часть Z2, заминка 5 мин Z1. Не ускоряться на подъёмах.

Гидрация: 350мл за 30 мин до бега · 200мл на 15-й мин ·
200мл на 35-й мин · 500мл после

**Сегодня держи пульс строго ниже 140 — следующая качественная сессия в среду.**

После тренировки напиши: rpe 6
```

### Фидбек (принимает telegram_bot)

Атлет пишет plain text в чат:

```
rpe 7
rpe 6 устал больше обычного
отдых
не бежал
```

Бот парсит RPE через regex, сохраняет в `feedback.log` и `recommendation_log`.
Команда `/status` — последние 3 записи из `recommendation_log`.

---

## events.log — формат и теги

Файл редактируется вручную. `context_agent` читает строки за последние 14 дней и проверяет: если сегодняшняя дата упоминается в логе, все флаги этого дня получают префикс `known_event|` — то есть аномалия объяснена и Coach Agent не будет её трактовать как сигнал перегрузки.

### Формат строки

```
YYYY-MM-DD  тег  описание
```

- Поля разделены одним или несколькими пробелами/табами
- Строки, начинающиеся с `#` — комментарии, игнорируются
- Описание свободное, длина не ограничена

### Теги

| Тег | Когда писать |
|---|---|
| `race-a` | Гонка A-приоритет (главная цель сезона) |
| `race-b` | Гонка B-приоритет |
| `race-c` | Гонка C-приоритет |
| `hard-run` | Необычно высокая нагрузка (Load > 90), объясняет ACWR caution/high_risk |
| `camp-start` | Начало тренировочного лагеря |
| `camp-end` | Конец лагеря, ожидается накопленная усталость |
| `no-sleep` | Плохой сон по внешней причине (переезд, перелёт, жара) |
| `illness` | Болезнь или симптомы — объясняет высокий RHR и низкий HRV |
| `travel` | Смена часового пояса, дорога |
| `heat` | Жара > 25°C во время тренировки, объясняет повышенный пульс |
| `rest-day` | Запланированный день отдыха вне Garmin-плана |
| `strength` | Силовая с высоким DOMS-риском, объясняет усталость ног |

### Примеры

```
# YYYY-MM-DD  тег  описание
2026-04-27  camp-start  беговой лагерь начало
2026-05-09  hard-run    Load 101, пик лагеря
2026-05-10  no-sleep    ночной переезд из лагеря
2026-05-23  race-c      23km trail Stirnu Buks
2026-07-18  race-b      50km trail
2026-08-01  race-a      50km UTMB Gauja Trail (главная цель)
```

---

## Структура проекта

```
agentic-garmin-coach/
├── .env                       # INTERVALS_*, ANTHROPIC_*, TELEGRAM_*, GARMIN_*
├── README.md
├── CLAUDE.md                  # инструкции для Claude Code
├── ATHLETE_MEMORY.md          # долгосрочная память (создаётся автоматически)
├── coach.db                   # SQLite (создаётся автоматически через init_db())
├── events.log                 # контекстные события (редактировать вручную)
├── feedback.log               # фидбек после тренировок (пишет Telegram-бот)
├── analyses/                  # JSON по датам (создаётся автоматически)
│
├── tools/
│   ├── show_activities.py     # просмотр последних активностей intervals.icu
│   ├── show_wellness.py       # просмотр wellness-данных с HRV/Form
│   └── analyze_thresholds.py  # расчёт персональных порогов по истории wellness
│
└── agents/
    ├── CLAUDE.md              # детали агентов: граф, State, промпты
    ├── data_agent.py          # ✅ delta-загрузка intervals.icu → SQLite
    ├── metrics.py             # ✅ HRV, ACWR, RHR, terrain, 80/20, мезоцикл
    ├── garmin_agent.py        # ✅ Garmin план (TTL 12ч) + RT (TTL 24ч)
    ├── context_agent.py       # ✅ events.log, feedback.log, флаги
    ├── coach_agent.py         # ✅ Sonnet → readiness JSON
    ├── plan_agent.py          # ✅ Sonnet → рекомендация тренировки
    ├── hydration_agent.py     # ✅ rule-based расписание гидрации
    ├── synthesis_agent.py     # ✅ Sonnet → Telegram-сообщение + analyses/
    ├── telegram_bot.py        # ✅ отправка + polling RPE-фидбека
    ├── memory_agent.py        # ✅ Sonnet → перезапись ATHLETE_MEMORY.md
    └── pipeline.py            # ✅ LangGraph граф + lock + feedback_loop
```

---

## Статус

- [x] Garmin ↔ intervals.icu синхронизация установлена
- [x] `/activities` endpoint проверен (96 активностей)
- [x] `/wellness` endpoint проверен (CTL/ATL/HRV/Sleep)
- [x] `events.log` создан (с 27.04)
- [x] `feedback.log` создан (с 12.05)
- [x] `analyze_thresholds.py`, `show_activities.py`, `show_wellness.py`
- [x] `data_agent.py` — delta-sync + `init_db()`
- [x] `metrics.py` — все вычисления
- [x] `garmin_agent.py` — plan + rt с TTL
- [x] `context_agent.py` — флаги + файловый контекст
- [x] `coach_agent.py` — readiness JSON
- [x] `plan_agent.py` — рекомендация тренировки
- [x] `hydration_agent.py` — расписание гидрации
- [x] `synthesis_agent.py` — Telegram-сообщение
- [x] `telegram_bot.py` — send + polling + RPE
- [x] `memory_agent.py` — еженедельная память
- [x] SQLite схема (`init_db()` в `data_agent.py`)
- [x] `analyses/` — создаётся автоматически `synthesis_agent.py`
- [x] `ATHLETE_MEMORY.md` — создаётся автоматически из шаблона `memory_agent.py`
- [x] `pipeline.py` — LangGraph граф + lock + feedback_loop
- [x] Telegram-бот зарегистрирован (`@dmitrydn_bot`)

---

*Май 2026*
