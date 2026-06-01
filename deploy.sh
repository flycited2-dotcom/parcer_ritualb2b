#!/bin/bash
# ============================================================
#  CRIMEA HOTEL PARSER — ONE-CLICK DEPLOY
#  Запуск: bash deploy.sh
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

DEPLOY_DIR="/home/ritual_parser"
ARCHIVE_NAME="ritual_parser.tar.gz"
SERVICE_NAME="ritual_parser"
PYTHON_BIN="python3"
PIP_BIN="pip3"
VENV_DIR="$DEPLOY_DIR/venv"
LOG_FILE="/tmp/ritual_parser_deploy.log"
: > "$LOG_FILE"
SYSTEMD_SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"
SYSTEMD_TIMER="/etc/systemd/system/${SERVICE_NAME}.timer"
HOTELS_ENV="/home/crimea_parser/.env"      # источник VK_TOKEN/GDrive (тот же сервер)
HOTELS_TOKEN="/home/crimea_parser/token.json"

log() { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"; }
ok()  { echo -e "${GREEN}[OK]${NC} $1" | tee -a "$LOG_FILE"; }
err() { echo -e "${RED}[ERR]${NC} $1" | tee -a "$LOG_FILE"; exit 1; }
warn(){ echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOG_FILE"; }

echo ""
echo -e "${BOLD}${BLUE}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║       RITUAL B2B PARSER — AUTO DEPLOY v1.0        ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. ПРОВЕРКА ПРАВ ──────────────────────────────────────────
log "Проверка прав sudo..."
if [ "$EUID" -ne 0 ]; then
    warn "Запущено без root. Некоторые шаги могут потребовать sudo."
    SUDO="sudo"
else
    SUDO=""
fi

# ── 2. СОЗДАНИЕ РАБОЧЕЙ ДИРЕКТОРИИ ───────────────────────────
log "Создание директории $DEPLOY_DIR..."
$SUDO mkdir -p "$DEPLOY_DIR"
$SUDO chown -R "$USER:$USER" "$DEPLOY_DIR" 2>/dev/null || true
ok "Директория готова"

# ── 3. РАСПАКОВКА АРХИВА ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_PATH="$SCRIPT_DIR/$ARCHIVE_NAME"

if [ -f "$ARCHIVE_PATH" ]; then
    log "Распаковка архива $ARCHIVE_NAME..."
    tar -xzf "$ARCHIVE_PATH" -C "$DEPLOY_DIR" --strip-components=1
    ok "Архив распакован"
else
    warn "Архив $ARCHIVE_NAME не найден рядом со скриптом."
    warn "Копируем файлы из текущей директории..."
    rsync -av --exclude='venv' --exclude='__pycache__' \
        --exclude='*.pyc' --exclude='.git' --exclude='output' \
        "$SCRIPT_DIR/" "$DEPLOY_DIR/" 2>/dev/null || \
    cp -r "$SCRIPT_DIR/." "$DEPLOY_DIR/"
    ok "Файлы скопированы"
fi

# - 3b. .env: создаём и подтягиваем VK_TOKEN/GDrive из парсера отелей -
log "Настройка .env..."
if [ ! -f "$DEPLOY_DIR/.env" ] && [ -f "$DEPLOY_DIR/.env.example" ]; then
    cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
    warn ".env создан из .env.example - заполни TG_BOT_TOKEN/TG_CHAT_ID/GDRIVE_FOLDER_ID"
fi
if [ -f "$HOTELS_ENV" ]; then
    VK_LINE=$(grep "^VK_TOKEN=" "$HOTELS_ENV" 2>/dev/null || true)
    [ -n "$VK_LINE" ] && sed -i "s|^VK_TOKEN=.*|$VK_LINE|" "$DEPLOY_DIR/.env" && ok "VK_TOKEN взят из $HOTELS_ENV"
    GD_LINE=$(grep "^GDRIVE_CREDENTIALS=" "$HOTELS_ENV" 2>/dev/null || true)
    [ -n "$GD_LINE" ] && sed -i "s|^GDRIVE_CREDENTIALS=.*|$GD_LINE|" "$DEPLOY_DIR/.env" || true
fi
if [ -f "$HOTELS_TOKEN" ]; then
    sed -i "s|^GDRIVE_TOKEN=.*|GDRIVE_TOKEN=$HOTELS_TOKEN|" "$DEPLOY_DIR/.env"
    ok "GDRIVE_TOKEN -> $HOTELS_TOKEN"
fi

# - 4. ПРОВЕРКА PYTHON
log "Проверка Python..."
if ! command -v $PYTHON_BIN &>/dev/null; then
    log "Устанавливаем Python 3..."
    $SUDO apt-get update -qq
    $SUDO apt-get install -y python3 python3-pip python3-venv
fi
PYTHON_VER=$($PYTHON_BIN --version 2>&1)
ok "Python: $PYTHON_VER"

# ── 5. СИСТЕМНЫЕ ЗАВИСИМОСТИ ─────────────────────────────────
log "Проверка системных зависимостей..."
PACKAGES="wget curl unzip xvfb xauth python3-venv"

MISSING=""
for pkg in $PACKAGES; do
    if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
        MISSING="$MISSING $pkg"
    fi
done

if [ -n "$MISSING" ]; then
    log "Устанавливаем системные пакеты:$MISSING"
    $SUDO apt-get update -qq
    $SUDO apt-get install -y $MISSING
    ok "Системные пакеты установлены"
else
    ok "Системные зависимости в порядке"
fi

# ── 6. ВИРТУАЛЬНОЕ ОКРУЖЕНИЕ ─────────────────────────────────
log "Создание виртуального окружения..."
if [ ! -d "$VENV_DIR" ]; then
    $PYTHON_BIN -m venv "$VENV_DIR"
    ok "Venv создан: $VENV_DIR"
else
    ok "Venv уже существует"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ── 7. УСТАНОВКА PYTHON-ЗАВИСИМОСТЕЙ ─────────────────────────
log "Установка Python зависимостей..."
$VENV_PIP install --upgrade pip -q
$VENV_PIP install -r "$DEPLOY_DIR/requirements.txt" -q
ok "Python пакеты установлены"

# ── 8. УСТАНОВКА PLAYWRIGHT + CHROMIUM ───────────────────────
log "Установка Playwright Chromium (может занять 2-3 минуты)..."
if ! "$VENV_PYTHON" -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.stop()" &>/dev/null 2>&1; then
    "$VENV_DIR/bin/playwright" install chromium
    "$VENV_DIR/bin/playwright" install-deps chromium
    ok "Chromium установлен"
else
    ok "Playwright уже настроен"
fi

# ── 9. СОЗДАНИЕ ПАПКИ OUTPUT ─────────────────────────────────
mkdir -p "$DEPLOY_DIR/output"
ok "Папка output/ создана"

# ── 10. ТЕСТ ЗАПУСКА (SMOKE TEST) ────────────────────────────
log "Smoke test — проверяем импорты..."
cd "$DEPLOY_DIR"
"$VENV_PYTHON" -c "
import sys
sys.path.insert(0, '.')
try:
    from utils.browser import create_browser_context
    from utils.storage import save_item, total
    from parsers import osm, vk_groups, yandex_maps, search_engine, crawler
    from parsers.email_finder import run_enrichment
    print('OK: все модули импортируются')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" || err "Smoke test провалился — проверь файлы"
ok "Smoke test пройден"

# ── 11. СОЗДАНИЕ SYSTEMD СЕРВИСА (oneshot) ───────────────────
log "Создание systemd сервиса..."

$SUDO tee "$SYSTEMD_SERVICE" > /dev/null <<EOF
[Unit]
Description=Ritual B2B Parser (one-shot)
After=network.target
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$DEPLOY_DIR
Environment=PYTHONUNBUFFERED=1
Environment=HEADLESS=0
ExecStart=/usr/bin/xvfb-run -a -s "-screen 0 1280x1024x24" $VENV_PYTHON $DEPLOY_DIR/main.py
TimeoutStartSec=12h
MemoryMax=3G
MemoryHigh=2500M
OOMPolicy=stop
StandardOutput=append:$DEPLOY_DIR/parser.log
StandardError=append:$DEPLOY_DIR/parser_error.log
EOF

ok "Systemd сервис создан: $SYSTEMD_SERVICE"

# ── 11d. WATCHDOG: алерт если парсер завис ──────────────────
SYSTEMD_WD_UNIT="/etc/systemd/system/ritual_watchdog.service"
SYSTEMD_WD_TIMER="/etc/systemd/system/ritual_watchdog.timer"
log "Создание watchdog..."

$SUDO tee "$SYSTEMD_WD_UNIT" > /dev/null <<EOF
[Unit]
Description=Ritual Parser Watchdog (alert if hung)

[Service]
Type=oneshot
WorkingDirectory=$DEPLOY_DIR
ExecStart=/bin/bash $DEPLOY_DIR/watchdog.sh
EOF

$SUDO tee "$SYSTEMD_WD_TIMER" > /dev/null <<EOF
[Unit]
Description=Ritual Parser Watchdog timer (every 10 min)

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
Unit=ritual_watchdog.service

[Install]
WantedBy=timers.target
EOF

chmod +x $DEPLOY_DIR/watchdog.sh
ok "Watchdog создан"

# ── 11b. СОЗДАНИЕ SYSTEMD-ЮНИТА ДЛЯ EMAIL FINDER ─────────────
SYSTEMD_EMAIL_UNIT="/etc/systemd/system/ritual_email_finder.service"
log "Создание email_finder юнита..."

$SUDO tee "$SYSTEMD_EMAIL_UNIT" > /dev/null <<EOF
[Unit]
Description=Ritual B2B Parser — Email Finder only (enrich latest CSV)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$DEPLOY_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_PYTHON $DEPLOY_DIR/run_email_finder.py
TimeoutStartSec=12h
StandardOutput=append:$DEPLOY_DIR/email_finder.log
StandardError=append:$DEPLOY_DIR/email_finder.log
EOF

ok "Email Finder юнит создан: $SYSTEMD_EMAIL_UNIT"

# ── 11c. СОЗДАНИЕ TEMPLATE-ЮНИТА ДЛЯ ЗАПУСКА ОДНОГО ИСТОЧНИКА ─
SYSTEMD_SOURCE_TEMPLATE="/etc/systemd/system/ritual_parser_source@.service"
log "Создание template-юнита ritual_parser_source@<name>..."

$SUDO tee "$SYSTEMD_SOURCE_TEMPLATE" > /dev/null <<EOF
[Unit]
Description=Ritual B2B Parser — single source: %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$DEPLOY_DIR
Environment=PYTHONUNBUFFERED=1
Environment=HEADLESS=0
Environment=ONLY_SOURCE=%i
Environment=SKIP_ENRICHMENT=1
ExecStart=/usr/bin/xvfb-run -a -s "-screen 0 1280x1024x24" $VENV_PYTHON $DEPLOY_DIR/main.py
TimeoutStartSec=6h
StandardOutput=append:$DEPLOY_DIR/parser.log
StandardError=append:$DEPLOY_DIR/parser_error.log
EOF

ok "Source-template юнит создан: $SYSTEMD_SOURCE_TEMPLATE"

# ── 12. СОЗДАНИЕ SYSTEMD ТАЙМЕРА (вс 03:00) ──────────────────
log "Создание systemd таймера..."

$SUDO tee "$SYSTEMD_TIMER" > /dev/null <<EOF
[Unit]
Description=Ritual Parser weekly run

[Timer]
OnCalendar=Mon *-*-* 03:00:00
Persistent=true
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

# Подчищаем старые cron-записи на случай повторного деплоя
( crontab -l 2>/dev/null | grep -v "ritual_parser\|$DEPLOY_DIR" ) | crontab - 2>/dev/null || true

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now ${SERVICE_NAME}.timer
$SUDO systemctl enable --now ritual_watchdog.timer
ok "Таймер активирован: пн 03:00, watchdog включён"

# ── 13. СОЗДАНИЕ СКРИПТА РУЧНОГО ЗАПУСКА ─────────────────────
cat > "$DEPLOY_DIR/run.sh" <<EOF
#!/bin/bash
# Ручной запуск парсера (headless по умолчанию)
cd $DEPLOY_DIR
echo "[\$(date)] Запуск парсера..."
PYTHONUNBUFFERED=1 $VENV_PYTHON main.py
echo "[\$(date)] Парсер завершил работу"
EOF
chmod +x "$DEPLOY_DIR/run.sh"
ok "Создан run.sh для ручного запуска"

# ── 14. СОЗДАНИЕ СКРИПТА ПРОСМОТРА ЛОГОВ ─────────────────────
cat > "$DEPLOY_DIR/logs.sh" <<EOF
#!/bin/bash
# Просмотр логов в реальном времени
tail -f $DEPLOY_DIR/parser.log
EOF
chmod +x "$DEPLOY_DIR/logs.sh"

# ── 15. СОЗДАНИЕ СКРИПТА ПРОСМОТРА РЕЗУЛЬТАТОВ ───────────────
cat > "$DEPLOY_DIR/results.sh" <<EOF
#!/bin/bash
# Показать последние результаты
LATEST=\$(ls -t $DEPLOY_DIR/output/*.csv 2>/dev/null | head -1)
if [ -z "\$LATEST" ]; then
    echo "Результатов пока нет. Запустите: ./run.sh"
else
    echo "Последний файл: \$LATEST"
    echo "Строк в файле: \$(wc -l < \$LATEST)"
    echo ""
    echo "--- Первые 5 записей ---"
    head -6 "\$LATEST"
fi
EOF
chmod +x "$DEPLOY_DIR/results.sh"

# ── 16. ФИНАЛЬНЫЙ ОТЧЁТ ──────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║              ДЕПЛОЙ ЗАВЕРШЁН УСПЕШНО!               ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "${BOLD}Расположение:${NC}       $DEPLOY_DIR"
echo -e "${BOLD}Результаты:${NC}         $DEPLOY_DIR/output/"
echo -e "${BOLD}Логи:${NC}               $DEPLOY_DIR/parser.log"
echo -e "${BOLD}Автозапуск:${NC}         Каждый понедельник в 03:00"
echo ""
echo -e "${BOLD}${YELLOW}Команды управления:${NC}"
echo -e "  ${CYAN}Запустить сейчас:${NC}    $DEPLOY_DIR/run.sh"
echo -e "  ${CYAN}Смотреть логи:${NC}       $DEPLOY_DIR/logs.sh"
echo -e "  ${CYAN}Смотреть результаты:${NC} $DEPLOY_DIR/results.sh"
echo ""
echo -e "${BOLD}${YELLOW}Systemd команды:${NC}"
echo -e "  ${CYAN}Прогон сейчас:${NC}   sudo systemctl start $SERVICE_NAME.service"
echo -e "  ${CYAN}Статус таймера:${NC}  systemctl status $SERVICE_NAME.timer"
echo -e "  ${CYAN}Список таймеров:${NC} systemctl list-timers | grep $SERVICE_NAME"
echo -e "  ${CYAN}Логи прогона:${NC}    journalctl -u $SERVICE_NAME.service -e"
echo ""

# ── СПРОСИТЬ: ЗАПУСТИТЬ ПРЯМО СЕЙЧАС? ────────────────────────
echo -e "${BOLD}Запустить парсер прямо сейчас? (y/n):${NC} \c"
read -r ANSWER
if [[ "$ANSWER" =~ ^[Yy]$ ]]; then
    log "Запуск парсера в фоне (xvfb-run)..."
    cd "$DEPLOY_DIR"
    nohup xvfb-run -a "$VENV_PYTHON" main.py >> "$DEPLOY_DIR/parser.log" 2>&1 &
    PARSER_PID=$!
    echo ""
    ok "Парсер запущен в фоне (PID: $PARSER_PID)"
    echo -e "  Логи: ${CYAN}tail -f $DEPLOY_DIR/parser.log${NC}"
    echo ""
fi
