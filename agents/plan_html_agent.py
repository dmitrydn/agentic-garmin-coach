"""
plan_html_agent.py — рендерит plans/gauja_90k_2026.md в статичный HTML.

Чистый Python, ноль LLM-токенов. Перегенерируется на каждый прогон
pipeline.py — дёшево (одно чтение файла, без сети), и гарантирует, что
отметка "сегодня" и обратный отсчёт до A-race всегда свежие, а любое
редактирование плана (трав­ма, изменение восстановления, отмена гонки)
видно в HTML сразу после следующего запуска пайплайна — без отдельного
шага синхронизации.

Запуск standalone: uv run agents/plan_html_agent.py
"""

from datetime import date, timedelta
from pathlib import Path

from context_agent import block_for_date, load_plan_config, to_date_str
from koop_plan_agent import entry_for_date

OUTPUT_PATH = Path(__file__).parent.parent / "plans" / "gauja_90k_2026.html"

_BLOCK_LABELS = {
    "recovery": "Recovery",
    "build_a":  "Build A",
    "build_b":  "Build B",
    "build_c":  "Build C",
    "taper":    "Taper",
    "a_race":   "A-RACE",
}
_BLOCK_COLORS = {
    "recovery": "#6b7280",
    "build_a":  "#2563eb",
    "build_b":  "#dc2626",
    "build_c":  "#7c3aed",
    "taper":    "#0891b2",
    "a_race":   "#ca8a04",
}
_TYPE_BADGES = {
    "rest":          ("Покой",        "#4b5563"),
    "easy":          ("Легко",        "#3b82f6"),
    "quality":       ("Качество",     "#f97316"),
    "long":          ("Длинный",      "#16a34a"),
    "strength":      ("Силовая",      "#9333ea"),
    "race":          ("СТАРТ",        "#ca8a04"),
    "back-to-back":  ("Back-to-back", "#0ea5e9"),
}
_WEEKDAY_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# ── Data assembly ──────────────────────────────────────────────────────────────

def _collect_calendar(config: dict) -> list[dict]:
    """Полный календарь от начала самого раннего блока до дня A-race включительно."""
    schedule = config.get("block_schedule", {})
    starts = [date.fromisoformat(to_date_str(b["start"])) for b in schedule.values() if "start" in b]
    if not starts:
        return []
    start       = min(starts)
    a_race_date = date.fromisoformat(to_date_str(config["a_race"]["date"]))

    days = []
    d = start
    while d <= a_race_date:
        days.append({
            "date":    d,
            "weekday": _WEEKDAY_RU[d.weekday()],
            "block":   block_for_date(config, d) or "unknown",
            "entry":   entry_for_date(config, d),
        })
        d += timedelta(days=1)
    return days


def _group_by_block(days: list[dict]) -> list[dict]:
    groups: list[dict] = []
    current = None
    for day in days:
        if current is None or current["block"] != day["block"]:
            current = {"block": day["block"], "days": []}
            groups.append(current)
        current["days"].append(day)
    return groups


# ── HTML rendering ──────────────────────────────────────────────────────────────

def _day_card(day: dict, today: date) -> str:
    entry = day["entry"]
    d = day["date"]
    classes = "day"
    if d == today:
        classes += " today"
    elif d < today:
        classes += " past"

    if not entry:
        return f"""<div class="{classes}"><div class="day-head">
          <span class="day-date">{d.strftime('%d.%m')} {day['weekday']}</span>
        </div></div>"""

    label, color = _TYPE_BADGES.get(entry.get("type"), (entry.get("type") or "?", "#4b5563"))
    dur_min = entry.get("duration_min")
    dur = f"{dur_min} мин" if dur_min else ("СТАРТ" if entry.get("type") == "race" else "")
    desc = entry.get("description") or ""

    return f"""<div class="{classes}">
      <div class="day-head">
        <span class="day-date">{d.strftime('%d.%m')} {day['weekday']}</span>
        <span class="badge" style="background:{color}">{label}</span>
        <span class="day-dur">{dur}</span>
      </div>
      <div class="day-desc">{desc}</div>
    </div>"""


