"""Объединяет все result_*.csv в output/ в единый master_all.csv + master_all.xlsx."""
from __future__ import annotations

import csv
import glob
import os
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.dirname(_HERE), "output")

# Field names must match storage.py FIELDS exactly (same order).
FIELDNAMES = [
    "city", "name", "client_type", "category",
    "address", "phone", "email", "website", "social",
    "comment", "source", "parsed_at",
]


def _dedup_key(row: dict) -> str:
    name = (row.get("name") or "").strip().lower()
    phone = (row.get("phone") or "").strip().replace(" ", "").replace("-", "")
    return f"{name}|{phone}"


def build_master(output_dir: str = OUTPUT_DIR) -> str:
    """
    Reads all result_*.csv (excluding *enriched* and master_all.csv),
    merges with deduplication, saves to master_all.csv.
    Returns path to the file.
    """
    pattern = os.path.join(output_dir, "result_*.csv")
    raw_files = sorted(
        [f for f in glob.glob(pattern) if "enriched" not in os.path.basename(f)],
        key=os.path.getmtime,
    )

    # `*enriched*.csv` ловит обе схемы именования:
    # старая — foo_enriched.csv, новая — result_enriched_TS.csv.
    enriched_glob = os.path.join(output_dir, "*enriched*.csv")
    enriched_bases = {
        os.path.basename(f).replace("_enriched", "")
        for f in glob.glob(enriched_glob)
    }

    seen: OrderedDict[str, dict] = OrderedDict()

    # Load raw files first (skip those that have an enriched version)
    for filepath in raw_files:
        base = os.path.basename(filepath)
        if base in enriched_bases:
            continue
        _load_csv_into(filepath, seen)

    # Load enriched files on top (they win on conflicts, fill in missing fields)
    for filepath in sorted(
        glob.glob(enriched_glob),
        key=os.path.getmtime,
    ):
        _load_csv_into(filepath, seen)

    rows = list(seen.values())
    master_path = os.path.join(output_dir, "master_all.csv")
    os.makedirs(output_dir, exist_ok=True)
    with open(master_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDNAMES, delimiter=";",
            extrasaction="ignore", restval="", quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"[merger] master_all.csv: {len(rows)} records from {len(raw_files)} files")
    return master_path


def _load_csv_into(filepath: str, seen: OrderedDict) -> None:
    try:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                key = _dedup_key(row)
                if key not in seen:
                    seen[key] = row
                else:
                    # Enrich existing record with missing fields from this row
                    existing = seen[key]
                    for field in FIELDNAMES:
                        if not existing.get(field) and row.get(field):
                            existing[field] = row[field]
    except Exception as e:
        print(f"[merger] error reading {filepath}: {e}")


def build_master_xlsx(output_dir: str = OUTPUT_DIR) -> tuple[str, str]:
    """Builds master_all.csv and master_all.xlsx. Returns (csv_path, xlsx_path)."""
    csv_path = build_master(output_dir)
    xlsx_path = os.path.join(output_dir, "master_all.xlsx")
    try:
        from utils.excel_export import build_xlsx
        result = build_xlsx(csv_path, xlsx_path)
        xlsx_path = result or xlsx_path
    except Exception as e:
        print(f"[merger] xlsx error: {e}")
        xlsx_path = ""
    return csv_path, xlsx_path
