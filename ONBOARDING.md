# Ritual B2B Parser — Onboarding

Парсер контактов ритуального/похоронного бизнеса (+флористика) по 4 субъектам РФ:
**Республика Крым, Севастополь, Запорожская обл., Херсонская обл.** — только территории
под фактическим контролем РФ. База для B2B-обзвона/email-кампаний заказчика.

Клон рабочего crimea-парсера (репо `hotels_sbor_baza`).
Дизайн: [docs/superpowers/specs/2026-06-01-ritual-parser-design.md](docs/superpowers/specs/2026-06-01-ritual-parser-design.md).

## Структура (плоская)

Исходники парсера — в корне, бот — в `ritual_admin_bot/`.

| Путь | Назначение |
|---|---|
| `main.py` | Оркестратор: `RUNNERS` (7 источников), enrichment, merge, xlsx, gdrive, TG-отчёт |
| `parsers/` | osm, wikidata, wikipedia, vk_groups, yandex_maps, search_engine, crawler + email_finder/site_finder/vk_email/vk_filter |
| `utils/` | storage (CSV+dedup), categories, geo_city, excel_export, merger, gdrive, telegram_notify, browser, http_retry, env_loader |
| `scripts/` | clean_garbage, archive_old, `fetch_vk_cities` (разовый), `cleanup_classification` |
| `deploy/` | `ritual_archive.{service,timer}`, logrotate; остальные юниты генерит `deploy.sh` |
| `tests/` | pytest (53 теста) |
| `ritual_admin_bot/` | aiogram-бот управления (на сервере → `/opt/ritual_admin_bot/`) |

## Источники (7, `main.py:RUNNERS`)

OSM Overpass (funeral-теги), Wikidata, Wikipedia, **VK Groups** (главный по объёму),
Я.Карты, Поиск (Я/Mail/Rambler/Bing), Crawler. Добор контактов: `email_finder`
(+`extract_socials` tg/inst/wa/ok), `site_finder`, `vk_email`.

## Классификация

`parsers/vk_filter.py:classify(name, activity)` → `ритуал` / `флористика` / `noise` / `ambiguous`
(приоритет ритуала; «цветы/букет» → флористика).
`utils/categories.py:normalize()` → client_type: ритуальное агентство / похоронное бюро /
ритуальный магазин / мастерская памятников / кладбищенские услуги / флористика / прочее.
`ambiguous` → `comment=needs_review` → вкладка XLSX «Требуют проверки».

## Запуск локально

```bash
python -m pytest tests/ -q          # тесты (53 green)
playwright install chromium         # один раз — для Chromium-источников
python main.py                      # полный прогон
ONLY_SOURCE=vk python main.py       # один источник (osm/wikidata/wikipedia/vk/yandex/search/crawler)
python scripts/fetch_vk_cities.py   # разово: VK city_id для городов ЗП/Хс (нужен VK_TOKEN)
```

## Деплой

Сервер `212.116.115.150` (тот же, что crimea), изолированно:
- `/home/ritual_parser/` — парсер, `/opt/ritual_admin_bot/` — бот
- systemd `ritual_*`, таймер **Mon 03:00 MSK** (crimea — Sun, не пересекаются)
- `bash deploy.sh` ставит парсер + юниты; бот — `ritual_admin_bot/install.sh`
- ⚠️ **НЕ запускать одновременно с crimea** (общий Chromium → OOM, RAM 5.8 ГБ)
- ⚠️ файлы из Windows: на сервере `sed -i 's/\r$//'` на `.sh`

`.env` (chmod 600): `deploy.sh` автоматически подтягивает `VK_TOKEN`/`GDRIVE_TOKEN`/`GDRIVE_CREDENTIALS`
из `/home/crimea_parser/.env`; вручную заполнить `TG_BOT_TOKEN`, `TG_CHAT_ID`, `GDRIVE_FOLDER_ID`.
**Секреты — не в git.**

## Управление через TG-бот

`/run`, `/run_emails`, `/run_source <key>`, `/status`, `/stats`, `/db`, `/master`,
`/logs`, `/health`, `/schedule`, `/timer_on`, `/timer_off`, `/drive`.
