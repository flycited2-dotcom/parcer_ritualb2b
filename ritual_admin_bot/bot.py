"""Telegram-бот управления Ritual B2B Parser.

Запускается на ТОМ ЖЕ сервере, что и парсер. Управляет через локальные
systemctl/journalctl. Авторизация — whitelist по chat_id (ADMIN_CHAT_IDS в .env).
"""
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()

from handlers.commands import router  # noqa: E402
from handlers.menu import menu_router  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        log.error("BOT_TOKEN не задан — выходим")
        sys.exit(1)

    if not os.getenv("ADMIN_CHAT_IDS"):
        log.warning("ADMIN_CHAT_IDS пустой — все запросы будут отвергнуты")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(menu_router)

    me = await bot.get_me()
    log.info("Стартуем %s (id=%s)", me.username, me.id)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
