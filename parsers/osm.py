"""OpenStreetMap Overpass API: tourism-объекты по полигону Крыма.

Один HTTP-запрос — JSON со всеми node/way/relation, у которых tourism=hotel|guest_house|...
В тегах напрямую: name, phone, email, website, addr:*.
"""
import json
import re
from datetime import datetime
from urllib.parse import urlparse
from urllib.request import Request

from utils.http_retry import http_request
from urllib.error import URLError, HTTPError

from utils.storage import save_item
from utils.geo_city import detect_city_by_coords

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

# Полигон: Крымский полуостров + Севастополь, с запасом
BBOX = "44.0,32.0,46.5,37.0"

QUERY = f"""
[out:json][timeout:90];
(
  node["tourism"~"^(hotel|guest_house|hostel|apartment|motel|chalet|camp_site|alpine_hut|wilderness_hut|caravan_site|resort)$"]({BBOX});
  way["tourism"~"^(hotel|guest_house|hostel|apartment|motel|chalet|camp_site|alpine_hut|wilderness_hut|caravan_site|resort)$"]({BBOX});
  relation["tourism"~"^(hotel|guest_house|hostel|apartment|motel|chalet|camp_site|alpine_hut|wilderness_hut|caravan_site|resort)$"]({BBOX});
  node["amenity"="boarding_house"]({BBOX});
  way["amenity"="boarding_house"]({BBOX});
  node["leisure"~"^(resort|sanatorium)$"]({BBOX});
  way["leisure"~"^(resort|sanatorium)$"]({BBOX});
);
out center tags;
"""

CITY_HINTS = (
    "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
    "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
    "Коктебель", "Партенит", "Гурзуф", "Новый Свет", "Форос",
    "Симеиз", "Алупка", "Ливадия", "Массандра", "Мисхор",
    "Канака", "Орджоникидзе", "Щёлкино", "Морское", "Малореченское",
)

CATEGORY_MAP = {
    "hotel": "отель",
    "guest_house": "гостевой дом",
    "hostel": "хостел",
    "apartment": "апартаменты",
    "motel": "мотель",
    "chalet": "шале",
    "camp_site": "кемпинг",
    "alpine_hut": "приют",
    "wilderness_hut": "приют",
    "caravan_site": "автокемпинг",
    "resort": "курорт",
    "boarding_house": "пансионат",
    "sanatorium": "санаторий",
}


def _normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return raw.strip()
    return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def _detect_city(tags: dict, lat: float | None = None, lon: float | None = None) -> str:
    # 1. addr:city / town / village / hamlet
    for k in ("addr:city", "addr:town", "addr:village", "addr:hamlet"):
        v = tags.get(k)
        if v:
            for c in CITY_HINTS:
                if c.lower() in v.lower():
                    return c
            return v
    # 2. полный адрес как строка
    addr_full = tags.get("addr:full") or tags.get("address") or ""
    for c in CITY_HINTS:
        if c in addr_full:
            return c
    # 3. фоллбек на координаты (bbox-таблица)
    by_coords = detect_city_by_coords(lat, lon)
    if by_coords:
        return by_coords
    # 4. ничего не сработало — общий регион
    return "Крым"


def _build_address(tags: dict) -> str:
    parts = []
    for k in ("addr:city", "addr:town", "addr:village"):
        if tags.get(k):
            parts.append(f"г. {tags[k]}")
            break
    if tags.get("addr:street"):
        s = "ул. " + tags["addr:street"]
        if tags.get("addr:housenumber"):
            s += f", {tags['addr:housenumber']}"
        parts.append(s)
    if tags.get("addr:postcode"):
        parts.append(tags["addr:postcode"])
    if not parts:
        return tags.get("addr:full") or tags.get("address") or ""
    return ", ".join(parts)


def _category(tags: dict) -> str:
    for k in ("tourism", "amenity", "leisure"):
        v = tags.get(k)
        if v and v in CATEGORY_MAP:
            return CATEGORY_MAP[v]
    return "размещение"


def _website(tags: dict) -> str:
    for k in ("website", "contact:website", "url"):
        v = tags.get(k)
        if v:
            v = v.strip()
            if not v.startswith("http"):
                v = "https://" + v
            return v
    return ""


def _email(tags: dict) -> str:
    for k in ("email", "contact:email"):
        v = tags.get(k)
        if v:
            return v.split(";")[0].strip()
    return ""


def _phone(tags: dict) -> str:
    for k in ("phone", "contact:phone", "phone:mobile", "contact:mobile"):
        v = tags.get(k)
        if v:
            return _normalize_phone(v.split(";")[0])
    return ""


def _fetch_overpass() -> list:
    body = QUERY.encode("utf-8")
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            req = Request(
                url, data=b"data=" + body,
                headers={"User-Agent": "ritual_parser/1.0", "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            raw = http_request(req, timeout=120)
            data = json.loads(raw.decode("utf-8"))
            return data.get("elements", [])
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            print(f"  [OSM] {url} fail: {e}")
            last_err = e
            continue
    print(f"  [OSM] все эндпоинты упали, последняя ошибка: {last_err}")
    return []


async def run(context):
    """context — Playwright BrowserContext, не используется. Сигнатура для совместимости с main.py."""
    print("\n=== OSM Overpass ===")
    elements = _fetch_overpass()
    print(f"  получено объектов: {len(elements)}")

    added = 0
    for el in elements:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("name:ru") or tags.get("operator") or ""
        if not name:
            continue
        # координаты: для node — lat/lon на верхнем уровне, для way/relation — center.lat/center.lon
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None and "center" in el:
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")
        item = {
            "city": _detect_city(tags, lat, lon),
            "name": name,
            "address": _build_address(tags),
            "phone": _phone(tags),
            "email": _email(tags),
            "website": _website(tags),
            "category": _category(tags),
            "source": "OSM",
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if save_item(item):
            added += 1

    print(f"\n[OSM] добавлено: {added}")
