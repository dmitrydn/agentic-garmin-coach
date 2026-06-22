"""
form_agent.py — Sonnet 4.6, еженедельный анализ беговой формы.

Читает activity_cache за 28 дней, анализирует Running Dynamics:
  EF (Efficiency Factor), каденс, GCT, вертикальные показатели, длину шага.
Сравнивает текущую неделю с 4-недельным средним.
Публикует отдельное сообщение в Telegram.

Запуск standalone:
  uv run agents/form_agent.py          ← анализ + отправка в Telegram
  uv run agents/form_agent.py --dry    ← только печать, без отправки
Из pipeline.py — по воскресеньям после memory_agent.
"""

import asyncio
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from statistics import mean

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── System prompt ─────────────────────────────────────────────────────────────

FORM_SYSTEM = """
Ты тренер по бегу. Пишешь еженедельный отчёт о беговой форме (Running Dynamics) атлету.

АТЛЕТ: мужчина 58 лет, стаж 9 лет, трейловый бег (Sūniši, Рига).
Устройство: Garmin Epix Gen 2. Два датчика ЧСС — HRM-Pro (нагрудный, точнее)
и Coros (натирает на длинных, поэтому атлет использует Coros на длинных
выходах и стартах, HRM-Pro — на остальных тренировках).
Главная цель: UTMB Gauja Trail 90km / 2500м D+ (01.08.2026).
Методология: 80/20 + персональный план (Jason Koop).

ИСТОЧНИК RUNNING DYNAMICS (поле rd_sensor_source у каждой тренировки):
- "chest_strap" — HRM-Pro, точные данные (Ground Contact Balance подтверждает датчик на груди).
- "wrist_estimated" — Coros или без HRM, GCT/VO/VR оценены акселерометром
  часов — менее точно, цифры систематически могут отличаться от chest_strap.
ОБЯЗАТЕЛЬНО: если в сравниваемых периодах (текущая неделя vs предыдущие)
встречаются ОБА источника — явно укажи это и предупреди, что часть изменения
GCT/VO/VR может быть артефактом смены датчика, а не реальной техники.
Если возможно, сравнивай в пределах одного источника (chest_strap к
chest_strap, wrist_estimated к wrist_estimated) и отдельно отметь длинные/
старты на Coros как менее точные по этим трём метрикам конкретно.
Каденс, stride length и EF не зависят от источника RD — сравнивай их как обычно.

ЕДИНИЦЫ И НОРМЫ (для атлетов 55+, трейл):
- EF (Efficiency Factor = watts/HR): рост = улучшение беговой экономики.
  Нормальный диапазон Z1-Z2: 1.2–1.8. Рост +0.05 за 4 нед = хороший сигнал.
- Каденс: значения ~170-185 = steps/min (оба шага). Значения ~85-93 = strides/min (один шаг).
  Оптимум для трейла: 172-180 steps/min или 86-90 strides/min.
- GCT (Ground Contact Time): 220–280 мс норма. Ниже = лучше.
  После VO2max или длинной тренировки GCT растёт на 10-20 мс — это нормально.
- Вертикальные показатели: oscillation хранится в мм (типичные значения 70-120 мм = 7-12 см).
  Vertical Ratio: 7-9% для трейла. Ниже = лучше.
- Stride Length: 0.9-1.2 м для Z1-Z2 трейла.

ВАЖНО — если данных мало:
- Если Running Dynamics (GCT, VO, VR) отсутствуют для большинства тренировок — скажи прямо
  и сосредоточься на EF и каденсе.
- Если менее 2 тренировок с любыми метриками — напиши: "Недостаточно данных для анализа.
  HRM-Pro должен быть одет на каждую тренировку."

СТРУКТУРА ОТЧЁТА (строго):
1. Заголовок: 📊 Беговая форма — [дата недели]
2. Таблица: текущая неделя vs 4-недельное среднее (только метрики с данными)
3. Ключевой тренд (2-3 предложения): что меняется и почему важно
4. **Один главный вывод** (жирным)
5. 1-2 конкретных технических рекомендации (дриллы, упражнения, изменения техники)

ПРИНЦИПЫ:
- Конкретные числа: не "GCT вырос" — а "GCT вырос с 248 до 261 мс (+5%)"
- Без воды: никаких "молодец", "отлично", "продолжайте в том же духе"
- Длина: 200-300 слов
- Формат: обычный текст с эмодзи. Без markdown заголовков (только **жирный** для вывода).
"""


# ── Data collection ───────────────────────────────────────────────────────────

def _avg(values: list) -> float | None:
    clean = [v for v in values if v is not None]
    return round(mean(clean), 2) if clean else None


