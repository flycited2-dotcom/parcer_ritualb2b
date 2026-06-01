"""VK API — поиск групп размещения в Крыму и добор контактов.

ENV: VK_TOKEN (user access_token со scope groups). Без токена — пропуск.

Логика:
1. groups.search по матрице city_id × категория → собираем уникальные group_id.
2. groups.getById пачками по 500 с fields=contacts,site,description,...
3. email: из contacts (приоритет фирменному — домен совпадает с site), затем из описания.
4. phone: из contacts. website: site (очищенный). social: vk.com/<screen_name>.
5. save_item — persistent dedup сам отсеет повторы между прогонами.
"""
import json
import os
import re
import time
import urllib.parse
from datetime import datetime
from urllib.parse import urlparse

from utils.http_retry import http_request

from parsers.vk_filter import classify as vk_classify
from utils.categories import normalize
from utils.storage import save_item, normalize_phone

API = "https://api.vk.com/method"
V = "5.131"
RPS_PAUSE = 0.34  # VK лимит ~3 запроса/сек

# Проверенные city_id (database.getCities, country_id=1)
VK_CITIES = {
    818:     "Ялта",
    627:     "Симферополь",
    185:     "Севастополь",
    799:     "Евпатория",
    1483:    "Феодосия",
    478:     "Керчь",
    2510:    "Алушта",
    7188:    "Судак",
    4331:    "Саки",
    475:     "Бахчисарай",
    5490687: "Коктебель",
    5490709: "Гурзуф",
    5490654: "Партенит",
    5490729: "Симеиз",
    5490701: "Алупка",
}

