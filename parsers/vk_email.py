"""Extract email from public VK group pages."""
from __future__ import annotations

import re
import urllib.request

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
_VK_SKIP = {"vk.com", "vkontakte.ru", "noreply"}


def extract_email_from_vk(vk_url: str, timeout: int = 20) -> str | None:
    """
    Fetch a public VK group/user page and extract the first email from the text.
    Returns email string or None. Never raises.
    """
    if not vk_url or "vk.com" not in vk_url:
        return None
    req = urllib.request.Request(
        vk_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    # Strip script/style tags to avoid matching obfuscated JS strings
    html_clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    emails = _EMAIL_RE.findall(html_clean)
    for email in emails:
        domain = email.split("@")[-1].lower()
        if not any(skip in domain for skip in _VK_SKIP):
            return email
    return None
