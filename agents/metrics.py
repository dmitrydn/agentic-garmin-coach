"""
metrics.py — все вычисления без LLM. LangGraph node: metrics_fn.

Научные источники:
  HRV rolling mean:   Plews et al. 2013, 2017; HRV4Training метод
  ACWR:               Gabbett 2016 — "The training-injury prevention paradox"
  RHR trend:          Halson 2014 — "Monitoring Training Load to Understand Fatigue"
  Terrain multiplier: Minetti et al. 2002 (cost of locomotion on gradient)
  80/20:              Seiler 2010 — "What is Best Practice for Training Intensity Distribution?"
  Мезоцикл 3+1:       Issurin 2010 — "New Horizons for the Methodology of Block Periodization"
"""

import sqlite3
from datetime import date, timedelta
from statistics import mean, stdev


# ── HRV: 7-дневное скользящее среднее ───────────────────────────────────────

def hrv_analysis(wellness_history: list[dict]) -> dict:
    """
    wellness_history — последние 14 дней из wellness_cache, сортировка по дате ASC.

    Интерпретация deviation (передавать в Coach Agent как контекст):
      > +5%       → высокая готовность
      -5%..+5%    → норма, по плану
      < -5%       → снизить интенсивность
      < -10%      → только восстановительное
      cv > 0.10   → нестабильная неделя, консервативнее
    """
    hrv_values = [
        d["hrv"] for d in wellness_history
        if d.get("hrv") and d["hrv"] > 0
    ]
    if len(hrv_values) < 3:
        return {
            "hrv_today":          None,
            "hrv_rolling_avg":    0.0,
            "hrv_deviation_pct":  0.0,
            "hrv_cv_week":        0.0,
        }

    today_hrv = hrv_values[-1]
    # Rolling avg считается по 7 дням ДО сегодня (Plews et al. 2017).
    # today_hrv не должен входить в собственный baseline — иначе отклонение
    # занижается при низком HRV и завышается при высоком.
    prev_values = hrv_values[:-1]
    last_7      = prev_values[-7:]
    rolling_avg = mean(last_7)
    deviation   = (today_hrv - rolling_avg) / rolling_avg

    cv = stdev(last_7) / mean(last_7) if len(last_7) >= 3 else 0.0

    return {
        "hrv_today":          today_hrv,
        "hrv_rolling_avg":    round(rolling_avg, 1),
        "hrv_deviation_pct":  round(deviation * 100, 1),
        "hrv_cv_week":        round(cv, 3),
    }


# ── ACWR: Acute:Chronic Workload Ratio ───────────────────────────────────────

def calculate_acwr(ctl: float, atl: float) -> dict:
    """
    ATL (7-дневное) / CTL (42-дневное) = нагрузка этой недели / хроническая.

    Зоны:
      < 0.8   → underload (детренинг)
      0.8-1.3 → optimal
      1.3-1.5 → caution (повышенный риск)
      > 1.5   → high_risk (обязательное снижение)
    """
    if not ctl or ctl <= 0:
        return {"acwr": 1.0, "acwr_zone": "unknown"}

    acwr = atl / ctl

    if acwr < 0.8:
        zone = "underload"
    elif acwr <= 1.3:
        zone = "optimal"
    elif acwr <= 1.5:
        zone = "caution"
    else:
        zone = "high_risk"

    return {"acwr": round(acwr, 2), "acwr_zone": zone}


# ── RHR: тренд за 3 дня ──────────────────────────────────────────────────────

def rhr_trend_analysis(wellness_history: list[dict]) -> dict:
    """
    Рост RHR на 3+ bpm за 3 дня = ранний признак перегрузки или болезни.
    Работает даже при нормальных HRV и sleep (Halson 2014).
    """
    rhr_values = [
        d["resting_hr"] for d in wellness_history[-4:]
        if d.get("resting_hr") and d["resting_hr"] > 0
    ]
    if len(rhr_values) < 2:
        return {"rhr_today": None, "rhr_trend": 0.0, "rhr_rising": False}

    today_rhr = rhr_values[-1]
    prev_avg  = mean(rhr_values[:-1])
    trend     = today_rhr - prev_avg

    return {
        "rhr_today":   today_rhr,
        "rhr_3d_avg":  round(prev_avg, 1),
        "rhr_trend":   round(trend, 1),
        "rhr_rising":  trend > 3,
    }


