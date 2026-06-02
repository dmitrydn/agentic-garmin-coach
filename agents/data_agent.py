"""
data_agent.py — LangGraph node: delta-загрузка intervals.icu → SQLite

Чистый Python, ноль LLM-токенов.
Читает только delta с last_sync — не всю историю.

Auth: Basic ("API_KEY", INTERVALS_API_KEY).
form = ctl - atl вычисляется локально — API всегда отдаёт 0.
"""

import asyncio
import os
import sqlite3
from datetime import date, datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

AUTH = ("API_KEY", os.getenv("INTERVALS_API_KEY", ""))
AID  = os.getenv("INTERVALS_ATHLETE_ID", "")
BASE = f"https://intervals.icu/api/v1/athlete/{AID}"


# ── Schema ──────────────────────────────────────────────────────────────────

def init_db(db_path: str = "coach.db") -> None:
    con = sqlite3.connect(db_path)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS wellness_cache (
        date        TEXT PRIMARY KEY,
        ctl         REAL,
        atl         REAL,
        form        REAL,
        hrv         REAL,
        resting_hr  INTEGER,
        sleep_score REAL,
        synced_at   TEXT
    );

    CREATE TABLE IF NOT EXISTS activity_cache (
        id               TEXT PRIMARY KEY,
        date             TEXT,
        name             TEXT,
        distance_m       REAL,
        duration_s       INTEGER,
        avg_hr           REAL,
        training_load    REAL,
        adjusted_load    REAL,
        avg_pace_s       REAL,
        elevation_gain_m REAL,
        time_in_z1       INTEGER,
        time_in_z2       INTEGER,
        surface          TEXT,
        rpe              INTEGER,
        synced_at        TEXT
    );

    CREATE TABLE IF NOT EXISTS garmin_cache (
        date                        TEXT PRIMARY KEY,
        body_battery_morning        INTEGER,
        training_readiness          INTEGER,
        training_status             TEXT,
        coach_workout_description   TEXT,
        upcoming_plan_json          TEXT,
        fetched_at                  TEXT
    );

    CREATE TABLE IF NOT EXISTS performance_cache (
        date            TEXT PRIMARY KEY,
        vo2max          REAL,
        lt_hr           INTEGER,
        lt_pace_s       REAL,
        sleep_deep_min  INTEGER,
        sleep_rem_min   INTEGER,
        sleep_light_min INTEGER,
        sleep_awake_min INTEGER,
        fetched_at      TEXT
    );

    CREATE TABLE IF NOT EXISTS strength_log (
        date                     TEXT PRIMARY KEY,
        phase                    TEXT,
        completed                BOOLEAN,
        perceived_difficulty     INTEGER,
        legs_heaviness_next_day  INTEGER,
        notes                    TEXT
    );

    CREATE TABLE IF NOT EXISTS recommendation_log (
        date                 TEXT PRIMARY KEY,
        readiness            TEXT,
        readiness_score      REAL,
        recommendation_type  TEXT,
        recommendation_text  TEXT,
        actual_rpe           INTEGER,
        actual_hr            REAL,
        hrv_next_day         REAL,
        outcome              TEXT
    );

    CREATE TABLE IF NOT EXISTS pipeline_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    # Schema migrations: add columns introduced after initial deploy
    for _col_sql in [
        "ALTER TABLE performance_cache ADD COLUMN hrv_garmin REAL",
        "ALTER TABLE performance_cache ADD COLUMN rhr_garmin INTEGER",
    ]:
        try:
            con.execute(_col_sql)
        except Exception:
            pass  # column already exists

    con.commit()
    con.close()


# ── Sync state ───────────────────────────────────────────────────────────────

def get_last_sync(db_path: str = "coach.db") -> str:
    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT value FROM pipeline_meta WHERE key='last_sync'"
    ).fetchone()
    con.close()
    if not row:
        return (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    return row[0]


def set_last_sync(date_str: str, db_path: str = "coach.db") -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT OR REPLACE INTO pipeline_meta VALUES ('last_sync', ?)",
        (date_str,)
    )
    con.commit()
    con.close()


# ── Fetch ────────────────────────────────────────────────────────────────────

async def fetch_wellness_delta(oldest: str, newest: str) -> list[dict]:
    """Wellness: ctl, atl, hrv, restingHR, sleepScore."""
    async with httpx.AsyncClient(auth=AUTH, timeout=20) as c:
        r = await c.get(f"{BASE}/wellness", params={"oldest": oldest, "newest": newest})
        r.raise_for_status()
        return r.json()


async def fetch_activities_delta(oldest: str, newest: str) -> list[dict]:
    """Activities: id, name, start_date_local, icu_training_load, avg_hr, distance, elapsed_time, elevation_gain."""
    async with httpx.AsyncClient(auth=AUTH, timeout=20) as c:
        r = await c.get(f"{BASE}/activities", params={"oldest": oldest, "newest": newest})
        r.raise_for_status()
        return r.json()


