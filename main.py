import asyncio
import glob
import os
import sys
from playwright.async_api import async_playwright

from utils.env_loader import load_all_env

load_all_env()
from utils.browser import create_browser_context
from utils.storage import total, get_output_file, cross_source_merge
from utils.telegram_notify import notify as tg_notify, checkpoint as tg_checkpoint
from utils import progress
from parsers import (
    osm, wikidata, wikipedia, gosreestr, vk_groups,
    yandex_maps, search_engine, avito, sutochno, ostrovok, twogis, crawler,
)
from parsers.email_finder import run_enrichment


# (label, runner, key) — key используется в env ONLY_SOURCE для точечного запуска.
RUNNERS = [
    # Быстрые HTTP-API источники сначала
    ("OSM",                            osm.run,           "osm"),
    ("Wikidata",                       wikidata.run,      "wikidata"),
    ("Wikipedia",                      wikipedia.run,     "wikipedia"),
    ("Госреестр Минэка",               gosreestr.run,     "gosreestr"),
    ("VK Groups",                      vk_groups.run,     "vk"),
    # Тяжёлые Chromium-источники
    ("Я.Карты",                        yandex_maps.run,   "yandex"),
    ("Поиск (Яндекс/Mail/Rambler/Bing)", search_engine.run, "search"),
    ("2ГИС",                           twogis.run,        "2gis"),
    ("Авито",                          avito.run,         "avito"),
    ("Суточно.ру",                     sutochno.run,      "sutochno"),
    ("Ostrovok",                       ostrovok.run,      "ostrovok"),
    # Crawler идёт последним — он опирается на уже собранные website
    ("Crawler",                        crawler.run,       "crawler"),
]


def _detect_resume() -> set[str]:
    """Защита от двойного старта + восстановление после kill/OOM/reboot.

    Возвращает set уже отработанных источников (если идём в режиме resume),
    либо завершает процесс если другой парсер ещё активно работает.
    """
    from datetime import datetime, timedelta

    prev = progress.read()
    if prev.get("status") != "running":
        return set()
    last_update_str = prev.get("last_update")
    if not last_update_str:
        return set()
    try:
        last_update = datetime.fromisoformat(last_update_str)
    except (ValueError, TypeError):
        return set()
    age = datetime.now() - last_update
    if age < timedelta(hours=1):
        print(f"⚠ progress.json status=running, last_update {int(age.total_seconds())}с назад.")
        print("  Другой процесс ещё работает — выход. (если уверен в обратном — сбрось progress.json вручную)")
        sys.exit(0)
    print(f"♻ Stale progress.json ({age.total_seconds()/3600:.1f}ч) — RESUME.")
    done = set(prev.get("completed_sources", []))
    if done:
        print(f"  Уже отработали: {sorted(done)}")
    return done