# ── Terrain Load Multiplier ───────────────────────────────────────────────────

def adjusted_training_load(activity: dict) -> float:
    """
    Garmin TSS для бега pace-based. Trail TSS занижен на 15-25%.
    Корректируем на основе elevation_gain.

    Sūniši: умеренный/тяжёлый рельеф до 15м/км набора.
    """
    base_load   = activity.get("training_load") or activity.get("icu_training_load") or 0.0
    distance_km = ((activity.get("distance_m") or activity.get("distance") or 0)) / 1000
    elev_gain   = activity.get("total_elevation_gain") or activity.get("elevation_gain_m") or 0.0

    if distance_km <= 0:
        return float(base_load)

    gain_per_km = elev_gain / distance_km

    if gain_per_km > 15:     # тяжёлый трейл
        multiplier = 1.20
    elif gain_per_km > 8:    # умеренный рельеф
        multiplier = 1.10
    else:                    # плоско
        multiplier = 1.00

    return round(base_load * multiplier, 1)


# ── 80/20 Compliance ─────────────────────────────────────────────────────────

def weekly_zone_ratio(week_activities: list[dict]) -> dict:
    """
    Доля Z1-Z2 от общего объёма недели. Цель: 80%.
    Минимум: 75% (compliant=True).

    intervals.icu отдаёт time_in_z1/z2 при ?fields=... или expand=true.
    Если полей нет — ratio=None, compliant=None.
    """
    z12_sec = sum(
        (a.get("time_in_z1") or 0) + (a.get("time_in_z2") or 0)
        for a in week_activities
    )

    total_sec = sum(
        (a.get("duration_s") or a.get("elapsed_time") or 0)
        for a in week_activities
    )

    if total_sec == 0:
        return {"z1z2_ratio": None, "z1z2_compliant": None, "total_minutes": 0}

    # Если z12_sec == 0 при наличии тренировок — поля time_in_z1/z2 не заполнены.
    # Возвращаем None вместо 0%, чтобы не поднимать ложный флаг 8020_violation.
    if z12_sec == 0:
        return {"z1z2_ratio": None, "z1z2_compliant": None,
                "total_minutes": round(total_sec / 60)}

    ratio = z12_sec / total_sec
    return {
        "z1z2_ratio":     round(ratio, 2),
        "z1z2_pct":       round(ratio * 100, 1),
        "z1z2_compliant": ratio >= 0.75,
        "target_80_20":   ratio >= 0.80,
        "total_minutes":  round(total_sec / 60),
    }


# ── Дней с последней качественной сессии ─────────────────────────────────────

def days_since_last_quality(activities: list[dict]) -> int:
    """
    Минимальный интервал между качественными сессиями для 58 лет: 48ч (2 дня).
    Качество = load > 70 или ключевые слова в названии.
    """
    today = date.today()
    quality = [
        a for a in activities
        if (a.get("training_load") or a.get("icu_training_load") or 0) > 70
        or any(kw in (a.get("name") or "").lower()
               for kw in ("interval", "threshold", "tempo", "качество", "интервал", "темп"))
    ]
    if not quality:
        return 99

    last_date = max(
        date.fromisoformat(
            (a.get("start_date_local") or a.get("date") or "")[:10]
        )
        for a in quality
        if (a.get("start_date_local") or a.get("date") or "")[:10]
    )
    return (today - last_date).days


# ── Мезоцикл 3+1 ─────────────────────────────────────────────────────────────

