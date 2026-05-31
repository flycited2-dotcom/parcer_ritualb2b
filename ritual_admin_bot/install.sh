#!/bin/bash
# Установка ritual_admin_bot на VPS.
# Запуск: bash install.sh
set -e

DEST=/opt/ritual_admin_bot
SUDO=$([ "$EUID" -eq 0 ] || echo sudo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/6] Копирую исходники в $DEST..."
$SUDO mkdir -p "$DEST"
$SUDO rsync -a --delete --exclude='venv' --exclude='__pycache__' \
    --exclude='.env' "$SCRIPT_DIR/" "$DEST/"

echo "[2/6] Создаю venv..."
$SUDO python3 -m venv "$DEST/venv"

echo "[3/6] Устанавливаю зависимости..."
$SUDO "$DEST/venv/bin/pip" install -q --upgrade pip
$SUDO "$DEST/venv/bin/pip" install -q -r "$DEST/requirements.txt"

echo "[4/6] Проверяю .env..."
if [ ! -f "$DEST/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env" ]; then
        $SUDO cp "$SCRIPT_DIR/.env" "$DEST/.env"
    else
        echo "  ⚠ $DEST/.env не найден. Скопируй .env.example → .env и заполни BOT_TOKEN/ADMIN_CHAT_IDS"
    fi
fi
$SUDO chmod 600 "$DEST/.env" 2>/dev/null || true

echo "[5/6] Настраиваю sudoers без пароля для systemctl..."
SUDOERS_FILE=/etc/sudoers.d/ritual_admin_bot
# Перечисляем команды явно (вместо * wildcard) — безопаснее.
SOURCES="osm wikidata yandex search 2gis avito sutochno ostrovok"
SOURCE_CMDS=""
for s in $SOURCES; do
    SOURCE_CMDS="$SOURCE_CMDS, /bin/systemctl start ritual_parser_source@${s}.service, /bin/systemctl stop ritual_parser_source@${s}.service"
done

$SUDO tee "$SUDOERS_FILE" > /dev/null <<EOF
# Бот управляет парсером без запроса пароля
root ALL=(root) NOPASSWD: /bin/systemctl start ritual_parser.service, /bin/systemctl stop ritual_parser.service, /bin/systemctl start ritual_email_finder.service, /bin/systemctl stop ritual_email_finder.service, /bin/systemctl enable ritual_parser.timer, /bin/systemctl disable ritual_parser.timer, /bin/systemctl start ritual_parser.timer, /bin/systemctl stop ritual_parser.timer${SOURCE_CMDS}
EOF
$SUDO chmod 0440 "$SUDOERS_FILE"
$SUDO visudo -c -f "$SUDOERS_FILE" >/dev/null || { echo "  ⚠ sudoers невалидный — удаляю"; $SUDO rm -f "$SUDOERS_FILE"; exit 1; }

echo "[6/6] Устанавливаю systemd-юнит..."
$SUDO cp "$DEST/ritual_admin_bot.service" /etc/systemd/system/
$SUDO systemctl daemon-reload
$SUDO systemctl enable ritual_admin_bot.service
$SUDO systemctl restart ritual_admin_bot.service

echo ""
echo "Готово."
echo "  Логи: journalctl -u ritual_admin_bot -f"
echo "       или tail -f /var/log/ritual_admin_bot.log"
echo "  Статус: systemctl status ritual_admin_bot"
