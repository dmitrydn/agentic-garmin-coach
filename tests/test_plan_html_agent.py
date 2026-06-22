"""
test_plan_html_agent.py — Layer I: plan_html_agent rendering correctness.

render_plan_html_fn must regenerate plans/gauja_90k_2026.html from the current
plans/gauja_90k_2026.md on every call, with no leftover state from a previous
run (today-marker and race countdown must reflect the date passed in, not a
stale cached render).
"""

from datetime import date

from context_agent import load_plan_config
from plan_html_agent import OUTPUT_PATH, _collect_calendar, _render_html, render_plan_html_fn


def _config():
    return load_plan_config()


def test_collect_calendar_spans_from_first_block_to_race_day():
    config = _config()
    days = _collect_calendar(config)
    assert days[0]["date"] == date(2026, 6, 22)
    assert days[-1]["date"] == date(2026, 8, 1)


def test_render_html_has_balanced_div_tags():
    config = _config()
    days = _collect_calendar(config)
    html = _render_html(config, days, date(2026, 6, 22))
    assert html.count("<div") == html.count("</div>")


def test_render_html_marks_today():
    config = _config()
    days = _collect_calendar(config)
    html = _render_html(config, days, date(2026, 7, 8))
    assert 'class="day today"' in html


def test_render_html_shows_race_day_badge():
    config = _config()
    days = _collect_calendar(config)
    html = _render_html(config, days, date(2026, 6, 22))
    assert "СТАРТ" in html


def test_render_plan_html_fn_writes_file(tmp_path, monkeypatch):
    target = tmp_path / "gauja_90k_2026.html"
    monkeypatch.setattr("plan_html_agent.OUTPUT_PATH", target)
    result = render_plan_html_fn({})
    assert result == {}
    assert target.exists()
    assert "<!DOCTYPE html>" in target.read_text(encoding="utf-8")
