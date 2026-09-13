"""Юнит-тесты нормализации URL - ключа дедупликации статей.

Чистая функция без ввода-вывода, поэтому проверяется параметризацией,
а не через API.
"""

import urllib.parse

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis.provisional import urls

from main import _normalize_url
from storage import _is_usable_url

# Фикстура изоляции хранилища autouse и потому приезжает и сюда, а
# hypothesis не любит функциональные фикстуры: они готовятся один раз на
# все примеры. Здесь это безвредно - тесты чистой функции диска не
# касаются вообще.
#
# deadline снят: вердикт свойства чистой функции не должен
# зависеть от загрузки машины.
_PROPERTY = settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@pytest.mark.parametrize(
    "first, second",
    [
        ("https://example.com/a", "http://example.com/a"),
        ("https://WWW.Example.com/a", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com/a/", "https://example.com//a"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),
        ("https://example.com/a?fbclid=x", "https://example.com/a"),
        ("https://example.com/a?gclid=x", "https://example.com/a"),
        ("https://example.com/a?yclid=x", "https://example.com/a"),
        ("https://example.com/a#top", "https://example.com/a"),
    ],
    ids=[
        "схема",
        "www и регистр хоста",
        "порт 443 по умолчанию",
        "порт 80 по умолчанию",
        "лишние и финальные слэши",
        "порядок параметров",
        "метки utm",
        "метка fbclid",
        "метка gclid",
        "метка yclid",
        "фрагмент",
    ],
)
def test_treats_as_equivalent(first, second):
    """Адреса, отличающиеся только оформлением, дают один ключ."""
    assert _normalize_url(first) == _normalize_url(second)


@pytest.mark.parametrize(
    "first, second",
    [
        ("https://example.com/a", "https://example.com/A"),
        ("https://example.com:8443/a", "https://example.com/a"),
        ("https://example.com/a?p=1", "https://example.com/a?p=2"),
        ("https://example.com/a?page=1", "https://example.com/a"),
        ("https://example.com/a", "https://sub.example.com/a"),
        ("https://example.com/a", "https://example.com/a/b"),
        ("https://example.com/a?ref=", "https://example.com/a"),
    ],
    ids=[
        "регистр пути значим",
        "нестандартный порт значим",
        "разные значения параметра",
        "значимый параметр не выбрасывается",
        "поддомен",
        "разные пути",
        "параметр с пустым значением значим",
    ],
)
def test_treats_as_different(first, second):
    """Разные статьи не склеиваются в один ключ."""
    assert _normalize_url(first) != _normalize_url(second)


def test_normalizes_scheme_to_http():
    """Схема в ключе всегда ``http`` - https не образует второй ключ."""
    assert _normalize_url("https://example.com/a").startswith("http://")


# --- Свойства (hypothesis) ---


@_PROPERTY
@given(urls())
def test_normalization_is_idempotent(raw):
    """Нормализация нормализованного ничего не меняет.

    Свойство важно тем, что ключ дедупликации должен быть единственным:
    если бы у одного адреса было два канонических вида, дубль прошёл бы
    незамеченным.

    Единственное исключение - повторный префикс ``www.``, оно вынесено в
    ``assume`` и отдельно описано тестом ниже. Проверять его здесь нечем:
    генератор таких хостов не выдаёт, а поведение для них осознанное.
    """
    once = _normalize_url(raw)
    assume(not (urllib.parse.urlsplit(once).hostname or "").startswith("www."))

    assert _normalize_url(once) == once


@_PROPERTY
@given(urls())
@example("http:///path")
@example("http://[::1]:8443/a")
@example("http://example.com:65535/a")
def test_every_record_storage_admits_yields_a_key(raw):
    """Адрес, пропущенный хранилищем, превращается в ключ без исключения.

    Утверждение о паре, а не об одной функции: хранилище решает, какие
    записи попадут в ``main``, и его проверка обязана быть достаточной
    для того, что ``main`` с ними делает. Разойдись они - и запись,
    прошедшая отсев, уронила бы ``POST /api/articles`` для всех адресов
    сразу, потому что ключ считается от каждой записи в хранилище.

    Примеры добраны к генератору руками: ``urls()`` не выдаёт ни адрес
    без хоста, ни литерал IPv6, а расходятся проверки именно на краях.
    """
    assume(_is_usable_url(raw))

    assert _normalize_url(raw).startswith("http://")


def test_repeated_www_prefix_is_stripped_once():
    """Повторный ``www.`` снимается один раз - и это не дефект дедупликации.

    ``www.www.example.com`` - настоящий отдельный хост,
    а не оформление ``example.com``. Снимать префикс до
    упора значило бы склеить две разные статьи, а ложное склеивание - потеря данных.
    """
    assert _normalize_url("http://www.www.example.com/a") == "http://www.example.com/a"
    assert _normalize_url("http://www.example.com/a") == "http://example.com/a"
