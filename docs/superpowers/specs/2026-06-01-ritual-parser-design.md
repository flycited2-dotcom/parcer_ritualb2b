# Ritual B2B Parser — Design Spec

> **Дата:** 2026-06-01
> **Статус:** Утверждённый дизайн → переход к плану реализации
> **Базируется на:** `crimea_parser` (репо `hotels_sbor_baza`), полный клон с переименованием

---

## 1. Цель и контекст

Создать парсер контактов компаний ритуальной/похоронной ниши в трёх регионах: **Республика Крым, Севастополь, Запорожская область, Херсонская область**. База нужна для B2B-обзвона/email-кампаний.

Целевые типы бизнеса (по запросу заказчика):
- ритуальные магазины
- агентства похоронные / похоронные бюро
- ритуальная атрибутика и товары (гробы, венки, корзины, иконы, лампады)
- услуги «под ключ» (организация церемоний, транспорт)
- продажа венков и ритуальных корзин
- мастерские памятников и надгробий

Дополнительно: **флористика** (флористические магазины, цветочные) — собираем рядом, на отдельную вкладку XLSX (будущая ниша).

Архитектурный клон `crimea_parser` — переиспользуем 90% кода (universal storage / dedup / source-parsers / watchdog / pytest / deploy). Меняем словари, географию, словари классификации, токены и пути.

---

## 2. Архитектура

```
TG: @RitualLeadBot (новый)         systemd: ritual_*
@RitualAdminBot (новый)              /home/ritual_parser/
       │                             ├── ritual_parser.service
       ↓                             │     (oneshot, MemoryMax=3G, TimeoutStartSec=12h)
ritual_admin_bot.service             ├── ritual_parser.timer (Mon 03:00 MSK)
       │                             ├── ritual_email_finder.service
       └─→ управление прогонами ←──→ │     (TimeoutStartSec=12h)
                                     ├── ritual_admin_bot.service (active running)
                                     ├── ritual_watchdog.service + .timer (10 min)
                                     └── ritual_archive.service + .timer (Mon 04:00)
                                            ↓
                                     /home/ritual_parser/output/
                                     ├── dedup.db
                                     ├── master_all.csv
                                     ├── master_all.xlsx
                                     ├── result_*.csv
                                     ├── result_enriched_*.csv
                                     └── archive/YYYY-MM.tar.gz
                                            ↓
                                     GDrive folder
                                     «Ritual_Leads_Crimea_ZP_KhO»
```

### Что сохраняется как в crimea_parser

