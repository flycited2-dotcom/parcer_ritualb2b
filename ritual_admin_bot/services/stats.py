"""Аналитика master_all.csv: сводка по базе + дельта с прошлого прогона."""
import csv
import json
import os
from collections import Counter
from datetime import datetime

PARSER_DIR = os.getenv("PARSER_DIR", "/home/ritual_parser")
MASTER_CSV = os.path.join(PARSER_DIR, "output", "master_all.csv")
SNAP_PATH = os.path.join(PARSER_DIR, "output", ".stats_prev.json")


def _read_rows(path: str) -> list[dict]:
    rows: list[dict] = []
    for delim in (";", ","):
        try:
            with open(path, encoding="utf-8-sig") as f:
                sample = f.read(2048)
                f.seek(0)
                if delim in sample:
                    reader = csv.DictReader(f, delimiter=delim)
                    rows = list(reader)
                    if rows and "name" in rows[0]:
                        return rows
        except Exception:
            continue
    return rows


def _compute(rows: list[dict]) -> dict:
    def has(k: str) -> int:
        return sum(1 for r in rows if (r.get(k) or "").strip())
    return {
        "total": len(rows),
        "email": has("email"),
        "phone": has("phone"),
        "website": has("website"),
        "by_source": Counter(r.get("source", "—") or "—" for r in rows),
        "by_type": Counter(r.get("client_type", "—") or "—" for r in rows),
        "by_city": Counter((r.get("city") or "—").strip() or "—" for r in rows),
    }


def _load_snapshot() -> dict | None:
    try:
        with open(SNAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_snapshot(s: dict, mtime: float) -> None:
    try:
        with open(SNAP_PATH, "w", encoding="utf-8") as f:
            json.dump({"total": s["total"], "email": s["email"],
                       "phone": s["phone"], "csv_mtime": mtime}, f)
    except Exception:
        pass


def _sign(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def get_stats_text() -> str:
    if not os.path.exists(MASTER_CSV):
        return "master_all.csv не найден — запусти прогон или /master."
    rows = _read_rows(MASTER_CSV)
    if not rows:
        return "master_all.csv пуст."

    s = _compute(rows)
    mtime = os.path.getmtime(MASTER_CSV)
    total = s["total"]

    def pct(n: int) -> str:
        return f"{100 * n / total:.0f}%" if total else "—"

    prev = _load_snapshot()
    if prev is None:
        _save_snapshot(s, mtime)
        delta = "дельта появится после следующего прогона"
    elif abs(prev.get("csv_mtime", 0) - mtime) > 1:
        delta = (f"{_sign(total - prev.get('total', 0))} записей, "
                 f"{_sign(s['email'] - prev.get('email', 0))} email, "
                 f"{_sign(s['phone'] - prev.get('phone', 0))} тел.")
        _save_snapshot(s, mtime)
    else:
        delta = "без изменений с прошлого прогона"

    lines = [
        "🗄 <b>База master_all</b>",
        f"Всего: <b>{total}</b>",
        f"С email: {s['email']} ({pct(s['email'])})",
        f"С телефоном: {s['phone']} ({pct(s['phone'])})",
        f"С сайтом: {s['website']} ({pct(s['website'])})",
        f"<i>С прошлого прогона:</i> {delta}",
        "",
        "<b>Топ городов:</b>",
    ]
    for city, n in s["by_city"].most_common(10):
        lines.append(f"  {city}: {n}")
    lines.append("")
    lines.append("<b>Источники:</b>")
    for k, n in s["by_source"].most_common():
        lines.append(f"  {k}: {n}")
    lines.append("")
    lines.append(f"Обновлён: {datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}")
    return "\n".join(lines)
