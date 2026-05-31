"""Тесты VK _clean_site (нормализация URL из contacts)."""
from parsers.vk_groups import _clean_site


def test_valid_site_normalized():
    assert _clean_site("hotel.ru") == "https://hotel.ru"
    assert _clean_site("https://hotel.ru/") == "https://hotel.ru"
    assert _clean_site("http://hotel.ru/contacts") == "http://hotel.ru/contacts"


def test_empty_returns_empty():
    assert _clean_site("") == ""
    assert _clean_site(None) == ""


def test_garbage_returns_empty():
    # Пустые/whitespace-only — нет токена для парсинга → ""
    assert _clean_site("   ") == ""
    assert _clean_site("\n\n") == ""


def test_extra_whitespace_stripped():
    # VK иногда даёт «hotel.ru | подробнее» — берём первый токен
    assert _clean_site("  hotel.ru extra text ") == "https://hotel.ru"
