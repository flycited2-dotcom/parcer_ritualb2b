#!/bin/bash
# Архивирует result_*.csv старше 30 дней в output/archive/YYYY-MM.tar.gz.
# master_all.csv / master_all.xlsx / dedup.db / progress.json — НЕ трогаем.
#
# Запуск еженедельно через systemd timer ritual_archive.timer (или cron).
# Идемпотентен — если архив за этот месяц уже есть, дописывает в него.

set -e
cd /home/ritual_parser/output

ARCHIVE_DIR="archive"
mkdir -p "$ARCHIVE_DIR"

# Ищем все result_*.csv (включая result_enriched_*) старше 30 дней.
mapfile -t OLD < <(find . -maxdepth 1 -type f -name 'result_*.csv' -mtime +30 2>/dev/null | sort)

if [ "${#OLD[@]}" -eq 0 ]; then
    echo "[archive] нет файлов старше 30 дней"
    exit 0
fi

echo "[archive] кандидатов: ${#OLD[@]}"

# Группируем по YYYY-MM из mtime
declare -A BY_MONTH
for f in "${OLD[@]}"; do
    yymm=$(date -r "$f" +%Y-%m)
    BY_MONTH[$yymm]+=" $f"
done

for yymm in "${!BY_MONTH[@]}"; do
    archive="$ARCHIVE_DIR/${yymm}.tar.gz"
    # shellcheck disable=SC2086
    files=${BY_MONTH[$yymm]}
    if [ -f "$archive" ]; then
        # tar -r не работает на сжатых .tar.gz. Распакуем, добавим, упакуем.
        tmpdir=$(mktemp -d)
        tar -xzf "$archive" -C "$tmpdir"
        # shellcheck disable=SC2086
        cp $files "$tmpdir/"
        tar -czf "$archive.tmp" -C "$tmpdir" .
        mv "$archive.tmp" "$archive"
        rm -rf "$tmpdir"
    else
        # shellcheck disable=SC2086
        tar -czf "$archive" $files
    fi
    echo "[archive] $archive: добавлено $(echo $files | wc -w) файлов"
    # shellcheck disable=SC2086
    rm -f $files
done

echo "[archive] готово"
