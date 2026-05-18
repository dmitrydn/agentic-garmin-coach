import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загрузка окружения
load_dotenv()

def get_intervals_data():
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    api_key = os.getenv("INTERVALS_API_KEY")
    
    if not athlete_id or not api_key:
        print("Ошибка: Проверьте INTERVALS_ATHLETE_ID и INTERVALS_API_KEY в .env")
        return

    auth = ("API_KEY", api_key)
    # Берем за последние 14 дней
    oldest = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    
    base_url = f"https://intervals.icu/api/v1/athlete/{athlete_id}"
    
    try:
        # 1. Получаем активности
        print(f"Загрузка данных для атлета {athlete_id}...")
        r_acts = requests.get(f"{base_url}/activities", auth=auth, params={"oldest": oldest})
        r_acts.raise_for_status()
        activities = r_acts.json()

        # 2. Получаем велнес
        r_well = requests.get(f"{base_url}/wellness", auth=auth, params={"oldest": oldest})
        r_well.raise_for_status()
        wellness = r_well.json()

        # Создаем мапу велнеса {дата: данные}
        well_map = {w.get('id'): w for w in wellness}

        # Печать заголовка
        header = f"{'ДАТА':<12} | {'НАЗВАНИЕ':<15} | {'W':<5} | {'HR':<3} | {'LOAD':<4} | {'EF':<4} | {'FORM':<6} | {'HRV'}"
        print("\n" + header)
        print("-" * len(header))

        # Сортируем активности по дате (свежие вверху)
        for act in sorted(activities, key=lambda x: x.get('start_date_local', ''), reverse=True):
            full_date = act.get('start_date_local', '')
            date_str = full_date[:10] # Отрезаем время
            
            # Данные тренировки
            name = act.get('name', 'Unknown')[:15]
            watts = act.get('icu_average_watts') or 0
            hr = act.get('average_heartrate') or 0
            load = act.get('icu_training_load') or 0
            
            # Данные велнеса на этот день
            day_well = well_map.get(date_str, {})
            ctl = day_well.get('ctl') or 0
            atl = day_well.get('atl') or 0
            hrv = day_well.get('hrv') or '-'
            
            # Считаем EF и Form вручную
            ef = act.get('efficiency_factor') or (watts / hr if hr > 0 else 0)
            form = day_well.get('form') if day_well.get('form') is not None else (ctl - atl)

            print(f"{date_str:<12} | {name:<15} | {watts:>3}W  | {hr:>3} | {load:<4} | {ef:.2f} | {form:<+6.1f} | {hrv}")

    except Exception as e:
        print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    get_intervals_data()