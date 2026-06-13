"""Регрессия: merger дедуп по (name, city), а не (name, phone).

Раньше одна фирма без телефона (raw CSV) и с телефоном (enriched CSV) давала
ДВЕ строки в master_all. Теперь схлопывается, недостающие поля доливаются.
"""
from utils.merger import _dedup_key


def test_dedup_key_ignores_phone():
    # одна фирма, один город, разный (или пустой) телефон → один ключ
    a = {"name": "Ритуал-Сервис", "city": "Ялта", "phone": ""}
    b = {"name": "Ритуал-Сервис", "city": "Ялта", "phone": "+7 (978) 123-45-67"}
    assert _dedup_key(a) == _dedup_key(b)


def test_dedup_key_normalizes_punctuation_and_case():
    a = {"name": "Ритуал «Вечность»", "city": "Симферополь"}
    b = {"name": "ритуал вечность", "city": "симферополь"}
    assert _dedup_key(a) == _dedup_key(b)


def test_dedup_key_distinguishes_cities():
    a = {"name": "Ритуал", "city": "Ялта"}
    b = {"name": "Ритуал", "city": "Керчь"}
    assert _dedup_key(a) != _dedup_key(b)
