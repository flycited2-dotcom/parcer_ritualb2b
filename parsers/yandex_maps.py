"""Парсер Яндекс.Карт по Крыму. Работает с РФ-IP.

Стратегия:
1. Открываем yandex.ru/maps/?text=<запрос>
2. Ждём появления .search-snippet-view, скроллим левую панель — подгружаются все
3. Из сниппета забираем name + address
4. Кликаем — URL меняется на /maps/org/<id>. Берём ID
5. По ID открываем yandex.ru/maps/org/<id>/?display-text=хотель — там телефон/сайт виден без WebGL
"""
import asyncio
import random
import re
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from utils.storage import save_item

ORG_ID_RE = re.compile(r"/maps/org/(\d+)")


CITIES = [
    "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
    "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
    "Коктебель", "Партенит", "Гурзуф",
]

# Категории берём шире — в выдачу попадает всё схожее
QUERIES = [
    ("гостиница {city}", "гостиница"),
    ("отель {city}", "отель"),
    ("пансионат {city}", "пансионат"),
    ("дом отдыха {city}", "дом отдыха"),
    ("база отдыха {city}", "база отдыха"),
    ("эллинг {city}", "эллинг"),
    ("гостевой дом {city}", "гостевой дом"),
    ("санаторий {city}", "санаторий"),
    ("апартаменты {city}", "апартаменты"),
    ("хостел {city}", "хостел"),
]

EXTRA_QUERIES_GLOBAL = [
    ("глэмпинг Крым", "глэмпинг", "Крым"),
    ("кемпинг Крым", "кемпинг", "Крым"),
    ("эллинг Крым", "эллинг", "Крым"),
    ("дом отдыха Крым", "дом отдыха", "Крым"),
]


async def _scroll_sidebar(page, n: int = 12):
    """Подгружаем все сниппеты левой панели."""
    for _ in range(n):
        try:
            await page.evaluate(
                """() => {
                    const sels = ['.scroll__container', '.search-list-view__list', '[class*="scroll__container"]'];
                    for (const s of sels) {
                        const el = document.querySelector(s);
                        if (el) { el.scrollTop = el.scrollHeight; return; }
                    }
                    window.scrollBy(0, 1500);
                }"""
            )
        except Exception:
            pass
        await page.wait_for_timeout(700)


async def _has_captcha(page) -> bool:
    try:
        if "captcha" in page.url.lower() or "showcaptcha" in page.url.lower():
            return True
    except Exception:
        pass
    return False


async def _click_show_phone(page) -> None:
    """Я.Карты часто прячут телефон под кнопкой/спойлером. Пробуем раскрыть."""
    selectors = [
        "[class*='card-phones-view__phone-number']",
        "[class*='card-phones']  button",
        "[class*='card-phones-view'] [role='button']",
        "div[class*='phone'] button",
        "button:has-text('Показать')",
        "span:has-text('Показать телефон')",
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if not el:
                continue
            await el.scroll_into_view_if_needed(timeout=1500)
            await el.click(timeout=2000)
            await page.wait_for_timeout(700)
            return
        except Exception:
            continue


async def _scrape_org_page(context, org_id: str) -> dict:
    """Открыть /maps/org/<id>/ напрямую: телефон/сайт/email видны без WebGL.
    В headed/xvfb-режиме телефон может быть скрыт за «Показать» — раскрываем.
    """
    out = {"phone": "", "website": "", "email": ""}
    page = await context.new_page()
    try:
        url = f"https://yandex.ru/maps/org/{org_id}/"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            return out

        # ждём появления контактного блока (любой из признаков)
        try:
            await page.wait_for_selector(
                "a[href^='tel:'], [class*='card-phones'], [itemprop='telephone'], "
                "[class*='_phone']",
                timeout=6000,
            )
        except Exception:
            await page.wait_for_timeout(2000)

        # пробуем раскрыть телефон, если он скрыт
        await _click_show_phone(page)

        # phone
        for sel in ["a[href^='tel:']", "[itemprop='telephone']",
                    "[class*='card-phones-view__phone-number']",
                    "[class*='card-phones']", "[class*='phones-item__text']",
                    "[class*='_phone']"]:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                if sel.startswith("a"):
                    href = await el.get_attribute("href") or ""
                    out["phone"] = href.replace("tel:", "").strip()
                else:
                    out["phone"] = (await el.inner_text()).strip()
                if out["phone"]:
                    break
            except Exception:
                continue

        # email
        try:
            em = await page.query_selector("a[href^='mailto:']")
            if em:
                href = await em.get_attribute("href") or ""
                out["email"] = href.replace("mailto:", "").split("?")[0].strip()
        except Exception:
            pass

        # website (не yandex)
        try:
            candidates = await page.query_selector_all("a[href^='http']")
            for el in candidates:
                href = await el.get_attribute("href") or ""
                host = urlparse(href).netloc.lower()
                if not host:
                    continue
                if any(b in host for b in ("yandex.", "ya.ru", "yastatic.")):
                    continue
                from urllib.parse import urlsplit, urlunsplit
                sp = urlsplit(href)
                out["website"] = urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))
                break
        except Exception:
            pass

        # fallback на innerText — иногда телефон есть только текстом
        if not out["phone"]:
            try:
                txt = await page.evaluate("document.body && document.body.innerText || ''")
                m = re.search(r"\+7[\s\-\(\)\d]{10,18}|8[\s\-\(\)\d]{10,18}", txt)
                if m:
                    out["phone"] = m.group(0)
            except Exception:
                pass
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return out


