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


# ── Контроль объёма недели против koop-плана ──────────────────────────────────

def weekly_volume_status(actual_minutes: float | None, target_minutes: float | None,
                          tolerance: float = 0.15, elapsed_fraction: float = 1.0) -> dict:
    """
    Сравнивает фактический недельный объём (мин) с ЦЕЛЬЮ НА ТЕКУЩИЙ МОМЕНТ недели:
    target × elapsed_fraction (доля прошедшей недели). Без пропорционирования цель
    в середине недели всегда «недобрана» просто потому, что неделя не дожита (ложный
    volume_under в пн-ср, который мог дёргать make-up). elapsed_fraction=1.0 → полная цель.
    Допуск ±15%. Флаги: volume_over / volume_under (context_flags).
    """
    if not target_minutes or actual_minutes is None:
        return {"volume_status": "unknown", "volume_pct": None}

    _frac = elapsed_fraction if (elapsed_fraction and elapsed_fraction > 0) else 1.0
    _expected = target_minutes * _frac
    pct = (actual_minutes - _expected) / _expected
    if pct > tolerance:
        status = "over"
    elif pct < -tolerance:
        status = "under"
    else:
        status = "on_track"
    return {"volume_status": status, "volume_pct": round(pct * 100, 1)}


# ── Вертикаль: недельный статус + спайк-детектор (механизм травмы ахилла) ─────

def weekly_vertical_status(actual_vert_m, target_vert_m, tolerance: float = 0.20,
                           elapsed_fraction: float = 1.0) -> dict:
    """Недельный D+ vs целью на ТЕКУЩИЙ момент недели (target_vert_m × elapsed_fraction).
    Пропорционирование убирает ложный статус в середине недели. Допуск ±20%.
    elapsed_fraction=1.0 → vs полная цель."""
    if not target_vert_m or actual_vert_m is None:
        return {"vertical_status": "unknown", "vertical_pct": None}
    _frac = elapsed_fraction if (elapsed_fraction and elapsed_fraction > 0) else 1.0
    _expected = target_vert_m * _frac
    pct = (actual_vert_m - _expected) / _expected
    if pct > tolerance:
        status = "over"
    elif pct < -tolerance:
        status = "under"
    else:
        status = "on_track"
    return {"vertical_status": status, "vertical_pct": round(pct * 100, 1)}


def vertical_acwr(vert_rows, today=None, chronic_floor_m: float = 120.0) -> dict:
    """
    Вертикальный ACWR = acute(D+ за 7д) / chronic(D+ за 28д / 4 = средненедельный).
    Ловит СПАЙКИ ВЕРТИКАЛИ — доказанный механизм травмы ахилла у этого атлета
    (injury first-cause: недельный D+ прыгал 400→1019→857 перед травмой). Нагрузочный
    ACWR этого не ловит (усредняет по load). chronic_floor не даёт метрике взрываться
    на пустой базе, но спайк на неадаптированном тендоне всё равно поднимает ratio.
    vert_rows: [(date_str, elevation_gain_m), ...] за ~28 дней.
    """
    today = today or date.today()
    acute = chronic28 = 0.0
    for d, elev in vert_rows:
        d = (d or "")[:10]
        if not d:
            continue
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            continue
        e = elev or 0.0
        days = (today - dd).days
        if 0 <= days < 28:
            chronic28 += e
            if days < 7:
                acute += e
    chronic_weekly = max(chronic28 / 4.0, chronic_floor_m)
    ratio = acute / chronic_weekly
    if ratio > 1.5:
        zone = "high_risk"
    elif ratio > 1.3:
        zone = "caution"
    else:
        zone = "optimal"
    return {
        "vertical_acwr":         round(ratio, 2),
        "vertical_acwr_zone":    zone,
        "acute_vert_m":          round(acute),
        "chronic_vert_weekly_m": round(chronic28 / 4.0),
    }


# ── Дней с последней качественной сессии ─────────────────────────────────────

def days_since_last_quality(activities: list[dict], plan_quality_dates: set | None = None) -> int:
    """
    Дней с последней КАЧЕСТВЕННОЙ (интенсивной) сессии; 99 если таких нет.

    Качество определяется по интенсивности/плану, НЕ по training_load: load
    растёт от ОБЪЁМА, поэтому лёгкий/длинный бег легко даёт load>70 и раньше
    ложно помечался качеством — из-за чего coach отменял реальные интервалы.
    Сессия = качество, если:
      • в названии ключевые слова (interval/tempo/threshold/интервал/темп/качество), ИЛИ
      • RPE >= 7 (когда заполнен), ИЛИ
      • план предписывал quality в этот день И была пробежка (plan_quality_dates).
    """
    plan_quality_dates = plan_quality_dates or set()
    KW = ("interval", "threshold", "tempo", "качество", "интервал", "темп")

    def _d(a: dict) -> str:
        return (a.get("start_date_local") or a.get("date") or "")[:10]

    def _is_quality(a: dict) -> bool:
        name = (a.get("name") or "").lower()
        if any(k in name for k in KW):
            return True
        rpe = a.get("rpe")
        if rpe is not None and rpe >= 7:
            return True
        return _d(a) in plan_quality_dates

    q_dates = [_d(a) for a in activities if _d(a) and _is_quality(a)]
    if not q_dates:
        return 99
    last_date = max(date.fromisoformat(d) for d in q_dates)
    return (date.today() - last_date).days


# ── Фактически выполненные тренировки (антигаллюцинационное заземление) ────────

