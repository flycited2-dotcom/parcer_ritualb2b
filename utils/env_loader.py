"""Загрузка секретов из расщеплённых .env-файлов.

Цель: уменьшить blast radius при компрометации одного секрета.
Грузит в таком порядке (последний выигрывает при коллизии ключей):
  1. .env                 — общий fallback / совместимость
  2. .env.tg              — Telegram токены и chat_id
  3. .env.vk              — VK_TOKEN
  4. .env.gdrive          — GDRIVE_FOLDER_ID, GDRIVE_TOKEN
  5. .env.local           — локальные оверрайды (DEBUG, HEADLESS=0 на ноуте и т.п.)

Все опциональны: если файла нет — игнорируем. Это backward-compat с текущим
прод-окружением, где живёт один монолитный `.env`.
"""
from __future__ import annotations

import glob
import os

from dotenv import load_dotenv

_FILES_PRIORITY = (".env", ".env.tg", ".env.vk", ".env.gdrive", ".env.local")


def load_all_env(base_dir: str | None = None) -> list[str]:
    """Загружает все .env-файлы из base_dir (по умолчанию — CWD).

    Возвращает список реально найденных файлов — для диагностики.
    """
    cwd = base_dir or os.getcwd()
    loaded: list[str] = []
    seen: set[str] = set()
    # сначала строгий приоритетный порядок
    for name in _FILES_PRIORITY:
        path = os.path.join(cwd, name)
        if os.path.isfile(path) and path not in seen:
            load_dotenv(path, override=True)
            loaded.append(name)
            seen.add(path)
    # потом любые дополнительные .env.* (например .env.crawler), не из списка
    for path in sorted(glob.glob(os.path.join(cwd, ".env.*"))):
        if path in seen:
            continue
        load_dotenv(path, override=True)
        loaded.append(os.path.basename(path))
        seen.add(path)
    return loaded
