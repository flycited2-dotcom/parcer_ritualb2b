"""Wikidata SPARQL: ритуальные организации в 4 регионах.

Включает типы: funeral home / ритуальная служба / крематорий / мастерская.
Возвращает: имя (ru), сайт, координаты, описание. Источник второстепенный
(размеченных в Wikidata ритуальных объектов мало), но дешёвый.
"""
import json
import os
import time
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request
from urllib.error import URLError, HTTPError

from utils.storage import save_item
from utils.http_retry import http_request

ENDPOINT = "https://query.wikidata.org/sparql"

CACHE_DIR = os.path.join("output", "cache")
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 дней

# P31 = instance of, P279 = subclass of, P131 = located in admin
# Регионы: Q15966495 = Республика Крым, Q42959 = Севастополь,
#          Q3697 = Запорожская обл., Q3699 = Херсонская обл.
# Типы (?root), проверены через wbsearchentities 2026-06-13:
#   Q1466031  = funeral home (похоронное бюро)
#   Q19833158 = funeral parlour (зал прощания)
#   Q157570   = crematorium (крематорий)
#   Q29586127 = funeral services industry (ритуальные услуги, отрасль)
# Старые коды были неверными: Q318296 = «похищение людей»,
# Q1149653 = «автоматизация зданий» — источник отдавал мусор/ноль.
SPARQL_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?typeLabel ?website WHERE {{
  ?item wdt:P31 ?type .
  ?type wdt:P279* ?root .
  VALUES ?root {{ wd:Q1466031 wd:Q19833158 wd:Q157570 wd:Q29586127 }}
  ?item wdt:P131* wd:{region} .
  OPTIONAL {{ ?item wdt:P856 ?website . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en". }}
}}
LIMIT 400
"""

REGIONS = ["Q15966495", "Q42959", "Q3697", "Q3699"]


def _cache_path(region: str) -> str:
    return os.path.join(CACHE_DIR, f"wikidata_{region}.json")


def _load_cache(region: str) -> list | None:
    path = _cache_path(region)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        age = time.time() - float(payload.get("fetched_at", 0))
        if age > CACHE_TTL_SECONDS:
            return None
        print(f"  [Wikidata] {region}: кэш age={int(age/3600)}ч < 7д, использую")
        return payload.get("data") or []
    except Exception as e:
        print(f"  [Wikidata] {region}: кэш повреждён ({e}), refetch")
        return None


def _save_cache(region: str, data: list) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        payload = {"fetched_at": time.time(), "data": data}
        tmp = _cache_path(region) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, _cache_path(region))
    except Exception as e:
        print(f"  [Wikidata] {region}: не сохранить кэш: {e}")


def _fetch_one(region: str) -> list:
    cached = _load_cache(region)
    if cached is not None:
        return cached
    sparql = SPARQL_TEMPLATE.format(region=region)
    qs = urlencode({"query": sparql, "format": "json"})
    url = f"{ENDPOINT}?{qs}"
    # WDQS периодически жёстко лимитирует (видели 429 «1 req / min»).
    # Поэтому свои длинные паузы, а не общий http_retry с секундными.
    for attempt in range(3):
        try:
            req = Request(url, headers={
                "User-Agent": "ritual_parser/1.0",
                "Accept": "application/sparql-results+json",
            })
            body = http_request(req, timeout=90, retries=0)
            data = json.loads(body.decode("utf-8"))
            rows = data.get("results", {}).get("bindings", [])
            _save_cache(region, rows)
            return rows
        except HTTPError as e:
            if e.code == 429 and attempt < 2:
                print(f"  [Wikidata] {region}: 429, ждём 70с (попытка {attempt + 1}/3)")
                time.sleep(70)
                continue
            print(f"  [Wikidata] {region} error: {e}")
            return []
        except (URLError, json.JSONDecodeError) as e:
            print(f"  [Wikidata] {region} error: {e}")
            return []
    return []


def _fetch():
    out = []
    for region in REGIONS:
        rows = _fetch_one(region)
        print(f"  [Wikidata] {region}: {len(rows)} строк")
        out.extend(rows)
    return out


def _val(b, k):
    v = b.get(k) or {}
    return v.get("value", "")


CITY_HINTS = (
    "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
    "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
    "Мелитополь", "Бердянск", "Энергодар", "Токмак", "Геническ",
    "Новая Каховка", "Каховка", "Скадовск", "Алёшки",
)


def _detect_city(name: str) -> str:
    for c in CITY_HINTS:
        if c.lower() in name.lower():
            return c
    return ""


async def run(context):
    print("\n=== Wikidata SPARQL ===")
    rows = _fetch()
    print(f"  получено объектов: {len(rows)}")

    added = 0
    for b in rows:
        name = _val(b, "itemLabel")
        if not name or name.startswith("Q"):  # без перевода — skip
            continue
        item = {
            "city": _detect_city(name),
            "name": name,
            "address": "",
            "phone": "",
            "email": "",
            "website": _val(b, "website"),
            "category": _val(b, "typeLabel") or "ритуальные услуги",
            "source": "Wikidata",
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if save_item(item):
            added += 1

    print(f"\n[Wikidata] добавлено: {added}")
