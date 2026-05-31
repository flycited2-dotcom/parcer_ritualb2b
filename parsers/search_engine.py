"""Поиск через Яндекс (yandex.ru/search/) — широкая матрица по Крыму.

На РФ-IP yandex.ru даёт прямой доступ. При капче скриптом, парсер логирует и
переходит к следующему запросу. Цель — собрать прямые сайты отелей с title.
Контакты добывает email_finder.
"""
import asyncio
import random
import re
from datetime import datetime
from urllib.parse import urlparse, quote_plus, parse_qs, unquote

from utils.storage import save_item

CATEGORIES = [
    "гостиница", "отель", "пансионат", "дом отдыха",
    "база отдыха", "эллинг", "глэмпинг", "кемпинг",
    "гостевой дом", "хостел", "санаторий", "апарт-отель",
]

CITIES = [
    "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
    "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
    "Коктебель", "Партенит", "Гурзуф", "Новый Свет", "Форос",
]

# «Человеческие» формулировки — собирают то, что не находится по жёсткой матрице.
BROAD_QUERIES = [
    "отдохнуть в Крыму",
    "отдых в Крыму",
    "отдых в Крыму на море",
    "отдых в Крыму с детьми",
    "отдых в Крыму всё включено",
    "куда поехать в Крым",
    "лучшие отели Крыма",
    "забронировать отель Крым",
    "снять жильё Крым",
    "Крым отель у моря",
    "санатории Крыма",
    "пансионаты Крыма",
    "базы отдыха Крым",
    "глэмпинг Крым",
    "эллинг Крым",
    "кемпинг Крым",
    "гостевой дом Крым",
    "официальный сайт отель Крым",
]

# То же, но с привязкой к городу.
BROAD_CITY_QUERIES = [
    "отдохнуть в {city}",
    "отдых в {city} Крым",
    "снять жильё в {city}",
    "забронировать отель {city} Крым",
    "официальный сайт отель {city}",
    "куда поехать в {city}",
    "санаторий {city} Крым официальный сайт",
    "пансионат {city} Крым официальный сайт",
]

AGGREGATOR_DOMAINS = {
    # Основные агрегаторы
    "avito.ru", "sutochno.ru", "ostrovok.ru", "booking.com", "tripadvisor.ru",
    "tripadvisor.com", "101hotels.com", "hotels.ru", "tutu.ru", "tury.ru",
    "tvil.ru", "trivago.ru", "tripz.ru", "tropki.ru", "hotellook.ru",
    "onetwotrip.com", "alean.ru", "putevka.com", "kudanamore.ru",
    "kurort-expert.ru", "nashvek.ru", "kurortix.ru", "tourister.ru",
    "votpusk.ru", "otzovik.com", "tophotels.ru", "domik.travel",
    "rekordovo.ru", "krimbooking.ru", "vkrim.info", "turum.net",
    "idisuda.ru", "turbaza.ru", "lazurny.ru", "multitour.ru",
    "ok-crimea.ru", "feo.ru", "azur.ru", "intourist.ru", "delfin-tour.ru",
    "edem-v-gosti.ru", "turbazy.ru", "hochu-na-yuga.ru", "mirturbaz.ru",
    "1-krim.ru", "privettur.ru", "travelata.ru", "level.travel",
    "onlinetours.ru", "bronevik.com", "sletat.ru", "agoda.com",
    "expedia.com", "domotur.com", "krym.com", "krym4you.com",
    "domclick.ru", "cian.ru", "domofond.ru", "youla.ru", "irr.ru",
    "russpass.ru", "tbank.ru", "tinkoff.ru", "sberbank.ru",
    # Поисковики и соцсети
    "yandex.ru", "ya.ru", "yandex.com", "yandex.eu", "yastatic.net",
    "google.com", "google.ru", "bing.com", "duckduckgo.com",
    "wikipedia.org", "youtube.com", "vk.com", "ok.ru",
    "instagram.com", "facebook.com", "t.me", "telegram.org",
    "rutube.ru", "dzen.ru", "rambler.ru", "mail.ru", "drom.ru",
    # Геокаталоги
    "2gis.ru", "2gis.com", "zoon.ru", "yell.ru", "flamp.ru",
    # Отзывы и доски
    "irecommend.ru", "otzyv.ru", "tonkosti.ru", "tonkosti-tour.ru",
    "100dorog.ru", "trip.com", "ostrovok.kz",
    # Специфичные крымские агрегаторы
    "crimea-hotels.com", "krym-hotels.com", "crimean.ru", "myrt.ru",
    "krym.travel", "spa-krim.ru",
    # Прочие
    "mts-link.ru", "travelpayouts.com", "ya.ru",
}


