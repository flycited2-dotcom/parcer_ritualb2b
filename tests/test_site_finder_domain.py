"""Регрессия: _extract_domain не должен съедать первые буквы домена.

str.lstrip("www.") убирает ЛЮБЫЕ ведущие символы из набора {w,.}, поэтому
'wiki.ru' превращался в 'iki.ru', а домены на 'w' ломали blacklist-проверку.
"""
from parsers.site_finder import _extract_domain


def test_strips_www_prefix_only():
    assert _extract_domain("https://www.ritual-yalta.ru/contacts") == "ritual-yalta.ru"


def test_keeps_leading_w_domain():
    # 'wiki.ru' раньше становился 'iki.ru' из-за lstrip
    assert _extract_domain("https://wiki.ru/page") == "wiki.ru"


def test_no_www():
    assert _extract_domain("https://ritual.crimea.ru") == "ritual.crimea.ru"
