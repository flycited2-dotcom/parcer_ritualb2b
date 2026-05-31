"""Find the official website of a hotel by name and city via DuckDuckGo."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request

_BLACKLIST = {
    "booking.com", "ostrovok.ru", "sutochno.ru", "tripadvisor.com",
    "yandex.ru", "google.com", "2gis.ru", "avito.ru", "vk.com",
    "instagram.com", "ok.ru", "otzovik.com", "zoon.ru", "hotels.com",
    "airbnb.com", "wikipedia.org",
    # сам DDG — если попали на anomaly-modal, первая ссылка ведёт на duckduckgo.com.
    # без этого фильтра email_finder уходит туда и записывает error+...@duckduckgo.com.
    "duckduckgo.com", "duckduckgo.org", "html.duckduckgo.com",
}

_RESULT_URL_RE = re.compile(r'<a[^>]+class="[^"]*result__url[^"]*"[^>]*>([^<]+)</a>', re.I)
_HREF_RE = re.compile(r'href="(https?://[^"]+)"', re.I)


def find_website(name: str, city: str, timeout: int = 15) -> str | None:
    """
    Search DuckDuckGo HTML for the official website of the given hotel.
    Returns a URL string or None. Uses only stdlib (no aiohttp needed).
    """
    query = urllib.parse.quote(f"{name} {city} официальный сайт")
    url = f"https://html.duckduckgo.com/html/?q={query}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; HotelEmailFinder/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    # Extract result URLs from DDG HTML response
    for match in _RESULT_URL_RE.finditer(html):
        href = match.group(1).strip()
        if not href.startswith("http"):
            href = "https://" + href
        domain = _extract_domain(href)
        if domain and not any(bl in domain for bl in _BLACKLIST):
            return href

    # Fallback: look for any https link not in blacklist
    for match in _HREF_RE.finditer(html):
        href = match.group(1)
        domain = _extract_domain(href)
        if domain and not any(bl in domain for bl in _BLACKLIST):
            return href

    return None


def _extract_domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lstrip("www.")
    except Exception:
        return ""
