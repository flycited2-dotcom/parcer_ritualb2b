#!/bin/bash
cd /home/ritual_parser
set -a; . ./.env; set +a
LATEST=$(ls -t output/result_enriched_*.csv 2>/dev/null | head -1)
[ -z "$LATEST" ] && LATEST=$(ls -t output/result_*.csv 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    ./venv/bin/python -c "
import os
from utils.telegram_notify import send_message
send_message(os.environ['TG_BOT_TOKEN'], os.environ['TG_CHAT_ID'],
             'Ritual B2B Parser — отчёт не сформирован: CSV не найден.')"
    exit 0
fi
PYTHONUNBUFFERED=1 ./venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from utils.telegram_notify import notify
notify('$LATEST', source_label='ночной прогон, отчёт 07:30')"