async def main():
    print("=" * 60)
    print("  CRIMEA HOTEL PARSER — запуск всех источников")
    print("=" * 60)

    headless_env = os.getenv("HEADLESS", "1").lower()
    headless = headless_env not in ("0", "false", "")

    only_source = (os.getenv("ONLY_SOURCE") or "").strip().lower()
    skip_enrichment = os.getenv("SKIP_ENRICHMENT", "0").lower() in ("1", "true", "yes")

    completed_already = _detect_resume()

    runners = RUNNERS
    if only_source:
        runners = [r for r in RUNNERS if r[2] == only_source]
        if not runners:
            print(f"⚠ ONLY_SOURCE={only_source!r} не совпадает ни с одним источником: "
                  f"{[r[2] for r in RUNNERS]}")
            return
    if completed_already:
        runners = [r for r in runners if r[0] not in completed_already]
        print(f"  После фильтра resume осталось runners: {[r[0] for r in runners]}")

    print(f"Headless: {headless}, ONLY_SOURCE: {only_source or '—'}, "
          f"SKIP_ENRICHMENT: {skip_enrichment}")
    print(f"Источники: {[r[0] for r in runners]}")

    progress.mark_started()
    # Resume — восстанавливаем список уже отработанных, чтобы mark_completed_source
    # дальше дописывался поверх, а не начинался с нуля.
    if completed_already:
        progress.update(completed_sources=sorted(completed_already))
    import time
    from utils.storage import total as storage_total

    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=headless)
        try:
            for label, runner, _key in runners:
                progress.mark_stage(label)
                stage_started = time.monotonic()
                count_before = storage_total()
                try:
                    await runner(context)
                    progress.mark_completed_source(label)
                    added = storage_total() - count_before
                    elapsed = int(time.monotonic() - stage_started)
                    try:
                        tg_checkpoint(label, added, storage_total(), elapsed)
                    except Exception as e:
                        print(f"[checkpoint] err: {e}")
                except Exception as e:
                    print(f"\n[{label}] критическая ошибка: {e}")
                    import traceback
                    traceback.print_exc()
                    try:
                        from utils.telegram_notify import send_message
                        tok = os.environ.get("TG_BOT_TOKEN", "")
                        chat = os.environ.get("TG_CHAT_ID", "")
                        if tok and chat:
                            send_message(tok, chat, f"⚠️ <b>{label}</b>: ошибка — <code>{str(e)[:200]}</code>")
                    except Exception:
                        pass
        finally:
            await browser.close()

    progress.mark_stage("cross_source_merge")
    print(f"\n✅ Собрано записей: {total()}")

    # Cross-source merge — подтягиваем недостающие phone/email/website
    # на записи Я.Карты/прочих из совпадающих по имени записей OSM/2ГИС.
    try:
        merged = cross_source_merge()
        if merged:
            print(f"🔗 Cross-source merge: обогащено {merged} ячеек")
    except Exception as e:
        print(f"[merge] ошибка: {e}")

    latest = get_output_file()
    enriched = None
    if not skip_enrichment and os.path.exists(latest):
        print(f"\n🔍 Запускаем Email Finder по: {latest}")
        enriched = await run_enrichment(latest)
    elif skip_enrichment:
        print("[email_finder] SKIP_ENRICHMENT=1 — пропускаем")

    progress.mark_stage("email_finder")
    final_csv = enriched or latest

    progress.mark_stage("xlsx")
    # XLSX-отчёт со вкладками по городам
    xlsx_path = ""
    if os.path.exists(final_csv):
        try:
            from utils.excel_export import build_xlsx
            xlsx_path = build_xlsx(final_csv) or ""
        except Exception as e:
            print(f"[xlsx] ошибка: {e}")

    auto_notify = os.getenv("AUTO_NOTIFY", "1").lower() not in ("0", "false", "")
    if auto_notify and os.path.exists(final_csv):
        try:
            tg_notify(final_csv, source_label="weekly run", xlsx_path=xlsx_path)
        except Exception as e:
            print(f"[telegram] критическая ошибка отчётности: {e}")
    elif not auto_notify:
        print("[telegram] AUTO_NOTIFY=0, отчёт не отправлен (отдельный планировщик)")

    # Auto-upload master CSV/XLSX to Google Drive (if GDRIVE_FOLDER_ID is set)
    if os.getenv("GDRIVE_FOLDER_ID"):
        try:
            from utils.merger import build_master_xlsx
            from utils.gdrive import upload_file
            master_csv, master_xlsx = build_master_xlsx()
            if master_csv and os.path.exists(master_csv):
                upload_file(master_csv)
            if master_xlsx and os.path.exists(master_xlsx):
                upload_file(master_xlsx)
        except Exception as e:
            print(f"[gdrive] {e}")

    progress.mark_finished("ok")
    print("\n🎉 Всё готово! Смотри папку output/")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        progress.mark_failed("KeyboardInterrupt")
        raise
    except Exception as e:
        progress.mark_failed(str(e))
        raise
