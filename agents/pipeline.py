"""
pipeline.py — LangGraph граф, точка входа.

Граф:
  data → metrics → garmin_plan → context → coach
         coach ──┬── [score ≤ 5] → garmin_rt → plan
                 └── [score > 5] ──────────────→ plan
                                  plan → hydration → synthesis → telegram → END

По воскресеньям вечером: + memory_agent (перезапись ATHLETE_MEMORY.md).

Запуск:
  uv run pipeline.py           # полный пайплайн
  uv run pipeline.py --dry     # без отправки в Telegram

Защита от параллельного запуска: файловый lock (.pipeline.lock).
"""

import asyncio
import fcntl
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

load_dotenv()

# ── Импорт агентов ────────────────────────────────────────────────────────────

from coach_agent import coach_agent_fn
from context_agent import context_agent_fn
from data_agent import data_agent_fn, init_db
from garmin_agent import garmin_plan_fn, garmin_rt_fn
from hydration_agent import hydration_fn
from memory_agent import memory_agent_fn
from metrics import metrics_fn, strength_load_today
from plan_agent import plan_agent_fn
from synthesis_agent import synthesis_fn
from telegram_bot import send_message


# ── State ─────────────────────────────────────────────────────────────────────

class CoachState(TypedDict, total=False):
    date: str

    # data_agent
    wellness_delta:   list[dict]
    activities_delta: list[dict]

    # metrics
    hrv_today:          float
    hrv_rolling_avg:    float
    hrv_deviation_pct:  float
    hrv_cv_week:        float
    acwr:               float
    acwr_zone:          str
    rhr_today:          float
    rhr_3d_avg:         float
    rhr_trend:          float
    rhr_rising:         bool
    adjusted_loads:     list[dict]
    days_since_quality: int
    z1z2_ratio_week:    float
    z1z2_compliant:     bool
    mesocycle_week:     int
    strength_load_today: float

    # garmin_agent
    upcoming_plan: list[dict]
    garmin_rt:     dict

    # context_agent
    context_flags:      list[str]
    athlete_memory:     str
    events_context:     str
    feedback_context:   str
    yesterday_analysis: str
    season_plan:        dict
    current_block:      str
    days_to_b_race:     int
    days_to_a_race:     int

    # coach_agent
    readiness:           str
    readiness_score:     float
    readiness_reasoning: str

    # plan_agent
    recommendation: dict

    # hydration_agent
    hydration_schedule: list[str]

    # synthesis_agent
    final_message: str
    analysis_json: dict

    # memory_agent
    athlete_memory_updated: bool


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _get_strength_state() -> tuple[str, bool]:
    """Читает последнюю запись strength_log из БД."""
    try:
        con = sqlite3.connect("coach.db")
        row = con.execute("""
            SELECT phase, completed FROM strength_log
            ORDER BY date DESC LIMIT 1
        """).fetchone()
        con.close()
        if row:
            return row[0], bool(row[1])
    except Exception:
        pass
    return "pre-race-c", False


def _save_recommendation_log(state: CoachState) -> None:
    """Сохраняет рекомендацию в recommendation_log для Memory Agent."""
    rec = state.get("recommendation") or {}
    try:
        con = sqlite3.connect("coach.db")
        con.execute("""
            INSERT OR REPLACE INTO recommendation_log
                (date, readiness, readiness_score, recommendation_type, recommendation_text)
            VALUES (?, ?, ?, ?, ?)
        """, (
            state.get("date"),
            state.get("readiness"),
            state.get("readiness_score"),
            rec.get("type"),
            rec.get("description"),
        ))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[pipeline] ошибка сохранения recommendation_log: {e}")


def _feedback_loop(state: CoachState) -> None:
    """
    Оценивает вчерашнюю рекомендацию: записывает hrv_next_day в recommendation_log.
    Вызывается до основного пайплайна, пока wellness уже загружен.
    """
    today      = state.get("date", "")
    yesterday  = ""
    try:
        from datetime import timedelta
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    except Exception:
        return

    wellness = state.get("wellness_delta") or []
    today_hrv = next(
        (w.get("hrv") for w in wellness if (w.get("id") or "")[:10] == today),
        None
    )
    if today_hrv is None:
        return

    try:
        con = sqlite3.connect("coach.db")
        con.execute("""
            UPDATE recommendation_log SET hrv_next_day = ?
            WHERE date = ? AND hrv_next_day IS NULL
        """, (today_hrv, yesterday))
        con.commit()
        con.close()
        print(f"[pipeline] feedback_loop: hrv_next_day={today_hrv} → {yesterday}")
    except Exception as e:
        print(f"[pipeline] feedback_loop ошибка: {e}")


# ── Узлы графа ────────────────────────────────────────────────────────────────

def node_data(state: CoachState) -> CoachState:
    print("\n[pipeline] ── data_agent ──")
    return asyncio.run(data_agent_fn(state))


def node_metrics(state: CoachState) -> CoachState:
    print("[pipeline] ── metrics ──")
    result = metrics_fn(state)

    # Дополняем силовой нагрузкой из strength_log
    phase, completed = _get_strength_state()
    result["strength_load_today"] = strength_load_today(phase, completed)

    return result


def node_garmin_plan(state: CoachState) -> CoachState:
    print("[pipeline] ── garmin_plan ──")
    return garmin_plan_fn(state)


