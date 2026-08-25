# План реабилитации ахилла → возврат к бегу — 2026 (v3)

> **Методология**: Achilles tendinopathy rehab / return-to-run (изометрия → HSR → прогрессия бега)
> **v3 — полная пересборка**: 2026-07-29. Гонка Gauja 90k (01.08) **ОТМЕНЕНА (DNS)** — см. §1.
> Старый гоночный план (v2.x, UTMB Gauja) — историческая часть, в силе только этот документ.
> **Использование**: читается `context_agent` (season_plan) и `koop_plan_agent`
> (день-в-день календарь). `plan_agent` адаптирует под readiness.

---

## 1. Почему план пересобран (DNS Gauja 90k)

Два УЗИ правого ахилла с интервалом 2 недели:

- **15.07.2026** — выраженный **активный** тендинит + перитендинит, ретрокалканеальный
  бурсит (жидкость до 5 мм), отёк тела Кагера, неоднородность, выраженная
  неоваскуляризация; разрывов/кальцинатов нет.
- **29.07.2026 (контроль)** — утолщение до 9 мм (на снимке до 10.8 мм),
  неоваскуляризация **сохраняется**, бурса 5 мм «как прежде». Вердикт рентгенолога:
  **без существенных изменений**. Сценарий C — ноль динамики за 2 недели покоя.

Интратендинозные неососуды = стадия 2 (dysrepair), не быстрая реактивная фаза.
Тендон, который не затихает даже в покое, не вынес бы 90 км / 2500 м D+ — реальный
риск был частичный/полный разрыв на дистанции. **Решение атлета 29.07: DNS.**

Доказанная причина травмы — повторные **спайки вертикали** на неадаптированном
возрастном тендоне (см. events.log analysis 13.07, [[achilles-injury-first-cause]]).
Любая вертикаль бегом — под жёстким контролем.

---

## 2. Цели

| Цель | Что | Условие |
|---|---|---|
| **Максимум** | 12.09.2026 — Stirnu Buks Lūsis ~30 км / D+600 м | Условная: только если переносимость заслужена к началу сентября (2 ч плоско + дозированная вертикаль с чистым утром). Rehab-mode: powerhike подъёмы, спуски контролируемо, финиш > время |
| **Минимум** | Вернуться в строй: длинные до 2 ч / D+100 м без флэра | Базовый спинной хребет плана. Достигается вне зависимости от 12.09 |

**Главный критерий прогрессии — реакция ахилла на СЛЕДУЮЩЕЕ УТРО (правило 24 ч),
а не УЗИ.** УЗИ опционально. Если утро после нагрузки не хуже (скованность ≤2/10,
уходит за минуты, подъём на носок безболезнен, нет хромоты) — нагрузку можно
удерживать/наращивать. Хуже — откат на шаг назад.

---

## 3. Макроструктура (29.07 → 12.09, ~6.5 недель)

| Блок | Даты | Суть |
|---|---|---|
| **rehab** | 29.07 – 03.08 | Разгрузка + изометрия + лёгкие плоские Z1 по утреннему гейту, вело/бассейн |
| **montenegro** | 04.08 – 18.08 | Отпуск. Хайкинг с сыном (медленно вверх/вниз, палки), бег ТОЛЬКО плоско |
| **rebuild1** | 19.08 – 24.08 | Возврат бегового объёма, старт HSR в зале, первый плоский длинный (80 мин) |
| **rebuild2** | 25.08 – 31.08 | Рост объёма, первое лёгкое качество, длинный 110 мин с дозированной вертикалью D+≤100 |
| **sharpen** | 01.09 – 11.09 | Осторожная трейл-специфика (race-sim до 2 ч), мини-тейпер к старту |
| **race** | 12.09 | Stirnu Buks — старт, если пройдены гейты |

---

## 4. Guardrails Черногория (04.08–18.08) — критично

Это недели 1–3 реабилитации на стадии-2 тендоне, и горы = вертикаль = **триггер травмы**.

- **Хайкинг** с сыном — можно: медленно вверх (powerhike, палки), **вниз только пешком**.
  Бегом по горам — НЕ бегать (быстрый/крутой спуск = эксцентрика+компрессия = флэр).
