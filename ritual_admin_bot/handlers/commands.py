"""Все команды бота. По 5-15 строк на хендлер — компактно и читаемо."""
import glob
import html
import logging
import os
import re

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (CallbackQuery, FSInputFile,
                            InlineKeyboardButton, InlineKeyboardMarkup, Message)



def esc(s: str) -> str:
    """HTML-escape для значений, идущих в parse_mode=HTML сообщения.
    systemctl/journalctl могут вернуть <,>,& — без эскейпа Telegram упадёт
    с TelegramBadRequest 'Unsupported start tag'.
    """
    return html.escape(s or "", quote=False)

from services.auth import ADMIN_IDS, is_admin
from services.csv_finder import (csv_summary, latest_csv, latest_enriched,
                                  latest_xlsx)
from services.systemd import (EMAILS_UNIT, PARSER_TIMER, PARSER_UNIT, _run,
                               health, is_active, journal_tail, systemctl)

log = logging.getLogger(__name__)
router = Router()

VALID_SOURCES = ("osm", "wikidata", "wikipedia", "vk", "yandex", "search",
                 "2gis", "avito", "sutochno", "ostrovok", "crawler")


@router.message(F.func(lambda m: not is_admin(m.chat.id)))
async def _block_strangers(message: Message) -> None:
    """Чужой chat_id — молчим, чтобы не светить наличие бота."""
    log.info("denied chat_id=%s text=%r", message.chat.id, (message.text or "")[:80])


@router.message(Command("start", "help"))
async def cmd_help(m: Message) -> None:
    text = (
        "<b>Управление Ritual B2B Parser</b>\n\n"
        "/menu — пульт на кнопках\n\n"
        "<b>Запуск</b>\n"
        "/run — полный прогон\n"
        "/run_emails — email_finder по master_all (вся база)\n"
        "/run_source <name> — один источник "
        f"({', '.join(VALID_SOURCES)})\n"
        "/stop — остановить текущий прогон\n\n"
        "<b>Информация</b>\n"
        "/status — стадия + последний CSV\n"
        "/stats — аналитика базы + дельта\n"
        "/sources — записи по источникам в свежем CSV\n"
        "/db — статистика SQLite dedup.db (всё время)\n"
        "/progress — живой прогресс прогона\n"
        "/logs [N] — N последних строк journalctl (по умолчанию 50)\n"
        "/health — uptime, диск, память\n\n"
        "<b>Файлы</b>\n"
        "/csv — последний result_*.csv\n"
        "/csv_enriched — последний result_enriched_*.csv\n"
        "/xlsx — последний result_*.xlsx\n"
        "/reports — список последних файлов output/ для скачивания\n"
        "/master — мастер-файл из всех прогонов\n"
        "/drive — папка Google Drive + перезалив\n\n"
        "<b>Расписание</b>\n"
        "/timer_on — включить еженедельный запуск\n"
        "/timer_off — отключить\n"
        "/schedule — текущее расписание"
    )
    await m.answer(text, parse_mode="HTML")


@router.message(Command("run"))
async def cmd_run(m: Message) -> None:
    if await is_active(PARSER_UNIT):
        await m.answer(f"⚠ {PARSER_UNIT} уже работает. /stop для остановки.")
        return
    code, out = await systemctl("start", PARSER_UNIT)
    if code == 0:
        await m.answer(f"✅ {PARSER_UNIT} запущен (TimeoutStartSec=12h, fire-and-forget)\n"
                       f"Прогресс: /status. Финальный отчёт придёт автоматически.")
    else:
        await m.answer(f"❌ systemctl start: rc={code}\n<pre>{out}</pre>", parse_mode="HTML")


@router.message(Command("run_emails"))
async def cmd_run_emails(m: Message) -> None:
    if await is_active(EMAILS_UNIT):
        await m.answer(f"⚠ {EMAILS_UNIT} уже работает.")
        return
    code, out = await systemctl("start", EMAILS_UNIT)
    if code == 0:
        await m.answer(f"✅ {EMAILS_UNIT} запущен — обогащает последний CSV.")
    else:
        await m.answer(f"❌ systemctl start: rc={code}\n<pre>{out}</pre>", parse_mode="HTML")