def mesocycle_week(start_date: str) -> int:
    """
    3 недели нагрузки + 1 восстановление.
    start_date — начало текущего мезоцикла (хранится в pipeline_meta).
    Возвращает 1, 2, 3 (нагрузка) или 4 (восстановление).

    Критично для интерпретации: form=-15 на неделе 3 = накопленная усталость,
    это норма. form=-15 на неделе 1 = сигнал перегрузки.
    """
    days = (date.today() - date.fromisoformat(start_date)).days
    return (days // 7) % 4 + 1


# ── Силовая нагрузка ─────────────────────────────────────────────────────────

STRENGTH_LOAD_ESTIMATE: dict[str, float] = {
    "pre-race-c":    0.0,
    "adaptation":   25.0,   # bodyweight — умеренный стресс
    "taper-b":       0.0,
    "between-races": 10.0,
    "taper-a":       0.0,
    "build":        50.0,   # с весами — серьёзный стресс
}


def strength_load_today(phase: str, completed: bool) -> float:
    """
    Добавлять к ATL при оценке общей нагрузки в Coach Agent промпте.
    Если силовая не выполнена — 0.
    """
    if not completed:
        return 0.0
    return STRENGTH_LOAD_ESTIMATE.get(phase, 0.0)


# ── LangGraph node ────────────────────────────────────────────────────────────

def metrics_fn(state: dict) -> dict:
    """Все вычисления, ноль токенов."""
    con = sqlite3.connect("coach.db")
    rows = con.execute("""
        SELECT date, ctl, atl, form, hrv, resting_hr, sleep_score
        FROM wellness_cache ORDER BY date DESC LIMIT 14
    """).fetchall()

    meso_row = con.execute(
        "SELECT value FROM pipeline_meta WHERE key='mesocycle_start'"
    ).fetchone()

    # 80/20 и days_since_quality — берём полную текущую неделю из кеша,
    # а не только delta. Delta может содержать 1 активность при ежедневном запуске.
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    week_rows = con.execute("""
        SELECT duration_s, training_load, name, date,
               time_in_z1, time_in_z2
        FROM activity_cache WHERE date >= ?
    """, (week_start,)).fetchall()

    # Силовая нагрузка сегодня — из strength_log
    today_str    = date.today().isoformat()
    strength_row = con.execute(
        "SELECT phase, completed FROM strength_log WHERE date=?", (today_str,)
    ).fetchone()

    con.close()

    history = [
        {
            "date": r[0], "ctl": r[1], "atl": r[2], "form": r[3],
            "hrv": r[4], "resting_hr": r[5], "sleep_score": r[6],
        }
        for r in reversed(rows)
    ]

    week_activities = [
        {
            "duration_s":   r[0], "training_load": r[1], "name": r[2],
            "date":         r[3], "time_in_z1":    r[4], "time_in_z2": r[5],
        }
        for r in week_rows
    ]

    today_w = history[-1] if history else {}
    ctl = today_w.get("ctl") or 0.0
    atl = today_w.get("atl") or 0.0

    hrv_data  = hrv_analysis(history)
    acwr_data = calculate_acwr(ctl, atl)
    rhr_data  = rhr_trend_analysis(history)
    zone_data = weekly_zone_ratio(week_activities)
    dsq       = days_since_last_quality(week_activities)

    adj_loads = [
        {**a, "adjusted_load": adjusted_training_load(a)}
        for a in state.get("activities_delta", [])
    ]

    meso_start = meso_row[0] if meso_row else "2026-05-01"
    meso_week  = mesocycle_week(meso_start)

    s_load = strength_load_today(
        strength_row[0], bool(strength_row[1])
    ) if strength_row else 0.0

    print(f"[metrics] HRV dev={hrv_data.get('hrv_deviation_pct')}% "
          f"ACWR={acwr_data.get('acwr')}({acwr_data.get('acwr_zone')}) "
          f"meso_week={meso_week} strength_load={s_load}")

    return {
        **hrv_data,
        **acwr_data,
        **rhr_data,
        "form_today":         today_w.get("form"),   # CTL-ATL из wellness_cache
        "z1z2_ratio_week":    zone_data.get("z1z2_ratio"),
        "z1z2_compliant":     zone_data.get("z1z2_compliant"),
        "days_since_quality": dsq,
        "mesocycle_week":     meso_week,
        "adjusted_loads":     adj_loads,
        "strength_load_today": s_load,
    }


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Тест на wellness_cache
    con = sqlite3.connect("coach.db")
    rows = con.execute("""
        SELECT date, ctl, atl, hrv, resting_hr
        FROM wellness_cache ORDER BY date DESC LIMIT 14
    """).fetchall()
    con.close()

    if not rows:
        print("wellness_cache пуст. Сначала запусти: uv run agents/data_agent.py")
    else:
        history = [
            {"date": r[0], "ctl": r[1], "atl": r[2], "hrv": r[3], "resting_hr": r[4]}
            for r in reversed(rows)
        ]
        ctl = history[-1].get("ctl") or 0
        atl = history[-1].get("atl") or 0

        print("HRV:", hrv_analysis(history))
        print("ACWR:", calculate_acwr(ctl, atl))
        print("RHR:", rhr_trend_analysis(history))
        print("days_since_quality:", days_since_last_quality([]))
        print("mesocycle_week:", mesocycle_week("2026-05-01"))
