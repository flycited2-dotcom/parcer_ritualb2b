"""Web crawler: рекурсивно ходит по сайтам уже собранных объектов, обнаруживает
новые объекты (соседние отели, сетевые филиалы) и контакты.

Стратегия:
1. Источник seed-доменов — текущий CSV (поле website всех записей).
2. На каждом домене:
   а) пробуем GET /sitemap.xml — оттуда быстро получаем 10-1000 страниц
   б) GET / — извлекаем все <a href>, в т.ч. /о-нас, /контакты, /филиалы, /партнеры
   в) обходим до MAX_PAGES_PER_DOMAIN страниц внутри домена
3. Из каждой посещённой страницы:
   - извлекаем phone/email/address (как email_finder)
   - извлекаем <title>/<h1> как потенциальное имя нового объекта (если на странице
     есть гостиничные триггеры: «гостиница», «отель», «забронировать», «номера»)
4. Ссылки на сторонние домены проверяем по эвристике «отельный сайт» —
   если домен не агрегатор и в title есть триггер → добавляем как seed-кандидат
   (но всё равно не больше MAX_TOTAL_PAGES).

Все save_item проходят через persistent dedup — повторов между прогонами не будет.
"""
import asyncio
import csv
import os
import re
from datetime import datetime
from urllib.parse import urlparse, urljoin

import aiohttp

from utils.storage import save_item
from parsers.search_engine import AGGREGATOR_DOMAINS, is_aggregator
from parsers.email_finder import pick_email, pick_phone, pick_address, pick_address_from_html


MAX_PAGES_PER_DOMAIN = 15
MAX_TOTAL_PAGES = 4000
PARALLEL = 15
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

HOTEL_TRIGGERS = (
    "отель", "гостиниц", "пансионат", "санатори", "база отдыха",
    "дом отдыха", "гостевой дом", "хостел", "апарт", "вилла",
    "эллинг", "глэмпинг", "кемпинг", "забронировать", "номера",
    "номерной фонд", "проживание", "размещение",
    "hotel", "resort", "villa", "guesthouse", "hostel", "spa",
)

# Интересные пути — приоритет в очереди обхода
INTERESTING_PATHS_RE = re.compile(
    r"/(contacts?|about|partner|filial|location|hotels?|objects?|"
    r"номера|контакт|о-нас|о_нас|о-компании|объект|филиал)",
    re.IGNORECASE,
)

A_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def _origin(url: str) -> str:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}"


def _strip(s: str) -> str:
    s = TAG_RE.sub(" ", s or "")
    return WS_RE.sub(" ", s).strip()


def _has_hotel_trigger(text: str) -> bool:
    low = (text or "").lower()
    return any(t in low for t in HOTEL_TRIGGERS)


def _load_seeds_from_csv(path: str) -> list[str]:
    if not path or not os.path.exists(path):
        return []
    origins: set[str] = set()
    for delim in (";", ","):
        try:
            with open(path, encoding="utf-8-sig") as f:
                sample = f.read(2048)
                f.seek(0)
                if delim not in sample:
                    continue
                for r in csv.DictReader(f, delimiter=delim):
                    w = (r.get("website") or "").strip()
                    if not w:
                        continue
                    o = _origin(w)
                    if not o or is_aggregator(o):
                        continue
                    origins.add(o)
                if origins:
                    break
        except Exception:
            continue
    return sorted(origins)


def _latest_csv() -> str:
    """Возвращает источник seed-доменов для Crawler.

    Приоритет master_all.csv: внутри одного прогона result_*.csv в начале
    ещё пустой (Crawler работает не последним), а master_all накопил тысячи
    доменов за все прошлые прогоны — это и есть лучший seed.
    """
    import glob
    master = "output/master_all.csv"
    if os.path.exists(master) and os.path.getsize(master) > 1024:
        return master
    files = sorted(glob.glob("output/result_2*.csv"), key=os.path.getmtime)
    return files[-1] if files else ""


def _name_from_html(html: str) -> str:
    for re_ in (H1_RE, TITLE_RE):
        m = re_.search(html)
        if m:
            t = _strip(m.group(1))
            if 3 <= len(t) <= 200:
                return t
    return ""


def _extract_links(html: str, base_origin: str) -> set[str]:
    links: set[str] = set()
    for m in A_HREF_RE.finditer(html):
        href = m.group(1).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(base_origin + "/", href)
        links.add(full.split("#")[0])
    return links


async def _fetch(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True,
                               headers={"User-Agent": UA}) as r:
            ctype = r.headers.get("Content-Type", "").lower()
            if "text/html" not in ctype and "xml" not in ctype:
                return ""
            return await r.text(errors="replace")
    except Exception:
        return ""


async def _sitemap_urls(session: aiohttp.ClientSession, origin: str) -> list[str]:
    txt = await _fetch(session, origin + "/sitemap.xml")
    if not txt:
        return []
    return re.findall(r"<loc>([^<]+)</loc>", txt, re.IGNORECASE)[:200]


def _detect_city_from_text(text: str) -> str:
    from parsers.osm import CITY_HINTS
    low = text.lower()
    for c in CITY_HINTS:
        if c.lower() in low:
            return c
    return "Крым"


