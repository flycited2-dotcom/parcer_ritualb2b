#!/bin/bash
# Ручной запуск парсера (headless по умолчанию)
cd /home/ritual_parser
echo "[$(date)] Запуск парсера..."
PYTHONUNBUFFERED=1 /home/ritual_parser/venv/bin/python main.py
echo "[$(date)] Парсер завершил работу"
