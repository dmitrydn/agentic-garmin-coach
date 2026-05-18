"""
tools/analyze_thresholds.py

Анализирует историческую wellness-статистику из intervals.icu
и предлагает персонализированные пороги аномалий для ANOMALY_THRESHOLDS.

Запуск: uv run tools/analyze_thresholds.py
"""

import os
import asyncio
import httpx
import statistics
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID")
API_KEY    = os.getenv("INTERVALS_API_KEY")
AUTH       = ("API_KEY", API_KEY)
BASE_URL   = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}"


# ── Загрузка данных ───────────────────────────────────────────────────────────

async def fetch_all_wellness() -> list[dict]:
    """Загружает всю wellness-историю из intervals.icu (с 2021)."""
    oldest = "2021-01-01"
    newest = datetime.now().strftime("%Y-%m-%d")

    url = f"{BASE_URL}/wellness"
    params = {"oldest": oldest, "newest": newest}

    async with httpx.AsyncClient(auth=AUTH, timeout=30) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    print(f"Загружено wellness-записей: {len(data)} ({oldest} → {newest})\n")
    return data


# ── Статистика ────────────────────────────────────────────────────────────────

def extract_metric(data: list[dict], field: str) -> list[float]:
    """Извлекает непустые значения метрики из wellness-данных."""
    values = []
    for d in data:
        v = d.get(field)
        if v is not None and v > 0:
            values.append(float(v))
    return values


