"""Whitelist по chat_id (Telegram)."""
import logging
import os

log = logging.getLogger(__name__)


def _parse_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.add(int(tok))
        except ValueError:
            log.warning("ADMIN_CHAT_IDS: невалидный токен %r", tok)
    return out


ADMIN_IDS: set[int] = _parse_ids(os.getenv("ADMIN_CHAT_IDS", ""))


def is_admin(chat_id: int) -> bool:
    return chat_id in ADMIN_IDS
