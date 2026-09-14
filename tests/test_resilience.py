"""Устойчивость к отказам и защита от SSRF.

Эти тесты покрывают инварианты «отказ части не должен становиться отказом целого»,
«потеря данных - худший из дефектов» и
«сервис не становится инструментом атаки на внутренние ресурсы».

Сеть здесь не используется: адреса задаются IP-литералами, поэтому
``socket.getaddrinfo`` отвечает без обращения к DNS. Исключений два:
тесты про разрешение имени подменяют сам ``getaddrinfo`` (им нужен
домен, а не литерал), а тест про установку защиты в опенер подменяет
транспорт ``urllib``, оставляя настоящей всю обработку ответа над ним.
"""

import io
import json
import logging
import socket
import urllib.response
import uuid
from email.message import Message

import pytest
from fastapi.testclient import TestClient

import main
import parser
import storage
from tests.conftest import raising

# --- Битые записи не роняют библиотеку ---


@pytest.mark.json_storage
def test_corrupted_file_does_not_break_list(client, stored_article, caplog):
    """Файл с невалидным JSON пропускается с предупреждением, остальные видны.

    Отказ части не становится отказом целого, но и молчаливое проглатывание
    запрещено. Без проверки лога тест зелен и с ``logger.warning`` заменённым на ``pass``.
    """
    caplog.set_level(logging.WARNING)
    good = stored_article(title="Целая")
    storage.DATA_DIR.joinpath("broken.json").write_text("{не json", encoding="utf-8")

    response = client.get("/api/articles")

    assert response.status_code == 200
    assert [a["id"] for a in response.json()] == [good["id"]]
    assert "broken.json" in caplog.text


@pytest.mark.json_storage
def test_incomplete_record_does_not_break_list(client, stored_article, caplog):
    """Запись без обязательных полей пропускается с предупреждением."""
    caplog.set_level(logging.WARNING)
    good = stored_article(title="Целая")
    storage.DATA_DIR.joinpath("partial.json").write_text(
        json.dumps({"id": str(uuid.uuid4()), "url": "https://example.com/x"}),
        encoding="utf-8",
    )

    body = client.get("/api/articles").json()

    assert [a["id"] for a in body] == [good["id"]]
    assert "partial.json" in caplog.text


@pytest.mark.json_storage
def test_unreadable_file_does_not_break_list(client, stored_article, caplog):
    """Нечитаемый файл пропускается с предупреждением так же, как повреждённый.

    Каталог с именем ``*.json`` попадает в выборку ``glob``, а попытка
    прочитать его даёт ``IsADirectoryError`` - подвид ``OSError``. Это
    воспроизводимый способ получить нечитаемый файл без ``chmod``,
    который под root ничего не запрещает и красит тесты только в CI.
    """
    caplog.set_level(logging.WARNING)
    good = stored_article(title="Целая")
    storage.DATA_DIR.joinpath("unreadable.json").mkdir()

    response = client.get("/api/articles")

    assert response.status_code == 200
    assert [a["id"] for a in response.json()] == [good["id"]]
    assert "unreadable.json" in caplog.text


@pytest.mark.json_storage
def test_corrupted_file_does_not_break_single_read(client, stored_article, caplog):
    """Битая запись отдаёт 404, а не 500, и попадает в лог."""
    caplog.set_level(logging.WARNING)
    article_id = str(uuid.uuid4())
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage.DATA_DIR.joinpath(f"{article_id}.json").write_text("{не json", encoding="utf-8")

    assert client.get(f"/api/articles/{article_id}").status_code == 404
    assert article_id in caplog.text


@pytest.mark.json_storage
def test_incomplete_record_does_not_break_single_read(client, caplog):
    """Запись без обязательных полей отдаёт 404 и попадает в лог.

    Зеркало ``test_corrupted_file_does_not_break_single_read``.
    """
    caplog.set_level(logging.WARNING)
    article_id = str(uuid.uuid4())
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage.DATA_DIR.joinpath(f"{article_id}.json").write_text(
        json.dumps({"id": article_id, "url": "https://example.com/x"}), encoding="utf-8"
    )

    assert client.get(f"/api/articles/{article_id}").status_code == 404
    assert article_id in caplog.text


# Строки, которые ``_is_valid_record`` пропускает как «url - строка», но
# которые модель ответа принять не может. Первые три роняют и сам разбор
# адреса (``parts.port``), остальные проходят разбор и падают уже на
# ``HttpUrl``: самодельная проверка на stdlib разошлась бы с моделью
# ответа в обе стороны, поэтому список смешанный намеренно. Порядок
# поэтому значим для комментария выше и меняться просто так не должен.
#
# Подпись стоит при самом случае, а не в отдельном списке ``ids``: два
# списка связывала только позиция, и вставка в середину переименовывала
# все последующие случаи молча. Подписи существуют ровно затем, чтобы
# сказать, какая граница упала, поэтому неверная стоит той самой
# диагностики, ради которой параметризация и заведена.
_UNUSABLE_URLS = [
    pytest.param("http://example.com:99999/x", id="порт вне диапазона"),
    pytest.param("http://[::1/", id="незакрытая скобка IPv6"),
    pytest.param("http://example.com:abc/x", id="порт не число"),
    pytest.param("ftp://example.com/x", id="чужая схема"),
    pytest.param("notaurl", id="строка без схемы"),
    pytest.param("", id="пустая строка"),
]