def node_context(state: CoachState) -> CoachState:
    print("[pipeline] ── context_agent ──")
    return context_agent_fn(state)


def node_coach(state: CoachState) -> CoachState:
    print("[pipeline] ── coach_agent ──")
    return coach_agent_fn(state)


def node_garmin_rt(state: CoachState) -> CoachState:
    print("[pipeline] ── garmin_rt (пограничный readiness) ──")
    return garmin_rt_fn(state)


def node_plan(state: CoachState) -> CoachState:
    print("[pipeline] ── plan_agent ──")
    return plan_agent_fn(state)


def node_hydration(state: CoachState) -> CoachState:
    print("[pipeline] ── hydration_agent ──")
    return hydration_fn(state)


def node_synthesis(state: CoachState) -> CoachState:
    print("[pipeline] ── synthesis_agent ──")
    return synthesis_fn(state)


def node_telegram(state: CoachState) -> CoachState:
    """Отправляет final_message в Telegram."""
    print("[pipeline] ── telegram ──")
    msg = state.get("final_message", "")
    if not msg:
        print("[pipeline] нет сообщения для отправки")
        return state

    dry_run = os.getenv("PIPELINE_DRY_RUN", "0") == "1"
    if dry_run:
        print("[pipeline] DRY RUN — сообщение не отправляется:")
        print("─" * 50)
        print(msg)
        print("─" * 50)
    else:
        asyncio.run(send_message(msg))

    _save_recommendation_log(state)
    return state


# ── Routing ───────────────────────────────────────────────────────────────────

def route_garmin_rt(state: CoachState) -> str:
    """
    Garmin real-time только при пограничном readiness_score ≤ 5.0.
    Экономит API-запросы к Garmin при очевидных решениях.
    """
    score = state.get("readiness_score", 6.0)
    if score <= 5.0:
        print(f"[pipeline] route → garmin_rt (score={score})")
        return "garmin_rt"
    print(f"[pipeline] route → plan напрямую (score={score})")
    return "plan"


# ── Построение графа ──────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(CoachState)

    g.add_node("data",        node_data)
    g.add_node("metrics",     node_metrics)
    g.add_node("garmin_plan", node_garmin_plan)
    g.add_node("context",     node_context)
    g.add_node("coach",       node_coach)
    g.add_node("garmin_rt",   node_garmin_rt)
    g.add_node("plan",        node_plan)
    g.add_node("hydration",   node_hydration)
    g.add_node("synthesis",   node_synthesis)
    g.add_node("telegram",    node_telegram)

    g.set_entry_point("data")

    g.add_edge("data",        "metrics")
    g.add_edge("metrics",     "garmin_plan")
    g.add_edge("garmin_plan", "context")
    g.add_edge("context",     "coach")

    g.add_conditional_edges(
        "coach",
        route_garmin_rt,
        {"garmin_rt": "garmin_rt", "plan": "plan"},
    )

    g.add_edge("garmin_rt", "plan")
    g.add_edge("plan",      "hydration")
    g.add_edge("hydration", "synthesis")
    g.add_edge("synthesis", "telegram")
    g.add_edge("telegram",  END)

    return g.compile()


# ── Файловый lock (защита от параллельных запусков) ───────────────────────────

LOCK_PATH = Path(".pipeline.lock")


class PipelineLock:
    def __enter__(self):
        self._f = open(LOCK_PATH, "w")
        try:
            fcntl.flock(self._f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._f.close()
            raise RuntimeError(
                "Пайплайн уже запущен (.pipeline.lock занят). "
                "Удалите файл вручную если процесс завис."
            )
        return self

    def __exit__(self, *_):
        fcntl.flock(self._f, fcntl.LOCK_UN)
        self._f.close()
        LOCK_PATH.unlink(missing_ok=True)


# ── Основная функция ──────────────────────────────────────────────────────────

def run_pipeline(dry_run: bool = False) -> CoachState:
    if dry_run:
        os.environ["PIPELINE_DRY_RUN"] = "1"
        print("[pipeline] режим DRY RUN (без отправки в Telegram)")

    init_db()

    start = datetime.now()
    today = date.today().isoformat()
    print(f"\n{'='*55}")
    print(f"  Agentic Coach · {today}  {start.strftime('%H:%M')}")
    print(f"{'='*55}")

    graph      = build_graph()
    init_state: CoachState = {"date": today}

    final_state: CoachState = graph.invoke(init_state)

    # feedback_loop: hrv_next_day вчерашней рекомендации
    _feedback_loop(final_state)

    # Memory Agent — только по воскресеньям (weekday 6)
    if date.today().weekday() == 6:
        print("\n[pipeline] воскресенье → memory_agent")
        memory_agent_fn(final_state)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{'='*55}")
    print(f"  Готово за {elapsed:.1f}с · readiness={final_state.get('readiness')} "
          f"({final_state.get('readiness_score')})")
    print(f"{'='*55}\n")

    return final_state


# ── Точка входа ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    dry = "--dry" in sys.argv

    try:
        with PipelineLock():
            result = run_pipeline(dry_run=dry)
    except RuntimeError as e:
        print(f"[pipeline] ⛔ {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[pipeline] прерван пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"[pipeline] ❌ неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
