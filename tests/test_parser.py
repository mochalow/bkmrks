"""Тесты извлечения текста и скачивания страниц.

Сеть не используется: скачивание подменяется на уровне ``_fetch`` или
``_opener``, а адреса задаются IP-литералами - ``socket.getaddrinfo``
отвечает по ним без обращения к DNS.

Публичный литерал ``93.184.216.34`` выбран потому, что диапазоны,
зарезервированные под документацию (``203.0.113.0/24``), сама проверка
считает непубличными и отклоняет.
"""

import io
import logging
import urllib.error

import pytest

import parser

PUBLIC_URL = "http://93.184.216.34/article"

ARTICLE_HTML = """
<!doctype html>
<html lang="ru">
<head>
    <title>Заголовок страницы</title>
    <meta name="author" content="Иван Иванов">
    <meta name="description" content="Краткое описание страницы.">
    <meta property="og:site_name" content="Пример СМИ">
    <meta property="og:image" content="https://example.com/cover.jpg">
</head>
<body>
<nav><a href="/">Главная</a><a href="/about">О нас</a></nav>
<article>
    <h1>Заголовок страницы</h1>
    <p>Первый абзац статьи, в котором достаточно текста, чтобы алгоритм
    извлечения признал его основным содержимым страницы, а не служебной
    разметкой вокруг него.</p>
    <p>Второй абзац продолжает мысль первого и добавляет ещё немного
    текста для надёжности извлечения.</p>
</article>
<footer>Все права защищены</footer>
</body>
</html>
"""


COMMENTED_HTML = """
<!doctype html>
<html lang="ru">
<head><title>Заголовок страницы</title></head>
<body>
<article>
    <h1>Заголовок страницы</h1>
    <p>Первый абзац статьи, в котором достаточно текста, чтобы алгоритм
    извлечения признал его основным содержимым страницы, а не служебной
    разметкой вокруг него.</p>
    <p>Второй абзац со <a href="https://example.com/source">ссылкой на источник</a>
    продолжает мысль и добавляет ещё немного текста для надёжности.</p>
</article>
<div class="comments">
    <p>КОММЕНТАРИЙ ЧИТАТЕЛЯ, тоже довольно длинный текст, чтобы его нельзя
    было отбросить как короткий шум разметки.</p>
</div>
</body>
</html>
"""
"""Страница с блоком комментариев и ссылкой внутри статьи.

Отдельно от :data:`ARTICLE_HTML`: та проверяет извлечение как таковое, а
эта - настройки, с которыми вызывается trafilatura.
"""


class _FakeResponse:
    """Минимальная замена ответа ``urlopen`` для тестов ``_fetch``."""

    def __init__(self, body: bytes, content_type: str = "text/html"):
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size):
        return self._body[:size]


# --- parse ---


def test_extracts_text_and_metadata(monkeypatch):
    """Из HTML извлекаются текст статьи и метаданные, навигация отбрасывается."""
    monkeypatch.setattr(
        parser, "_fetch", lambda url: (ARTICLE_HTML.encode("utf-8"), "text/html; charset=utf-8")
    )

    result = parser.parse(PUBLIC_URL)

    assert result["title"] == "Заголовок страницы"
    assert "Первый абзац статьи" in result["content"]
    assert "Все права защищены" not in result["content"]
    assert result["author"] == "Иван Иванов"
    assert result["description"] == "Краткое описание страницы."
    assert result["sitename"] == "Пример СМИ"
    assert result["image"] == "https://example.com/cover.jpg"


def test_rejects_non_html_content_type(monkeypatch):
    """Не-HTML страница отклоняется с указанием фактического типа."""
    monkeypatch.setattr(parser, "_fetch", lambda url: (b"%PDF-1.4", "application/pdf"))

    with pytest.raises(ValueError, match="неподдерживаемый тип содержимого"):
        parser.parse(PUBLIC_URL)


def test_rejects_page_without_article_text(monkeypatch):
    """Страница без основного содержимого - честная ошибка, а не пустая статья."""
    monkeypatch.setattr(parser, "_fetch", lambda url: (b"<html><body></body></html>", "text/html"))

    with pytest.raises(ValueError, match="Не удалось извлечь текст"):
        parser.parse(PUBLIC_URL)


