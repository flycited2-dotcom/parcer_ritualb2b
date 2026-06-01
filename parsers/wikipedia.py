"""Wikipedia (ru) — категории «Похоронные бюро», «Ритуальные услуги», «Крематории России».

API ru.wikipedia.org/w/api.php:
1. categorymembers — получаем список страниц в категории
2. parse?prop=wikitext — забираем wikitext страницы, парсим infobox

Из infobox достаём: name, website, address, phone, координаты.
Без капч, без авторизации, рейт-лимит мягкий.
"""
import json
import re
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request

from utils.http_retry import http_request
from urllib.error import URLError, HTTPError

from utils.storage import save_item

API = "https://ru.wikipedia.org/w/api.php"
UA = "ritual_parser/1.0 (research; alex@example.com)"

CATEGORIES = [
    "Похоронные бюро",
    "Ритуальные услуги",
    "Крематории России",
]

CITY_HINTS = (
    "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
    "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
    "Коктебель", "Партенит", "Гурзуф", "Новый Свет", "Форос",
    "Алупка", "Ливадия", "Мисхор", "Симеиз", "Массандра",
    "Мелитополь", "Бердянск", "Энергодар", "Токмак", "Геническ",
    "Новая Каховка", "Каховка", "Скадовск", "Алёшки",
)


def _http_json(url: str) -> dict:
    try:
        req = Request(url, headers={"User-Agent": UA})
        body = http_request(req, timeout=30)
        return json.loads(body.decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        print(f"  [Wiki] err: {e}")
        return {}


def _category_members(category: str) -> list[str]:
    """Список заголовков страниц в категории."""
    out = []
    cont = ""
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Категория:{category}",
            "cmlimit": "500",
            "format": "json",
        }
        if cont:
            params["cmcontinue"] = cont
        data = _http_json(f"{API}?{urlencode(params)}")
        for m in data.get("query", {}).get("categorymembers", []):
            t = m.get("title", "")
            if t and not t.startswith(("Категория:", "Шаблон:", "Файл:")):
                out.append(t)
        cont = data.get("continue", {}).get("cmcontinue", "")
        if not cont:
            break
    return out


def _page_wikitext(title: str) -> str:
    params = {
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "format": "json",
    }
    data = _http_json(f"{API}?{urlencode(params)}")
    return data.get("parse", {}).get("wikitext", {}).get("*", "")


# Парсим строки infobox вида |website=https://... или |телефон=+7...
INFO_RE = re.compile(r"\|\s*([a-zA-Zа-яА-Я_\- ]+?)\s*=\s*([^\n|][^\n]*)")
URL_RE = re.compile(r"https?://[^\s\]\}\)\,]+")
PHONE_RE = re.compile(r"(?:\+7|8)[\s\-\(]?\d{3}[\s\-\)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _detect_city(text: str) -> str:
    for c in CITY_HINTS:
        if c in text:
            return c
    return "Крым"


def _extract_from_infobox(wikitext: str, title: str) -> dict:
    out = {
        "name": title,
        "address": "",
        "phone": "",
        "email": "",
        "website": "",
        "category": "",
    }
    # выделяем содержимое infobox: {{Карточка ... }}
    m = re.search(r"\{\{Карточка[^|]+\|(.*?)\n\}\}", wikitext,
                  re.IGNORECASE | re.DOTALL)
    body = m.group(1) if m else wikitext[:5000]

    fields: dict[str, str] = {}
    for fm in INFO_RE.finditer(body):
        k = fm.group(1).strip().lower()
        v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", fm.group(2)).strip()
        v = re.sub(r"<[^>]+>", "", v).strip()
        if v:
            fields[k] = v

    # имя
    for k in ("название", "имя", "name", "имя_рус", "название_рус"):
        if k in fields:
            out["name"] = fields[k][:200]
            break

    # сайт
    for k in ("сайт", "website", "url", "homepage"):
        if k in fields:
            url_m = URL_RE.search(fields[k])
            if url_m:
                out["website"] = url_m.group(0).rstrip(".,;)")
                break

    # адрес
    for k in ("адрес", "address", "местоположение", "расположение", "город"):
        if k in fields and fields[k] and len(fields[k]) < 200:
            out["address"] = fields[k]
            break

    # phone/email
    for v in fields.values():
        if not out["phone"]:
            pm = PHONE_RE.search(v)
            if pm:
                out["phone"] = pm.group(0)
        if not out["email"]:
            em = EMAIL_RE.search(v)
            if em:
                out["email"] = em.group(0)

    # категория (тип объекта)
    for k in ("тип", "type", "статус"):
        if k in fields:
            out["category"] = fields[k][:80]
            break

    return out


async def run(context):
    """context не используется (HTTP-only)."""
    print("\n=== Wikipedia (категории) ===")
    all_titles: set[str] = set()
    for cat in CATEGORIES:
        titles = _category_members(cat)
        print(f"  [Wiki] {cat}: {len(titles)} страниц")
        all_titles.update(titles)

    print(f"  всего уникальных страниц: {len(all_titles)}")

    added = 0
    for i, title in enumerate(sorted(all_titles), 1):
        wt = _page_wikitext(title)
        if not wt:
            continue
        try:
            data = _extract_from_infobox(wt, title)
        except Exception as e:
            print(f"  [Wiki] infobox err {title}: {e}")
            continue
        if not data["name"]:
            continue
        city = _detect_city(data["address"] or data["name"])
        if save_item({
            "city": city,
            "name": data["name"],
            "address": data["address"],
            "phone": data["phone"],
            "email": data["email"],
            "website": data["website"],
            "category": data["category"] or "ритуальные услуги",
            "source": "Wikipedia",
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }):
            added += 1
        if i % 50 == 0:
            print(f"  [Wiki] прогресс: {i}/{len(all_titles)} обработано, +{added}")

    print(f"\n[Wikipedia] добавлено: {added}")
