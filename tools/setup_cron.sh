#!/usr/bin/env bash
# Устанавливает cron-задания для пайплайна.
# Запуск: bash tools/setup_cron.sh
# Требует: uv установлен (проверяет автоматически).

set -euo pipefail

UV=$(command -v uv 2>/dev/null || true)
if [ -z "$UV" ]; then
    echo "Ошибка: uv не найден в PATH."
    echo "Установите: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# Удаляем старые задания этого проекта и добавляем новые
TMPFILE=$(mktemp)
(crontab -l 2>/dev/null | grep -v "agentic-garmin-coach" || true) > "$TMPFILE"
cat >> "$TMPFILE" <<EOF

# agentic-garmin-coach
0 7  * * *  cd $PROJECT_DIR && $UV run agents/pipeline.py >> $LOG_DIR/pipeline.log 2>&1
0 21 * * *  cd $PROJECT_DIR && $UV run agents/telegram_bot.py poll >> $LOG_DIR/bot.log 2>&1
EOF

crontab "$TMPFILE"
rm "$TMPFILE"

echo "Cron установлен:"
crontab -l | grep "agentic-garmin-coach"