def percentile(data: list[float], p: float) -> float:
    """Вычисляет p-й перцентиль."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(sorted_data) - 1)
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def stats(values: list[float]) -> dict:
    if len(values) < 5:
        return {}
    return {
        "n":       len(values),
        "mean":    statistics.mean(values),
        "median":  statistics.median(values),
        "std":     statistics.stdev(values),
        "min":     min(values),
        "max":     max(values),
        "p5":      percentile(values, 5),
        "p10":     percentile(values, 10),
        "p15":     percentile(values, 15),
        "p25":     percentile(values, 25),
        "p75":     percentile(values, 75),
        "p85":     percentile(values, 85),
        "p90":     percentile(values, 90),
        "p95":     percentile(values, 95),
    }


# ── Гистограмма (текстовая) ───────────────────────────────────────────────────

def histogram(values: list[float], bins: int = 10, width: int = 40) -> str:
    if not values:
        return "нет данных"
    lo, hi = min(values), max(values)
    if lo == hi:
        return "все значения одинаковые"
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        i = min(int((v - lo) / step), bins - 1)
        counts[i] += 1
    max_count = max(counts)
    lines = []
    for i, c in enumerate(counts):
        left  = lo + i * step
        bar   = "█" * int(c / max_count * width)
        lines.append(f"  {left:6.1f} │{bar:<{width}} {c}")
    return "\n".join(lines)


# ── Анализ и предложения ──────────────────────────────────────────────────────

def analyze_metric(
    name: str,
    values: list[float],
    direction: str,          # "low_bad" или "high_bad"
    current_threshold: float,
    field_label: str,
    unit: str = "",
) -> dict:
    """
    direction="low_bad"  → аномалия когда значение НИЖЕ порога (HRV, Sleep, Form)
    direction="high_bad" → аномалия когда значение ВЫШЕ порога (RHR, ATL)
    """
    s = stats(values)
    if not s:
        print(f"⚠ {name}: недостаточно данных\n")
        return {}

    # Предложение порога
    if direction == "low_bad":
        proposed = round(s["p10"], 1)      # 10-й перцентиль
        mean_1sd = round(s["mean"] - 1.5 * s["std"], 1)
        alt_label = "mean - 1.5σ"
    else:
        proposed = round(s["p90"], 1)      # 90-й перцентиль
        mean_1sd = round(s["mean"] + 1.5 * s["std"], 1)
        alt_label = "mean + 1.5σ"

    # Сколько дней попадает под текущий и предложенный порог
    if direction == "low_bad":
        current_flagged  = sum(1 for v in values if v < current_threshold)
        proposed_flagged = sum(1 for v in values if v < proposed)
    else:
        current_flagged  = sum(1 for v in values if v > current_threshold)
        proposed_flagged = sum(1 for v in values if v > proposed)

    current_pct  = current_flagged  / len(values) * 100
    proposed_pct = proposed_flagged / len(values) * 100

    print(f"{'─'*60}")
    print(f"📊 {name.upper()}  ({field_label})")
    print(f"{'─'*60}")
    print(f"  Записей с данными: {s['n']}")
    print(f"  Среднее:   {s['mean']:.1f}{unit}  |  Медиана: {s['median']:.1f}{unit}")
    print(f"  Std:       {s['std']:.1f}{unit}")
    print(f"  Диапазон:  {s['min']:.1f} – {s['max']:.1f}{unit}")
    print()
    print(f"  Перцентили:")
    print(f"    5%={s['p5']:.1f}  10%={s['p10']:.1f}  25%={s['p25']:.1f}  "
          f"75%={s['p75']:.1f}  90%={s['p90']:.1f}  95%={s['p95']:.1f}")
    print()
    print(f"  Текущий порог:    {current_threshold}{unit}")
    print(f"    → флагирует {current_flagged} дней ({current_pct:.1f}%)")
    print()
    print(f"  Предложенный (p10/p90): {proposed}{unit}")
    print(f"    → флагирует {proposed_flagged} дней ({proposed_pct:.1f}%)")
    print(f"  Альтернативный ({alt_label}): {mean_1sd}{unit}")
    print()
    print(f"  Гистограмма:")
    print(histogram(values))
    print()

    return {
        "metric": name,
        "direction": direction,
        "n": s["n"],
        "mean": round(s["mean"], 1),
        "median": round(s["median"], 1),
        "std": round(s["std"], 1),
        "p10": round(s["p10"], 1),
        "p90": round(s["p90"], 1),
        "current_threshold": current_threshold,
        "proposed_threshold": proposed,
        "alt_threshold": mean_1sd,
        "current_flag_pct": round(current_pct, 1),
        "proposed_flag_pct": round(proposed_pct, 1),
    }


def print_baseline_hrv(values: list[float], recent_days: int = 90):
    """
    Отдельный анализ HRV: личная baseline и rolling window.
    Для атлетов с HRM-Pro baseline критична.
    """
    if not values:
        return

    all_stats = stats(values)
    recent = values[-recent_days:] if len(values) >= recent_days else values
    recent_stats = stats(recent)

    print(f"{'─'*60}")
    print(f"💜 HRV — ДЕТАЛЬНЫЙ АНАЛИЗ (важно для возраста 58)")
    print(f"{'─'*60}")
    print(f"  Вся история:    mean={all_stats['mean']:.1f}  "
          f"median={all_stats['median']:.1f}  std={all_stats['std']:.1f}")
    print(f"  Последние {recent_days}д:  mean={recent_stats['mean']:.1f}  "
          f"median={recent_stats['median']:.1f}  std={recent_stats['std']:.1f}")
    print()
    print(f"  Рекомендуемые правила для Coach Agent:")
    hrv_baseline = round(recent_stats["median"], 1)
    hrv_low      = round(recent_stats["p15"], 1)
    hrv_critical = round(recent_stats["p5"], 1)
    print(f"    Baseline (медиана 90д):  {hrv_baseline}")
    print(f"    Пониженный (p15):        {hrv_low}  → лёгкая тренировка")
    print(f"    Критический (p5):        {hrv_critical}  → отдых / перепроверить")
    print(f"    Выше baseline +10%:      {round(hrv_baseline * 1.1, 1)}  → можно интенсивнее")
    print()


def print_summary(results: list[dict]):
    print(f"{'='*60}")
    print("✅ ИТОГ — обновлённый ANOMALY_THRESHOLDS")
    print(f"{'='*60}")
    print()
    print("ANOMALY_THRESHOLDS = {")
    for r in results:
        if not r:
            continue
        comment = (
            f"# p10 вашей истории, флагирует {r['proposed_flag_pct']}% дней"
            if r["direction"] == "low_bad"
            else f"# p90 вашей истории, флагирует {r['proposed_flag_pct']}% дней"
        )
        print(f'    "{r["metric"]}": {r["proposed_threshold"]},  {comment}')
    print("}")
    print()
    print("# Целевой диапазон флагирования: 5–15% дней.")
    print("# Если слишком много ложных тревог — увеличь порог на 5-10%.")
    print("# Если агент пропускает реальные проблемы — уменьши.")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("АНАЛИЗ ПЕРСОНАЛЬНЫХ ПОРОГОВ АНОМАЛИЙ")
    print("intervals.icu → статистика → ANOMALY_THRESHOLDS")
    print("=" * 60)
    print()

    data = await fetch_all_wellness()

    # Текущие generic пороги
    CURRENT = {
        "sleep_score": 40,
        "hrv":         25,
        "resting_hr":  65,
        "atl":         80,
        "form":       -25,
    }

    # Извлечь метрики
    sleep_vals = extract_metric(data, "sleepScore")
    hrv_vals   = extract_metric(data, "hrv")
    rhr_vals   = extract_metric(data, "restingHR")
    atl_vals   = extract_metric(data, "atl")

    # Form = CTL - ATL
    form_vals = []
    for d in data:
        ctl = d.get("ctl")
        atl = d.get("atl")
        if ctl and atl and ctl > 0 and atl > 0:
            form_vals.append(round(ctl - atl, 1))

    results = []

    results.append(analyze_metric(
        name="sleep_score",
        values=sleep_vals,
        direction="low_bad",
        current_threshold=CURRENT["sleep_score"],
        field_label="sleepScore из intervals.icu",
        unit="",
    ))

    results.append(analyze_metric(
        name="hrv",
        values=hrv_vals,
        direction="low_bad",
        current_threshold=CURRENT["hrv"],
        field_label="hrv из intervals.icu (HRM-Pro)",
        unit="",
    ))

    print_baseline_hrv(hrv_vals, recent_days=90)

    results.append(analyze_metric(
        name="resting_hr",
        values=rhr_vals,
        direction="high_bad",
        current_threshold=CURRENT["resting_hr"],
        field_label="restingHR из intervals.icu",
        unit=" bpm",
    ))

    results.append(analyze_metric(
        name="atl",
        values=atl_vals,
        direction="high_bad",
        current_threshold=CURRENT["atl"],
        field_label="atl из intervals.icu",
        unit="",
    ))

    results.append(analyze_metric(
        name="form",
        values=form_vals,
        direction="low_bad",
        current_threshold=CURRENT["form"],
        field_label="form = CTL - ATL (вычисляется)",
        unit="",
    ))

    print_summary(results)

    # Дополнительно: посчитать сколько wellness-записей без данных
    print(f"{'─'*60}")
    print("📋 ПОКРЫТИЕ ДАННЫХ")
    print(f"{'─'*60}")
    total = len(data)
    print(f"  Всего wellness-дней: {total}")
    print(f"  Sleep score:  {len(sleep_vals)} ({len(sleep_vals)/total*100:.0f}%)")
    print(f"  HRV:          {len(hrv_vals)} ({len(hrv_vals)/total*100:.0f}%)")
    print(f"  Resting HR:   {len(rhr_vals)} ({len(rhr_vals)/total*100:.0f}%)")
    print(f"  ATL:          {len(atl_vals)} ({len(atl_vals)/total*100:.0f}%)")
    print(f"  Form:         {len(form_vals)} ({len(form_vals)/total*100:.0f}%)")
    print()
    if len(hrv_vals) / total < 0.5:
        print("  ⚠ HRV покрывает менее 50% дней — пороги HRV менее надёжны.")
        print("    HRM-Pro начал собирать данные позже чем другие метрики.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
