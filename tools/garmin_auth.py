"""
Одноразовый интерактивный логин в Garmin Connect.

Запускай вручную при первом запуске или после истечения токенов:
    uv run tools/garmin_auth.py

Что делает:
  1. Берёт GARMIN_EMAIL / GARMIN_PASSWORD из .env
  2. Если Garmin требует MFA — запрашивает код через stdin
  3. Сохраняет токены в .garmin_session/
  4. После этого garmin_agent.py использует сохранённые токены без логина и MFA

Повторный запуск нужен только если увидишь:
  [garmin_plan] недоступен: ... — значит токены протухли (обычно раз в год).
"""

import os
from pathlib import Path

import garminconnect
from dotenv import load_dotenv

load_dotenv()

SESSION_DIR = Path(__file__).parent.parent / ".garmin_session"


def main() -> None:
    email    = os.getenv("GARMIN_EMAIL", "")
    password = os.getenv("GARMIN_PASSWORD", "")

    if not email or not password:
        print("Ошибка: GARMIN_EMAIL и GARMIN_PASSWORD должны быть в .env")
        return

    print(f"Логин в Garmin Connect как {email}...")
    print("Если появится запрос MFA-кода — введи код из приложения/SMS.\n")

    api = garminconnect.Garmin(
        email,
        password,
        prompt_mfa=lambda: input("MFA code: "),
    )
    api.login(tokenstore=str(SESSION_DIR))

    name = api.get_full_name()
    print(f"\nУспешно. Привет, {name}!")
    print(f"Токены сохранены в {SESSION_DIR}/")
    print("\nГотово. garmin_agent.py теперь работает без повторного логина.")


if __name__ == "__main__":
    main()