def _block_section(group: dict, config: dict, today: date) -> str:
    block = group["block"]
    label = _BLOCK_LABELS.get(block, block)
    color = _BLOCK_COLORS.get(block, "#4b5563")
    days  = group["days"]
    date_range = f"{days[0]['date'].strftime('%d.%m')} – {days[-1]['date'].strftime('%d.%m')}"

    target = (config.get("weekly_targets") or {}).get(block) or {}
    target_html = ""
    if target:
        target_html = (
            f'<span class="target">цель: {target.get("target_minutes", "?")} мин · '
            f'{target.get("target_tss", "?")} TSS · {target.get("target_vert_m", "?")} м D+</span>'
        )

    cards = "\n".join(_day_card(day, today) for day in days)
    return f"""<section class="block" style="border-left-color:{color}">
      <div class="block-head">
        <h2 style="color:{color}">{label}</h2>
        <span class="block-range">{date_range} · {len(days)} дн.</span>
        {target_html}
      </div>
      <div class="days-grid">{cards}</div>
    </section>"""


_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; background: #0f1115; color: #e5e7eb;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.container { max-width: 960px; margin: 0 auto; }
header { margin-bottom: 28px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.subtitle { color: #9ca3af; font-size: 14px; }
.countdown {
  display: inline-block; margin-top: 12px; padding: 10px 18px;
  background: linear-gradient(135deg,#ca8a04,#92400e); border-radius: 10px;
  font-weight: 600; font-size: 15px; color: #fff;
}
.block {
  background: #161a22; border-left: 4px solid; border-radius: 8px;
  padding: 16px 20px; margin-bottom: 18px;
}
.block-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.block-head h2 { font-size: 17px; margin: 0; }
.block-range { color: #9ca3af; font-size: 13px; }
.target { color: #6b7280; font-size: 12px; margin-left: auto; }
.days-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px,1fr)); gap: 8px; }
.day {
  background: #1f2430; border-radius: 6px; padding: 10px 12px; font-size: 13px;
  border: 1px solid transparent;
}
.day.today { border-color: #facc15; background: #2a2510; }
.day.past { opacity: 0.4; }
.day-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.day-date { font-weight: 600; color: #d1d5db; }
.badge { font-size: 11px; padding: 2px 7px; border-radius: 10px; color: white; font-weight: 600; }
.day-dur { margin-left: auto; color: #9ca3af; font-size: 12px; }
.day-desc { color: #9ca3af; line-height: 1.4; }
footer { margin-top: 24px; color: #4b5563; font-size: 12px; text-align: center; }
"""


def _render_html(config: dict, days: list[dict], today: date) -> str:
    groups = _group_by_block(days)
    a_race = config.get("a_race") or {}
    a_race_date = date.fromisoformat(to_date_str(a_race["date"]))
    days_to_race = (a_race_date - today).days

    sections = "\n".join(_block_section(g, config, today) for g in groups)
    race_name = a_race.get("name", "Training Plan")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{race_name} — план подготовки</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>{race_name}</h1>
    <div class="subtitle">{a_race.get('distance_km', '?')} km / {a_race.get('elevation_gain_m', '?')} м D+ · {a_race_date.strftime('%d.%m.%Y')}</div>
    <div class="countdown">{days_to_race} дней до старта</div>
  </header>
  {sections}
  <footer>Сгенерировано автоматически из plans/gauja_90k_2026.md · {today.strftime('%d.%m.%Y')}</footer>
</div>
</body>
</html>"""


# ── LangGraph node ────────────────────────────────────────────────────────────

def render_plan_html_fn(state: dict | None = None) -> dict:
    """Python, ноль LLM-токенов. Перегенерирует plans/gauja_90k_2026.html."""
    config = load_plan_config()
    if not config:
        print("[plan_html] не удалось прочитать план — HTML не обновлён")
        return {}

    today = date.today()
    days  = _collect_calendar(config)
    if not days:
        print("[plan_html] block_schedule пуст — HTML не обновлён")
        return {}

    html = _render_html(config, days, today)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"[plan_html] обновлён {OUTPUT_PATH} ({len(days)} дней)")
    return {}


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    render_plan_html_fn()