async def _extract_org_id_after_click(page) -> str:
    """После клика на сниппет URL уходит на /maps/org/<id>. Возвращаем id."""
    try:
        # ждём смены URL
        for _ in range(10):
            cur = page.url
            m = ORG_ID_RE.search(cur)
            if m:
                return m.group(1)
            await page.wait_for_timeout(300)
    except Exception:
        pass
    return ""


async def _process_query(context, query_text: str, category: str, city: str):
    page = await context.new_page()
    try:
        url = f"https://yandex.ru/maps/?text={quote_plus(query_text)}"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  goto fail: {e}")
            return 0

        # ждём появления сниппетов
        try:
            await page.wait_for_selector(".search-snippet-view", timeout=15000)
        except Exception:
            await page.wait_for_timeout(4000)

        if await _has_captcha(page):
            print("  CAPTCHA, пропуск запроса")
            return 0

        await _scroll_sidebar(page, n=10)

        snippets = await page.query_selector_all(".search-snippet-view")
        print(f"  сниппетов: {len(snippets)}")

        added = 0
        for i, sn in enumerate(snippets[:30]):
            try:
                # имя из сниппета
                name = ""
                for sel in [".search-business-snippet-view__title",
                            ".search-snippet-view__title",
                            "[class*='SnippetTitle']", "h3", "[class*='title']"]:
                    el = await sn.query_selector(sel)
                    if el:
                        t = (await el.inner_text()).strip()
                        if t:
                            name = t
                            break
                if not name:
                    continue

                # адрес из сниппета (если виден)
                address = ""
                for sel in [".search-business-snippet-view__address",
                            "[class*='address']"]:
                    el = await sn.query_selector(sel)
                    if el:
                        a = (await el.inner_text()).strip()
                        if a:
                            address = a
                            break

                # клик по сниппету → URL уходит на /maps/org/<id>
                details = {"phone": "", "website": "", "email": ""}
                try:
                    await sn.scroll_into_view_if_needed()
                    await sn.click(timeout=4000)
                    await page.wait_for_timeout(random.randint(1500, 2500))
                    org_id = await _extract_org_id_after_click(page)
                    if org_id:
                        details = await _scrape_org_page(context, org_id)
                except Exception:
                    pass

                if save_item({
                    "city": city,
                    "name": name,
                    "address": address,
                    "phone": details["phone"],
                    "email": details["email"],
                    "website": details["website"],
                    "category": category,
                    "source": "Я.Карты",
                    "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }):
                    added += 1

                await asyncio.sleep(random.uniform(0.6, 1.4))
            except Exception as e:
                print(f"  err snippet#{i}: {e}")
                continue

        return added
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def run(context):
    print("\n=== Я.Карты ===")
    total = 0

    for q_tmpl, category in QUERIES:
        for city in CITIES:
            q = q_tmpl.format(city=city)
            print(f"\n[Я.Карты] {q}")
            try:
                added = await _process_query(context, q, category, city)
                total += added
                print(f"  + {added}")
            except Exception as e:
                print(f"  CRIT: {e}")
            await asyncio.sleep(random.uniform(2.5, 5.0))

    for q, category, city in EXTRA_QUERIES_GLOBAL:
        print(f"\n[Я.Карты] {q}")
        try:
            added = await _process_query(context, q, category, city)
            total += added
            print(f"  + {added}")
        except Exception as e:
            print(f"  CRIT: {e}")
        await asyncio.sleep(random.uniform(3.0, 5.0))

    print(f"\n[Я.Карты] всего новых: {total}")