_WEEKDAY_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def format_recent_activities(activities: list[dict], today: date | None = None) -> dict:
    """
    Строит фактический журнал последних выполненных тренировок для LLM-агентов.

    Назначение — заземление: LLM-агенты (coach/plan/synthesis) не должны
    ВЫДУМЫВАТЬ выполненные тренировки. Раньше в промпт передавался только
    upcoming_plan (будущее), и модель при отсутствии фактов о прошлом
    сочиняла историю, копируя текст сегодняшнего плана («вчера были 4x3 Z3»).

    Возвращает:
      summary — человекочитаемый список последних тренировок (или явное
                указание, что данных нет / они устарели);
      days_since_last_activity — сколько дней назад последняя запись (или None).

    Если самая свежая запись старше 1 дня — в summary добавляется явный
    маркер устаревания, чтобы модель писала «данных нет», а не фантазировала.
    """
    today = today or date.today()

    dated = []
    for a in activities:
        d_str = (a.get("start_date_local") or a.get("date") or "")[:10]
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        dated.append((d, a))

    if not dated:
        return {
            "summary": "нет записанных тренировок за последние 10 дней — "
                       "НЕ придумывай выполненные тренировки, их не было в данных",
            "days_since_last_activity": None,
        }

    dated.sort(key=lambda x: x[0], reverse=True)
    last_date = dated[0][0]
    days_since = (today - last_date).days

    lines = []
    for d, a in dated:
        load = a.get("training_load") or a.get("icu_training_load") or 0
        dur_min = round((a.get("duration_s") or a.get("moving_time") or 0) / 60)
        z1_min = round((a.get("time_in_z1") or 0) / 60)
        z2_min = round((a.get("time_in_z2") or 0) / 60)
        name = (a.get("name") or "тренировка").strip()
        wd = _WEEKDAY_RU[d.weekday()]
        parts = [f"{d.strftime('%d.%m')} ({wd}) — {name}: {dur_min}мин, load {round(load)}"]
        if z1_min or z2_min:
            parts.append(f"Z1 {z1_min}м/Z2 {z2_min}м")
        rpe = a.get("rpe")
        if rpe is not None:
            parts.append(f"RPE {rpe}")
        lines.append(", ".join(parts))

    summary = "\n".join(lines)
    if days_since >= 2:
        summary = (
            f"⚠ Последняя пробежка {days_since} дн. назад ({last_date.strftime('%d.%m')}). "
            f"За более поздние дни данных о выполненных тренировках НЕТ — "
            f"не выдавай плановые тренировки за выполненные.\n" + summary
        )

    return {"summary": summary, "days_since_last_activity": days_since}


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
               time_in_z1, time_in_z2, rpe, elevation_gain_m
        FROM activity_cache WHERE date >= ?
    """, (week_start,)).fetchall()

    # 28-дневная вертикаль для vertical_acwr (спайк-детектор набора высоты)
    vert_start = (date.today() - timedelta(days=28)).isoformat()
    vert_rows = con.execute(
        "SELECT date, elevation_gain_m FROM activity_cache WHERE date >= ?",
        (vert_start,),
    ).fetchall()

    # Фактически выполненные тренировки за 10 дней — заземление для LLM,
    # чтобы coach/plan/synthesis не выдумывали историю (см. format_recent_activities).
    recent_start = (date.today() - timedelta(days=10)).isoformat()
    recent_rows = con.execute("""
        SELECT duration_s, training_load, name, date,
               time_in_z1, time_in_z2, rpe
        FROM activity_cache WHERE date >= ? ORDER BY date DESC
    """, (recent_start,)).fetchall()

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
            "rpe":          r[6], "elevation_gain_m": r[7],
        }
        for r in week_rows
    ]

    recent_activities = [
        {
            "duration_s":   r[0], "training_load": r[1], "name": r[2],
            "date":         r[3], "time_in_z1":    r[4], "time_in_z2": r[5],
            "rpe":          r[6],
        }
        for r in recent_rows
    ]
    recent = format_recent_activities(recent_activities)

    today_w = history[-1] if history else {}
    ctl = today_w.get("ctl") or 0.0
    atl = today_w.get("atl") or 0.0

    hrv_data  = hrv_analysis(history)
    acwr_data = calculate_acwr(ctl, atl)
    rhr_data  = rhr_trend_analysis(history)
    zone_data = weekly_zone_ratio(week_activities)
    week_total_vert = sum((a.get("elevation_gain_m") or 0.0) for a in week_activities)
    vert_data = vertical_acwr(vert_rows)
    # Plan-aware quality detection: дни, где персональный план предписывал quality.
    # Ленивый импорт (context_agent импортирует metrics — избегаем циклического импорта).
    plan_quality_dates: set = set()
    try:
        from context_agent import load_plan_config
        from koop_plan_agent import entry_for_date
        _cfg = load_plan_config()
        if _cfg:
            _pd = date.fromisoformat(week_start)
            while _pd <= date.today():
                _pe = entry_for_date(_cfg, _pd)
                if _pe and _pe.get("type") == "quality":
                    plan_quality_dates.add(_pd.isoformat())
                _pd += timedelta(days=1)
    except Exception as _ex:
        print(f"[metrics] plan_quality_dates unavailable: {_ex}")
    dsq       = days_since_last_quality(week_activities, plan_quality_dates)

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
        "form_today":         today_w.get("form"),
        "sleep_score":        today_w.get("sleep_score"),
        "z1z2_ratio_week":    zone_data.get("z1z2_ratio"),
        "z1z2_compliant":     zone_data.get("z1z2_compliant"),
        "week_total_minutes": zone_data.get("total_minutes"),
        "week_total_vert":    round(week_total_vert),
        **vert_data,
        "days_since_quality": dsq,
        "mesocycle_week":     meso_week,
        "adjusted_loads":     adj_loads,
        "strength_load_today": s_load,
        "recent_activities_summary":  recent["summary"],
        "days_since_last_activity":   recent["days_since_last_activity"],
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
