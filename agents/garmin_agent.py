"""
garmin_agent.py — Garmin Connect, три режима, чистый Python.

Использует python-garminconnect (garth не используется напрямую).
Токены хранятся в .garmin_session/ — после первого запуска garmin_auth.py
повторный логин и MFA не нужны.

garmin_plan_fn        → план Coach (fbtAdaptiveWorkout) на 7 дней, TTL 12ч
garmin_performance_fn → VO2max + Lactate Threshold + Sleep stages, TTL 24ч
garmin_rt_fn          → Body Battery, Readiness, Status, TTL 24ч

Graceful degradation: если Garmin недоступен — пустой dict/список,
пайплайн продолжается без Garmin-данных.
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import garminconnect
from dotenv import load_dotenv

load_dotenv()

_SESSION_DIR = Path(__file__).parent.parent / ".garmin_session"


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_api() -> garminconnect.Garmin:
    """
    Загружает сохранённые токены из .garmin_session/.
    Если токенов нет — поднимает RuntimeError с инструкцией вместо попытки
    credentials-логина (который на сервере упадёт на MFA).
    """
    token_file = _SESSION_DIR / "garmin_tokens.json"
    if not token_file.exists():
        raise RuntimeError(
            f"Garmin-токены не найдены: {token_file}\n"
            "Запусти один раз на этом хосте: uv run tools/garmin_auth.py"
        )
    api = garminconnect.Garmin(
        os.getenv("GARMIN_EMAIL", ""),
        os.getenv("GARMIN_PASSWORD", ""),
    )
    api.login(tokenstore=str(_SESSION_DIR))
    return api


# ── Cache helpers ─────────────────────────────────────────────────────────────

def get_garmin_cache(today: str) -> dict | None:
    con = sqlite3.connect("coach.db")
    row = con.execute(
        "SELECT body_battery_morning, training_readiness, training_status, "
        "upcoming_plan_json, fetched_at FROM garmin_cache WHERE date=?",
        (today,)
    ).fetchone()
    con.close()
    if not row or not row[4]:
        return None
    age_hours = (datetime.now() - datetime.fromisoformat(row[4])).total_seconds() / 3600
    return {
        "body_battery":        row[0],
        "training_readiness":  row[1],
        "training_status":     row[2],
        "upcoming_plan_json":  row[3],
        "age_hours":           age_hours,
    }


def _save_garmin_plan(date_str: str, plan: list) -> None:
    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO garmin_cache (date, upcoming_plan_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            upcoming_plan_json=excluded.upcoming_plan_json,
            fetched_at=excluded.fetched_at
    """, (date_str, json.dumps(plan, ensure_ascii=False), datetime.now().isoformat()))
    con.commit()
    con.close()


