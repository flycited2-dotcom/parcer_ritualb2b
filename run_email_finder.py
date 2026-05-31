"""Запустить ТОЛЬКО email_finder на самом свежем result_*.csv в output/.

Используется отдельным systemd-юнитом ritual_email_finder.service —
бот может /run_emails не запуская весь парсинг заново.
"""
import asyncio
import glob
import os
import sys

# гарантируем, что `utils.*` и `parsers.*` импортируются от корня скрипта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.env_loader import load_all_env  # noqa: E402

load_all_env()

from parsers.email_finder import run_enrichment  # noqa: E402
from utils.telegram_notify import notify as tg_notify  # noqa: E402


def latest_unenriched_csv(output_dir: str) -> str | None:
    """Самый свежий result_*.csv, который ещё не enriched."""
    pattern = os.path.join(output_dir, "result_*.csv")
    files = [f for f in glob.glob(pattern)
             if "enriched" not in os.path.basename(f)]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


async def main() -> None:
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    master_path = os.path.join(output_dir, "master_all.csv")

    # ENRICH_LATEST=1 preserves old behavior (process only newest result_*.csv)
    if os.getenv("ENRICH_LATEST", "0").lower() in ("1", "true"):
        target = latest_unenriched_csv(output_dir)
        if not target:
            print("Нет result_*.csv в output/ — нечего обогащать.")
            return
    else:
        # Default: build/use master_all.csv (all runs, deduplicated)
        if not os.path.exists(master_path):
            print("master_all.csv не найден — собираю из result_*.csv…")
            try:
                from utils.merger import build_master
                master_path = build_master(output_dir)
            except Exception as e:
                print(f"[merger] {e}")
                return
        target = master_path

    print(f"Обогащаем: {target}")
    enriched = await run_enrichment(target)

    xlsx_path = ""
    if enriched:
        try:
            from utils.excel_export import build_xlsx
            xlsx_path = build_xlsx(enriched) or ""
        except Exception as e:
            print(f"[xlsx] {e}")

    if enriched and os.getenv("AUTO_NOTIFY", "1").lower() not in ("0", "false", ""):
        try:
            tg_notify(enriched, source_label="email_finder rerun", xlsx_path=xlsx_path)
        except Exception as e:
            print(f"[telegram] {e}")

    # Auto-upload to Google Drive
    if os.getenv("GDRIVE_FOLDER_ID"):
        try:
            from utils.merger import build_master_xlsx
            from utils.gdrive import upload_file
            master_csv, master_xlsx = build_master_xlsx()
            if master_csv and os.path.exists(master_csv):
                upload_file(master_csv)
            if master_xlsx and os.path.exists(master_xlsx):
                upload_file(master_xlsx)
            if enriched and os.path.exists(enriched):
                upload_file(enriched)
        except Exception as e:
            print(f"[gdrive] {e}")


if __name__ == "__main__":
    asyncio.run(main())