- **Бег — только плоское** (набережная/ровное), Z1, короткое, гейт по утру.
- Изометрия икры продолжается через день (5×45 с, ровный пол, пятка не ниже уровня).
- Гидратация в жару, натрий.

Нарушение guardrails по спускам — самый вероятный способ убить цель 12.09.

---

## 5. Силовая / реабилитация тендона

Ахилл-безопасный протокол, деталь → `plans/achilles_protocol_2026-07-09.md`.
**Убрано (противопоказано при инсерции/бурсите): глубокий присед, эксцентрика икры
со свесом пятки, step-down** — грузят прикрепление через дорсифлексию/компрессию.

| Фаза | Что |
|---|---|
| rehab / montenegro | Изометрия икры 5×45 с (2-нога, ровный пол), RDL, hip thrust, кор |
| rebuild1–2 | **HSR** (heavy slow resistance): подъём на носки тяжело-медленно 3–4×6–10, ровный пол, полный контроль без свеса пятки; RDL, hip thrust, кор. Прогрессия веса при чистом ахилле |
| sharpen | HSR облегчённо, последняя силовая ~05.09, дальше стоп до старта |

---

## 6. Ключевые пороги

| Маркер | Порог | Действие |
|---|---|---|
| Утро ахилла после нагрузки | ≤2/10, уходит за минуты | GO на удержание/рост |
| Утро ахилла | хуже вчерашнего / хромота / боль на подъёме на носок | Откат: бег отменить, вело/изометрия, гейт назавтра |
| Вертикаль бегом | спуски = эксцентрика | Только пешком/powerhike до sharpen; в race-sim — контролируемо |
| ACWR | >1.3 снижать объём | См. `metrics.py` |
| HRV отклонение | <−10% | Только Z1/off |

---

## 7. Машиночитаемая конфигурация