def _save_garmin_rt(date_str: str, data: dict) -> None:
    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO garmin_cache
            (date, body_battery_morning, training_readiness, training_status, fetched_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            body_battery_morning=excluded.body_battery_morning,
            training_readiness=excluded.training_readiness,
            training_status=excluded.training_status,
            fetched_at=excluded.fetched_at
    """, (
        date_str,
        data.get("body_battery"),
        data.get("training_readiness"),
        data.get("training_status"),
        datetime.now().isoformat(),
    ))
    con.commit()
    con.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

# ── Training Status labels ────────────────────────────────────────────────────

_TRAINING_STATUS_LABELS: dict[str, str] = {
    "RECOVERY_1":     "Восстановление (нагрузка ниже хронической нормы)",
    "RECOVERY_2":     "Восстановление (значительно ниже нормы)",
    "MAINTAINING_1":  "Поддержание формы",
    "MAINTAINING_2":  "Поддержание (стабильно)",
    "PRODUCTIVE_1":   "Продуктивная нагрузка — идёт адаптация",
    "PRODUCTIVE_2":   "Продуктивная нагрузка (высокая интенсивность)",
    "PEAKING_1":      "Пик формы / тейпер",
    "PEAKING_2":      "Пик формы (высокий уровень)",
    "DETRAINING_1":   "Детренированность — нагрузка слишком низкая",
    "OVERREACHING_1": "Перегрузка — необходимо снизить нагрузку",
    "OVERREACHING_2": "Функциональная перегрузка (риск)",
}


def _training_status_label(code: str | None) -> str:
    if not code:
        return "н/д"
    return _TRAINING_STATUS_LABELS.get(code, code)


def _steps_duration_s(steps: list) -> int:
    """
    Рекурсивно суммирует продолжительность шагов тренировки (секунды).
    Обрабатывает RepeatGroupDTO (repeats × inner steps) и time-based шаги.

    Garmin хранит длительность интервальных тренировок в структуре шагов,
    а не в top-level поле — поэтому длинные пробежки API отдаёт сразу, а
    VO2max/интервалы нужно считать вручную.
    """
    total = 0
    for step in steps:
        if step.get("type") == "RepeatGroupDTO":
            n = step.get("numberOfIterations") or 1
            inner = step.get("workoutSteps") or []
            total += n * _steps_duration_s(inner)
        else:
            end_cond = step.get("endCondition") or {}
            cond_key = (end_cond.get("conditionTypeKey") or "").lower()
            if "time" in cond_key:
                total += step.get("endConditionValue") or 0
    return total


def _duration_from_segments(data: dict) -> int | None:
    """
    Ищет workoutSegments в data или data['workout'] и суммирует шаги.
    Возвращает секунды или None если нет шагов или итог = 0.
    """
    for root in (data, data.get("workout") or {}):
        segments = root.get("workoutSegments") or []
        total = 0
        for seg in segments:
            total += _steps_duration_s(seg.get("workoutSteps") or [])
        if total > 0:
            return total
    return None


def _extract_duration_min(api, item: dict) -> tuple[int, bool]:
    """
    Длительность тренировки из calendar item.
    Возвращает (duration_min, is_estimated).

    Порядок:
    1. Прямые поля calendar item (быстро, но часто пусто для fbtAdaptiveWorkout)
    2. get_scheduled_workout_by_id → top-level поля → парсинг шагов
    3. get_workout_by_id → top-level поля → парсинг шагов
    4. Заголовочная эвристика (последний резерв)

    fbtAdaptiveWorkout не хранит длительность в calendar item.
    Длинные пробежки Garmin отдаёт в top-level поле, но VO2max / интервалы —
    только в структуре шагов (workoutSegments → RepeatGroupDTO).
    """
    _DURATION_FIELDS = (
        "durationInSeconds", "scheduledWorkoutEstimatedDurationInSecs",
        "estimatedDurationInSecs",
    )

    # 1. Прямые поля
    for field in _DURATION_FIELDS:
        val = item.get(field)
        if val:
            return round(val / 60), False
    for field in ("durationMinutes", "duration_min"):
        val = item.get(field)
        if val:
            return int(val), False

    # 2. get_scheduled_workout_by_id
    item_id = item.get("id") or item.get("scheduledWorkoutId")
    if item_id:
        try:
            details = api.get_scheduled_workout_by_id(item_id)
            for field in _DURATION_FIELDS:
                val = details.get(field)
                if val:
                    return round(val / 60), False
            val = details.get("durationMinutes")
            if val:
                return int(val), False
            total_s = _duration_from_segments(details)
            if total_s:
                print(f"[garmin_plan] duration from steps: {round(total_s/60)}мин для '{item.get('title')}'")
                return round(total_s / 60), False
        except Exception as e:
            print(f"[garmin_plan] get_scheduled_workout_by_id({item_id}) failed: {e}")

    # 3. get_workout_by_id
    workout_id = item.get("workoutId")
    if workout_id:
        try:
            details = api.get_workout_by_id(workout_id)
            for field in _DURATION_FIELDS:
                val = details.get(field)
                if val:
                    return round(val / 60), False
            total_s = _duration_from_segments(details)
            if total_s:
                print(f"[garmin_plan] duration from steps (workout): {round(total_s/60)}мин для '{item.get('title')}'")
                return round(total_s / 60), False
        except Exception as e:
            print(f"[garmin_plan] get_workout_by_id({workout_id}) failed: {e}")

    # 4. Заголовочная эвристика — последний резерв
    title = (item.get("title") or "").lower()
    _DURATION_HEURISTIC = {
        "recovery": 30, "easy": 45, "base": 50,
        "aerobic": 60, "threshold": 55, "tempo": 55,
        "interval": 55, "speed": 55, "long": 130, "endurance": 100,
    }
    for keyword, mins in _DURATION_HEURISTIC.items():
        if keyword in title:
            print(f"[garmin_plan] duration heuristic '{keyword}'→{mins}мин для '{item.get('title')}'")
            return mins, True

    print(f"[garmin_plan] duration unknown для '{item.get('title')}', fields={list(item.keys())[:15]}")
    return 0, True


def _extract_morning_battery(bb_list: list, target_date: str) -> int | None:
    """
    Пик Body Battery за день = максимум из bodyBatteryValuesArray.
    Пик всегда утром после сна, потом Battery снижается.
    """
    for entry in bb_list:
        if entry.get("date") != target_date:
            continue
        values = entry.get("bodyBatteryValuesArray") or []
        if values:
            levels = [v[1] for v in values if len(v) >= 2 and v[1] > 0]
            return max(levels) if levels else None
        return entry.get("charged")  # fallback: суммарный заряд за ночь
    return None


# ── LangGraph nodes ───────────────────────────────────────────────────────────

def garmin_plan_fn(state: dict) -> dict:
    """
    TTL 12ч. Garmin Coach план (fbtAdaptiveWorkout) на 7 дней вперёд.
    Если Garmin недоступен → upcoming_plan=[], Coach Agent использует
    стандартную недельную структуру (Пн=силовая, Ср=качество, Сб=длинный...).
    """
    today_str = state["date"]

    cached = get_garmin_cache(today_str)
    if cached and cached["age_hours"] < 12 and cached.get("upcoming_plan_json"):
        plan = json.loads(cached["upcoming_plan_json"])
        print(f"[garmin_plan] кеш ({cached['age_hours']:.1f}ч), {len(plan)} тренировок")
        return {"upcoming_plan": plan}

    try:
        api      = _get_api()
        today    = date.fromisoformat(today_str)
        end_date = today + timedelta(days=6)

        # 7-дневное окно может пересекать границу месяца
        months = {(today.year, today.month)}
        if (end_date.year, end_date.month) != (today.year, today.month):
            months.add((end_date.year, end_date.month))

        all_items: list = []
        for yr, mo in months:
            r = api.get_scheduled_workouts(yr, mo)
            all_items.extend(r.get("calendarItems", []))

        raw_workouts = [
            w for w in all_items
            if w.get("itemType") == "fbtAdaptiveWorkout"
            and w.get("date")
            and today_str <= w["date"] <= end_date.isoformat()
        ]

        # Получаем точные длительности из Adaptive Training Plan (одним запросом).
        # fbtAdaptiveWorkout не хранит duration в calendar items — только в taskList
        # плана, где каждая задача содержит estimatedDurationInSecs и workoutUuid.
        atp_data: dict[str, dict] = {}  # workoutUuid → {duration_s, detail}
        atp_plan_id = next(
            (w.get("trainingPlanId") for w in raw_workouts if w.get("trainingPlanId")),
            None
        )
        if atp_plan_id:
            try:
                atp = api.get_adaptive_training_plan_by_id(atp_plan_id)
                for task in (atp.get("taskList") or []):
                    tw = task.get("taskWorkout") or {}
                    uuid = tw.get("workoutUuid")
                    dur  = tw.get("estimatedDurationInSecs")
                    if uuid and dur:
                        atp_data[uuid] = {
                            "duration_s": dur,
                            "detail": tw.get("workoutDescription"),
                        }
                print(f"[garmin_plan] ATP plan {atp_plan_id}: {len(atp_data)} длительностей")
            except Exception as e:
                print(f"[garmin_plan] get_adaptive_training_plan_by_id({atp_plan_id}) failed: {e}")

        plan = []
        for w in raw_workouts:
            uuid     = w.get("workoutUuid")
            atp_item = atp_data.get(uuid) if uuid else None

            if atp_item:
                duration_min       = round(atp_item["duration_s"] / 60)
                duration_estimated = False
                workout_detail     = atp_item.get("detail")  # "131bpm" / "5x3:00@166bpm"
                print(f"[garmin_plan] {w['date']} '{w.get('title')}': {duration_min}мин из ATP plan")
            else:
                duration_min, duration_estimated = _extract_duration_min(api, w)
                workout_detail = None

            plan.append({
                "date":               w["date"],
                "type":               w.get("sportTypeKey") or "running",
                "description":        w.get("title"),
                "workout_detail":     workout_detail,
                "duration_min":       duration_min,
                "duration_estimated": duration_estimated,
            })

        _save_garmin_plan(today_str, plan)
        print(f"[garmin_plan] загружен из Garmin, {len(plan)} тренировок")
        return {"upcoming_plan": plan}

    except Exception as e:
        print(f"[garmin_plan] недоступен: {e} — продолжаем без плана")
        return {"upcoming_plan": []}


def garmin_rt_fn(state: dict) -> dict:
    """
    TTL 24ч. Вызывается только при readiness_score <= 5.0 (route_garmin_rt).
    Body Battery + Training Readiness (score 0-100) + Training Status.
    """
    today_str = state["date"]

    cached = get_garmin_cache(today_str)
    if cached and cached["age_hours"] < 24 and cached.get("body_battery") is not None:
        print(f"[garmin_rt] кеш ({cached['age_hours']:.1f}ч)")
        return {"garmin_rt": {
            "body_battery":        cached["body_battery"],
            "training_readiness":  cached["training_readiness"],
            "training_status":     cached["training_status"],
        }}

    try:
        api = _get_api()

        # Body Battery: пик за день = значение после сна
        bb_list    = api.get_body_battery(today_str)
        bb_morning = _extract_morning_battery(bb_list, today_str)

        # Training Readiness: score 0-100, level HIGH/MEDIUM/LOW
        tr_list  = api.get_training_readiness(today_str)
        tr_today = next(
            (r for r in tr_list if r.get("calendarDate") == today_str), {}
        ) if isinstance(tr_list, list) else {}
        readiness = tr_today.get("score")

        # Training Status: PEAKING_1, MAINTAINING_1, PRODUCTIVE_1 и т.д.
        ts_data     = api.get_training_status(today_str)
        device_data = next(
            iter(
                ts_data.get("mostRecentTrainingStatus", {})
                       .get("latestTrainingStatusData", {}).values()
            ),
            {},
        )
        status = device_data.get("trainingStatusFeedbackPhrase")

        result = {
            "body_battery":        bb_morning,
            "training_readiness":  readiness,
            "training_status":     status,
            "training_status_label": _training_status_label(status),
        }
        _save_garmin_rt(today_str, result)
        print(f"[garmin_rt] BB={bb_morning}, Readiness={readiness}, "
              f"Status={status} ({_training_status_label(status)})")
        return {"garmin_rt": result}

    except Exception as e:
        print(f"[garmin_rt] недоступен: {e}")
        return {"garmin_rt": {}}


# ── Performance cache helpers ─────────────────────────────────────────────────

def _get_performance_cache(today_str: str) -> dict | None:
    """TTL 24ч. None если нет записи или запись устарела."""
    try:
        con = sqlite3.connect("coach.db")
        row = con.execute("""
            SELECT vo2max, lt_hr, lt_pace_s,
                   sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
                   fetched_at, hrv_garmin, rhr_garmin
            FROM performance_cache WHERE date=?
        """, (today_str,)).fetchone()
        con.close()
        if not row or not row[7]:
            return None
        age_h = (datetime.now() - datetime.fromisoformat(row[7])).total_seconds() / 3600
        if age_h > 24:
            return None
        return {
            "vo2max":          row[0],
            "lt_hr":           row[1],
            "lt_pace_s":       row[2],
            "sleep_deep_min":  row[3],
            "sleep_rem_min":   row[4],
            "sleep_light_min": row[5],
            "sleep_awake_min": row[6],
            "hrv_garmin":      row[8],
            "rhr_garmin":      row[9],
        }
    except Exception:
        return None


def _save_performance_cache(date_str: str, data: dict) -> None:
    try:
        con = sqlite3.connect("coach.db")
        con.execute("""
            INSERT INTO performance_cache
                (date, vo2max, lt_hr, lt_pace_s,
                 sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
                 hrv_garmin, rhr_garmin,
                 fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
                vo2max=excluded.vo2max,
                lt_hr=excluded.lt_hr,
                lt_pace_s=excluded.lt_pace_s,
                sleep_deep_min=excluded.sleep_deep_min,
                sleep_rem_min=excluded.sleep_rem_min,
                sleep_light_min=excluded.sleep_light_min,
                sleep_awake_min=excluded.sleep_awake_min,
                hrv_garmin=excluded.hrv_garmin,
                rhr_garmin=excluded.rhr_garmin,
                fetched_at=excluded.fetched_at
        """, (
            date_str,
            data.get("vo2max"),
            data.get("lt_hr"),
            data.get("lt_pace_s"),
            data.get("sleep_deep_min"),
            data.get("sleep_rem_min"),
            data.get("sleep_light_min"),
            data.get("sleep_awake_min"),
            data.get("hrv_garmin"),
            data.get("rhr_garmin"),
            datetime.now().isoformat(),
        ))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[garmin_performance] ошибка сохранения кеша: {e}")


# ── Performance API helpers ───────────────────────────────────────────────────

def _fetch_vo2max(api, date_str: str) -> float | None:
    """
    VO2max из Garmin через get_max_metrics(date).
    API возвращает данные только для дат с активностями.
    Структура: list[{generic: {vo2MaxPreciseValue, vo2MaxValue}, ...}]

    Стратегия: сначала дата последней активности из БД (быстро),
    потом перебор дней назад до 30, потом значение из performance_cache.
    """
    def _extract(data) -> float | None:
        if not isinstance(data, list) or not data:
            return None
        item = data[0]
        generic = item.get("generic") or {}
        return generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")

    # 1. Дата последней активности из БД — наиболее вероятная дата с VO2max
    try:
        con = sqlite3.connect("coach.db")
        row = con.execute(
            "SELECT date FROM activity_cache WHERE date <= ? ORDER BY date DESC LIMIT 1",
            (date_str,)
        ).fetchone()
        con.close()
        if row:
            val = _extract(api.get_max_metrics(row[0]))
            if val:
                return val
    except Exception:
        pass

    # 2. Перебор последних 14 дней (VO2max обновляется только при активности)
    for days_back in range(1, 14):
        check = (date.fromisoformat(date_str) - timedelta(days=days_back)).isoformat()
        try:
            val = _extract(api.get_max_metrics(check))
            if val:
                return val
        except Exception:
            pass

    # 3. Значение из предыдущих запусков performance_cache
    try:
        cutoff = (date.fromisoformat(date_str) - timedelta(days=30)).isoformat()
        con = sqlite3.connect("coach.db")
        row = con.execute("""
            SELECT vo2max FROM performance_cache
            WHERE vo2max IS NOT NULL AND date >= ? AND date < ?
            ORDER BY date DESC LIMIT 1
        """, (cutoff, date_str)).fetchone()
        con.close()
        if row:
            return row[0]
    except Exception:
        pass

    return None


def _fetch_lt(api) -> tuple[int | None, float | None]:
    """
    LT HR (bpm) и темп (s/km) из get_lactate_threshold().

    Структура ответа: {"speed_and_heart_rate": {"heartRate": 154, "speed": 0.34...}, ...}
    speed — это pace в с/м (секунд на метр), а не скорость в м/с.
    Конвертация: pace_s/km = speed_spm × 1000.
    """
    try:
        data = api.get_lactate_threshold()

        # Основной формат: вложен в speed_and_heart_rate
        shr = data.get("speed_and_heart_rate") if isinstance(data, dict) else None
        if shr:
            hr       = shr.get("heartRate") or shr.get("heartRateBeatsPerMinute")
            speed_spm = shr.get("speed")    # с/м (pace), не м/с
            pace_s   = round(speed_spm * 1000) if speed_spm else None
            if hr:
                return int(hr), pace_s

        # Fallback: плоский dict или другие вложения
        candidates = [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for c in candidates:
            if not isinstance(c, dict):
                continue
            hr = (c.get("heartRateBeatsPerMinute") or c.get("heartRate")
                  or c.get("lactateThresholdHeartRate"))
            speed_spm = c.get("speed")
            pace_s = round(speed_spm * 1000) if speed_spm else None
            if hr:
                return int(hr), pace_s

        print(f"[garmin_performance] LT: неожиданная структура: "
              f"{json.dumps(data, ensure_ascii=False)[:200]}")
    except Exception as e:
        print(f"[garmin_performance] LT ошибка: {e}")
    return None, None


def _fetch_sleep_stages(api, date_str: str) -> dict:
    """Стадии сна за прошлую ночь (Garmin хранит по дате пробуждения)."""
    empty = {
        "sleep_deep_min": None, "sleep_rem_min": None,
        "sleep_light_min": None, "sleep_awake_min": None,
    }
    try:
        data = api.get_sleep_data(date_str)
        dto = data.get("dailySleepDTO") or {}
        if not dto:
            return empty
        return {
            "sleep_deep_min":  round((dto.get("deepSleepSeconds")  or 0) / 60),
            "sleep_rem_min":   round((dto.get("remSleepSeconds")   or 0) / 60),
            "sleep_light_min": round((dto.get("lightSleepSeconds") or 0) / 60),
            "sleep_awake_min": round((dto.get("awakeSleepSeconds") or 0) / 60),
        }
    except Exception as e:
        print(f"[garmin_performance] sleep stages ошибка: {e}")
    return empty


def _fetch_garmin_hrv_rhr(api, today_str: str) -> dict:
    """
    HRV (lastNightAvg) и RHR из Garmin Connect — данные доступны после утренней
    синхронизации часов, до того как intervals.icu получит те же значения.
    """
    result: dict = {"hrv_garmin": None, "rhr_garmin": None}

    try:
        hrv_data = api.get_hrv_data(today_str)
        if hrv_data:
            summary = hrv_data.get("hrvSummary") or {}
            result["hrv_garmin"] = summary.get("lastNightAvg")
    except Exception as e:
        print(f"[garmin_performance] HRV недоступен: {e}")

    try:
        stats = api.get_stats(today_str)
        if stats:
            result["rhr_garmin"] = stats.get("restingHeartRate")
    except Exception as e:
        print(f"[garmin_performance] RHR недоступен: {e}")

    return result


def _compute_vo2max_trend(current: float | None, today_str: str) -> str:
    """
    Сравнивает текущий VO2max с последним значением из performance_cache
    (за последние 60 дней). Порог: ±0.5 — игнорируем шум округления Garmin.
    """
    if current is None:
        return "unknown"
    try:
        cutoff = (date.fromisoformat(today_str) - timedelta(days=60)).isoformat()
        con    = sqlite3.connect("coach.db")
        row    = con.execute("""
            SELECT vo2max FROM performance_cache
            WHERE date < ? AND vo2max IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """, (today_str,)).fetchone()
        con.close()
        if not row or row[0] is None:
            return "unknown"
        diff = current - row[0]
        if diff > 0.5:
            return "rising"
        elif diff < -0.5:
            return "falling"
        return "stable"
    except Exception:
        return "unknown"


def _pace_str(pace_s: float | None) -> str:
    """Converts seconds/km to 'M:SS/km' string."""
    if not pace_s:
        return "н/д"
    mins, secs = divmod(int(pace_s), 60)
    return f"{mins}:{secs:02d}/км"


# ── LangGraph node: performance ───────────────────────────────────────────────

def garmin_performance_fn(state: dict) -> dict:
    """
    TTL 24ч. VO2max (с трендом), Lactate Threshold HR/pace, стадии сна.
    Медленно меняющиеся данные — не требуют частого обновления.
    """
    today_str = state["date"]

    cached = _get_performance_cache(today_str)
    if cached:
        trend = _compute_vo2max_trend(cached.get("vo2max"), today_str)
        print(f"[garmin_performance] кеш — VO2max={cached.get('vo2max')} ({trend}), "
              f"LT={cached.get('lt_hr')}bpm, "
              f"sleep deep={cached.get('sleep_deep_min')}мин REM={cached.get('sleep_rem_min')}мин, "
              f"HRV={cached.get('hrv_garmin')} RHR={cached.get('rhr_garmin')}")
        return {
            **cached,
            "vo2max_trend":    trend,
            "hrv_garmin_today": cached.get("hrv_garmin"),
            "rhr_garmin_today": cached.get("rhr_garmin"),
        }

    try:
        api = _get_api()

        vo2max           = _fetch_vo2max(api, today_str)
        lt_hr, lt_pace_s = _fetch_lt(api)
        sleep            = _fetch_sleep_stages(api, today_str)
        hrv_rhr          = _fetch_garmin_hrv_rhr(api, today_str)
        vo2max_trend     = _compute_vo2max_trend(vo2max, today_str)

        result = {
            "vo2max":    vo2max,
            "lt_hr":     lt_hr,
            "lt_pace_s": lt_pace_s,
            **sleep,
            **hrv_rhr,
        }
        _save_performance_cache(today_str, result)

        print(f"[garmin_performance] VO2max={vo2max} ({vo2max_trend}), "
              f"LT={lt_hr}bpm/{_pace_str(lt_pace_s)}, "
              f"sleep deep={sleep.get('sleep_deep_min')}мин REM={sleep.get('sleep_rem_min')}мин, "
              f"HRV={hrv_rhr.get('hrv_garmin')} RHR={hrv_rhr.get('rhr_garmin')}")
        return {
            **result,
            "vo2max_trend":    vo2max_trend,
            "hrv_garmin_today": hrv_rhr.get("hrv_garmin"),
            "rhr_garmin_today": hrv_rhr.get("rhr_garmin"),
        }

    except Exception as e:
        print(f"[garmin_performance] недоступен: {e}")
        return {
            "vo2max": None, "vo2max_trend": None,
            "lt_hr": None, "lt_pace_s": None,
            "sleep_deep_min": None, "sleep_rem_min": None,
            "sleep_light_min": None, "sleep_awake_min": None,
            "hrv_garmin_today": None, "rhr_garmin_today": None,
        }


# ── Standalone test ───────────────────────────────────────────────────────────

def _debug_workout_raw(today_str: str | None = None) -> None:
    """
    Выводит сырой ответ Garmin API для тренировок текущей недели.
    Нужен для диагностики проблем с парсингом длительности.
    Запуск: uv run agents/garmin_agent.py --debug
    """
    today_str = today_str or date.today().isoformat()
    today     = date.fromisoformat(today_str)
    end_date  = today + timedelta(days=6)

    api = _get_api()

    months = {(today.year, today.month)}
    if (end_date.year, end_date.month) != (today.year, today.month):
        months.add((end_date.year, end_date.month))

    all_items: list = []
    for yr, mo in months:
        r = api.get_scheduled_workouts(yr, mo)
        all_items.extend(r.get("calendarItems", []))

    raw_workouts = [
        w for w in all_items
        if w.get("itemType") == "fbtAdaptiveWorkout"
        and w.get("date")
        and today_str <= w["date"] <= end_date.isoformat()
    ]

    print(f"\n[debug] fbtAdaptiveWorkout на {today_str}..{end_date.isoformat()}: {len(raw_workouts)} шт.")
    for w in raw_workouts:
        print(f"\n{'─'*60}")
        print(f"  date={w.get('date')}  title='{w.get('title')}'")
        print(f"  item keys: {sorted(w.keys())}")
        print(f"  durationInSeconds={w.get('durationInSeconds')}  "
              f"scheduledWorkoutEstimatedDurationInSecs={w.get('scheduledWorkoutEstimatedDurationInSecs')}  "
              f"estimatedDurationInSecs={w.get('estimatedDurationInSecs')}")
        print(f"  id={w.get('id')}  scheduledWorkoutId={w.get('scheduledWorkoutId')}  workoutId={w.get('workoutId')}")

        item_id = w.get("id") or w.get("scheduledWorkoutId")
        if item_id:
            try:
                details = api.get_scheduled_workout_by_id(item_id)
                print(f"\n  get_scheduled_workout_by_id({item_id}):")
                print(f"    top-level keys: {sorted(details.keys())[:20]}")
                for f in ("durationInSeconds", "scheduledWorkoutEstimatedDurationInSecs", "estimatedDurationInSecs", "durationMinutes"):
                    if details.get(f):
                        print(f"    {f} = {details.get(f)}")
                segs = details.get("workoutSegments") or (details.get("workout") or {}).get("workoutSegments") or []
                print(f"    workoutSegments: {len(segs)} сегментов")
                for i, seg in enumerate(segs):
                    steps = seg.get("workoutSteps") or []
                    print(f"      seg[{i}]: {len(steps)} шагов")
                    for j, step in enumerate(steps[:8]):
                        ec = step.get("endCondition") or {}
                        print(f"        step[{j}]: type={step.get('type')}  "
                              f"endCondition.conditionTypeKey={ec.get('conditionTypeKey')}  "
                              f"endConditionValue={step.get('endConditionValue')}  "
                              f"numberOfIterations={step.get('numberOfIterations')}")
                        if step.get("workoutSteps"):
                            inner = step["workoutSteps"]
                            print(f"          inner steps: {len(inner)}")
                            for k, s in enumerate(inner[:5]):
                                ec2 = s.get("endCondition") or {}
                                print(f"            inner[{k}]: type={s.get('type')}  "
                                      f"conditionTypeKey={ec2.get('conditionTypeKey')}  "
                                      f"endConditionValue={s.get('endConditionValue')}")
                total_s = _duration_from_segments(details)
                print(f"    _duration_from_segments → {total_s}s = {round(total_s/60) if total_s else None}мин")
            except Exception as e:
                print(f"    get_scheduled_workout_by_id FAILED: {e}")

        workout_id = w.get("workoutId")
        if workout_id:
            try:
                details2 = api.get_workout_by_id(workout_id)
                print(f"\n  get_workout_by_id({workout_id}):")
                print(f"    top-level keys: {sorted(details2.keys())[:20]}")
                total_s2 = _duration_from_segments(details2)
                print(f"    _duration_from_segments → {total_s2}s = {round(total_s2/60) if total_s2 else None}мин")
            except Exception as e:
                print(f"    get_workout_by_id FAILED: {e}")

        dur_min, is_est = _extract_duration_min(api, w)
        print(f"\n  → _extract_duration_min: {dur_min}мин  estimated={is_est}")


if __name__ == "__main__":
    import sys
    today = date.today().isoformat()
    state = {"date": today}

    if "--debug" in sys.argv:
        print("=== DEBUG: сырые данные Garmin API ===")
        _debug_workout_raw(today)
        sys.exit(0)

    print("=== garmin_plan_fn ===")
    result = garmin_plan_fn(state)
    for w in result.get("upcoming_plan", []):
        print(f"  {w}")

    print("\n=== garmin_performance_fn ===")
    from data_agent import init_db
    init_db()
    perf = garmin_performance_fn(state)
    print(f"  VO2max:   {perf.get('vo2max')} ({perf.get('vo2max_trend')})")
    print(f"  LT HR:    {perf.get('lt_hr')} bpm / {_pace_str(perf.get('lt_pace_s'))}")
    print(f"  Sleep:    deep={perf.get('sleep_deep_min')}мин "
          f"REM={perf.get('sleep_rem_min')}мин "
          f"light={perf.get('sleep_light_min')}мин "
          f"awake={perf.get('sleep_awake_min')}мин")

    print("\n=== garmin_rt_fn ===")
    result2 = garmin_rt_fn({**state, "readiness_score": 4.0})
    print(f"  {result2.get('garmin_rt')}")
