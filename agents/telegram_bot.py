"""
telegram_bot.py — отправка Telegram-сообщения + получение RPE-фидбека.

Два режима:
1. send_message(text) — отправить final_message атлету
2. Webhook/polling — получить фидбек после тренировки, сохранить в feedback.log и БД

Фидбек-формат (пишет атлет в чат):
  rpe 7
  rpe 6 устал больше обычного
  отдых (без тренировки)

Сохраняется в:
  feedback.log        — для context_agent (быстрое чтение)
  recommendation_log  — для memory_agent (еженедельный анализ)
"""

import logging
import os
import re
import sqlite3
from datetime import date

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

logging.basicConfig(
    format="%(asctime)s [telegram_bot] %(message)s",
    level=logging.INFO,
)


# ── Send ──────────────────────────────────────────────────────────────────────

async def send_message(text: str) -> None:
    """Отправить сообщение атлету. Используется из pipeline.py."""
    app = Application.builder().token(BOT_TOKEN).build()
    async with app:
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=text,
            parse_mode=None,   # plain text, без markdown
        )
    print(f"[telegram_bot] отправлено, {len(text)} символов")


# ── Feedback handlers ─────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает входящие сообщения от атлета."""
    if update.effective_chat.id != CHAT_ID:
        return  # игнорируем чужие чаты

    text    = (update.message.text or "").strip().lower()
    today   = date.today().isoformat()

    # Парсим RPE: "rpe 7", "rpe7", "rpe:7", "усилие 7"
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
        # Просто записываем как заметку
        _save_feedback(today, rpe=None, notes=text)
        await update.message.reply_text(
            "📝 Записал заметку. Для RPE напиши: rpe 7"
        )


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


# ── Save feedback ─────────────────────────────────────────────────────────────

def _save_feedback(today: str, rpe: int | None, notes: str) -> None:
    """Сохраняет в feedback.log и recommendation_log."""
    # feedback.log для context_agent
    with open("feedback.log", "a", encoding="utf-8") as f:
        line = f"{today} rpe={rpe}"
        if notes:
            line += f" notes={notes}"
        f.write(line + "\n")

    # recommendation_log для memory_agent.
    # INSERT OR REPLACE + ON CONFLICT — несовместимые механизмы в SQLite.
    # Используем чистый upsert: только actual_rpe, остальные поля не трогаем.
    con = sqlite3.connect("coach.db")
    con.execute("""
        INSERT INTO recommendation_log (date, actual_rpe)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET actual_rpe=excluded.actual_rpe
    """, (today, rpe))
    con.commit()
    con.close()

    print(f"[telegram_bot] фидбек сохранён: {today} rpe={rpe} notes={notes!r}")


# ── Polling bot ───────────────────────────────────────────────────────────────

def run_bot() -> None:
    """Запускает polling для получения фидбека. Запускать отдельно от pipeline."""
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("[telegram_bot] запуск polling...")
    app.run_polling()


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        # uv run agents/telegram_bot.py bot → запустить polling
        run_bot()
    else:
        # uv run agents/telegram_bot.py → отправить тестовое сообщение
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
