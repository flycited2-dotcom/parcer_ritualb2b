"""Тесты приоритета email."""
from parsers.email_finder import _email_score


def test_blocklist_returns_minus_one():
    assert _email_score("noreply@hotel.ru", "hotel.ru") == -1
    assert _email_score("admin@yandex.ru", "") == -1
    assert _email_score("user@example.com", "") == -1


def test_image_extension_returns_minus_one():
    assert _email_score("logo@cdn.example.com.png", "") == -1


def test_corporate_email_beats_generic():
    """Email с доменом сайта (фирменный) приоритетнее, чем чужой домен."""
    corporate = _email_score("info@hotel.ru", "hotel.ru")
    foreign = _email_score("info@gmail.com", "hotel.ru")
    assert corporate > foreign


def test_preferred_prefix_beats_random():
    """booking@/info@ приоритетнее, чем random@."""
    info_score = _email_score("info@hotel.ru", "hotel.ru")
    random_score = _email_score("contact123@hotel.ru", "hotel.ru")
    assert info_score > random_score