def _collect_form_data() -> dict:
    """Читает активности за 28 дней с Running Dynamics из activity_cache."""
    today     = date.today().isoformat()
    month_ago = (date.today() - timedelta(days=28)).isoformat()
    week_ago  = (date.today() - timedelta(days=7)).isoformat()

    con = sqlite3.connect("coach.db")
    rows = con.execute("""
        SELECT date, name, distance_m, duration_s, avg_hr, avg_pace_s,
               elevation_gain_m, avg_cadence, avg_gct_ms, avg_vertical_osc_mm,
               avg_vertical_ratio, avg_stride_length_m, efficiency_factor,
               training_load, time_in_z1, time_in_z2, rd_sensor_source
        FROM activity_cache
        WHERE date >= ? AND date <= ?
        ORDER BY date
    """, (month_ago, today)).fetchall()
    con.close()

    activities = []
    for r in rows:
        duration_min = round(r[3] / 60) if r[3] else None
        pace_str = None
        if r[5]:
            m, s = divmod(int(r[5]), 60)
            pace_str = f"{m}:{s:02d}/km"
        activities.append({
            "date":                 r[0],
            "name":                 r[1],
            "distance_km":          round(r[2] / 1000, 1) if r[2] else None,
            "duration_min":         duration_min,
            "avg_hr":               r[4],
            "avg_pace":             pace_str,
            "elevation_gain_m":     round(r[6]) if r[6] else None,
            "avg_cadence":          r[7],
            "avg_gct_ms":           r[8],
            "avg_vertical_osc_mm":  r[9],
            "avg_vertical_ratio":   r[10],
            "avg_stride_length_m":  r[11],
            "efficiency_factor":    round(r[12], 3) if r[12] else None,
            "training_load":        r[13],
            "rd_sensor_source":     r[16],
        })

    current_week  = [a for a in activities if a["date"] >= week_ago]
    prior_3_weeks = [a for a in activities if a["date"] < week_ago]

    # Сводные средние для быстрой проверки покрытия данных
    def _summary(acts: list[dict]) -> dict:
        sources = [a["rd_sensor_source"] for a in acts if a["rd_sensor_source"]]
        return {
            "runs":              len(acts),
            "avg_ef":            _avg([a["efficiency_factor"] for a in acts]),
            "avg_cadence":       _avg([a["avg_cadence"] for a in acts]),
            "avg_gct_ms":        _avg([a["avg_gct_ms"] for a in acts]),
            "avg_vertical_osc":  _avg([a["avg_vertical_osc_mm"] for a in acts]),
            "avg_vertical_ratio": _avg([a["avg_vertical_ratio"] for a in acts]),
            "avg_stride_m":      _avg([a["avg_stride_length_m"] for a in acts]),
            "rd_sensor_mix":     {s: sources.count(s) for s in set(sources)} or "нет данных",
        }

    return {
        "today":              today,
        "week_ago":           week_ago,
        "month_ago":          month_ago,
        "current_week":       current_week,
        "current_week_avg":   _summary(current_week),
        "prior_3_weeks":      prior_3_weeks,
        "prior_3_weeks_avg":  _summary(prior_3_weeks),
    }


# ── LangGraph node ────────────────────────────────────────────────────────────

def form_agent_fn(state: dict | None = None) -> dict:
    """
    Sonnet 4.6. Анализирует Running Dynamics за 28 дней.
    Возвращает {"form_report": str}.
    Можно вызывать standalone или из pipeline.py по воскресеньям.
    """
    data = _collect_form_data()

    total_runs = len(data["current_week"]) + len(data["prior_3_weeks"])
    if total_runs == 0:
        msg = "📊 Беговая форма — нет данных за последние 28 дней."
        print("[form_agent] нет активностей")
        return {"form_report": msg}

    user_content = f"""
Дата анализа: {data['today']}

Сводные средние:
Текущая неделя ({data['week_ago']} → {data['today']}):
{json.dumps(data['current_week_avg'], ensure_ascii=False, indent=2)}

Предыдущие 3 недели ({data['month_ago']} → {data['week_ago']}):
{json.dumps(data['prior_3_weeks_avg'], ensure_ascii=False, indent=2)}

Детальные тренировки текущей недели:
{json.dumps(data['current_week'], ensure_ascii=False, indent=2)}

Детальные тренировки предыдущих 3 недель (для контекста):
{json.dumps(data['prior_3_weeks'], ensure_ascii=False, indent=2)}

Напиши еженедельный отчёт о беговой форме по структуре из system prompt.
""".strip()

    print("[form_agent] запрос к Sonnet 4.6...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=FORM_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    report = response.content[0].text.strip()

    print(f"[form_agent] отчёт готов, {len(report)} символов")
    return {"form_report": report}


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from telegram_bot import send_message

    dry = "--dry" in sys.argv

    result = form_agent_fn()
    report = result["form_report"]

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    if dry:
        print("\n[form_agent] DRY RUN — сообщение не отправляется")
    else:
        print("\n[form_agent] отправка в Telegram...")
        asyncio.run(send_message(report))
        print("[form_agent] отправлено")