QUERIES = [
    "ритуальные услуги", "ритуальное агентство", "похоронное бюро",
    "ритуальный магазин", "ритуальная атрибутика", "ритуальные товары",
    "венки", "памятники на могилу", "гробы", "надгробия",
    "ограды на могилу", "крематорий", "поминальные товары",
    "мастерская памятников",
    # флористика (попутная ниша)
    "цветочный магазин", "доставка цветов",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_BLOCKLIST = ("noreply", "no-reply", "example.", "@vk.com", "@vkontakte")

PREFERRED_PREFIXES = ("reservation", "reservations", "booking", "reserve", "book",
                      "reception", "info", "sales", "office", "hotel", "manager")

# VK API error codes, означающие что VK_TOKEN недействителен.
_TOKEN_DEAD_CODES = (5, 15, 27, 28)
_token_alert_sent = False  # один алерт за прогон


def _maybe_alert_token_dead(error: dict) -> None:
    """Шлёт TG-алерт один раз за прогон, если ошибка VK означает invalid token."""
    global _token_alert_sent
    if _token_alert_sent:
        return
    code = error.get("error_code")
    if code not in _TOKEN_DEAD_CODES:
        return
    _token_alert_sent = True
    msg = error.get("error_msg", "?")
    try:
        from utils.telegram_notify import send_message
        tok = os.environ.get("TG_BOT_TOKEN", "")
        chat = os.environ.get("TG_CHAT_ID", "")
        if tok and chat:
            send_message(tok, chat, (
                f"❌ <b>VK_TOKEN протух</b> (code={code}): <code>{msg[:120]}</code>\n"
                "Получи новый по инструкции из docs/HANDOFF: "
                "oauth.vk.com/authorize?client_id=2685278&scope=groups,offline&...\n"
                "Затем обнови VK_TOKEN в /home/ritual_parser/.env"
            ))
    except Exception as e:
        print(f"  [VK] не смог отправить алерт о токене: {e}")


def _call(method: str, token: str, **params) -> dict:
    params["access_token"] = token
    params["v"] = V
    url = f"{API}/{method}?{urllib.parse.urlencode(params)}"
    try:
        body = http_request(url, timeout=25)
        resp = json.loads(body.decode("utf-8", errors="replace"))
    except Exception as e:
        return {"error": {"error_msg": str(e)}}
    if isinstance(resp, dict) and "error" in resp:
        _maybe_alert_token_dead(resp["error"])
    return resp


def _site_domain(site: str) -> str:
    try:
        h = urlparse(site if "://" in site else "http://" + site).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _clean_site(site: str) -> str:
    if not site:
        return ""
    try:
        site = site.strip().split()[0]
        if not site.startswith("http"):
            site = "https://" + site
        sp = urlparse(site)
        if not sp.netloc:
            return ""
        return f"{sp.scheme}://{sp.netloc}{sp.path}".rstrip("/")
    except Exception:
        # мусор в поле site (IPv6-подобное, скобки и т.п.) — не сайт
        return ""


def _pick_email(contacts: list, description: str, site_domain: str) -> str:
    """Лучший email: фирменный (домен сайта) > правильный префикс > любой."""
    cands = []
    for c in contacts or []:
        e = (c.get("email") or "").strip()
        if e and "@" in e:
            cands.append(e)
    cands += EMAIL_RE.findall(description or "")

    best, best_score = "", -1
    for e in cands:
        low = e.lower()
        if any(b in low for b in EMAIL_BLOCKLIST):
            continue
        score = 0
        local, _, domain = low.partition("@")
        if site_domain and (domain == site_domain or domain.endswith("." + site_domain)):
            score += 100
        for i, pref in enumerate(PREFERRED_PREFIXES):
            if local == pref or local.startswith(pref + "."):
                score += 50 - i
                break
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 0 else ""


def _pick_phone(contacts: list) -> str:
    for c in contacts or []:
        p = (c.get("phone") or "").strip()
        if p:
            return normalize_phone(p)
    return ""


def _client_type(verdict: str, name: str, activity: str) -> str:
    """client_type записи: детальный для ритуала, 'флористика', '' для ambiguous."""
    if verdict == "флористика":
        return "флористика"
    if verdict == "ритуал":
        ct = normalize(f"{name} {activity}")
        return ct if ct != "прочее" else "ритуальное агентство"
    return ""  # ambiguous → пусто; помечается needs_review


async def run(context):
    """context не используется (HTTP-only)."""
    token = os.getenv("VK_TOKEN", "").strip()
    if not token:
        print("\n=== VK: VK_TOKEN не задан, пропуск ===")
        return

    print("\n=== VK Groups ===")

    # 1. Сбор group_id по матрице город × категория
    found: dict[int, str] = {}  # group_id -> city_name откуда нашли
    for city_id, city_name in VK_CITIES.items():
        for q in QUERIES:
            r = _call("groups.search", token, q=q, city_id=city_id,
                      count=200, sort=0)
            time.sleep(RPS_PAUSE)
            if "error" in r:
                msg = r["error"].get("error_msg", "?")
                if "Too many" in msg:
                    time.sleep(1.0)
                continue
            for it in r.get("response", {}).get("items", []):
                gid = it.get("id")
                if gid and gid not in found:
                    found[gid] = city_name
        print(f"  [VK] {city_name}: накоплено {len(found)} групп")

    if not found:
        print("  [VK] ничего не найдено")
        return

    print(f"  [VK] всего уникальных групп: {len(found)}")

    # 2. Детали пачками по 500
    added = 0
    skipped_noise = 0
    flagged_ambiguous = 0
    gids = list(found.keys())
    for start in range(0, len(gids), 500):
        chunk = gids[start:start + 500]
        r = _call("groups.getById", token,
                  group_ids=",".join(map(str, chunk)),
                  fields="contacts,site,description,addresses,activity,city,screen_name")
        time.sleep(RPS_PAUSE)
        if "error" in r:
            print(f"  [VK] getById err: {r['error'].get('error_msg', '?')[:80]}")
            time.sleep(1.0)
            continue
        resp = r.get("response")
        groups = resp.get("groups") if isinstance(resp, dict) else resp
        for g in groups or []:
            name = (g.get("name") or "").strip()
            if not name:
                continue
            gid = g.get("id")
            site = _clean_site(g.get("site") or "")
            sdom = _site_domain(site)
            contacts = g.get("contacts") or []
            desc = g.get("description") or ""
            email = _pick_email(contacts, desc, sdom)
            phone = _pick_phone(contacts)
            city_obj = g.get("city") or {}
            city = (city_obj.get("title") if isinstance(city_obj, dict) else "") \
                or found.get(gid, "Крым")
            screen = g.get("screen_name") or f"club{gid}"
            social = f"https://vk.com/{screen}"
            activity = g.get("activity") or "размещение"

            verdict = vk_classify(name, activity)
            if verdict == "noise":
                skipped_noise += 1
                continue
            comment = "needs_review" if verdict == "ambiguous" else ""
            client_type = _client_type(verdict, name, activity)
            if verdict == "ambiguous":
                flagged_ambiguous += 1

            if save_item({
                "city": city,
                "name": name,
                "address": "",
                "phone": phone,
                "email": email,
                "website": site,
                "social": social,
                "category": activity,
                "client_type": client_type,
                "comment": comment,
                "source": "VK",
                "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }):
                added += 1

    print(f"\n[VK] добавлено: {added} | пропущено шума: {skipped_noise} "
          f"| помечено ambiguous: {flagged_ambiguous}")