NAV_NAME_BLACKLIST_RE = re.compile(
    r"^(о\s*нас|о\s*компании|контакт|отзыв|фото|галере|новост|"
    r"номера|услуг|карта\s*сайт|404|index|главн|меню|каталог)",
    re.IGNORECASE,
)


def _is_real_object_name(name: str) -> bool:
    """Имя выглядит как реальный объект (а не навигационная страница)?"""
    if not name or len(name) < 4:
        return False
    if NAV_NAME_BLACKLIST_RE.match(name.strip()):
        return False
    # отбрасываем чистые доменные имена типа "1crimea.com"
    if re.match(r"^[a-z0-9\-]+\.[a-z]{2,}$", name.strip().lower()):
        return False
    return True


async def _crawl_domain(session: aiohttp.ClientSession, origin: str,
                       visited_pages: set[str], total_counter: list[int]) -> int:
    """Обходим один домен. 1 домен = 1 объект. Имя — с главной,
    контакты собираем со всех страниц.
    """
    pages_in_domain = 0
    queue: list[str] = []

    # sitemap первым делом
    sitemap = await _sitemap_urls(session, origin)
    if sitemap:
        for u in sitemap:
            if _origin(u) == origin:
                queue.append(u)

    queue.insert(0, origin + "/")
    queue.sort(key=lambda u: 0 if INTERESTING_PATHS_RE.search(u) else 1)

    main_name = ""        # имя с главной (или /о-нас)
    best_phone = ""
    best_email = ""
    best_address = ""
    has_hotel_trigger = False

    while queue and pages_in_domain < MAX_PAGES_PER_DOMAIN \
            and total_counter[0] < MAX_TOTAL_PAGES:
        url = queue.pop(0)
        if url in visited_pages:
            continue
        visited_pages.add(url)
        total_counter[0] += 1
        pages_in_domain += 1

        html = await _fetch(session, url)
        if not html:
            continue

        # Триггер «отельности» хоть на одной странице → засчитываем домен
        if not has_hotel_trigger and _has_hotel_trigger(html[:8000]):
            has_hotel_trigger = True

        # Имя — приоритет: главная (первая успешная), затем /о-нас если на главной не нашли
        if not main_name:
            cand = _name_from_html(html)
            if _is_real_object_name(cand):
                main_name = cand

        # Контакты — берём первое непустое
        if not best_email:
            best_email = pick_email(html)
        if not best_phone:
            best_phone = pick_phone(html)
        if not best_address:
            best_address = pick_address_from_html(html) or pick_address(_strip(html))

        if pages_in_domain < MAX_PAGES_PER_DOMAIN:
            for link in _extract_links(html, origin):
                if _origin(link) != origin:
                    continue
                if link in visited_pages or link in queue:
                    continue
                if INTERESTING_PATHS_RE.search(link):
                    queue.insert(0, link)
                elif len(queue) < MAX_PAGES_PER_DOMAIN * 2:
                    queue.append(link)

    # Запись только если: есть имя + домен похож на отельный
    if not main_name or not has_hotel_trigger:
        return 0

    city = _detect_city_from_text(best_address or main_name)
    cat = "размещение"
    low_name = main_name.lower()
    for trig in HOTEL_TRIGGERS:
        if trig in low_name:
            cat = trig
            break

    if save_item({
        "city": city,
        "name": main_name,
        "address": best_address,
        "phone": best_phone,
        "email": best_email,
        "website": origin,
        "category": cat,
        "source": "Crawler",
        "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }):
        return 1
    return 0


async def run(context):
    """context — Playwright не используется (HTTP-only crawler).
    Сигнатура для совместимости с main.py.
    """
    print("\n=== Crawler ===")
    seeds = _load_seeds_from_csv(_latest_csv())
    if not seeds:
        print("[Crawler] нет seed-доменов (CSV пуст или нет website). Пропуск.")
        return

    print(f"[Crawler] seed-доменов: {len(seeds)}, "
          f"max_pages_per_domain={MAX_PAGES_PER_DOMAIN}, "
          f"max_total_pages={MAX_TOTAL_PAGES}, parallel={PARALLEL}")

    visited_pages: set[str] = set()
    total_counter = [0]  # mutable closure
    added_total = 0

    connector = aiohttp.TCPConnector(limit=PARALLEL, ssl=False)
    async with aiohttp.ClientSession(connector=connector,
                                     timeout=HTTP_TIMEOUT) as session:
        sem = asyncio.Semaphore(PARALLEL)

        async def _one(origin):
            nonlocal added_total
            async with sem:
                if total_counter[0] >= MAX_TOTAL_PAGES:
                    return
                try:
                    n = await _crawl_domain(session, origin, visited_pages, total_counter)
                    if n:
                        added_total += n
                        print(f"  [Crawler] {origin} → +{n} (всего страниц: {total_counter[0]})")
                except Exception as e:
                    print(f"  [Crawler] {origin} err: {e}")

        await asyncio.gather(*[_one(o) for o in seeds])

    print(f"\n[Crawler] обойдено страниц: {total_counter[0]}, добавлено: {added_total}")
