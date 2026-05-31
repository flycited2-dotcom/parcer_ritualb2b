import csv
import html
import os
import re
from datetime import datetime

from utils.categories import normalize as normalize_category
from utils import dedup, progress

FIELDS = [
    "city", "name", "client_type", "category",
    "address", "phone", "email", "website", "social",
    "comment", "source", "parsed_at",
]

OUTPUT_DIR = "output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"result_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")

# Разделитель `;` — RU Excel читает столбцы из коробки.
CSV_DELIMITER = ";"

_seen = set()
_rows = []
# Header пишем один раз при первом append. Сбрасывается на _rewrite_all.
_header_written = False


def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return (raw or "").strip()
    return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: str) -> str:
    """Готовим значение к записи в CSV.

    - убираем HTML-теги (VK иногда отдаёт name с <a>/<br>; ломали TG parse_mode=HTML)
    - декодируем HTML entities (&amp; → &, &nbsp; → пробел)
    - схлопываем whitespace и переносы — иначе Excel ломает строку
    """
    if not value:
        return ""
    s = str(value)
    s = _HTML_TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ").replace(" ", " ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _key(item):
    return f"{item.get('name','').lower().strip()}|{item.get('city','').lower().strip()}"


def save_item(item):
    global _rows
    if not item.get("name"):
        return False
    k = _key(item)
    # in-memory дубль внутри текущего процесса
    if k in _seen:
        return False
    # persistent дубль через SQLite — переживает рестарт парсера
    if not dedup.mark_seen(item.get("name", ""), item.get("city", ""),
                            item.get("source", "")):
        _seen.add(k)
        return False
    _seen.add(k)

    cleaned = {k_: _clean(item.get(k_, "")) for k_ in FIELDS}
    if cleaned.get("phone"):
        cleaned["phone"] = normalize_phone(cleaned["phone"])
    if not cleaned.get("client_type"):
        cleaned["client_type"] = normalize_category(cleaned.get("category", ""))

    _rows.append(cleaned)
    _append_last()
    # обновляем счётчик в progress.json раз в 10 записей (чтобы не перегружать диск)
    if len(_rows) % 10 == 0:
        try:
            progress.mark_count(len(_rows))
        except Exception:
            pass
    print(f"  ✓ [{cleaned['source']}] {cleaned['city']} | {cleaned['name']} | "
          f"{cleaned.get('phone') or '—'} | {cleaned.get('email') or '—'}")
    return True


def _append_last():
    """Дописать последнюю строку _rows в CSV (без rewrite всего файла).

    Header пишется один раз при первом вызове. Для больших прогонов это
    линейная сложность, в отличие от O(N²) полного rewrite на каждый save.
    """
    global _header_written
    if not _rows:
        return
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    mode = "a" if _header_written else "w"
    with open(OUTPUT_FILE, mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDS,
            delimiter=CSV_DELIMITER, quoting=csv.QUOTE_ALL,
            extrasaction="ignore", restval="",
        )
        if not _header_written:
            writer.writeheader()
            _header_written = True
        writer.writerow(_rows[-1])


def _rewrite_all():
    """Полный rewrite файла из _rows. Используется после cross_source_merge,
    которая мутирует существующие строки in-place."""
    global _header_written
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDS,
            delimiter=CSV_DELIMITER, quoting=csv.QUOTE_ALL,
            extrasaction="ignore", restval="",
        )
        writer.writeheader()
        writer.writerows(_rows)
    _header_written = True


# Сохраняем _flush() как алиас на rewrite — для обратной совместимости
# с внешним кодом, который мог вызывать utils.storage._flush() напрямую.
_flush = _rewrite_all


def total():
    return len(_rows)


def get_output_file():
    return OUTPUT_FILE


_NAME_NORMALIZE_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    """Жёстко нормализуем имя для сопоставления записей из разных источников.
    'Отель «Ялта», 4*' → 'отель ялта 4'.
    """
    if not name:
        return ""
    s = name.lower()
    s = _NAME_NORMALIZE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


_MERGE_FIELDS = ("phone", "email", "website", "address", "social")
# Чем выше score источника — тем приоритетнее его данные при совпадениях.
_SOURCE_PRIORITY = {
    "OSM": 5,
    "2ГИС": 4,
    "Авито": 3,
    "Я.Карты": 2,
    "Суточно.ру": 2,
    "Ostrovok": 1,
    "Wikidata": 1,
}


def cross_source_merge() -> int:
    """Сшиваем записи разных источников с похожими именами в одном городе.
    Берём недостающие поля у записи с наивысшим source priority.
    Возвращаем число обогащённых ячеек.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in _rows:
        norm = _normalize_name(r.get("name", ""))
        if not norm:
            continue
        city = (r.get("city") or "").lower().strip()
        groups.setdefault((norm, city), []).append(r)

    enriched = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        # сортируем по приоритету источника убыванию
        rows_sorted = sorted(
            rows,
            key=lambda r: _SOURCE_PRIORITY.get(r.get("source", ""), 0),
            reverse=True,
        )
        for r in rows:
            for f in _MERGE_FIELDS:
                if r.get(f):
                    continue
                for donor in rows_sorted:
                    if donor is r:
                        continue
                    val = donor.get(f)
                    if val:
                        r[f] = val
                        enriched += 1
                        break
    if enriched:
        _rewrite_all()
    return enriched