def is_aggregator(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        for agg in AGGREGATOR_DOMAINS:
            if host == agg or host.endswith("." + agg):
                return True
        return False
    except Exception:
        return True


def extract_name(title: str) -> str:
    if not title:
        return ""
    t = re.split(r"\s[—\-|·]\s", title)[0].strip()
    t = re.sub(r"\s{2,}", " ", t)
    return t[:200]


async def has_captcha(page) -> bool:
    try:
        url = page.url
        if "showcaptcha" in url or "captcha" in url.lower():
            return True
        for sel in ["form#checkbox-captcha-form", ".CheckboxCaptcha", "[class*='captcha']"]:
            el = await page.query_selector(sel)
            if el:
                return True
    except Exception:
        pass
    return False


async def search_yandex(page, query: str, pages: int = 2) -> list:
    results = []
    for p in range(pages):
        url = f"https://yandex.ru/search/?text={quote_plus(query)}&p={p}"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 3500))
        except Exception as e:
            print(f"  [Yandex] goto fail: {e}")
            continue

        if await has_captcha(page):
            print("  [Yandex] CAPTCHA, пропуск")
            return results

        # Современная разметка Я.Поиска: .serp-item, .OrganicTitle-Link, .Path-Item
        items = await page.query_selector_all(".serp-item")
        for it in items:
            try:
                a = await it.query_selector("a.OrganicTitle-Link, a.Link.organic__url, h2 a")
                if not a:
                    continue
                href = await a.get_attribute("href") or ""
                if not href.startswith("http"):
                    continue
                title = (await a.inner_text()).strip()
                results.append((title, href))
            except Exception:
                continue
        if not items:
            break
    return results


async def search_bing(page, query: str, pages: int = 2) -> list:
    results = []
    for p in range(pages):
        first = p * 10 + 1
        url = f"https://www.bing.com/search?q={quote_plus(query)}&first={first}&setlang=ru&cc=RU"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(random.randint(1500, 2500))
        except Exception as e:
            print(f"  [Bing] goto fail: {e}")
            continue

        items = await page.query_selector_all("li.b_algo")
        for it in items:
            try:
                a = await it.query_selector("h2 a")
                if not a:
                    continue
                href = await a.get_attribute("href") or ""
                if not href.startswith("http"):
                    continue
                title = (await a.inner_text()).strip()
                results.append((title, href))
            except Exception:
                continue
    return results


async def search_mailru(page, query: str) -> list:
    """go.mail.ru — RU поисковик, мягкая антибот-политика."""
    results = []
    url = f"https://go.mail.ru/search?q={quote_plus(query)}&fr=main"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(random.randint(1500, 2500))
    except Exception as e:
        print(f"  [Mail] goto fail: {e}")
        return results

    # Mail.Поиск: .result__a, h3 a, .SearchSnippet a, [data-mid]
    for sel in ["a.result__a", "h3 a", ".SerpItem a[href^='http']",
                "div.RG-result a[href^='http']"]:
        items = await page.query_selector_all(sel)
        if items:
            for el in items:
                try:
                    href = await el.get_attribute("href") or ""
                    if not href.startswith("http") or "mail.ru" in href:
                        continue
                    title = (await el.inner_text()).strip()
                    if title:
                        results.append((title, href))
                except Exception:
                    continue
            if results:
                break
    return results


async def search_rambler(page, query: str) -> list:
    """nova.rambler.ru — поиск через своё API + Я.Поиск-партнёрство."""
    results = []
    url = f"https://nova.rambler.ru/search?query={quote_plus(query)}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(random.randint(1500, 2500))
    except Exception as e:
        print(f"  [Rambler] goto fail: {e}")
        return results

    for sel in [".Serp__title a", ".SerpItem__title a", "a[class*='Title']",
                "h3 a[href^='http']"]:
        items = await page.query_selector_all(sel)
        if items:
            for el in items:
                try:
                    href = await el.get_attribute("href") or ""
                    if not href.startswith("http") or "rambler.ru" in href:
                        continue
                    title = (await el.inner_text()).strip()
                    if title:
                        results.append((title, href))
                except Exception:
                    continue
            if results:
                break
    return results