**utils/** (универсальные модули, переиспользуются без правок):
- `storage.py` (CSV + dedup + append-mode, FIELDS остаются прежними)
- `browser.py`, `safe_browser.py` (Playwright контекст)
- `progress.py`, `dedup.py`
- `http_retry.py` (retry с backoff)
- `env_loader.py` (load_all_env для split secrets)
- `telegram_notify.py`
- `gdrive.py`
- `merger.py` (с фиксом glob `*enriched*.csv` уже встроен)

**parsers/** (универсальные парсеры, меняются только словари):
- `email_finder.py` (+ новый `extract_socials` для tg/inst/wa/ok)
- `site_finder.py`
- `vk_email.py`
- `crawler.py`

**deploy/scripts:** `watchdog.sh`, `archive_old.sh`, `clean_garbage.py`, `pytest.ini`, deploy-юниты, logrotate-конфиг — всё переиспользуется с заменой `crimea_*` → `ritual_*`.

### Что удаляется

- `parsers/sutochno.py` — отельный агрегатор аренды
- `parsers/ostrovok.py` — отельный агрегатор
- `parsers/avito.py` — отельные объявления, ban IP
- `parsers/twogis.py` — Крым геоблок (опционально вернуть в фазе 2 для Запорожья/Херсонщины, если 2ГИС там открыт)
- `parsers/gosreestr.py` — реестр гостиниц, NXDOMAIN с 2022
- `crimea_bot.service` (бот №1 stdlib) — не клонируем

### Что адаптируется (правки конкретных функций)

- `utils/categories.py` — `client_type`: ритуальное агентство / похоронное бюро / ритуальный магазин / мастерская памятников / кладбищенские услуги / флористика / прочее
- `utils/geo_city.py` — `CITY_BBOXES`: +25 городов Запорожской и Херсонской областей
- `parsers/vk_groups.py` — `VK_CITIES`, `QUERIES`, переименование HOTEL_* → RITUAL_*
- `parsers/osm.py` — Overpass: `shop=funeral_directors`, `office=funeral_directors`, `amenity=funeral_hall`, `amenity=crematorium`, `craft=stonemason`
- `parsers/wikidata.py` — Q1530940 / Q1149653 / Q1326031; REGIONS: Q15966495, Q42959, Q3697, Q3699
- `parsers/wikipedia.py` — Категории: «Похоронные бюро», «Ритуальные услуги», «Крематории России»
- `parsers/yandex_maps.py` — `QUERIES` ритуальные
- `parsers/search_engine.py` — `QUERIES` ритуальные
- `parsers/crawler.py` — `HOTEL_TRIGGERS` → `RITUAL_TRIGGERS + FLORIST_TRIGGERS`
- `parsers/vk_filter.py` — `RITUAL_KEYWORDS` + `FLORIST_KEYWORDS` + RITUAL_NOISE (минимальный)
- `utils/excel_export.py` — добавляет вкладки «Сводка», «Все ритуальные», «Флористика», «Требуют проверки», далее по городам

---

## 3. Региональная конфигурация

### 3.1 Крым (наследуется из crimea_parser geo_city)

Симферополь, Севастополь, Ялта (+микрорайоны: Ливадия, Гурзуф, Партенит, Мисхор, Алупка, Симеиз, Форос, Кореиз, Никита, Гаспра, Голубой Залив, Кацивели, Понизовка, Массандра), Алушта (+Малореченское, Солнечногорское, Рыбачье, Семидворье), Евпатория, Саки, Заозёрное, Новофёдоровка, Витино, Окуневка, Межводное, Черноморское, Феодосия, Береговое, Приморский, Орджоникидзе, Курортное, Коктебель, Морское, Судак, Новый Свет, Керчь, Щёлкино, Бахчисарай, Соколиное, Песчаное, Угловое, Любимовка, Кача, Балаклава, Орлиное.

### 3.2 Запорожская область (новые bbox в geo_city)

| Город | lat_min – lat_max | lon_min – lon_max |
|---|---|---|
| Мелитополь | 46.82 – 46.88 | 35.34 – 35.42 |
| Бердянск | 46.74 – 46.78 | 36.74 – 36.84 |
| Энергодар | 47.49 – 47.52 | 34.62 – 34.68 |
| Токмак | 47.24 – 47.28 | 35.69 – 35.76 |
| Каменка-Днепровская | 47.47 – 47.51 | 34.39 – 34.45 |
| Васильевка | 47.43 – 47.46 | 35.27 – 35.31 |
| Приморск | 46.72 – 46.76 | 36.32 – 36.39 |
| Молочанск | 47.20 – 47.22 | 35.59 – 35.63 |
| Пологи | 47.46 – 47.49 | 36.24 – 36.31 |
| Куйбышево | 47.31 – 47.34 | 36.66 – 36.72 |

### 3.3 Херсонская область (новые bbox в geo_city)

| Город | lat_min – lat_max | lon_min – lon_max |
|---|---|---|
| Геническ | 46.16 – 46.19 | 34.79 – 34.85 |
| Новая Каховка | 46.74 – 46.78 | 33.34 – 33.40 |
| Каховка | 46.81 – 46.84 | 33.46 – 33.52 |
| Скадовск | 46.10 – 46.13 | 32.89 – 32.95 |
| Алёшки (б. Цюрупинск) | 46.62 – 46.66 | 32.71 – 32.78 |
| Голая Пристань | 46.51 – 46.54 | 32.51 – 32.57 |
| Чаплинка | 46.36 – 46.39 | 33.52 – 33.58 |
| Новотроицкое | 46.32 – 46.35 | 34.32 – 34.38 |
| Великая Лепетиха | 47.16 – 47.19 | 33.95 – 34.01 |

### 3.4 VK city_ids

Список VK city_id для Запорожья и Херсонщины вычисляется один раз скриптом `scripts/fetch_vk_cities.py`:
- Принимает список city_name
- Вызывает `database.getCities(country_id=1, q=<name>)` через VK API
- Печатает соответствие `name → id` для копирования в `vk_groups.py:VK_CITIES`

Для крымских городов VK city_id наследуются из `crimea_parser/parsers/vk_groups.py:VK_CITIES` — копируются как есть в ритуальную версию.

### 3.5 OSM Overpass bbox

Единая большая bbox на 4 региона: `46.0 – 48.0 lat, 32.0 – 37.5 lon`. Внутри запроса фильтрация по `admin_level=4` для отсева ошибочных пограничных совпадений.

### 3.6 Wikidata regions

```python
REGIONS = [
    "Q15966495",  # Республика Крым
    "Q42959",     # Севастополь
    "Q3697",      # Запорожская область
    "Q3699",      # Херсонская область
]
```

### 3.7 Зона неопределённого контроля (de-facto под Украиной)

Не фильтруем на парсинге, помечаем в Excel-вкладке предупреждением. Конкретный список городов в `utils/geo_city.py:DISPUTED_CITIES`:

```python
DISPUTED_CITIES = (
    "Запорожье",   # центр области, под Украиной
    "Херсон",      # центр области, под Украиной
    "Берислав",    # правый берег Днепра
    "Покровка",    # правый берег
)
```

Запись попадает в эту группу, если `city` ∈ `DISPUTED_CITIES` ИЛИ обнаружена эвристически по lat/lon вне известных RU-bbox.

В `excel_export.py` отдельная Excel-вкладка «Зона под вопросом» или подсветка строк жёлтым в основной таблице — выберется при имплементации.

---

## 4. Словари

### 4.1 client_type (utils/categories.py)

| client_type | Что входит |
|---|---|
| `ритуальное агентство` | полный цикл «под ключ», транспорт, церемонии |
| `похоронное бюро` | оформление документов, ритуал, гроб + транспорт |
| `ритуальный магазин` | гробы, венки, корзины, иконы, лампады, атрибутика |
| `мастерская памятников` | надгробия, ограды, памятники из камня |
| `кладбищенские услуги` | копка, благоустройство |
| `флористика` | флористические магазины, цветочные |
| `прочее` | fallback |

Маппинг строка-категории → client_type через regex (как `normalize_category` в crimea).

### 4.2 RITUAL_KEYWORDS (стемы для классификации)

```python
RITUAL_KEYWORDS = (
    "ритуал",        # ритуальный, ритуальные
    "похорон",       # похоронный, похороны
    "погреб",        # погребение, погребальный
    "венк",          # венок, венки, венков
    "гроб",          # гроб, гробы, гробница
    "надгроб",       # надгробие, надгробный
    "памятник",      # памятник могилу
    "кладбищ",       # кладбище, кладбищенский
    "кремац",        # кремация, крематорий
    "мемориал",      # мемориал, мемориальный
    "усопш",         # усопший
    "отпеван",       # отпевание
    "поминк",        # поминки
    "ритуальн",      # ритуальная атрибутика
    "ритуальные товар",
    "корзин ритуал",
)
```

### 4.3 FLORIST_KEYWORDS (для отдельной классификации, не noise)

```python
FLORIST_KEYWORDS = (
    "флорист",       # флорист, флористика
    "цветочн",       # цветочный магазин
    "букет",         # букеты
    "цветы",         # цветы общее
)
```

### 4.4 RITUAL_NOISE (минимальный шумовой словарь)

```python
RITUAL_NOISE = (
    "свадебн",       # свадебные торжества
    "торт",          # торты
    "детск",         # детский магазин (false-positive «корзинка»)
)
```

### 4.5 Логика классификации в vk_filter

```
есть RITUAL_KEYWORD   → client_type = ритуальный
есть FLORIST_KEYWORD  → client_type = флористика
оба                   → client_type = ритуальный (приоритет)
ни тех, ни других, есть NOISE → skip
ни тех, ни других, нет NOISE  → ambiguous, comment=needs_review
```

### 4.6 RITUAL_QUERIES (VK / поисковики / Я.Карты)

```python
RITUAL_QUERIES = [
    "ритуальные услуги",
    "ритуальное агентство",
    "похоронное бюро",
    "ритуальный магазин",
    "ритуальная атрибутика",
    "венки",
    "венки купить",
    "памятники на могилу",
    "гробы купить",
    "надгробия",
    "крематорий",
    "поминальные товары",
    "ритуальные товары",
    "мастерская памятников",
    "ограды на могилу",
]
```

15 запросов × ~25 городов = ~375 vk.search вызовов (по 200 групп = до 75K на бумаге; реально 2-8K уникальных после дедупа).

### 4.7 OSM теги

```
shop=funeral_directors
office=funeral_directors
amenity=funeral_hall
amenity=crematorium
craft=stonemason   ← border-case: мастер по камню → ambiguous, comment=needs_review
```

### 4.8 Wikipedia категории

```
Категория:Похоронные_бюро
Категория:Ритуальные_услуги
Категория:Крематории_России
```

Исключаем: «Кладбища_по_алфавиту» (объекты, не бизнес).

### 4.9 Социальные сети (extract_socials)

Добавляется в `parsers/email_finder.py:extract_socials(html_or_text) → dict`:

| Платформа | Регекс | Результат |
|---|---|---|
| Telegram | `t\.me/([A-Za-z][\w_]{4,31})` или `tg://resolve?domain=<name>` | `tg:@handle` |
| Instagram | `instagram\.com/([A-Za-z][\w.]{1,29})` | `inst:@handle` |
| WhatsApp | `wa\.me/(\+?\d{10,15})` или `api\.whatsapp\.com/send\?phone=(\d+)` | `wa:+7...` (нормализуется через normalize_phone) |
| OK | `ok\.ru/group/(\d+)` или `ok\.ru/([A-Za-z][\w.]{2,29})` | `ok:<name>` |
| YouTube | (фаза 2, не сейчас) | — |

Все найденные ссылки конкатенируются в поле `social`, разделитель `;`. Если `phone` пустой, но найден WhatsApp — заполняем `phone` оттуда.

---

## 5. Структура проекта

```
parser_ritualb2b/                              # новый git-репо
├── ONBOARDING.md
├── tz_ritual_parser.docx                       # ТЗ заказчика (генерируем из дизайна)
├── _deploy_helper.py                           # paramiko-helper
├── .gitignore
├── docs/
│   ├── HANDOFF_2026-06-01.md                   # стартовый handoff
│   └── superpowers/specs/
│       └── 2026-06-01-ritual-parser-design.md  # этот файл
├── ritual_parser/                              # ⭐ исходники
│   ├── main.py
│   ├── deploy.sh
│   ├── watchdog.sh
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── .env.example
│   ├── .env.{tg,vk,gdrive}.example
│   ├── parsers/
│   │   ├── osm.py, wikidata.py, wikipedia.py
│   │   ├── vk_groups.py, vk_filter.py, vk_email.py
│   │   ├── yandex_maps.py, search_engine.py
│   │   ├── crawler.py
│   │   ├── email_finder.py
│   │   └── site_finder.py
│   ├── utils/
│   │   ├── storage.py, browser.py, safe_browser.py
│   │   ├── progress.py, dedup.py
│   │   ├── geo_city.py, categories.py
│   │   ├── http_retry.py, env_loader.py
│   │   ├── telegram_notify.py, excel_export.py
│   │   ├── merger.py, gdrive.py
│   ├── scripts/
│   │   ├── clean_garbage.py
│   │   ├── archive_old.sh
│   │   ├── fetch_vk_cities.py                  # 🆕 разовый
│   │   └── cleanup_classification.py           # 🆕 аналог cleanup_vk.py
│   ├── deploy/
│   │   ├── ritual_parser.{service,timer}
│   │   ├── ritual_email_finder.service
│   │   ├── ritual_admin_bot.service
│   │   ├── ritual_watchdog.{service,timer}
│   │   ├── ritual_archive.{service,timer}
│   │   └── logrotate-ritual_parser.conf
│   └── tests/
│       ├── conftest.py
│       ├── test_normalize_phone.py
│       ├── test_email_score.py
│       ├── test_geo_city.py                    # дополнен ЗП/Хс
│       ├── test_vk_clean_site.py
│       ├── test_pick_address.py
│       ├── test_storage_append.py
│       ├── test_ritual_keywords.py             # 🆕
│       └── test_extract_socials.py             # 🆕
└── ritual_admin_bot/                            # ⭐ aiogram-бот
    ├── bot.py
    ├── handlers/{commands.py, menu.py}
    └── services/{auth.py, csv_finder.py, systemd.py}
```

### Переименование (find-replace при копировании)

| Найти (везде кроме внутренних Python imports) | Заменить |
|---|---|
| `crimea_parser` | `ritual_parser` |
| `Crimea Hotel Parser` | `Ritual B2B Parser` |
| `parser_admin_bot` (директория, systemd, упоминания в комментариях) | `ritual_admin_bot` |
| `crimea_email_finder` | `ritual_email_finder` |
| `crimea_watchdog` | `ritual_watchdog` |
| `crimea_archive` | `ritual_archive` |
| `/home/crimea_parser/` | `/home/ritual_parser/` |
| `/root/parser_admin_bot/` | `/root/ritual_admin_bot/` |
| `crimea_bot` (systemd-юнит) | (удалить, не клонируется) |

**Внутренние Python imports не меняются** (например `from services.systemd import ...`, `from utils.storage import ...`) — структура пакетов одинаковая, переименовывается только корневой путь и systemd-метки.

Hotel-специфичные строковые литералы (HOTEL_KEYWORDS, HOTEL_TRIGGERS, HOTEL_QUERIES, hotel_*) переименовываются в RITUAL_KEYWORDS / RITUAL_TRIGGERS / RITUAL_QUERIES.

---

## 6. Деплой

### 6.1 Сервер

Тот же sprinthost: `212.116.115.150` (Ubuntu 24.04, 5.8 GB RAM + 2 GB swap, 67 GB диск).

Изоляция от crimea_parser:
- отдельная папка `/home/ritual_parser/`
- отдельная `dedup.db`
- отдельные systemd-юниты с префиксом `ritual_`
- отдельный TG-бот, отдельный TG-чат, отдельная GDrive-папка
- **не запускать одновременно с crimea** (общий Chromium → OOM)

### 6.2 Расписание

| Юнит | Когда | Длительность |
|---|---|---|
| `crimea_parser.timer` | Sun 03:00 MSK | 6-12 часов |
| `ritual_parser.timer` | **Mon 03:00 MSK** | 6-10 часов |
| `crimea_archive.timer` | Mon 04:00 MSK | < 1 мин |
| `ritual_archive.timer` | Mon 05:00 MSK | < 1 мин |
| `crimea_watchdog.timer`, `ritual_watchdog.timer` | каждые 10 мин | < 1 сек |

Понедельник 03:00 для ritual — гарантированный свободный интервал после crimea и его архивации.

### 6.3 Секреты

Новые токены/IDs (получены от заказчика, хранятся в local memory, **не в репо**):
- `TG_BOT_TOKEN` — новый бот (заказчик предоставил)
- `TG_CHAT_ID` — новая группа (заказчик предоставил)
- `GDRIVE_FOLDER_ID` — новая папка (заказчик предоставил)
- `VK_TOKEN` — переиспользуется из crimea_parser
- `GDRIVE_TOKEN` (token.json) и `credentials.json` — переиспользуются из crimea_parser

Все попадают в `/home/ritual_parser/.env` (chmod 600) при деплое через `_deploy_helper.py`. Никогда не в git.

### 6.4 Пользовательский workflow после деплоя

Управление через TG: `/run`, `/run_emails`, `/run_source`, `/status`, `/stats`, `/sources`, `/db`, `/master`, `/logs`, `/health`, `/timer_on/off`, `/schedule`, `/drive`.

Автоматика: понедельник 03:00 — прогон, ~9 часов, отчёт в TG-чат + GDrive upload.

### 6.5 Формат TG-отчёта

```
✅ Ritual B2B Parser — еженедельный прогон
📊 Собрано: N уникальных
   ритуальные:    X (Y%)
   флористика:    X (Y%)
   нужно проверить: X (Y%)
📞 С телефоном: X (Y%)
📧 С email:     X (Y%)
🌐 С сайтом:    X (Y%)
По городам: топ-5 — ...
Файл: master_all.xlsx (приложен)
GDrive: ссылка
```

### 6.6 Excel вкладки

1. **Сводка** — цифры + распределение по client_type + по городам
2. **Все ритуальные** — client_type ∈ ритуальные
3. **Флористика** — client_type = флористика
4. **Требуют проверки** — comment=needs_review + zone=disputed
5–N. По городам — фильтр по client_type через AutoFilter

---

## 7. Тестирование

### 7.1 Pytest baseline

~42 теста, все green:
- 6 файлов унаследованы из crimea (normalize_phone, email_score, vk_clean_site, pick_address, storage_append, geo_city)
- `test_geo_city.py` расширен новыми городами Запорожья/Херсонщины
- 🆕 `test_ritual_keywords.py` — классификация RITUAL/FLORIST/NOISE/ambiguous (8 тестов)
- 🆕 `test_extract_socials.py` — регексы tg/inst/wa/ok (6 тестов)

### 7.2 Smoke-test после деплоя

15 минут, чек-лист:
- [ ] `_deploy_helper.py ping` отвечает
- [ ] `systemctl status ritual_*` корректные
- [ ] 4 таймера активны
- [ ] @RitualLeadBot отвечает на `/start`
- [ ] `/health` показывает RAM/диск
- [ ] `/run_source vk` с ONLY_CITY=Симферополь, ONLY_QUERY="ритуальные услуги" даёт ≥ 5 строк
- [ ] `/master` присылает CSV
- [ ] `pytest tests/ -q` зелёный на сервере

### 7.3 Критерии приёмки полного прогона (~10 часов)

**Пройдено:**
- ✅ ≥ 800 уникальных записей в master_all
- ✅ ритуальные ≥ 40%, флористика ≥ 10%, ambiguous ≤ 25%
- ✅ phone ≥ 25%, email ≥ 12%
- ✅ Все 4 региона представлены
- ✅ XLSX книга с нужными вкладками
- ✅ GDrive получил CSV+XLSX
- ✅ Watchdog 0 алертов
- ✅ Swap usage < 50%
- ✅ Прогон завершился `Result: success`

**Требует доработки:**
- ⚠️ < 300 уникальных → расширить RITUAL_QUERIES
- ⚠️ ритуальных < 30% → корректировать стемы в vk_filter
- ⚠️ ЗП/Хс = 0 → проверить bbox и VK_CITIES
- ⚠️ OOM → recreate_context_every=20

### 7.4 Мониторинг первого месяца

- 4 прогона без watchdog-алертов
- Рост +200-500 уникальных/неделю первые 2-3 прогона
- Доля флористики 15-25% от ритуальных
- VK_TOKEN жив (нет TG-алертов error_code 5/15)
- Диск < 60%, RAM peak < 5 GB

---

## 8. Out of scope (фаза 2)

Не входит в текущий MVP, обсуждаемо после первого успешного прогона:

1. `parsers/twogis.py` для Запорожья/Херсонщины (проверить, открыт ли 2ГИС для этих регионов)
2. Расширить `extract_socials` на YouTube/RuTube
3. Telegram-каталоги ритуальных бизнесов (если найдём публичный источник)
4. Парсинг отзывов с Я.Карт (качественная оценка лида)
5. Интеграция с CRM (Bitrix24/AmoCRM) для автоматической загрузки лидов
6. ML-классификатор client_type вместо regex-словарей

### Что НЕ планируется в принципе

- Telegram MTProto-парсинг (серая зона, банят аккаунты)
- Instagram-scraping (Meta блочит, банит)
- Yandex.Search через нелегальный API
- Спам-функции (только сбор контактов, рассылку делает заказчик отдельно)

---

## 9. Риски и допущения

| Риск | Митигация |
|---|---|
| VK_TOKEN протухнет | Health-check уже есть (наследуется из phase 9 crimea), TG-алерт на error_code 5/15/27/28 |
| Я.Карты заблокируют новые регионы как Крым | Fallback на VK + поисковики (которые дают 60-70% базы) |
| OOM при email_finder на 5K+ сайтов | swap 2GB + MemoryMax=3G + safe_browser recreate_context |
| Конфликт ресурсов с crimea_parser | Разнесены по timer (Mon vs Sun), не запускать вручную одновременно |
| Малая база в Запорожье/Херсонщине | Принимаем — это новые регионы РФ, OSM/Wikipedia плохо размечены, основной сборщик — VK + Поиск |
| Шум в данных | vk_filter + comment=needs_review + отдельная Excel-вкладка для ручной проверки |
| Дубли с crimea_parser (один и тот же отель попал и в hotel-парсер и в ritual-парсер) | dedup.db изолирован, перекрёстные дубли не страшны (разная аудитория обзвона) |

---

## 10. Acceptance summary

**Дизайн утверждён, если переход к плану реализации даёт:**
- Полный клон crimea_parser в `C:\Users\user\Documents\GitHub\parser_ritualb2b`
- Деплой на тот же сервер в `/home/ritual_parser/` и `/root/ritual_admin_bot/`
- Первый smoke-test зелёный
- Первый полный прогон даёт ≥ 800 уникальных записей с указанным распределением

**После утверждения spec → переход к writing-plans skill для детального плана реализации.**
