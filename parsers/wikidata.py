"""Wikidata SPARQL: размещения в Крыму и Севастополе.

Включает: hotel, resort, sanatorium, hostel, guest house, motel, etc.
Возвращает: имя (ru), сайт, координаты, описание.
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

# P31 = instance of, P279 = subclass of, P17 = country, P131 = located in admin
# Q15966495 = Crimea (subject of dispute), Q42959 = Sevastopol
# Q27686 = hotel, Q907311 = resort, Q822402 = sanatorium, Q26529 = hostel,
# Q1244442 = guest house, Q11707 = restaurant (skip), Q43229 = organization
SPARQL_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?typeLabel ?website WHERE {{
  ?item wdt:P31 ?type .
  ?type wdt:P279* ?root .
  VALUES ?root {{ wd:Q27686 wd:Q907311 wd:Q822402 wd:Q26529 wd:Q1244442 }}
  ?item wdt:P131* wd:{region} .
  OPTIONAL {{ ?item wdt:P856 ?website . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en". }}
}}
LIMIT 400
"""

REGIONS = ["Q15966495", "Q42959"]  # Республика Крым, Севастополь


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
    try:
        req = Request(url, headers={
            "User-Agent": "ritual_parser/1.0",
            "Accept": "application/sparql-results+json",
        })
        body = http_request(req, timeout=90)
        data = json.loads(body.decode("utf-8"))
        rows = data.get("results", {}).get("bindings", [])
        _save_cache(region, rows)
        return rows
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        print(f"  [Wikidata] {region} error: {e}")
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


CITY_HINTS = ("Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
              "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай")


def _detect_city(name: str) -> str:
    for c in CITY_HINTS:
        if c.lower() in name.lower():
            return c
    return "Крым"


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
            "category": _val(b, "typeLabel") or "размещение",
            "source": "Wikidata",
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if save_item(item):
            added += 1

    print(f"\n[Wikidata] добавлено: {added}")