@router.message(Command("run_source"))
async def cmd_run_source(m: Message, command: CommandObject) -> None:
    name = (command.args or "").strip().lower()
    if name not in VALID_SOURCES:
        await m.answer(f"Источник: {', '.join(VALID_SOURCES)}")
        return
    unit = f"ritual_parser_source@{name}.service"
    code, out = await _run("sudo", "-n", "systemctl", "start", "--no-block", unit)
    if code == 0:
        await m.answer(f"✅ {unit} запущен (ONLY_SOURCE={name}, без email_finder).")
    else:
        await m.answer(f"❌ rc={code}\n<pre>{out[:1000]}</pre>", parse_mode="HTML")


@router.message(Command("stop"))
async def cmd_stop(m: Message) -> None:
    code, out = await systemctl("stop", PARSER_UNIT)
    if code == 0:
        await m.answer(f"🛑 {PARSER_UNIT} остановлен.")
    else:
        await m.answer(f"❌ systemctl stop: rc={code}\n<pre>{out}</pre>", parse_mode="HTML")


_OUTPUT_DIR = "/home/ritual_parser/output"


@router.message(Command("reports"))
async def cmd_reports(m: Message) -> None:
    files = sorted(
        glob.glob(os.path.join(_OUTPUT_DIR, "*.csv")) +
        glob.glob(os.path.join(_OUTPUT_DIR, "*.xlsx")),
        key=os.path.getmtime,
        reverse=True,
    )[:10]
    if not files:
        await m.answer("Нет файлов в output/")
        return
    buttons = []
    for f in files:
        name = os.path.basename(f)
        size_kb = os.path.getsize(f) // 1024
        buttons.append([InlineKeyboardButton(text=f"📄 {name} ({size_kb} KB)",
                                              callback_data=f"dl:{name}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer("Выберите файл:", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("dl:"))
async def cb_download_file(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    name = os.path.basename(callback.data[3:])  # sanitize: strip any path component
    path = os.path.join(_OUTPUT_DIR, name)
    if not os.path.exists(path):
        await callback.message.answer(f"Файл не найден: {esc(name)}")
        await callback.answer()
        return
    await callback.message.answer_document(FSInputFile(path), caption=f"📎 {esc(name)}")
    await callback.answer()


@router.message(Command("master"))
async def cmd_master(m: Message) -> None:
    await m.answer("⏳ Собираю мастер-файл…")
    try:
        import sys
        sys.path.insert(0, "/home/ritual_parser")
        from utils.merger import build_master_xlsx  # type: ignore[import]
        csv_path, xlsx_path = build_master_xlsx()
        await m.answer_document(FSInputFile(csv_path), caption="📊 master_all.csv")
        if xlsx_path and os.path.exists(xlsx_path):
            await m.answer_document(FSInputFile(xlsx_path), caption="📊 master_all.xlsx")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {esc(str(e))}")


@router.message(Command("status"))
async def cmd_status(m: Message) -> None:
    from services.panel import status_text
    await m.answer(await status_text(), parse_mode="HTML")


@router.message(Command("logs"))
async def cmd_logs(m: Message, command: CommandObject) -> None:
    n = 50
    arg = (command.args or "").strip()
    if arg.isdigit():
        n = max(1, min(int(arg), 500))
    out = await journal_tail(PARSER_UNIT, n=n)
    if len(out) > 3500:
        out = out[-3500:]
    await m.answer(f"<pre>{out or 'пусто'}</pre>", parse_mode="HTML")


@router.message(Command("health"))
async def cmd_health(m: Message) -> None:
    out = await health()
    await m.answer(f"<pre>{out}</pre>", parse_mode="HTML")


@router.message(Command("sources"))
async def cmd_sources(m: Message) -> None:
    """Записи по источникам в свежем CSV (перенесено из ritual_bot)."""
    import csv as csv_mod
    path = latest_csv()
    if not path:
        await m.answer("⚠ Нет CSV в output/")
        return
    sources: dict[str, int] = {}
    total = 0
    try:
        with open(path, encoding="utf-8-sig") as f:
            for row in csv_mod.DictReader(f, delimiter=";"):
                total += 1
                src = (row.get("source") or "").strip() or "—"
                sources[src] = sources.get(src, 0) + 1
    except Exception as e:
        await m.answer(f"❌ Ошибка чтения CSV: {esc(str(e))}")
        return
    lines = [f"<b>По источникам</b> в <code>{esc(os.path.basename(path))}</code>:"]
    for src, n in sorted(sources.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {esc(src)}: <b>{n}</b>")
    lines.append(f"\nИтого: <b>{total}</b>")
    await m.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("db"))
async def cmd_db(m: Message) -> None:
    """Статистика SQLite dedup.db за все прогоны (перенесено из ritual_bot)."""
    try:
        import sys
        sys.path.insert(0, "/home/ritual_parser")
        from utils import dedup  # type: ignore[import]
        total = dedup.total()
        by_src = dedup.stats_by_source()
    except Exception as e:
        await m.answer(f"❌ Ошибка чтения dedup.db: {esc(str(e))}")
        return
    lines = [
        "<b>База за все прогоны (dedup.db)</b>",
        f"Уникальных записей: <b>{total}</b>",
        "",
        "<b>По источникам</b>:",
    ]
    for s, n in sorted(by_src.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {esc(s)}: <b>{n}</b>")
    await m.answer("\n".join(lines), parse_mode="HTML")


async def _send_file(m: Message, path: str | None, label: str) -> None:
    if not path or not os.path.exists(path):
        await m.answer(f"⚠ {label}: файлов нет в output/")
        return
    await m.answer_document(FSInputFile(path), caption=csv_summary(path))


@router.message(Command("csv"))
async def cmd_csv(m: Message) -> None:
    await _send_file(m, latest_csv(), "result_*.csv")


@router.message(Command("csv_enriched"))
async def cmd_csv_enriched(m: Message) -> None:
    await _send_file(m, latest_enriched(), "result_enriched_*.csv")


@router.message(Command("xlsx"))
async def cmd_xlsx(m: Message) -> None:
    await _send_file(m, latest_xlsx(), "result_*.xlsx")


@router.message(Command("timer_on"))
async def cmd_timer_on(m: Message) -> None:
    code, out = await systemctl("enable", PARSER_TIMER)
    code2, out2 = await systemctl("start", PARSER_TIMER)
    if code == 0 and code2 == 0:
        await m.answer(f"✅ {PARSER_TIMER}: enabled+started (вс 03:00)")
    else:
        await m.answer(f"<pre>enable: rc={code}\n{out}\nstart: rc={code2}\n{out2}</pre>",
                       parse_mode="HTML")


@router.message(Command("timer_off"))
async def cmd_timer_off(m: Message) -> None:
    code, out = await systemctl("stop", PARSER_TIMER)
    code2, out2 = await systemctl("disable", PARSER_TIMER)
    if code == 0 and code2 == 0:
        await m.answer(f"🛑 {PARSER_TIMER}: остановлен и отключён")
    else:
        await m.answer(f"<pre>stop: rc={code}\n{out}\ndisable: rc={code2}\n{out2}</pre>",
                       parse_mode="HTML")


@router.message(Command("schedule"))
async def cmd_schedule(m: Message) -> None:
    code, out = await _run("systemctl", "list-timers", "--all", PARSER_TIMER)
    if code != 0:
        await m.answer(f"<pre>rc={code}\n{out}</pre>", parse_mode="HTML")
        return
    await m.answer(f"<pre>{out}</pre>", parse_mode="HTML")
