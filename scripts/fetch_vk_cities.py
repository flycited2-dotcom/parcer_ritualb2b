"""Разовый скрипт: получить VK city_id для городов Запорожской/Херсонской обл.

VK API database.getCities(country_id=1, q=<name>). Печатает строки `id: "name",`
готовые к вставке в parsers/vk_groups.py:VK_CITIES. Нужен VK_TOKEN.

Запуск:  python scripts/fetch_vk_cities.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

try:
    from utils.env_loader import load_all_env
    load_all_env()
except Exception:
    pass

API = "https://api.vk.com/method"
V = "5.131"

# Только города под фактическим контролем РФ (спорная зона исключена).
CITIES = [
    # Запорожская обл.
    "Мелитополь", "Бердянск", "Энергодар", "Токмак", "Васильевка",
    "Каменка-Днепровская", "Приморск", "Молочанск", "Пологи", "Куйбышево",
    # Херсонская обл. (левобережье)
    "Геническ", "Новая Каховка", "Каховка", "Скадовск", "Алёшки",
    "Голая Пристань", "Чаплинка", "Новотроицкое", "Великая Лепетиха",
]


def _get_cities(token: str, q: str):
    params = {"country_id": 1, "q": q, "count": 5, "access_token": token, "v": V}
    url = f"{API}/database.getCities?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return [], str(e)
    if "error" in data:
        return [], data["error"].get("error_msg", "?")
    return data.get("response", {}).get("items", []), ""


def main() -> None:
    token = os.getenv("VK_TOKEN", "").strip()
    if not token:
        print("VK_TOKEN не задан (env / .env.vk). Прерываю.")
        sys.exit(1)

    print("# Скопируй нужные строки в parsers/vk_groups.py:VK_CITIES")
    for name in CITIES:
        items, err = _get_cities(token, name)
        time.sleep(0.34)  # VK ~3 rps
        if err:
            print(f'    # {name}: ошибка — {err}')
            continue
        if not items:
            print(f'    # {name}: не найдено')
            continue
        top = items[0]
        meta = " ".join(x for x in (top.get("region", ""), top.get("area", "")) if x)
        print(f'    {top["id"]}: "{name}",  # VK title: {top.get("title")} [{meta}]')


if __name__ == "__main__":
    main()