def test_missing_content_type_falls_back_to_html(monkeypatch):
    """Ответ без ``Content-Type`` считается HTML в кодировке utf-8."""
    monkeypatch.setattr(parser, "_fetch", lambda url: (ARTICLE_HTML.encode("utf-8"), ""))

    assert "Первый абзац статьи" in parser.parse(PUBLIC_URL)["content"]


def test_comments_do_not_land_in_article_text(monkeypatch):
    """Комментарии читателей в текст статьи не попадают.

    ``include_comments=False`` - настройка, а не поведение библиотеки по
    умолчанию, и переворачивается она незаметно: обсуждение под статьёй
    попало бы и в чтение, и в поиск, и в оценку времени чтения.
    """
    monkeypatch.setattr(
        parser, "_fetch", lambda url: (COMMENTED_HTML.encode("utf-8"), "text/html")
    )

    content = parser.parse(PUBLIC_URL)["content"]

    assert "Первый абзац статьи" in content
    assert "КОММЕНТАРИЙ ЧИТАТЕЛЯ" not in content


def test_link_targets_are_kept_in_article_text(monkeypatch):
    """Адрес ссылки сохраняется в тексте статьи.

    ``include_links=True`` - тоже осознанная настройка: читатель видит,
    куда вела ссылка, даже когда разметки уже нет. Тест фиксирует
    наблюдение, а не желание: trafilatura отдаёт такие ссылки в виде
    ``[текст](адрес)``, и именно в этом виде они уезжают в ``content``.
    """
    monkeypatch.setattr(
        parser, "_fetch", lambda url: (COMMENTED_HTML.encode("utf-8"), "text/html")
    )

    content = parser.parse(PUBLIC_URL)["content"]

    assert "ссылкой на источник" in content
    assert "https://example.com/source" in content


def test_strips_metadata_frontmatter():
    """YAML-заголовок, добавленный извлекателем, в текст статьи не попадает."""
    assert parser._strip_frontmatter("---\ntitle: X\n---\nТекст.") == "Текст."
    assert parser._strip_frontmatter("Текст без заголовка.") == "Текст без заголовка."


def test_strip_frontmatter_keeps_horizontal_rules_in_body():
    """Черта внутри статьи не принимается за конец заголовка метаданных.

    Убирается ровно первый блок: ``maxsplit=1``. С большим значением
    статья обрезалась бы на первой же горизонтальной черте в тексте, и
    потеря была бы молчаливой - ни ошибки, ни пустого результата, просто
    половина статьи.
    """
    text = "---\ntitle: X\n---\nПервая часть.\n---\nВторая часть."

    assert parser._strip_frontmatter(text) == "Первая часть.\n---\nВторая часть."


# --- _encode_url ---


def test_encodes_non_ascii_path():
    """Кириллица в пути кодируется - иначе ``urllib`` падает на UnicodeEncodeError."""
    encoded = parser._encode_url("https://example.com/wiki/Интернет")

    assert encoded == "https://example.com/wiki/%D0%98%D0%BD%D1%82%D0%B5%D1%80%D0%BD%D0%B5%D1%82"


def test_encodes_non_ascii_host_as_idna():
    """Кириллический домен переводится в punycode."""
    assert parser._encode_url("https://пример.рф/a") == "https://xn--e1afmkfd.xn--p1ai/a"


def test_rejects_malformed_domain():
    """Домен, который не кодируется в IDNA, даёт честную ошибку, а не 500.

    Кодек ``idna`` падает на пустой или слишком длинной метке; без
    перехвата это был бы ``UnicodeError`` и ответ 500 вместо 422.
    """
    with pytest.raises(ValueError, match="Некорректное доменное имя"):
        parser._encode_url("https://пример..рф/x")


def test_keeps_already_encoded_url_intact():
    """Уже закодированный адрес не кодируется повторно."""
    url = "https://example.com/a%20b?x=1&y=2"

    assert parser._encode_url(url) == url


# --- _guard_public_url ---


def test_guard_rejects_unsupported_scheme():
    """Схема не http(s) отклоняется до любых сетевых действий."""
    with pytest.raises(ValueError, match="Неподдерживаемая схема"):
        parser._guard_public_url("ftp://93.184.216.34/x")


