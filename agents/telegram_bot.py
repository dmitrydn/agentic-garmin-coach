"""
telegram_bot.py — отправка Telegram-сообщения + получение RPE-фидбека.

Три режима:
1. send_message(text)   — отправить final_message атлету (из pipeline.py)
2. send_evening_poll()  — отправить вечерний опрос RPE+ноги (standalone/pipeline)
3. run_bot()            — постоянный процесс: polling + CallbackQuery + job queue 21:00

Форматы feedback.log:
  Ручной текст:   YYYY-MM-DD rpe=N notes=текст
  Telegram-опрос: YYYY-MM-DDThh:mm:ss | TYPE: TELEGRAM_POLL | RPE: N | LEGS_HEAVINESS: N

Запуск:
  uv run agents/telegram_bot.py          → тестовое утреннее сообщение
  uv run agents/telegram_bot.py poll     → отправить вечерний опрос прямо сейчас
  uv run agents/telegram_bot.py bot      → запустить бота-демона
"""

import datetime
import logging
import os
import re
import sqlite3
from datetime import date

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

logging.basicConfig(
    format="%(asctime)s [telegram_bot] %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# RPE, выбранный на первом шаге опроса. Сбрасывается при рестарте процесса.
_poll_state: dict[int, dict] = {}


# ── Send ──────────────────────────────────────────────────────────────────────

async def send_message(text: str) -> None:
    """Отправить сообщение атлету. Используется из pipeline.py."""
    app = Application.builder().token(BOT_TOKEN).build()
    async with app:
        await app.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=None)
    print(f"[telegram_bot] отправлено, {len(text)} символов")


# ── Evening poll ──────────────────────────────────────────────────────────────

async def send_evening_poll_message(bot) -> None:
    """Отправляет вечерний опрос с inline-кнопками RPE 1–10."""
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=f"poll_rpe:{i}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"poll_rpe:{i}") for i in range(6, 11)],
    ]
    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Дмитрий, как прошёл сегодняшний день?\n\n"
            "Оцени субъективное усилие (RPE):\n"
            "1 = совсем легко  ·  10 = максимально тяжело"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    print("[telegram_bot] вечерний опрос отправлен")


async def send_evening_poll() -> None:
    """Standalone-вызов: отправить вечерний опрос без polling."""
    app = Application.builder().token(BOT_TOKEN).build()
    async with app:
        await send_evening_poll_message(app.bot)


# ── Poll callback handler ─────────────────────────────────────────────────────

_LEGS_LABEL = ["", "лёгкие", "немного тяжёлые", "умеренные", "тяжёлые", "очень тяжёлые"]


async def handle_poll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Двухшаговый опрос:
      Шаг 1. Атлет нажимает RPE → сохраняем в _poll_state, редактируем сообщение на кнопки ног.
      Шаг 2. Атлет нажимает Legs → сохраняем оба значения, показываем финальный текст.
    """
    query = update.callback_query
    if query.message.chat.id != CHAT_ID:
        await query.answer()
        return

    await query.answer("Данные приняты ✅")

    data  = query.data or ""
    today = date.today().isoformat()

    if data.startswith("poll_rpe:"):
        rpe = int(data.split(":")[1])
        _poll_state[CHAT_ID] = {"rpe": rpe}

        keyboard = [[
            InlineKeyboardButton(str(i), callback_data=f"poll_legs:{i}")
            for i in range(1, 6)
        ]]
        await query.edit_message_text(
            text=(
                f"RPE: {rpe} ✅\n\n"
                "Теперь оцени усталость ног:\n"
                "1 = лёгкие  ·  5 = очень тяжёлые"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("poll_legs:"):
        legs = int(data.split(":")[1])
        rpe  = _poll_state.pop(CHAT_ID, {}).get("rpe")

        _save_poll_feedback(today, rpe, legs)

        await query.edit_message_text(
            text=(
                "Записал ✅\n\n"
                f"RPE: {rpe}  |  Ноги: {legs} — {_LEGS_LABEL[legs]}\n\n"
                "Спокойной ночи, Дмитрий!"
            )
        )


# ── Text feedback handlers ────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ручной ввод атлета: rpe 7, отдых, заметки."""
    if update.effective_chat.id != CHAT_ID:
        return

    text  = (update.message.text or "").strip().lower()
    today = date.today().isoformat()

    rpe_match = re.search(r"(?:rpe|усилие)[:\s]*(\d+)", text)
    notes     = re.sub(r"(?:rpe|усилие)[:\s]*\d+", "", text).strip()

    if rpe_match:
        rpe = int(rpe_match.group(1))
        _save_feedback(today, rpe, notes)
        await update.message.reply_text(
            f"✅ Записал: RPE {rpe}" + (f" — {notes}" if notes else "")
        )
    elif "отдых" in text or "не бежал" in text or "пропустил" in text:
        _save_feedback(today, rpe=None, notes="пропущено: " + text)
        await update.message.reply_text("📝 Записал: тренировка пропущена")
    else:
        _save_feedback(today, rpe=None, notes=text)
        await update.message.reply_text("📝 Записал заметку. Для RPE напиши: rpe 7")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — последние 3 записи из recommendation_log."""
    if update.effective_chat.id != CHAT_ID:
        return
    con = sqlite3.connect("coach.db")
    rows = con.execute("""
        SELECT date, readiness, readiness_score, recommendation_type, actual_rpe
        FROM recommendation_log ORDER BY date DESC LIMIT 3
    """).fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("Данных пока нет.")
        return

    lines = ["Последние записи:"]
    for r in rows:
        rpe_str = f"RPE={r[4]}" if r[4] else "RPE не записан"
        lines.append(f"{r[0]}: {r[1]} ({r[2]}) → {r[3]} | {rpe_str}")
    await update.message.reply_text("\n".join(lines))


# ── Save helpers ──────────────────────────────────────────────────────────────

def _save_feedback(today: str, rpe: int | None, notes: str) -> None:
    """Сохраняет ручной ввод в feedback.log и recommendation_log."""
    with open("feedback.log", "a", encoding="utf-8") as f:
        line = f"{today} rpe={rpe}"
        if notes:
            line += f" notes={notes}"
        f.write(line + "\n")

    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO recommendation_log (date, actual_rpe)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET actual_rpe=excluded.actual_rpe
    """, (today, rpe))
    con.commit()
    con.close()

    print(f"[telegram_bot] фидбек сохранён: {today} rpe={rpe} notes={notes!r}")


