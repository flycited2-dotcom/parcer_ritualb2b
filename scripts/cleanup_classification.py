"""Retro-чистка master_all.csv от VK-шума.

Применяет parsers.vk_filter.classify к VK-записям master_all.csv.
По умолчанию dry-run: печатает разбивку и примеры.
С --apply:
  1. Делает backup: master_all.csv.bak.<timestamp>
  2. Перезаписывает master_all.csv без noise; ambiguous остаются с comment='vk_review'
  3. Пишет output/master_all_noise.csv — все удалённые noise-записи для аудита.
"""
import csv
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parsers.vk_filter import classify  # noqa: E402

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
MASTER = os.path.join(OUTPUT, "master_all.csv")
NOISE = os.path.join(OUTPUT, "master_all_noise.csv")


def _read(path: str) -> tuple[list[dict], list[str], str]:
    with open(path, encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        delim = ";" if ";" in sample else ","
        reader = csv.DictReader(f, delimiter=delim)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return rows, fields, delim


def _write(path: str, rows: list[dict], fields: list[str], delim: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=delim,
                           quoting=csv.QUOTE_ALL, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(apply: bool = False) -> None:
    if not os.path.exists(MASTER):
        print(f"Не нашёл {MASTER}")
        return

    rows, fields, delim = _read(MASTER)
    vk_total = noise = ambiguous = hotel = 0
    noise_rows: list[dict] = []
    keep_rows: list[dict] = []

    for r in rows:
        if (r.get("source") or "").upper() != "VK":
            keep_rows.append(r)
            continue
        vk_total += 1
        v = classify(r.get("name", ""), r.get("category", ""))
        if v == "hotel":
            hotel += 1
            keep_rows.append(r)
        elif v == "noise":
            noise += 1
            noise_rows.append(r)
        else:  # ambiguous
            ambiguous += 1
            if not (r.get("comment") or "").strip():
                r["comment"] = "vk_review"
            keep_rows.append(r)

    print(f"Всего записей в master_all: {len(rows)}")
    print(f"VK всего: {vk_total}")
    print(f"  hotel:     {hotel}")
    print(f"  noise:     {noise}  ← удалятся при --apply")
    print(f"  ambiguous: {ambiguous}  ← остаются, помечаются comment=vk_review")
    print(f"После очистки: {len(keep_rows)}")

    if not apply:
        print("\n--- ПРИМЕРЫ noise (первые 15) ---")
        for r in noise_rows[:15]:
            n = (r.get("name") or "")[:42]
            a = (r.get("category") or "")[:30]
            print(f"  {n:<42} | activity={a}")
        print("\nDry-run. Запусти с --apply чтобы применить.")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    bak = MASTER + f".bak.{ts}"
    shutil.copy2(MASTER, bak)
    print(f"\nBackup: {bak}")

    _write(MASTER, keep_rows, fields, delim)
    print(f"Перезаписан {MASTER} ({len(keep_rows)} строк)")

    if noise_rows:
        _write(NOISE, noise_rows, fields, delim)
        print(f"Шум: {NOISE} ({len(noise_rows)} строк)")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