def test_guard_rejects_url_without_host():
    """Адрес без хоста отклоняется."""
    with pytest.raises(ValueError, match="отсутствует хост"):
        parser._guard_public_url("http:///path")


def test_guard_passes_when_dns_fails(resolver):
    """Неразрешимое имя пропускается: блокировать нечего, упадёт скачивание.

    Иначе временный сбой DNS выглядел бы для пользователя как обвинение
    в попытке достучаться до внутренней сети.
    """
    def fail(*args, **kwargs):
        raise parser.socket.gaierror("имя не разрешается")

    resolver(fail)

    parser._guard_public_url("https://example.com/a")


def test_guard_allows_public_address():
    """Публичный адрес проходит проверку."""
    parser._guard_public_url(PUBLIC_URL)


# --- _fetch ---


def test_fetch_returns_body_and_content_type(monkeypatch):
    """Успешное скачивание отдаёт байты и заголовок типа содержимого."""
    monkeypatch.setattr(
        parser._opener, "open", lambda request, timeout: _FakeResponse(b"<html>", "text/html")
    )

    assert parser._fetch(PUBLIC_URL) == (b"<html>", "text/html")


@pytest.mark.parametrize("size", [9, 10], ids=["меньше лимита", "ровно лимит"])
def test_fetch_accepts_response_within_limit(monkeypatch, size):
    """Ответ размером до лимита включительно скачивается целиком."""
    monkeypatch.setattr(
        parser._opener, "open", lambda request, timeout: _FakeResponse(b"x" * size)
    )

    content, _ = parser._fetch(PUBLIC_URL, max_bytes=10)

    assert content == b"x" * size


@pytest.mark.parametrize("size", [11, 100], ids=["на байт больше лимита", "много больше"])
def test_fetch_rejects_oversized_response(monkeypatch, size):
    """Ответ больше лимита отклоняется, не дочитываясь целиком в память."""
    monkeypatch.setattr(
        parser._opener, "open", lambda request, timeout: _FakeResponse(b"x" * size)
    )

    with pytest.raises(ValueError, match="превышает допустимый размер"):
        parser._fetch(PUBLIC_URL, max_bytes=10)


def test_fetch_reports_http_error_with_code(monkeypatch):
    """Код ответа сайта попадает в сообщение об ошибке."""

    def raise_http_error(request, timeout):
        raise urllib.error.HTTPError(PUBLIC_URL, 403, "Forbidden", {}, None)

    monkeypatch.setattr(parser._opener, "open", raise_http_error)

    with pytest.raises(ValueError, match="Сайт вернул ошибку 403"):
        parser._fetch(PUBLIC_URL)


def test_fetch_closes_response_of_http_error(monkeypatch):
    """Ответ с кодом ошибки закрывается сразу, а не ждёт сборщика мусора.

    ``HTTPError`` - не только исключение, но и файловый объект поверх
    соединения. Оно уезжает наверх в ``__cause__`` у ``ValueError``,
    поэтому незакрытый ответ держит сокет всю обработку запроса.

    Ссылка ``error`` держится до конца теста намеренно: без неё ответ
    закрывает сборщик мусора, и проверка становится тавтологией.
    """
    body = io.BytesIO(b"<html>403</html>")
    error = urllib.error.HTTPError(PUBLIC_URL, 403, "Forbidden", {}, body)

    def raise_http_error(request, timeout):
        raise error

    monkeypatch.setattr(parser._opener, "open", raise_http_error)

    with pytest.raises(ValueError, match="Сайт вернул ошибку 403"):
        parser._fetch(PUBLIC_URL)

    assert body.closed, "ответ остался открытым до сборки мусора"


def test_fetch_reports_timeout_with_seconds(monkeypatch):
    """Таймаут отличается от других сбоев и называет число секунд."""

    def raise_timeout(request, timeout):
        raise TimeoutError

    monkeypatch.setattr(parser._opener, "open", raise_timeout)

    with pytest.raises(ValueError, match="не ответил за 15 секунд"):
        parser._fetch(PUBLIC_URL)


def test_fetch_reports_timeout_wrapped_in_url_error(monkeypatch):
    """Таймаут, завёрнутый в URLError, распознаётся как таймаут."""

    def raise_wrapped(request, timeout):
        raise urllib.error.URLError(TimeoutError())

    monkeypatch.setattr(parser._opener, "open", raise_wrapped)

    with pytest.raises(ValueError, match="не ответил за"):
        parser._fetch(PUBLIC_URL)