def _save_poll_feedback(today: str, rpe: int | None, legs: int | None) -> None:
    """Сохраняет данные вечернего опроса в feedback.log, recommendation_log, strength_log."""
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open("feedback.log", "a", encoding="utf-8") as f:
        f.write(f"{ts} | TYPE: TELEGRAM_POLL | RPE: {rpe} | LEGS_HEAVINESS: {legs}\n")

    con = sqlite3.connect("coach.db")
    if rpe is not None:
        con.execute("""
            INSERT INTO recommendation_log (date, actual_rpe)
            VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET actual_rpe=excluded.actual_rpe
        """, (today, rpe))
    if legs is not None:
        # Только legs_heaviness_next_day; остальные поля strength_log остаются NULL.
        con.execute("""
            INSERT INTO strength_log (date, legs_heaviness_next_day)
            VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET
                legs_heaviness_next_day=excluded.legs_heaviness_next_day
        """, (today, legs))
    con.commit()
    con.close()

    print(f"[telegram_bot] вечерний опрос сохранён: {today} rpe={rpe} legs={legs}")


# ── Polling bot ───────────────────────────────────────────────────────────────

async def _job_evening_poll(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job Queue: вызывается каждый день в 21:00."""
    await send_evening_poll_message(context.bot)


def run_bot() -> None:
    """
    Запускает бота как постоянный процесс (polling + job queue).

    Архитектура на Малинке:
      - pipeline.py запускается cron в 07:00 → отправляет утренний брифинг через send_message()
      - telegram_bot.py bot запускается один раз при старте системы и работает постоянно:
          * принимает ручной RPE-фидбек от атлета (текстом)
          * принимает нажатия inline-кнопок вечернего опроса
          * сам отправляет вечерний опрос в 21:00 через job_queue

    Автозапуск (добавить в crontab):
      @reboot sleep 10 && cd /path/to/project && uv run agents/telegram_bot.py bot >> logs/bot.log 2>&1 &

    Или через systemd (рекомендуется для стабильности):
      ExecStart=uv run agents/telegram_bot.py bot
    """
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CallbackQueryHandler(handle_poll_callback, pattern=r"^poll_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_daily(
        _job_evening_poll,
        time=datetime.time(21, 0, 0),
        name="evening_poll",
    )

    print("[telegram_bot] запуск polling + вечерний опрос 21:00 ежедневно...")
    app.run_polling()


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "send"

    if mode == "bot":
        run_bot()
    elif mode == "poll":
        # uv run agents/telegram_bot.py poll → отправить вечерний опрос прямо сейчас
        asyncio.run(send_evening_poll())
    else:
        test_text = (
            "⚠️ Умеренная готовность\n\n"
            "HRV чуть ниже baseline (-3%), ACWR оптимальный 1.05.\n\n"
            "ТРЕНИРОВКА: лёгкий бег 50 мин в Z1-Z2, пульс 120-135.\n"
            "Первые 10 мин разминка Z1, основная часть Z2, последние 5 мин заминка.\n\n"
            "ГИДРАЦИЯ: 350мл до бега · 200мл на 15-й мин · 200мл на 35-й мин · 500мл после\n\n"
            "**Ключевое:** не ускоряться на подъёмах, держать пульс ниже 140.\n\n"
            "После тренировки напиши: rpe 6"
        )
        asyncio.run(send_message(test_text))
