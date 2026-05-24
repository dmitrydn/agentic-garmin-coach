"""
telegram_bot.py — отправка Telegram-сообщения + сбор ответов на вечерний опрос.

Два крон-задания, никакого демона:
  0 7  * * *  uv run agents/pipeline.py          ← утренний брифинг (вызывает send_message)
  0 21 * * *  uv run agents/telegram_bot.py poll  ← отправить вечерний опрос

Ответы атлета хранятся в очереди Telegram до утра.
context_agent вызывает collect_poll_response() при старте пайплайна — забирает
callback-данные через getUpdates и подтверждает их offset-ом.

Standalone:
  uv run agents/telegram_bot.py          → тестовое утреннее сообщение
  uv run agents/telegram_bot.py poll     → отправить вечерний опрос прямо сейчас
  uv run agents/telegram_bot.py fetch    → забрать ответы из очереди (тест)
"""

import asyncio
import logging
import os
import sqlite3
from datetime import date, timedelta

from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

logging.basicConfig(
    format="%(asctime)s [telegram_bot] %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)


# ── Send ──────────────────────────────────────────────────────────────────────

async def send_message(text: str) -> None:
    """Отправить сообщение атлету. Используется из pipeline.py."""
    app = Application.builder().token(BOT_TOKEN).build()
    async with app:
        await app.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=None)
    print(f"[telegram_bot] отправлено, {len(text)} символов")


# ── Evening poll ──────────────────────────────────────────────────────────────

async def send_evening_poll() -> None:
    """
    Отправляет вечерний опрос с inline-кнопками. Запускается cron в 21:00.
    Шаг 1 — RPE 1–10. Шаг 2 — усталость ног 1–5.
    Ответы остаются в очереди Telegram до утреннего пайплайна.
    """
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=f"poll_rpe:{i}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"poll_rpe:{i}") for i in range(6, 11)],
    ]
    app = Application.builder().token(BOT_TOKEN).build()
    async with app:
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "Дмитрий, как прошёл сегодняшний день?\n\n"
                "Оцени субъективное усилие (RPE):\n"
                "1 = совсем легко  ·  10 = максимально тяжело"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        keyboard2 = [[
            InlineKeyboardButton(str(i), callback_data=f"poll_legs:{i}")
            for i in range(1, 6)
        ]]
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text="Оцени усталость ног:\n1 = лёгкие  ·  5 = очень тяжёлые",
            reply_markup=InlineKeyboardMarkup(keyboard2),
        )
    print("[telegram_bot] вечерний опрос отправлен")


# ── Fetch poll response ───────────────────────────────────────────────────────

async def _async_fetch_poll_response() -> dict | None:
    """
    Читает необработанные обновления из Telegram getUpdates.
    Извлекает последние poll_rpe и poll_legs из callback_query.
    Подтверждает все обновления (offset = last_id + 1) — очередь очищается.
    """
    bot = Bot(token=BOT_TOKEN)
    async with bot:
        updates = await bot.get_updates(timeout=5, limit=100)
        if not updates:
            return None

        rpe, legs = None, None
        last_id = updates[-1].update_id

        for upd in updates:
            cq = upd.callback_query
            if not cq or not cq.message or cq.message.chat.id != CHAT_ID:
                continue
            data = cq.data or ""
            if data.startswith("poll_rpe:"):
                rpe = int(data.split(":")[1])
            elif data.startswith("poll_legs:"):
                legs = int(data.split(":")[1])

        # Подтверждаем все обновления — иначе завтра они появятся снова
        await bot.get_updates(offset=last_id + 1, timeout=1)

    if rpe is None and legs is None:
        return None
    return {"rpe": rpe, "legs": legs}


def collect_poll_response(today: str) -> dict | None:
    """
    Sync-обёртка для вызова из context_agent (07:00).
    Забирает ответы на вчерашний вечерний опрос, сохраняет в БД.
    Возвращает {"rpe": int|None, "legs": int|None} или None.
    """
    poll = asyncio.run(_async_fetch_poll_response())
    if poll:
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        _save_poll_to_db(yesterday, poll.get("rpe"), poll.get("legs"))
        print(f"[telegram_bot] poll получен: {poll}")
    else:
        print("[telegram_bot] poll: ответов нет")
    return poll


def _save_poll_to_db(yesterday: str, rpe: int | None, legs: int | None) -> None:
    """Сохраняет RPE и усталость ног в recommendation_log и strength_log."""
    con = sqlite3.connect("coach.db")
    if rpe is not None:
        con.execute("""
            INSERT INTO recommendation_log (date, actual_rpe) VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET actual_rpe=excluded.actual_rpe
        """, (yesterday, rpe))
    if legs is not None:
        con.execute("""
            INSERT INTO strength_log (date, legs_heaviness_next_day) VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET
                legs_heaviness_next_day=excluded.legs_heaviness_next_day
        """, (yesterday, legs))
    con.commit()
    con.close()


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "send"

    if mode == "poll":
        asyncio.run(send_evening_poll())
    elif mode == "fetch":
        result = collect_poll_response(date.today().isoformat())
        print(f"fetch result: {result}")
    else:
        test_text = (
            "⚠️ Умеренная готовность\n\n"
            "HRV чуть ниже baseline (-3%), ACWR оптимальный 1.05.\n\n"
            "ТРЕНИРОВКА: лёгкий бег 50 мин в Z1-Z2, пульс 120-135.\n"
            "Первые 10 мин разминка Z1, основная часть Z2, последние 5 мин заминка.\n\n"
            "ГИДРАЦИЯ: 350мл до бега · 200мл на 15-й мин · 200мл на 35-й мин · 500мл после\n\n"
            "После тренировки напиши: rpe 6"
        )
        asyncio.run(send_message(test_text))
