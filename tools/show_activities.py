import os
import asyncio
import httpx
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

INTERVALS_ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID")
INTERVALS_API_KEY = os.getenv("INTERVALS_API_KEY")

async def count_activities():
    # Проверка на наличие ключей
    if not INTERVALS_ATHLETE_ID or not INTERVALS_API_KEY:
        print("Ошибка: Проверьте, что в .env файле заполнены ID и KEY")
        return

    start_date = "2025-09-10"
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    url = f"https://intervals.icu/api/v1/athlete/{INTERVALS_ATHLETE_ID}/activities"
    params = {
        "oldest": start_date,
        "newest": end_date
    }
    
    # Рекомендуемый способ авторизации для Intervals API
    auth = ("API_KEY", INTERVALS_API_KEY)

    async with httpx.AsyncClient(auth=auth) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status() # Выдаст ошибку, если статус не 200
            
            activities = response.json()
            count = len(activities)
            
            print(f"--- Результат анализа ---")
            print(f"Найдено активностей: {count}")
            
            if count > 0:
                print(f"{'Дата':<12} | {'Название':<25} | {'Набор':<7} | {'TSS':<5}")
                print("-" * 55)
                
                # Берем последние 5 для примера, чтобы не заспамить консоль
                print(f"{'Дата':<10} | {'Название':<15} | {'Мощность':<8} | {'Пульс':<7} | {'Нагрузка':<8} | {'EF'}")
                print("-" * 75)
                
                for act in activities[:5]:
                    name = act.get('name', 'Unknown')
                    date = act.get('start_date_local', '')[:10]
                    
                    avg_watts = act.get('icu_average_watts') or 0
                    avg_hr = act.get('average_heartrate') or 0
                    total_load = act.get('icu_training_load') or 0
                    
                    # Считаем EF сами, если API отдает 0
                    ef = act.get('efficiency_factor') or 0
                    if ef == 0 and avg_hr > 0:
                        # Обычно используется Normalized Power, но для базы Average Power тоже ок
                        ef = avg_watts / avg_hr

                    print(f"{date:<10} | {name[:15]:<15} | {avg_watts:>3}W      | HR: {avg_hr:>3} | Load: {total_load:<3} | EF: {ef:.2f}")



        except httpx.HTTPStatusError as e:
            print(f"Ошибка API: {e.response.status_code}")
        except Exception as e:
            print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(count_activities())
