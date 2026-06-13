"""Сборка статуса и inline-клавиатур для пульт-меню."""
import os
import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.csv_finder import csv_summary, latest_csv
from services.systemd import (EMAILS_UNIT, PARSER_UNIT, is_active)

_STAGE_RE = re.compile(r"===\s*([^=]+?)\s*===")


def _current_stage() -> str:
    log_path = os.path.join(os.getenv("PARSER_DIR", "/home/ritual_parser"),
                            "parser.log")
    if not os.path.exists(log_path):
        return "—"
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-200:]
        for line in reversed(tail):
            m = _STAGE_RE.search(line)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return "—"


async def status_text() -> str:
    parser_active = await is_active(PARSER_UNIT)
    emails_active = await is_active(EMAILS_UNIT)
    csv_info = csv_summary(latest_csv() or "")
    return "\n".join([
        "📊 <b>Статус</b>",
        f"{PARSER_UNIT}: {'🟢 active' if parser_active else '⚪ inactive'}",
        f"{EMAILS_UNIT}: {'🟢 active' if emails_active else '⚪ inactive'}",
        f"Стадия: <b>{_current_stage()}</b>",
        "",
        "<b>Последний CSV</b>",
        f"<pre>{csv_info}</pre>",
    ])


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Excel в чат", "menu:excel")],
        [_btn("▶ Прогон", "menu:run"), _btn("📈 Статус", "menu:status")],
        [_btn("🔄 Прогресс", "menu:progress"), _btn("🗄 Стата базы", "menu:stats")],
        [_btn("📁 Файлы", "menu:files"), _btn("☁ Drive", "menu:drive")],
        [_btn("🗓 Расписание", "menu:sched")],
    ])


def run_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🚀 Полный прогон", "menu:do_run")],
        [_btn("✉ Обогатить master (email)", "menu:do_emails")],
        [_btn("🛑 Стоп", "menu:do_stop")],
        [_btn("◀ Назад", "menu:home")],
    ])


def drive_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔁 Перезалить master сейчас", "menu:reupload")],
        [_btn("◀ Назад", "menu:home")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("◀ Назад", "menu:home")]])
