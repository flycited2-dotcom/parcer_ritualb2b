#!/bin/bash
# Показать последние результаты
LATEST=$(ls -t /home/ritual_parser/output/*.csv 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    echo "Результатов пока нет. Запустите: ./run.sh"
else
    echo "Последний файл: $LATEST"
    echo "Строк в файле: $(wc -l < $LATEST)"
    echo ""
    echo "--- Первые 5 записей ---"
    head -6 "$LATEST"
fi