def test_fetch_reports_connection_failure(monkeypatch):
    """Прочие сетевые сбои дают отдельное понятное сообщение."""

    def raise_url_error(request, timeout):
        raise urllib.error.URLError("соединение отклонено")

    monkeypatch.setattr(parser._opener, "open", raise_url_error)

    with pytest.raises(ValueError, match="Не удалось подключиться"):
        parser._fetch(PUBLIC_URL)


# Пара тестов на одном и том же теле в MAX_IMAGE_BYTES + 1 байт: обложке
# оно велико, странице - нет. По отдельности каждый тест зелен и с одним
# лимитом вместо двух; вместе они доказывают, что лимиты различены.
#
# Тело занимает около 5 МБ, а _FakeResponse.read отдаёт срез, то есть копию.
# На двух тестах это незаметно, размножать приём не стоит.


def test_fetch_reads_page_over_image_limit(monkeypatch):
    """Страница крупнее лимита обложки скачивается: у HTML лимит свой."""
    body = b"x" * (parser.MAX_IMAGE_BYTES + 1)
    monkeypatch.setattr(
        parser._opener, "open", lambda request, timeout: _FakeResponse(body, "text/html")
    )

    assert parser._fetch(PUBLIC_URL) == (body, "text/html")


def test_fetch_image_rejects_body_over_image_limit(monkeypatch, caplog):
    """Обложка того же размера отклоняется: лимит картинки меньше."""
    caplog.set_level(logging.WARNING)
    body = b"x" * (parser.MAX_IMAGE_BYTES + 1)
    monkeypatch.setattr(
        parser._opener, "open", lambda request, timeout: _FakeResponse(body, "image/jpeg")
    )

    assert parser.fetch_image("/cover.jpg", "http://93.184.216.34/a") is None
    assert "превышает допустимый размер" in caplog.text


# --- fetch_image ---


def test_fetch_image_returns_bytes_and_type(monkeypatch):
    """Обложка возвращается вместе с определённым MIME-типом."""
    monkeypatch.setattr(
        parser, "_fetch", lambda url, timeout, max_bytes: (b"\xff\xd8", "image/jpeg; charset=binary")
    )

    assert parser.fetch_image("/cover.jpg", "http://93.184.216.34/a") == (b"\xff\xd8", "image/jpeg")


def test_fetch_image_resolves_relative_url(monkeypatch):
    """Относительный адрес обложки разрешается относительно страницы."""
    seen = {}

    def fake_fetch(url, timeout, max_bytes):
        seen["url"] = url
        return b"\xff\xd8", "image/jpeg"

    monkeypatch.setattr(parser, "_fetch", fake_fetch)

    parser.fetch_image("/img/cover.jpg", "http://93.184.216.34/blog/a")

    assert seen["url"] == "http://93.184.216.34/img/cover.jpg"


def test_fetch_image_swallows_download_error(monkeypatch, caplog):
    """Сбой скачивания обложки не бросается наружу, но и не молчит.

    Обложка необязательна, поэтому её
    отсутствие ничем наружу не проявляется, и запись в лог -
    единственный след того, почему у статьи нет картинки. Без проверки
    тест зелен и с ``logger.warning``, заменённым на ``pass``.
    """
    caplog.set_level(logging.WARNING)

    def raise_value_error(url, timeout, max_bytes):
        raise ValueError("Сайт не ответил")

    monkeypatch.setattr(parser, "_fetch", raise_value_error)

    assert parser.fetch_image("/cover.jpg", "http://93.184.216.34/a") is None
    assert "Сайт не ответил" in caplog.text
    assert "93.184.216.34/cover.jpg" in caplog.text


def test_fetch_image_rejects_non_image_content(monkeypatch, caplog):
    """Ответ не-изображением отбрасывается и называется в логе.

    Тип содержимого попадает в запись: без него причина «обложки нет»
    неотличима от сетевого сбоя, а лечатся эти два случая по-разному.
    """
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(
        parser, "_fetch", lambda url, timeout, max_bytes: (b"<html>", "text/html")
    )

    assert parser.fetch_image("/cover.jpg", "http://93.184.216.34/a") is None
    assert "text/html" in caplog.text
