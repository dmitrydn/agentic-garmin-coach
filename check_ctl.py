import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Сразу грузим переменные
load_dotenv()
ID = os.getenv("INTERVALS_ATHLETE_ID")
KEY = os.getenv("INTERVALS_API_KEY")

# 2. Прямая проверка — если это не напечатается, значит .env не виден
print(f"--- Запуск. ID: {ID} ---")

# 3. Настройка параметров
auth = ("API_KEY", KEY)
date_limit = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
url = f"https://intervals.icu/api/v1/athlete/{ID}"

# 4. Запрос данных (без функций, просто поток)
try:
    print(f"Запрашиваю активности с {date_limit}...")
    r_a = requests.get(f"{url}/activities", auth=auth, params={"oldest": date_limit})
    r_w = requests.get(f"{url}/wellness", auth=auth, params={"oldest": date_limit})
    
    activities = r_a.json()
    wellness = r_w.json()
    
    print(f"Получено: {len(activities)} тренировок и {len(wellness)} записей велнеса")

    # Создаем карту велнеса
    w_map = {w.get('id'): w for w in wellness}

    print(f"{'ДАТА':<12} | {'W':<4} | {'G-LOAD':<6} | {'PWR-Ld':<6} | {'HR-Ld':<6} | {'SOURCE'}")
    print("-" * 60)
    
    for a in sorted(activities, key=lambda x: x.get('start_date_local', ''), reverse=True):
        dt = a.get('start_date_local', '')[:10]
        w = a.get('icu_average_watts') or 0
        g_load = a.get('icu_training_load') or 0 # То, что прислал Garmin
        
        # Прямые расчеты Intervals на основе твоих данных HRM-Pro
        pwr_load = a.get('icu_power_training_load') or 0 
        hr_load = a.get('icu_hr_training_load') or 0
        
        source = a.get('icu_load_source', '???')
        
        print(f"{dt:<12} | {w:>3}W | {g_load:<6} | {pwr_load:<6.1f} | {hr_load:<6.1f} | {source}")
except Exception as e:
    print(f"ПРОИЗОШЛА ОШИБКА: {e}")

print("--- Завершено ---")