@pytest.mark.json_storage
@pytest.mark.parametrize("url", _UNUSABLE_URLS)
def test_unusable_url_does_not_break_list(client, stored_article, caplog, url):
    """Запись с непригодным адресом пропускается, а не роняет список.

    Такая запись появляется не через API: её оставляет ручная правка
    файла или импорт из чужого хранилища. Для библиотеки это тот же
    случай, что битый JSON, - одна испорченная запись, и обходиться с
    ней нужно так же, иначе отказ части становится отказом целого.

    Проверка лога обязательна по той же причине, что и у соседей: без
    неё тест зелен и с ``logger.warning``, заменённым на ``pass``.
    """
    caplog.set_level(logging.WARNING)
    good = stored_article(title="Целая")
    broken = stored_article(url=url)

    response = client.get("/api/articles")

    assert response.status_code == 200
    assert [a["id"] for a in response.json()] == [good["id"]]
    assert broken["id"] in caplog.text


@pytest.mark.json_storage
def test_unusable_url_does_not_break_export(client, stored_article):
    """Экспорт отдаёт целые записи, а не падает на одной непригодной.

    Экспорт - последняя возможность забрать данные из сломанного
    хранилища, поэтому падать на одной записи ему нельзя тем более.
    """
    good = stored_article(title="Целая")
    stored_article(url="http://example.com:99999/x")

    response = client.get("/api/export", params={"format": "json"})

    assert response.status_code == 200
    assert [a["id"] for a in response.json()] == [good["id"]]


@pytest.mark.json_storage
def test_unusable_url_does_not_break_single_record_endpoints(client, stored_article):
    """Ручки одной статьи отвечают 404, а не 500.

    К одной записи ведут три двери: чтение, добавление тега и удаление
    тега. Пятисотый ответ вместо 404 рассказывает клиенту о внутреннем
    устройстве вместо ответа на заданный вопрос.
    """
    broken = stored_article(url="http://example.com:99999/x")
    article_id = broken["id"]

    assert client.get(f"/api/articles/{article_id}").status_code == 404
    assert client.post(f"/api/articles/{article_id}/tags", json={"tag": "тег"}).status_code == 404
    assert client.delete(f"/api/articles/{article_id}/tags/тег").status_code == 404


@pytest.mark.json_storage
def test_unusable_url_does_not_block_saving_new_articles(client, stored_article, parsed_page):
    """Непригодная запись на диске не запрещает сохранять новые статьи.

    Дедупликация считает ключ от каждой
    записи в хранилище, поэтому одна испорченная строка делает
    невозможным сохранение любой новой статьи. Пользователь при этом
    не может ни узнать причину, ни обойти её из интерфейса.
    """
    stored_article(url="http://example.com:99999/x")
    parsed_page(title="Новая")

    response = client.post("/api/articles", json={"url": "https://example.com/new"})

    assert response.status_code == 201


# --- Обложка необязательна ---


def test_article_is_saved_when_cover_download_fails(client, parsed_page):
    """Не скачалась обложка - статья всё равно сохраняется."""
    parsed_page(image="https://example.com/cover.jpg", cover=None)

    response = client.post("/api/articles", json={"url": "https://example.com/a"})

    assert response.status_code == 201
    assert response.json()["image"] is None


def test_cover_is_rolled_back_when_article_write_fails(data_dir, monkeypatch):
    """Сбой записи JSON откатывает уже сохранённую обложку.

    Проверяется юнитом, а не через HTTP: ``save_article`` пробрасывает
    ``OSError`` дальше, в ``main`` его никто не ловит, и клиент получил бы
    голое исключение вместо ответа.

    Инвариант важен тем, что без отката на диске оставался бы файл
    обложки, на который никто не ссылается.
    """
    article_id = str(uuid.uuid4())
    monkeypatch.setattr(storage, "save", raising(OSError("диск заполнен")))

    with pytest.raises(OSError):
        storage.save_article(
            {"id": article_id, "url": "https://example.com/a"},
            (b"\xff\xd8binary", "image/jpeg"),
            image_ref=f"/api/articles/{article_id}/image",
        )

    assert storage.image_path(article_id) is None