```yaml
a_race:
  name: Stirnu Buks Lūsis
  date: 2026-09-12
  distance_km: 30
  elevation_gain_m: 600
  priority: A
  status: firm
  note: FIRM GO (решение атлета 25.08.2026). Rehab-mode; дневные сессии под утренним ахилл-гейтом.

# Gauja 90k (2026-08-01) отменена 29.07 — DNS, см. §1 и events.log (тег dns).
# b_race намеренно отсутствует.

current_block: rebuild2

block_schedule:
  rehab:      {start: "2026-07-29", end: "2026-08-03"}
  montenegro: {start: "2026-08-04", end: "2026-08-18"}
  rebuild1:   {start: "2026-08-19", end: "2026-08-24"}
  rebuild2:   {start: "2026-08-25", end: "2026-08-31"}
  sharpen:    {start: "2026-09-01", end: "2026-09-11"}
  a_race:     {date: "2026-09-12"}

weekly_targets:
  rehab:      {target_minutes: 150, target_tss: 80,  target_vert_m: 20}
  montenegro: {target_minutes: 200, target_tss: 110, target_vert_m: 100}
  rebuild1:   {target_minutes: 245, target_tss: 170, target_vert_m: 60}
  rebuild2:   {target_minutes: 270, target_tss: 200, target_vert_m: 480}
  sharpen:    {target_minutes: 205, target_tss: 150, target_vert_m: 220}

# weekly_templates: ключ блока -> день недели (mon..sun) -> прескрипция дня.
# Используется koop_plan_agent.py для блоков rehab/montenegro/rebuild1/rebuild2/sharpen.
weekly_templates:
  rehab:
    mon: {type: rest,     duration_min: 0,  zones: [],          terrain: "-",    description: "Покой. Изометрия икры 3-4×45с (ровный пол, пятка не ниже уровня, без дорсифлексии)."}
    tue: {type: easy,     duration_min: 30, zones: ["Z1"],      terrain: "flat", description: "30 мин Z1 плоско, D+≤15м — ТОЛЬКО если утро ахилла чистое (≤2/10, уходит за минуты). Хуже → ходьба/вело. Вердикт по след. утру."}
    wed: {type: easy,     duration_min: 25, zones: ["Z1"],      terrain: "flat", description: "25 мин Z1 плоско, D+≤15м, гейт по утру. Иначе изометрия + прогулка."}
    thu: {type: easy,     duration_min: 45, zones: ["Z2"],      terrain: "bike", description: "ВЕЛО или бассейн 45 мин Z2 — аэробная база без нагрузки на тендон (НЕ бег). + изометрия 3×45с."}
    fri: {type: strength, duration_min: 35, zones: [],          terrain: "gym",  description: "Rehab-зал (Achilles-safe): изометрия икры 5×45с (2-нога, ровный пол), RDL 3×8, hip thrust 3×10, кор. БЕЗ глубокого приседа/эксцентрики икры/step-down."}
    sat: {type: easy,     duration_min: 30, zones: ["Z1"],      terrain: "flat", description: "30 мин Z1 плоско, D+≤15м, гейт по утру. + изометрия."}
    sun: {type: easy,     duration_min: 50, zones: ["Z2"],      terrain: "bike", description: "ВЕЛО/бассейн 50 мин Z2 (НЕ бег). Держим аэробку, разгружаем ахилл."}

  montenegro:
    mon: {type: easy,     duration_min: 60, zones: ["Z1"],      terrain: "hike", description: "Поход с сыном: медленно вверх (powerhike, палки), спуски ПЕШКОМ. Бегом по горам — НЕ бегать."}
    tue: {type: easy,     duration_min: 35, zones: ["Z1"],      terrain: "flat", description: "35 мин Z1 бег ТОЛЬКО плоско (набережная/ровное), D+≤20м, гейт по утру. Никакого бега по рельефу."}
    wed: {type: easy,     duration_min: 90, zones: ["Z1"],      terrain: "hike", description: "Поход, медленно, палки. Time on feet ок, но вниз только пешком (эксцентрика бегом = триггер). Гидратация."}
    thu: {type: easy,     duration_min: 35, zones: ["Z1"],      terrain: "flat", description: "35 мин Z1 бег плоско, D+≤20м, гейт по утру."}
    fri: {type: strength, duration_min: 25, zones: [],          terrain: "gym",  description: "Изометрия икры 5×45с + hip thrust/кор (bodyweight, в отпуске). Ахилл-безопасно."}
    sat: {type: easy,     duration_min: 40, zones: ["Z1","Z2"], terrain: "flat", description: "40 мин Z1-Z2 бег плоско, D+≤20м, гейт по утру. Или поход, если бег не хочется."}
    sun: {type: rest,     duration_min: 0,  zones: [],          terrain: "-",    description: "Покой или лёгкая прогулка. Изометрия."}

  rebuild1:
    mon: {type: rest,     duration_min: 0,  zones: [],          terrain: "-",    description: "Покой. Изометрия/HSR-разгрузка."}
    tue: {type: easy,     duration_min: 50, zones: ["Z2"],      terrain: "flat", description: "50 мин Z2 плоско, D+≤30м. Возврат к беговому объёму, гейт по утру."}
    wed: {type: easy,     duration_min: 40, zones: ["Z1"],      terrain: "flat", description: "40 мин Z1 плоско + 4×20с strides по ровному в конце, D+≤30м."}
    thu: {type: easy,     duration_min: 45, zones: ["Z1"],      terrain: "flat", description: "45 мин Z1 плоско, D+≤30м, восстановительный."}
    fri: {type: strength, duration_min: 40, zones: [],          terrain: "gym",  description: "HSR-фаза: тяжёлый медленный подъём на носки 3×8-10 (ровный пол, полный контроль, БЕЗ провала пятки/step-down), RDL 3×8, hip thrust 3×10, кор. Прогрессия веса при чистом ахилле."}
    sat: {type: long,     duration_min: 80, zones: ["Z2"],      terrain: "flat", description: "Длинный 80 мин Z2 ПЛОСКО, D+≤50м. Первый возврат к длинному — плоско, гейт по утру, bail-able."}
    sun: {type: easy,     duration_min: 45, zones: ["Z1","Z2"], terrain: "bike", description: "45 мин лёгкий бег плоско ИЛИ вело, по самочувствию после длинного."}

  rebuild2:
    mon: {type: rest,     duration_min: 0,   zones: [],          terrain: "-",       description: "Покой. Изометрия/HSR-разгрузка."}
    tue: {type: easy,     duration_min: 55,  zones: ["Z2"],      terrain: "flat",    description: "55 мин Z2 плоско, D+≤30м."}
    wed: {type: quality,  duration_min: 50,  zones: ["Z2","Z3"], terrain: "flat",    description: "Первое лёгкое качество: 15 WU → 4×3 мин Z3 (2 мин Z1 между) → CD, ПЛОСКО, D+≤30м. Первой под нож если ахилл шумит."}
    thu: {type: easy,     duration_min: 50,  zones: ["Z1"],      terrain: "flat",    description: "50 мин Z1 плоско, D+≤30м."}
    fri: {type: strength, duration_min: 40,  zones: [],          terrain: "gym",     description: "HSR прогрессия: подъём на носки 4×6-8 тяжело-медленно, RDL 3×8, hip thrust, кор."}
    sat: {type: long,     duration_min: 110, zones: ["Z1","Z2"], terrain: "rolling", description: "Длинный 110 мин Z1-Z2, D+≤100м — ПЕРВАЯ дозированная вертикаль. Подъёмы powerhike, спуски контролируемо/пешком. Гейт по утру, bail-able. Тест переносимости вертикали."}
    sun: {type: easy,     duration_min: 50,  zones: ["Z1"],      terrain: "flat",    description: "50 мин Z1 плоско или вело, восстановление."}

  sharpen:
    mon: {type: rest,     duration_min: 0,   zones: [],          terrain: "-",     description: "Покой. HSR-разгрузка."}
    tue: {type: easy,     duration_min: 50,  zones: ["Z2"],      terrain: "flat",  description: "50 мин Z2 плоско + 4×20с strides, D+≤30м."}
    wed: {type: quality,  duration_min: 55,  zones: ["Z2","Z3"], terrain: "flat",  description: "15 WU → 5×3 мин Z3 (2 мин Z1) → CD, ПЛОСКО, D+≤30м."}
    thu: {type: easy,     duration_min: 45,  zones: ["Z1"],      terrain: "flat",  description: "45 мин Z1 плоско, D+≤30м."}
    fri: {type: strength, duration_min: 35,  zones: [],          terrain: "gym",   description: "Последняя силовая цикла (~05.09): HSR облегчённо, hip thrust, кор. После — силовая стоп до старта."}
    sat: {type: long,     duration_min: 120, zones: ["Z1","Z2"], terrain: "trail", description: "Ключевая race-sim: 120 мин на трейле, D+ до 300-400м, ГЕЙТ ЖЁСТКО по ахиллу. Все подъёмы powerhike, спуски контролируемо. Rehab-mode репетиция 12.09. Любое утро хуже/боль на спуске → срезать/отменить."}
    sun: {type: easy,     duration_min: 45,  zones: ["Z1"],      terrain: "flat",  description: "45 мин Z1 плоско, восстановление после трейла."}

# daily_overrides (в ключе taper_days — koop_plan читает его раньше блочных шаблонов):
# финальные 18 дней 26.08→11.09 закодированы по датам (решённый план; человекочит. версия — plans/lusis1_final18_2026-08-25.md).
taper_days:
  # --- Неделя 1 (26.08–31.08): специфика + единственная race-sim на боевой трассе ---
  "2026-08-26": {type: strength, duration_min: 55, zones: [], terrain: "gym", description: "Силовая (единственная в неделю): HSR подъём на носки 4×6-8 тяжело-медленно (ровный пол, БЕЗ провала пятки/step-down), RDL 3×8, hip thrust 3×10, кор."}
  "2026-08-27": {type: quality, duration_min: 50, zones: ["Z2","Z3"], terrain: "flat", description: "Единственное качество блока: 15 WU → 4×3 мин Z3 (2 мин Z1 между) → CD, ПЛОСКО, D+≤30м. Первой под нож если утро ахилла шумит."}
  "2026-08-28": {type: rest, duration_min: 0, zones: [], terrain: "-", description: "Полный отдых (день отдыха недели). Опц. прогулка 15-20 мин. Свежесть перед субботней трассой."}
  "2026-08-29": {type: long, duration_min: 120, zones: ["Z1","Z2"], terrain: "trail", description: "КЛЮЧЕВАЯ race-sim НА БОЕВОЙ ТРАССЕ Lūsis (разведка + тест ахилла): 1:45-2:00, гоночные кроссовки, D+ до гоночного уровня. Powerhike ВСЕ подъёмы, первые спуски контролируемо (НЕ бомбить). Питание ~65 г/ч. Bail-able — не обязан весь круг. ЖЁСТКИЙ ГЕЙТ; после — 72ч без вертикали."}
  "2026-08-30": {type: rest, duration_min: 0, zones: [], terrain: "-", description: "Отдых или ходьба 20-30 мин. Первая точка гейта по трассе (утро)."}
  "2026-08-31": {type: easy, duration_min: 40, zones: ["Z1"], terrain: "flat", description: "40 мин Z1 ПЛОСКО, D+≤20м — только если утро ахилла чистое (ещё в 72ч окне после трассы → держать плоско). Хуже → отдых/вело."}
  # --- Неделя 2 (01.09–08.09): ранний тейпер, острота, длинного больше нет ---
  "2026-09-01": {type: easy, duration_min: 40, zones: ["Z1","Z2"], terrain: "flat", description: "40 мин Z1-Z2 плоско + 4×20с strides, D+≤20м, или отдых по самочувствию. Окно реакции на трассу закрывается — гейт."}
  "2026-09-02": {type: strength, duration_min: 45, zones: [], terrain: "gym", description: "Силовая (поддерживающая, легче): HSR облегчённо 3×8, RDL, hip thrust, кор. Ахилл-ограничения те же."}
  "2026-09-03": {type: easy, duration_min: 45, zones: ["Z2"], terrain: "flat", description: "45 мин Z2 плоско + 6×20с strides, D+≤30м."}
  "2026-09-04": {type: easy, duration_min: 60, zones: ["Z2"], terrain: "flat", description: "60 мин Z2 плоско, внутри 10 мин на ГОНОЧНОМ усилии (контроль, не жёстко), D+≤30м. Единственное касание гоночного темпа."}
  "2026-09-05": {type: rest, duration_min: 0, zones: [], terrain: "-", description: "Полный отдых (день отдыха недели). Изометрия лёгкая опц."}
  "2026-09-06": {type: long, duration_min: 75, zones: ["Z1","Z2"], terrain: "rolling", description: "Средне-длинный 70-75 мин Z2, ~200м пологого D+ (спуски бегом ЛЕГКО), D+≤200м. ПОСЛЕДНИЙ бег дольше часа. Гейт по утру. НЕ вторая race-sim."}
  "2026-09-07": {type: easy, duration_min: 30, zones: ["Z1"], terrain: "flat", description: "30 мин Z1 плоско, D+≤15м, или полный отдых по ногам."}
  "2026-09-08": {type: easy, duration_min: 40, zones: ["Z1"], terrain: "flat", description: "40 мин Z1 плоско + 4×20с strides, D+≤15м."}
  # --- Неделя 3 (09.09–11.09): пик тейпера ---
  "2026-09-09": {type: easy, duration_min: 33, zones: ["Z1","Z2"], terrain: "flat", description: "33 мин Z1-Z2 плоско + 3×20с strides, D+≤15м."}
  "2026-09-10": {type: rest, duration_min: 0, zones: [], terrain: "-", description: "Полный отдых или расбег 20 мин. Ноги свежими."}
  "2026-09-11": {type: easy, duration_min: 22, zones: ["Z1"], terrain: "flat", description: "Предгоночный праймер: 22 мин легко + 3×20с ускорения, D+≤15м. Гейт-чек, подготовка снаряжения/палок."}

race_day:
  "2026-09-12": {type: race, duration_min: null, zones: ["Z1","Z2"], terrain: "Stirnu Buks Lūsis", description: "СТАРТ Stirnu Buks Lūsis ~30км / D+600м. FIRM GO. REHAB-MODE: powerhike ВСЕ подъёмы, спуски контролируемо (не разгоняться — эксцентрика грузит ахилл), финиш важнее времени. Гидратация + натрий. Если утро ахилла с болью/хромотой — пересмотр в день старта."}

peak_weekly_vert_m: 480
peak_long_run_h: 2.0
taper_start_final: 2026-09-01

training_zones: garmin-5zone
methodology: achilles-tendinopathy-rehab-return-to-run
```

---

*Plan v3 authored: 2026-07-29 · Achilles rehab → return-to-run · заменяет гоночный план UTMB Gauja (DNS).*
*Обновлять при: смене блока, флэре/регрессе ахилла, решении по старту 12.09, смене целей.*