# ── Save ─────────────────────────────────────────────────────────────────────

def save_wellness(records: list[dict], db_path: str = "coach.db") -> None:
    now = datetime.now().isoformat()
    con = sqlite3.connect(db_path)
    for d in records:
        ctl = d.get("ctl") or 0.0
        atl = d.get("atl") or 0.0
        con.execute(
            "INSERT OR REPLACE INTO wellness_cache VALUES (?,?,?,?,?,?,?,?)",
            (
                d.get("id"),
                ctl,
                atl,
                round(ctl - atl, 2),   # form вычисляем сами
                d.get("hrv"),
                d.get("restingHR"),
                d.get("sleepScore"),
                now,
            )
        )
    con.commit()
    con.close()


def save_activities(records: list[dict], db_path: str = "coach.db") -> None:
    now = datetime.now().isoformat()
    con = sqlite3.connect(db_path)
    for a in records:
        dist = a.get("distance") or 0
        dur  = a.get("elapsed_time") or 0
        pace = (dur / (dist / 1000)) if dist > 0 else None
        # ON CONFLICT DO UPDATE — не трогаем rpe (пишет telegram_bot),
        # adjusted_load (пишет metrics_fn), surface (вручную).
        # Обновляем только поля из intervals.icu.
        con.execute("""
            INSERT INTO activity_cache
                (id, date, name, distance_m, duration_s, avg_hr,
                 training_load, adjusted_load, avg_pace_s, elevation_gain_m,
                 time_in_z1, time_in_z2, surface, rpe, synced_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                date=excluded.date,
                name=excluded.name,
                distance_m=excluded.distance_m,
                duration_s=excluded.duration_s,
                avg_hr=excluded.avg_hr,
                training_load=excluded.training_load,
                avg_pace_s=excluded.avg_pace_s,
                elevation_gain_m=excluded.elevation_gain_m,
                time_in_z1=excluded.time_in_z1,
                time_in_z2=excluded.time_in_z2,
                synced_at=excluded.synced_at
        """,
            (
                str(a.get("id")),
                (a.get("start_date_local") or "")[:10],
                a.get("name"),
                dist,
                dur,
                a.get("average_heartrate"),
                a.get("icu_training_load"),
                None,                        # adjusted_load — заполнит metrics_fn
                pace,
                a.get("total_elevation_gain"),
                a.get("time_in_z1"),
                a.get("time_in_z2"),
                None,                        # surface — вручную
                None,                        # rpe — из Telegram
                now,
            )
        )
    con.commit()
    con.close()


# ── LangGraph node ────────────────────────────────────────────────────────────

async def data_agent_fn(state: dict) -> dict:
    """
    Чистый Python, ноль токенов. Не читает всю историю — только delta.
    Async: LangGraph может запускать граф асинхронно, asyncio.run() внутри
    уже запущенного event loop вызывает RuntimeError.
    """
    init_db()
    today     = date.today().isoformat()
    last_sync = get_last_sync()

    print(f"[data_agent] delta: {last_sync} → {today}")

    try:
        wellness = await fetch_wellness_delta(last_sync, today)
    except Exception as e:
        print(f"[data_agent] ошибка wellness: {e} — продолжаем с пустым delta")
        wellness = []

    try:
        activities = await fetch_activities_delta(last_sync, today)
    except Exception as e:
        print(f"[data_agent] ошибка activities: {e} — продолжаем с пустым delta")
        activities = []

    if wellness:
        save_wellness(wellness)
    if activities:
        save_activities(activities)
    if wellness or activities:
        set_last_sync(today)

    print(f"[data_agent] wellness: {len(wellness)}, activities: {len(activities)}")
    return {
        "date":             today,
        "wellness_delta":   wellness,
        "activities_delta": activities,
    }


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    today = date.today().isoformat()
    last  = get_last_sync()

    print(f"Delta: {last} → {today}")
    w = asyncio.run(fetch_wellness_delta(last, today))
    a = asyncio.run(fetch_activities_delta(last, today))

    print(f"\nWellness ({len(w)} записей):")
    for d in w[-5:]:
        ctl  = d.get("ctl") or 0
        atl  = d.get("atl") or 0
        print(f"  {d['id']}: CTL={ctl:.1f} ATL={atl:.1f} Form={ctl-atl:+.1f} "
              f"HRV={d.get('hrv')} RHR={d.get('restingHR')} Sleep={d.get('sleepScore')}")

    print(f"\nActivities ({len(a)} записей):")
    for act in a[-3:]:
        print(f"  {act.get('start_date_local','')[:10]} {act.get('name')} "
              f"load={act.get('icu_training_load')} hr={act.get('average_heartrate')}")