def test_write_error_without_cover_is_propagated(data_dir, monkeypatch):
    """Сбой записи, когда обложки не было, просто пробрасывается наружу.

    Зеркало предыдущего теста: откатывать нечего, и попытка отката не
    должна подменить исходную ошибку своей.
    """
    monkeypatch.setattr(storage, "save", raising(OSError("диск заполнен")))

    with pytest.raises(OSError, match="диск заполнен"):
        storage.save_article(
            {"id": str(uuid.uuid4()), "url": "https://example.com/a"}, None
        )


# --- Защита от SSRF ---


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/x",
        "http://172.16.0.1/x",
        "http://192.168.1.1/x",
        "http://0.0.0.0/x",
        "http://[::1]/x",
        # Единственный адрес в таблице, который отклоняет не первая
        # клауза проверки, а вторая: у зарезервированных блоков IPv6
        # ``is_global`` истинно, и без ``is_reserved`` они считались бы
        # публичными. У IPv4 такого случая нет - там 240.0.0.0/4 уже
        # не глобальный, и вторая клауза ничего не решает.
        "http://[4000::1]/x",
    ],
    ids=[
        "localhost",
        "облачные метаданные",
        "приватная сеть 10/8",
        "приватная сеть 172.16/12",
        "домашняя сеть",
        "нулевой адрес",
        "IPv6 loopback",
        "зарезервированный блок IPv6",
    ],
)
def test_rejects_non_public_address(client, url):
    """Адрес во внутренней сети отклоняется до скачивания.

    Фикстура подмены сети здесь намеренно не используется: проверяется
    именно настоящий ``parser.parse`` с его защитой.
    """
    response = client.post("/api/articles", json={"url": url})

    assert response.status_code == 422
    assert "непубличный" in response.json()["detail"]


@pytest.mark.parametrize(
    "resolved_ip",
    ["127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0"],
    ids=[
        "loopback",
        "приватная сеть 10/8",
        "приватная сеть 172.16/12",
        "домашняя сеть",
        "облачные метаданные",
        "нулевой адрес",
    ],
)
def test_domain_resolving_to_private_address_is_rejected(resolver, resolved_ip):
    """Проверяется адрес ПОСЛЕ разрешения имени, а не текст URL.

    Домен, резолвящийся в 127.0.0.1, - классический обход наивной
    проверки: по тексту адрес выглядит публичным. Тесты на IP-литералах
    этот случай не ловят - они зелены и с проверкой вида
    ``host.startswith("127.")``.

    IPv6 сюда не входит: у ``AF_INET6`` другая форма ``sockaddr``, а
    ``::1`` уже покрыт литералом в таблице выше.
    """
    resolver(
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved_ip, 443))]
    )

    with pytest.raises(ValueError, match="непубличный"):
        parser._guard_public_url("https://совершенно-безобидный.example/")


def test_all_resolved_addresses_are_checked(resolver):
    """Приватный адрес отклоняется, даже если он у имени не первый.

    Имя резолвится сразу в несколько адресов, и порядок задаёт не
    приложение: его выбирает резолвер и меняет от запроса к запросу.
    Проверка, смотрящая только на первый ответ, отклоняет такой хост
    через раз - то есть не отклоняет вовсе, и полагаться на неё нельзя.

    Публичный адрес стоит первым намеренно: с проверкой только первого
    элемента тест обязан краснеть.
    """
    resolver(
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]
    )

    with pytest.raises(ValueError, match="непубличный"):
        parser._guard_public_url("https://совершенно-безобидный.example/")


def test_rejects_redirect_to_private_address():
    """Редирект на внутренний адрес отклоняется, и ответ на нём закрывается.

    Без этой проверки публичный хост мог бы ответить ``302`` на
    внутренний адрес и обойти защиту на входе.

    Ответ читает и закрывает ``http_error_302`` - но только после
    возврата из ``redirect_request``, то есть на отказе не закрывает
    никогда. Закрыть его - работа самого охранника, поэтому вместо
    ``None`` вторым аргументом стоит объект, у которого это можно
    спросить.
    """
    handler = parser._GuardedRedirectHandler()
    response = io.BytesIO()

    with pytest.raises(ValueError, match="непубличный"):
        handler.redirect_request(None, response, 302, "Found", {}, "http://10.0.0.1/admin")

    assert response.closed


def test_allows_redirect_to_public_address(monkeypatch):
    """Редирект на публичный адрес проверку проходит.

    Адрес - IP-литерал, поэтому настоящая ``_guard_public_url`` работает
    без обращения к DNS и подменять её не нужно. Подмена здесь и была бы
    ошибкой: тест утверждает про эту проверку и, отключив её, перестал бы
    утверждать вообще что-либо - мутант «проверка отвергает всё, включая
    публичные адреса» оставался бы зелёным.

    Подменён только вызов базового класса: настоящему ``super()`` нужны
    живые ``req`` и ``fp``, а предмет утверждения - что до него дошло.
    """
    handler = parser._GuardedRedirectHandler()
    monkeypatch.setattr(
        parser.urllib.request.HTTPRedirectHandler,
        "redirect_request",
        lambda *args, **kwargs: "запрос-редиректа",
    )

    result = handler.redirect_request(None, None, 302, "Found", {}, "http://93.184.216.34/b")

    assert result == "запрос-редиректа"


