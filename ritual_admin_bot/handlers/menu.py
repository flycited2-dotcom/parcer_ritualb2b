"""Пульт-меню на inline-кнопках. Каждый раздел зовёт сервисы рендера."""
import glob
import logging
import os

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from services.auth import ADMIN_IDS, is_admin
from services.drive import get_drive_text, reupload_master
from services.panel import (back_kb, drive_kb, main_menu_kb, run_menu_kb,
                            status_text)
from services.progress import get_progress_text
from services.stats import get_stats_text
from services.systemd import (EMAILS_UNIT, PARSER_TIMER, PARSER_UNIT, _run,
                              is_active, systemctl)

log = logging.getLogger(__name__)
menu_router = Router()

_OUTPUT_DIR = os.path.join(os.getenv("PARSER_DIR", "/home/ritual_parser"), "output")
_PANEL = "<b>Пульт управления Ritual B2B Parser</b>\nВыбери раздел:"


def _files_kb() -> InlineKeyboardMarkup | None:
    files = sorted(
        glob.glob(os.path.join(_OUTPUT_DIR, "*.csv")) +
        glob.glob(os.path.join(_OUTPUT_DIR, "*.xlsx")),
        key=os.path.getmtime, reverse=True,
    )[:10]
    if not files:
        return None
    rows = [[InlineKeyboardButton(
        text=f"📄 {os.path.basename(f)} ({os.path.getsize(f) // 1024} KB)",
        callback_data=f"dl:{os.path.basename(f)}")] for f in files]
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@menu_router.message(Command("menu"))
async def cmd_menu(m: Message) -> None:
    if not is_admin(m.chat.id):
        return
    await m.answer(_PANEL, parse_mode="HTML", reply_markup=main_menu_kb())


@menu_router.message(Command("stats"))
async def cmd_stats(m: Message) -> None:
    if not is_admin(m.chat.id):
        return
    await m.answer(get_stats_text(), parse_mode="HTML", reply_markup=back_kb())


@menu_router.message(Command("progress"))
async def cmd_progress(m: Message) -> None:
    if not is_admin(m.chat.id):
        return
    await m.answer(get_progress_text(), parse_mode="HTML", reply_markup=back_kb())


@menu_router.message(Command("drive"))
async def cmd_drive(m: Message) -> None:
    if not is_admin(m.chat.id):
        return
    await m.answer(await get_drive_text(), parse_mode="HTML",
                   reply_markup=drive_kb(), disable_web_page_preview=True)


async def _edit(cb: CallbackQuery, text: str, kb, preview: bool = False) -> None:
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb,
                                   disable_web_page_preview=not preview)
    except TelegramBadRequest:
        pass  # «message is not modified» при повторном нажатии
    await cb.answer()


@menu_router.callback_query(F.data.startswith("menu:"))
async def on_menu(cb: CallbackQuery) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer()
        return
    action = cb.data.split(":", 1)[1]

    if action == "home":
        await _edit(cb, _PANEL, main_menu_kb())
    elif action == "run":
        await _edit(cb, "▶ <b>Прогон</b>\nЧто запустить?", run_menu_kb())
    elif action == "status":
        await _edit(cb, await status_text(), back_kb())
    elif action == "progress":
        await _edit(cb, get_progress_text(), back_kb())
    elif action == "stats":
        await _edit(cb, get_stats_text(), back_kb())
    elif action == "drive":
        await _edit(cb, await get_drive_text(), drive_kb())
    elif action == "files":
        kb = _files_kb()
        await _edit(cb, "📁 Файлы output/:" if kb else "Нет файлов в output/",
                    kb or back_kb())
    elif action == "sched":
        _, out = await _run("systemctl", "list-timers", "--all", PARSER_TIMER)
        await _edit(cb, f"🗓 <b>Расписание</b>\n<pre>{out.strip() or '—'}</pre>", back_kb())
    elif action == "reupload":
        await cb.answer("Перезаливаю…")
        await cb.message.answer(await reupload_master())
    elif action == "do_run":
        if await is_active(PARSER_UNIT):
            await cb.answer("Уже работает", show_alert=True)
        else:
            code, out = await systemctl("start", PARSER_UNIT)
            await cb.message.answer("✅ Прогон запущен." if code == 0
                                    else f"❌ rc={code}\n{out[:500]}")
            await cb.answer()
    elif action == "do_emails":
        if await is_active(EMAILS_UNIT):
            await cb.answer("Уже работает", show_alert=True)
        else:
            code, out = await systemctl("start", EMAILS_UNIT)
            await cb.message.answer("✅ email_finder по master запущен." if code == 0
                                    else f"❌ rc={code}\n{out[:500]}")
            await cb.answer()
    elif action == "do_stop":
        code, out = await systemctl("stop", PARSER_UNIT)
        await cb.message.answer("🛑 Остановлено." if code == 0
                                else f"❌ rc={code}\n{out[:500]}")
        await cb.answer()
    else:
        await cb.answer()
