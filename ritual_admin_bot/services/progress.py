"""Живой прогресс прогона из output/progress.json."""
import json
import os
from datetime import datetime

PARSER_DIR = os.getenv("PARSER_DIR", "/home/ritual_parser")
PROGRESS = os.path.join(PARSER_DIR, "output", "progress.json")

_ICON = {"running": "🟢", "ok": "✅", "error": "❌", "finished": "✅"}


def get_progress_text() -> str:
    if not os.path.exists(PROGRESS):
        return "progress.json не найден — прогон ещё не запускался."
    try:
        with open(PROGRESS, encoding="utf-8") as f:
            p = json.load(f)
    except Exception as e:
        return f"Не прочитать progress.json: {e}"

    status = p.get("status", "—")
    done = p.get("completed_sources", []) or []
    last = p.get("last_update", "") or ""

    stale = ""
    try:
        mins = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 60
        if status == "running" and mins > 20:
            stale = f"\n⚠ нет обновлений {mins:.0f} мин — возможно завис/упал"
    except Exception:
        pass

    lines = [
        f"{_ICON.get(status, '⚪')} <b>Прогресс</b>: {status}",
        f"Стадия: <b>{p.get('stage', '—')}</b>",
        f"Собрано на стадии: {p.get('current_count', '—')}",
        f"Завершено источников: {len(done)} ({', '.join(done) or '—'})",
        f"Старт: {p.get('started_at', '—')}",
        f"Обновлено: {last}{stale}",
    ]
    return "\n".join(lines)
