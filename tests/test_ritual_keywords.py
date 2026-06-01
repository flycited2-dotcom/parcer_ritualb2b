"""Тесты классификации vk_filter + нормализации categories под ритуал."""
from parsers.vk_filter import classify
from utils.categories import normalize


def test_ritual_by_name():
    assert classify("Ритуальные услуги «Память»", "Магазин") == "ритуал"
    assert classify("Похоронное бюро Вечность", "") == "ритуал"
    assert classify("Мастерская памятников", "") == "ритуал"
    assert classify("Венки и корзины", "") == "ритуал"
    assert classify("Гробы оптом", "") == "ритуал"


def test_florist():
    assert classify("Цветочный магазин Роза", "") == "флористика"
    assert classify("Доставка букетов", "Цветы") == "флористика"
    assert classify("Студия флористики", "") == "флористика"


def test_ritual_priority_over_florist():
    # есть и ритуал, и цветы → ритуал (приоритет по дизайну 4.5)
    assert classify("Ритуальные венки и цветы", "") == "ритуал"


def test_noise():
    assert classify("Свадебный салон", "") == "noise"
    assert classify("Детский магазин игрушек", "") == "noise"
    assert classify("Праздничные торты на заказ", "") == "noise"


def test_ambiguous():
    # ни ритуал, ни флорист, ни шум → на ручную проверку
    assert classify("ООО Вектор", "Услуги") == "ambiguous"
    assert classify("", "") == "ambiguous"


def test_normalize_client_type():
    assert normalize("ритуальные услуги") == "ритуальное агентство"
    assert normalize("похоронное бюро") == "похоронное бюро"
    assert normalize("памятники") == "мастерская памятников"
    assert normalize("надгробия") == "мастерская памятников"
    assert normalize("крематорий") == "кладбищенские услуги"
    assert normalize("цветочный магазин") == "флористика"
    assert normalize("венки") == "ритуальный магазин"
    assert normalize("") == "прочее"
    assert normalize("автосервис") == "прочее"


def test_normalize_osm_tags():
    assert normalize("funeral_directors") == "ритуальное агентство"
    assert normalize("stonemason") == "мастерская памятников"
