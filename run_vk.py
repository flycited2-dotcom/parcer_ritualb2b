"""Запустить ТОЛЬКО VK-добор (HTTP-only, без Chromium) и обновить master.

Можно гонять параллельно с email_finder — лёгкий, не трогает браузер.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.env_loader import load_all_env  # noqa: E402

load_all_env()

from parsers import vk_groups  # noqa: E402
from utils.storage import total  # noqa: E402


async def main() -> None:
    await vk_groups.run(None)
    print(f"\nВсего в прогоне VK: {total()}")

    # влить в master_all
    try:
        from utils.merger import build_master
        master = build_master("output")
        print(f"[merger] master обновлён: {master}")
    except Exception as e:
        print(f"[merger] {e}")

    # отчёт
    if os.getenv("AUTO_NOTIFY", "1").lower() not in ("0", "false", ""):
        try:
            import glob
            from utils.telegram_notify import notify
            latest = max(glob.glob("output/result_2*.csv"), key=os.path.getmtime)
            notify(latest, source_label="VK-добор")
        except Exception as e:
            print(f"[telegram] {e}")


if __name__ == "__main__":
    asyncio.run(main())
