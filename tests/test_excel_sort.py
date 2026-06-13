"""Это инструмент для обзвона → записи с телефоном должны идти первыми."""
from utils.excel_export import _sort_rows


def test_phone_rows_come_first():
    rows = [
        {"name": "Без контактов", "city": "Ялта", "phone": "", "email": ""},
        {"name": "Только email", "city": "Ялта", "phone": "", "email": "a@b.ru"},
        {"name": "С телефоном", "city": "Ялта", "phone": "+7 978 1112233", "email": ""},
    ]
    ordered = [r["name"] for r in _sort_rows(rows)]
    assert ordered == ["С телефоном", "Только email", "Без контактов"]


def test_within_same_contact_level_sorted_by_city_then_name():
    rows = [
        {"name": "Бета", "city": "Ялта", "phone": "+7 978 1", "email": ""},
        {"name": "Альфа", "city": "Ялта", "phone": "+7 978 2", "email": ""},
        {"name": "Гамма", "city": "Керчь", "phone": "+7 978 3", "email": ""},
    ]
    ordered = [r["name"] for r in _sort_rows(rows)]
    # Керчь < Ялта по алфавиту; внутри Ялты Альфа < Бета
    assert ordered == ["Гамма", "Альфа", "Бета"]