async def _enrich_now(context, origin: str) -> dict:
    """Открыть страницу-результат и сразу слизать имя, адрес, телефон, email."""
    from parsers.email_finder import enrich_from_website
    page = await context.new_page()
    out = {"name": "", "address": "", "phone": "", "email": ""}
    try:
        try:
            await page.goto(origin, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            return out
        await page.wait_for_timeout(1500)
        # имя — приоритет: <h1>, потом <title>
        try:
            h1 = await page.query_selector("h1")
            if h1:
                txt = (await h1.inner_text()).strip()
                if txt and 3 <= len(txt) <= 200:
                    out["name"] = txt
            if not out["name"]:
                title = await page.title()
                out["name"] = (title or "").strip()[:200]
        except Exception:
            pass
        # email/phone/address через общий помощник
        try:
            email, phone, address = await enrich_from_website(page, origin)
            out["email"] = email
            out["phone"] = phone
            out["address"] = address
        except Exception:
            pass
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return out


async def _process_search_query(context, search_page, query: str,
                                 city: str, category: str,
                                 seen_origins: set) -> int:
    """Один поисковый запрос. Возвращает сколько новых записей сохранил."""
    print(f"\n[Поиск] {query}")
    hits = []
    # Цепочка: Я → Mail → Rambler → Bing. Если первый дал, остальное пропускаем.
    try:
        hits = await search_yandex(search_page, query, pages=2)
        print(f"  [Я] {len(hits)}")
    except Exception as e:
        print(f"  [Я] err: {e}")
    if not hits:
        try:
            hits = await search_mailru(search_page, query)
            print(f"  [Mail] {len(hits)}")
        except Exception as e:
            print(f"  [Mail] err: {e}")
    if not hits:
        try:
            hits = await search_rambler(search_page, query)
            print(f"  [Rambler] {len(hits)}")
        except Exception as e:
            print(f"  [Rambler] err: {e}")
    if not hits:
        try:
            hits = await search_bing(search_page, query, pages=2)
            print(f"  [Bing] {len(hits)}")
        except Exception as e:
            print(f"  [Bing] err: {e}")

    kept = 0
    for title, url in hits:
        try:
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            continue
        if origin in seen_origins or is_aggregator(url):
            continue
        seen_origins.add(origin)

        # сразу заходим на страницу и слизываем
        details = await _enrich_now(context, origin)
        # имя — лучшее из: h1/title страницы → иначе title из выдачи
        name = details["name"] or extract_name(title)
        if not name:
            continue

        if save_item({
            "city": city,
            "name": name,
            "address": details["address"],
            "phone": details["phone"],
            "email": details["email"],
            "website": origin,
            "category": category,
            "source": "Поиск",
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }):
            kept += 1

        # пауза между визитами на сайты
        await asyncio.sleep(random.uniform(1.0, 2.0))

    print(f"  + {kept}")
    await asyncio.sleep(random.uniform(2.0, 3.5))
    return kept


async def run(context):
    page = await context.new_page()
    print("\n=== Поиск (Яндекс + Bing) ===")

    seen_origins: set[str] = set()
    total_added = 0

    # 1. Узкая матрица «категория × город»
    for category in CATEGORIES:
        for city in CITIES:
            try:
                total_added += await _process_search_query(
                    context, page, f"{category} {city} Крым",
                    city, category, seen_origins,
                )
            except Exception as e:
                print(f"  CRIT: {e}")
        await asyncio.sleep(random.uniform(3.0, 6.0))

    # 2. Широкие «человеческие» запросы по Крыму без города
    for q in BROAD_QUERIES:
        try:
            total_added += await _process_search_query(
                context, page, q, "Крым", "общий", seen_origins,
            )
        except Exception as e:
            print(f"  CRIT: {e}")

    # 3. Широкие запросы с городом
    for tmpl in BROAD_CITY_QUERIES:
        for city in CITIES:
            try:
                total_added += await _process_search_query(
                    context, page, tmpl.format(city=city),
                    city, "общий", seen_origins,
                )
            except Exception as e:
                print(f"  CRIT: {e}")
        await asyncio.sleep(random.uniform(3.0, 6.0))

    print(f"\n[Поиск] всего новых: {total_added}")
    await page.close()
