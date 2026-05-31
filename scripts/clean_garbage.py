"""Чистка DDG-мусора в собранных CSV.

site_finder при попадании на anomaly-страницу DuckDuckGo первой ссылкой брал
сам duckduckgo.com → website загрязнялся, email_finder уходил туда и записывал
email типа error+<hash>@duckduckgo.com. Этот скрипт обнуляет такие поля
во всех существующих CSV (master_all + все result_enriched_*).

Запуск:
    cd /home/ritual_parser && ./venv/bin/python scripts/clean_garbage.py

Идемпотентен — повторный запуск ничего не меняет.
"""
from __future__ import annotations

import csv
import glob
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.storage import CSV_DELIMITER, FIELDS  # noqa: E402

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

# Любая из этих подстрок в lower-cased поле → считаем мусором.
GARBAGE_WEBSITE_SUBSTR = ("duckduckgo.com", "duckduckgo.org")
GARBAGE_EMAIL_SUBSTR = ("@duckduckgo.com", "@duckduckgo.org")


def _is_garbage_website(value: str) -> bool:
    low = (value or "").lower()
    return any(s in low for s in GARBAGE_WEBSITE_SUBSTR)


def _is_garbage_email(value: str) -> bool:
    low = (value or "").lower().strip()
    if not low:
        return False
    if any(s in low for s in GARBAGE_EMAIL_SUBSTR):
        return True
    # форма error+<hash>@... — DDG anomaly-report
    if low.startswith("error+"):
        return True
    return False


def _read_csv(path: str) -> tuple[list[dict], list[str], str]:
    """Возвращает (rows, fieldnames, delimiter)."""
    for delim in (";", ","):
        try:
            with open(path, encoding="utf-8-sig") as f:
                sample = f.read(2048)
                f.seek(0)
                if delim not in sample:
                    continue
                reader = csv.DictReader(f, delimiter=delim)
                rows = list(reader)
                if rows and "name" in (reader.fieldnames or []):
                    return rows, list(reader.fieldnames), delim
        except Exception:
            continue
    return [], [], ";"


def _clean_rows(rows: list[dict]) -> tuple[int, int]:
    cleared_sites = cleared_emails = 0
    for r in rows:
        if _is_garbage_website(r.get("website", "")):
            r["website"] = ""
            cleared_sites += 1
        if _is_garbage_email(r.get("email", "")):
            r["email"] = ""
            cleared_emails += 1
    return cleared_sites, cleared_emails


def _write_csv(path: str, rows: list[dict], fieldnames: list[str], delim: str) -> None:
    tmp = path + ".cleaning.tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames,
            delimiter=delim, quoting=csv.QUOTE_ALL,
            extrasaction="ignore", restval="",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def clean_file(path: str, make_backup: bool = True) -> dict:
    rows, fieldnames, delim = _read_csv(path)
    if not rows:
        return {"path": path, "skipped": "не удалось прочитать"}
    cs, ce = _clean_rows(rows)
    if cs == 0 and ce == 0:
        return {"path": path, "total": len(rows), "websites_cleared": 0, "emails_cleared": 0}
    if make_backup:
        backup = path + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(path, backup)
    _write_csv(path, rows, fieldnames, delim)
    return {"path": path, "total": len(rows), "websites_cleared": cs, "emails_cleared": ce,
            "backup": backup if make_backup else None}


def main() -> None:
    targets = []
    master = os.path.join(OUTPUT_DIR, "master_all.csv")
    if os.path.exists(master):
        targets.append(master)
    targets += sorted(glob.glob(os.path.join(OUTPUT_DIR, "result_enriched_*.csv")))
    targets += sorted(glob.glob(os.path.join(OUTPUT_DIR, "result_2*.csv")))
    # уберём дубли (master или enriched могли попасть дважды)
    seen, dedup = set(), []
    for p in targets:
        if p not in seen:
            seen.add(p); dedup.append(p)

    print(f"Файлов на проверку: {len(dedup)}")
    total_sites = total_emails = touched_files = 0
    for p in dedup:
        r = clean_file(p)
        if "skipped" in r:
            print(f"  SKIP {os.path.basename(p)}: {r['skipped']}")
            continue
        cs, ce = r["websites_cleared"], r["emails_cleared"]
        if cs or ce:
            touched_files += 1
            total_sites += cs
            total_emails += ce
            print(f"  ✓ {os.path.basename(p)}: {r['total']} строк, "
                  f"websites обнулено: {cs}, emails обнулено: {ce}")
        else:
            print(f"  · {os.path.basename(p)}: {r['total']} строк, мусора нет")

    print(f"\nИТОГО: затронуто файлов {touched_files}, "
          f"websites обнулено {total_sites}, emails обнулено {total_emails}")


if __name__ == "__main__":
    main()
