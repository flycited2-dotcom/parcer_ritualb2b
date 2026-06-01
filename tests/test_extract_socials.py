"""Тесты извлечения соц-ссылок (tg / instagram / whatsapp / ok)."""
from parsers.email_finder import extract_socials, socials_to_str


def test_all_platforms():
    t = ("свяжитесь t.me/ritual_yalta или instagram.com/pohorony.krym "
         "wa.me/+79781112233 ok.ru/group/12345678")
    d = extract_socials(t)
    assert d["tg"] == "tg:@ritual_yalta"
    assert d["inst"] == "inst:@pohorony.krym"
    assert d["wa"] == "wa:+79781112233"
    assert d["ok"] == "ok:12345678"


def test_tg_resolve_form():
    assert extract_socials("tg://resolve?domain=ritualkerch")["tg"] == "tg:@ritualkerch"


def test_whatsapp_api_form():
    d = extract_socials("api.whatsapp.com/send?phone=79781112233")
    assert d["wa"] == "wa:79781112233"


def test_ok_named_group():
    assert extract_socials("ok.ru/ritualsevastopol")["ok"] == "ok:ritualsevastopol"


def test_skip_reserved_and_service_links():
    # служебные пути, не профили организаций
    assert "tg" not in extract_socials("t.me/share/url?x=1")
    assert "inst" not in extract_socials("instagram.com/p/Abc123def")


def test_empty():
    assert extract_socials("") == {}
    assert extract_socials("здесь нет ссылок") == {}


def test_socials_to_str_order():
    d = {"wa": "wa:+7999", "tg": "tg:@a"}
    # порядок фиксированный: tg, inst, wa, ok
    assert socials_to_str(d) == "tg:@a; wa:+7999"
