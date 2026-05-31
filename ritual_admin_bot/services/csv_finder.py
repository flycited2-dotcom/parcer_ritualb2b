"""Поиск свежего CSV в output-директории парсера."""
import glob
import os

PARSER_DIR = os.getenv("PARSER_DIR", "/home/ritual_parser")
OUTPUT_DIR = os.path.join(PARSER_DIR, "output")


def latest_csv(prefix: str = "result_") -> str | None:
    """Вернуть путь до самого свежего <prefix>*.csv или None."""
    pattern = os.path.join(OUTPUT_DIR, f"{prefix}*.csv")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def latest_enriched() -> str | None:
    return latest_csv("result_enriched_")


def latest_xlsx() -> str | None:
    pattern = os.path.join(OUTPUT_DIR, "result_*.xlsx")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def csv_summary(path: str) -> str:
    """Краткая сводка по CSV: всего строк, размер."""
    if not path or not os.path.exists(path):
        return "файл не найден"
    size = os.path.getsize(path)
    try:
        with open(path, encoding="utf-8-sig") as f:
            rows = sum(1 for _ in f) - 1  # минус заголовок
    except Exception:
        rows = -1
    mtime = os.path.getmtime(path)
    from datetime import datetime
    return (
        f"{os.path.basename(path)}\n"
        f"строк: {rows}, размер: {size/1024:.1f} KB\n"
        f"обновлён: {datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}"
    )