_PRIVATE_TARGET = "http://10.0.0.1/admin"
"""Адрес, на который «сайт» уводит редиректом в тесте ниже."""


def _fake_http_open(_handler, request):
    """Транспорт вместо сети: публичный адрес отвечает редиректом, приватный - страницей.

    Подменяется самый нижний слой ``urllib``, поэтому всё, что выше -
    разбор кода ответа, чтение ``Location``, решение о переходе, - в
    тесте настоящее.
    """
    url = request.get_full_url()
    headers = Message()
    if url == _PRIVATE_TARGET:
        headers["Content-Type"] = "text/html"
        body = "<html>внутренняя страница</html>".encode("utf-8")
        response = urllib.response.addinfourl(io.BytesIO(body), headers, url, 200)
        response.msg = "OK"
        return response
    headers["Location"] = _PRIVATE_TARGET
    response = urllib.response.addinfourl(io.BytesIO(b""), headers, url, 302)
    response.msg = "Found"
    return response


def test_redirect_guard_is_wired_into_the_opener(monkeypatch):
    """Скачивание не идёт по редиректу во внутреннюю сеть.

    Два теста выше проверяют сам ``_GuardedRedirectHandler`` и остаются
    зелёными, если собрать ``_opener`` без него: обработчик по умолчанию
    редирект выполнит, и запрос уйдёт на внутренний адрес. Проверять
    класс в отрыве от места, где он установлен, значит охранять деталь и
    не охранять поведение - здесь проверяется именно установка.

    Приватный адрес в подменённом транспорте отвечает страницей, а не
    отказом: без защиты тест обязан не бросить исключение вовсе, а не
    бросить какое-нибудь другое.
    """
    monkeypatch.setattr(parser.urllib.request.HTTPHandler, "http_open", _fake_http_open)

    with pytest.raises(ValueError, match="непубличный"):
        parser._fetch("http://93.184.216.34/article")


def _fake_image_response(_handler, request):
    """Транспорт, отвечающий картинкой на любой адрес.

    Нужен, чтобы отказ защиты был отличим от отказа сети: со снятой
    защитой тест обязан получить обложку, а не другое исключение.
    """
    headers = Message()
    headers["Content-Type"] = "image/png"
    response = urllib.response.addinfourl(
        io.BytesIO(b"\x89PNG\r\n"), headers, request.get_full_url(), 200
    )
    response.msg = "OK"
    return response


def test_cover_is_not_downloaded_from_private_address(monkeypatch, caplog):
    """Обложка с внутреннего адреса не скачивается, и отказ идёт от защиты.

    Адрес обложки - второй управляемый снаружи URL в системе: он
    приходит не от пользователя, а со скачанной чужой страницы, и
    ``fetch_image`` его резолвит и качает.

    Одного «вернулось None» мало: ``fetch_image`` по контракту глотает
    любой ``ValueError``, и столько же вернётся при обычном сетевом
    отказе, то есть и при снятой защите. Красным тест делает сочетание:
    транспорт отвечает картинкой, а в логе обязана оказаться причина
    отказа - «непубличный».
    """
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(parser.urllib.request.HTTPHandler, "http_open", _fake_image_response)

    result = parser.fetch_image(
        "http://169.254.169.254/latest/meta-data/", "https://example.com/article"
    )

    assert result is None
    assert "непубличный" in caplog.text


# --- Внутренний сбой не раскрывает устройство ---


def test_server_error_does_not_leak_traceback(monkeypatch):
    """Непредвиденный сбой отдаёт 500 без стека и внутренних подробностей.

    Общая фикстура ``client`` тут не годится: она поднимает исключение
    обработчика наружу, в тест, вместо того чтобы вернуть ответ, - тела
    ответа с ней просто не существует. Поэтому клиент поднимается
    локально, с ``raise_server_exceptions=False``.

    Мутант, которого ловит тест, - ``FastAPI(debug=True)``: приложение
    начинает отдавать HTML-страницу со стеком вызовов, то есть свою
    внутреннюю структуру всякому, кто сумел уронить обработчик.
    """
    monkeypatch.setattr(storage, "load_all", raising(RuntimeError("сбой хранилища")))

    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/articles")

    assert response.status_code == 500
    assert "traceback" not in response.text.lower()
    assert "RuntimeError" not in response.text
    assert "сбой хранилища" not in response.text
