"""Тесты определения города по координатам."""
from utils.geo_city import detect_city_by_coords


def test_yalta_center():
    # Координаты выбраны так, чтобы не попасть в bbox микрорайонов
    # (Ливадия 34.130-34.170, Массандра 34.180-34.215). Микрорайоны идут
    # в CITY_BBOXES раньше Ялты, поэтому совпадают первыми.
    assert detect_city_by_coords(44.500, 34.175) == "Ялта"


def test_simferopol_center():
    assert detect_city_by_coords(44.952, 34.102) == "Симферополь"


def test_sevastopol_center():
    assert detect_city_by_coords(44.616, 33.525) == "Севастополь"


def test_open_sea_returns_empty():
    """Точка в Чёрном море — не Крым → пустая строка."""
    assert detect_city_by_coords(43.0, 32.0) == ""


def test_none_returns_empty():
    assert detect_city_by_coords(None, None) == ""
    assert detect_city_by_coords(44.5, None) == ""
    assert detect_city_by_coords(None, 34.1) == ""


def test_melitopol():
    # Запорожская обл., bbox 46.82-46.88 / 35.34-35.42
    assert detect_city_by_coords(46.85, 35.38) == "Мелитополь"


def test_genichesk():
    # Херсонская обл. (левобережье), bbox 46.16-46.19 / 34.79-34.85
    assert detect_city_by_coords(46.17, 34.82) == "Геническ"


def test_novaya_kakhovka():
    assert detect_city_by_coords(46.76, 33.37) == "Новая Каховка"


def test_excluded_zaporizhzhia_city_not_mapped():
    # Запорожье-город (спорная зона) намеренно НЕ в bbox → не определяется как
    # конкретный город (возвращает "", запись не привязывается к РФ-городу).
    assert detect_city_by_coords(47.83, 35.14) == ""
