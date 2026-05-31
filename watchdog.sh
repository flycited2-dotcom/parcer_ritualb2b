#!/bin/bash
# Ritual Parser Watchdog. Запускается каждые 10 минут.
# 1. Если парсер active и CSV не менялся > 30 мин → алерт "завис"
# 2. Если парсер active и прошло >= 30 мин с прошлого heartbeat → heartbeat
# 3. Если парсер failed после старта → алерт о падении (1 раз)
# 4. Если email_finder failed → алерт (1 раз)
# 5. Если parser неактивен, но progress.json status=running → сброс на idle
# 6. Если нет успешного прогона >10 дней (mtime result_enriched_*.csv) → алерт

set -e
cd /home/ritual_parser
set -a; . ./.env; set +a

STATE_FILE=/tmp/ritual_watchdog_state
mkdir -p $(dirname $STATE_FILE)

NOW=$(date +%s)
STATE=$(systemctl is-active ritual_parser.service 2>/dev/null || true)
[ -z "$STATE" ] && STATE=unknown

send_tg() {
    local msg="$1"
    curl -sS --max-time 20 -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT_ID}" \
        --data-urlencode "text=${msg}" \
        --data-urlencode "parse_mode=HTML" >/dev/null 2>&1 || true
}

# 1. Парсер не активен — снимаем флаги, при failed уведомляем один раз.
# Не выходим: блоки 4-6 ниже не зависят от состояния парсера.
if [ "$STATE" != "active" ] && [ "$STATE" != "activating" ]; then
    if [ "$STATE" = "failed" ] && [ ! -f "$STATE_FILE.fail_sent" ]; then
        send_tg "❌ <b>Парсер упал</b> (systemctl: failed). /status для деталей."
        touch "$STATE_FILE.fail_sent"
    fi
    rm -f "$STATE_FILE.hang_sent" "$STATE_FILE.last_heartbeat"
fi

# Парсер живой → сбрасываем флаг fail_sent
if [ "$STATE" = "active" ] || [ "$STATE" = "activating" ]; then
    rm -f "$STATE_FILE.fail_sent"
fi

# Блоки 2-3 имеют смысл только при работающем парсере.
PARSER_ACTIVE=0
if [ "$STATE" = "active" ] || [ "$STATE" = "activating" ]; then
    PARSER_ACTIVE=1
fi

LATEST=$(ls -t /home/ritual_parser/output/result_2*.csv 2>/dev/null | grep -v enriched | head -1)

# 2. Зависание: CSV не растёт > 30 мин
if [ $PARSER_ACTIVE -eq 1 ] && [ -n "$LATEST" ]; then
    MTIME=$(stat -c %Y "$LATEST")
    AGE=$(( NOW - MTIME ))
    if [ $AGE -gt 1800 ] && [ ! -f "$STATE_FILE.hang_sent" ]; then
        # узнаём этап из progress.json
        STAGE="?"
        if [ -f /home/ritual_parser/output/progress.json ]; then
            STAGE=$(python3 -c "import json; d=json.load(open('/home/ritual_parser/output/progress.json')); print(d.get('stage','?'))" 2>/dev/null || echo "?")
        fi
        send_tg "⚠️ <b>Парсер завис?</b> Этап <code>${STAGE}</code>, CSV не растёт $((AGE/60)) мин. /tail 50 для деталей."
        touch "$STATE_FILE.hang_sent"
    fi
    # сбрасываем флаг если CSV снова обновился
    if [ $AGE -lt 600 ]; then
        rm -f "$STATE_FILE.hang_sent"
    fi
fi

# 3. Heartbeat каждые 30 минут пока парсер активен
LAST_HB=$(cat "$STATE_FILE.last_heartbeat" 2>/dev/null || echo 0)
SINCE_HB=$(( NOW - LAST_HB ))
if [ $PARSER_ACTIVE -eq 1 ] && [ $SINCE_HB -ge 1800 ]; then
    STAGE="?"
    COUNT="?"
    QUERY=""
    if [ -f /home/ritual_parser/output/progress.json ]; then
        EVAL=$(python3 -c "
import json
try:
    d = json.load(open('/home/ritual_parser/output/progress.json'))
    print(d.get('stage','?'))
    print(d.get('current_count',0))
    print(d.get('current_query',''))
    print(','.join(d.get('completed_sources',[])))
except Exception:
    print('?'); print(0); print(''); print('')
" 2>/dev/null)
        STAGE=$(echo "$EVAL" | sed -n '1p')
        COUNT=$(echo "$EVAL" | sed -n '2p')
        QUERY=$(echo "$EVAL" | sed -n '3p')
        DONE=$(echo "$EVAL" | sed -n '4p')
    fi
    MSG="💓 <b>Heartbeat</b>: парсер работает
Этап: <code>${STAGE}</code>
Записей в прогоне: <b>${COUNT}</b>"
    if [ -n "$QUERY" ]; then
        MSG="${MSG}
Текущий запрос: <code>${QUERY}</code>"
    fi
    if [ -n "$DONE" ]; then
        MSG="${MSG}
Готовые источники: ${DONE}"
    fi
    send_tg "$MSG"
    echo "$NOW" > "$STATE_FILE.last_heartbeat"
fi

# 4. Мониторинг email_finder — алертим один раз при failed.
EF_STATE=$(systemctl is-active ritual_email_finder.service 2>/dev/null || echo unknown)
if [ "$EF_STATE" = "failed" ]; then
    if [ ! -f "$STATE_FILE.ef_fail_sent" ]; then
        send_tg "❌ <b>email_finder упал</b> (systemctl: failed). journalctl -u ritual_email_finder -n 50 для деталей."
        touch "$STATE_FILE.ef_fail_sent"
    fi
elif [ "$EF_STATE" = "active" ] || [ "$EF_STATE" = "activating" ]; then
    rm -f "$STATE_FILE.ef_fail_sent"
fi

# 5. Если парсер inactive/failed, но progress.json показывает status=running —
# сбрасываем на idle (stale state после kill/OOM/reboot).
if [ "$STATE" != "active" ] && [ "$STATE" != "activating" ] \
        && [ -f /home/ritual_parser/output/progress.json ]; then
    python3 - <<'PY' 2>/dev/null || true
import json, os
p = '/home/ritual_parser/output/progress.json'
try:
    with open(p) as f:
        d = json.load(f)
    if d.get('status') == 'running':
        d['status'] = 'idle'
        d['stage'] = d.get('stage', '') + ' (reset by watchdog)'
        tmp = p + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
except Exception:
    pass
PY
fi

# 6. Алерт если давно не было успешного завершения прогона.
# Признак успеха — наличие result_enriched_*.csv (создаётся после email_finder).
LATEST_ENRICHED=$(ls -t /home/ritual_parser/output/result_enriched_*.csv 2>/dev/null | head -1)
if [ -n "$LATEST_ENRICHED" ]; then
    EMTIME=$(stat -c %Y "$LATEST_ENRICHED")
    EAGE_DAYS=$(( (NOW - EMTIME) / 86400 ))
    if [ $EAGE_DAYS -ge 10 ] && [ ! -f "$STATE_FILE.stale_sent" ]; then
        send_tg "⚠️ <b>Нет успешных прогонов</b> ${EAGE_DAYS} дней. Последний result_enriched_*: $(basename "$LATEST_ENRICHED"). Проверь ritual_parser.timer."
        touch "$STATE_FILE.stale_sent"
    fi
    if [ $EAGE_DAYS -lt 8 ]; then
        rm -f "$STATE_FILE.stale_sent"
    fi
fi
