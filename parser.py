"""Извлечение чистого текста статьи из веб-страницы.

Модуль оборачивает библиотеку *trafilatura*: скачивает HTML по URL,
убирает навигацию, рекламу и служебную разметку, возвращает заголовок,
метаданные и основной текст. Используется при сохранении новой статьи
через API (:func:`main.create_article`).

Страница скачивается самостоятельно (через stdlib ``urllib``), а не через
``trafilatura.fetch_url`` - это даёт доступ к статусу HTTP-ответа и
заголовкам, поэтому сбои можно различать честно (таймаут, HTTP-ошибка,
неподдерживаемый тип содержимого), а не одним общим сообщением.

``favor_recall=True`` выбран по итогам сравнения на массиве реальных
страниц: ``favor_precision`` иногда целиком выбрасывает вводный абзац
статьи, а не только инфобоксы и служебные ссылки.

Защита от SSRF: все запросы (включая редиректы) проверяются через
:func:`_guard_public_url`.

Пример::

    from parser import parse

    result = parse("https://example.com/article")
    print(result["title"], len(result["content"]))
"""

import ipaddress
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message

import trafilatura

logger = logging.getLogger(__name__)

USER_AGENT = "bkmrks/0.2.0 (+https://github.com/mochalow/bkmrks)"
"""User-Agent, под которым бот представляется сайтам."""

FETCH_TIMEOUT = 15
"""Таймаут скачивания страницы или изображения, в секундах."""

MAX_HTML_BYTES = 10 * 1024 * 1024
"""Максимальный размер HTML-страницы, которую стоит скачивать."""

MAX_IMAGE_BYTES = 5 * 1024 * 1024
"""Максимальный размер обложки статьи, которую стоит скачивать."""

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


def _guard_public_url(url: str) -> None:
    """Отклоняет URL, ведущий в приватную/служебную сеть (защита от SSRF).

    Приложение скачивает произвольный указанный пользователем адрес,
    поэтому без проверки его можно направить на внутренние ресурсы:
    ``localhost``, приватные диапазоны (``10/8``, ``192.168/16``),
    link-local (``169.254/16`` - облачный metadata-эндпоинт) и т.п.
    Хост резолвится в IP, и если хотя бы один из адресов непубличный,
    запрос не выполняется.

    Проверка применяется и к исходному адресу, и к каждому редиректу
    (см. :class:`_GuardedRedirectHandler`) - иначе публичный хост мог бы
    ответить ``302`` на внутренний адрес.

    Args:
        url: Адрес, уже приведённый к ASCII через :func:`_encode_url`.

    Raises:
        ValueError: Схема не http(s), хост отсутствует или резолвится
            в непубличный IP.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Неподдерживаемая схема URL: {url}")
    host = parts.hostname
    if not host:
        raise ValueError(f"В URL отсутствует хост: {url}")
    try:
        infos = socket.getaddrinfo(host, parts.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # DNS не разрешился - пусть падает уже само скачивание с обычной
        # сетевой ошибкой, здесь блокировать нечего.
        return
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_reserved:
            raise ValueError(f"Адрес указывает на непубличный ресурс: {url}")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Пропускает редиректы только на публичные адреса (защита от SSRF)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _guard_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_GuardedRedirectHandler)


def _encode_url(url: str) -> str:
    """Приводит IRI (не-ASCII символы в пути) к валидному URI.

    Браузеры кодируют такие адреса автоматически, а ``urllib.request`` -
    нет: URL вроде ``.../wiki/Интернет`` роняет его с ``UnicodeEncodeError``
    вместо честной ошибки скачивания.
    """
    parts = urllib.parse.urlsplit(url)
    try:
        netloc = parts.netloc.encode("ascii").decode("ascii")
    except UnicodeEncodeError:
        try:
            netloc = parts.netloc.encode("idna").decode("ascii")
        except UnicodeError as e:
            # idna-кодек падает на слишком длинных или пустых метках -
            # превращаем в честную ошибку скачивания, а не в 500.
            raise ValueError(f"Некорректное доменное имя в адресе: {url}") from e
    return urllib.parse.urlunsplit((
        parts.scheme,
        netloc,
        urllib.parse.quote(parts.path, safe="/%"),
        urllib.parse.quote(parts.query, safe="=&%"),
        urllib.parse.quote(parts.fragment, safe="%"),
    ))


def _fetch(
        url: str,
        timeout: float = FETCH_TIMEOUT,
        max_bytes: int = MAX_HTML_BYTES,
) -> tuple[bytes, str]:
    """Скачивает URL и возвращает сырые байты вместе с заголовком Content-Type.

    Используется как для HTML-страниц, так и для обложек статей. Адрес и
    каждый его редирект проверяются на принадлежность публичной сети
    (:func:`_guard_public_url`). Тело читается с ограничением ``max_bytes``:
    ответ большего размера отклоняется до того, как будет прочитан целиком,
    чтобы одна ссылка не смогла исчерпать память.

    Raises:
        ValueError: Если адрес непубличный, не удалось подключиться к сайту,
            истёк таймаут, сервер ответил кодом ошибки или ответ превысил
            допустимый размер.
    """
    encoded = _encode_url(url)
    _guard_public_url(encoded)
    request = urllib.request.Request(encoded, headers={"User-Agent": USER_AGENT})
    try:
        with _opener.open(request, timeout=timeout) as response:
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError(
                    f"Ответ превышает допустимый размер ({max_bytes} байт): {url}"
                )
            return content, response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise ValueError(f"Сайт вернул ошибку {e.code}: {url}") from e
    except TimeoutError as e:
        raise ValueError(f"Сайт не ответил за {timeout:.0f} секунд: {url}") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ValueError(f"Сайт не ответил за {timeout:.0f} секунд: {url}") from e
        raise ValueError(f"Не удалось подключиться к сайту: {url}") from e


def _strip_frontmatter(text: str) -> str:
    """Убирает YAML-заголовок, который ``extract_with_metadata`` добавляет в текст.

    Метаданные оттуда не нужны - они уже доступны как типизированные
    поля ``Document`` (``doc.author``, ``doc.date`` и т.д.).
    """
    if text.startswith("---\n"):
        return text.split("\n---\n", 1)[1]
    return text


def parse(url: str) -> dict:
    """Скачивает страницу и извлекает из неё читаемый текст и метаданные.

    Полностью полагается на :func:`_fetch` (с защитой SSRF, лимитом размера
    и обработкой ошибок). Далее использует ``trafilatura.extract_with_metadata``
    с ``favor_recall=True``.

    Args:
        url: Полный HTTP(S)-адрес страницы.

    Returns:
        Словарь с ключами:

        * ``title`` - заголовок статьи или ``None``.
        * ``content`` - очищенный текст статьи (plain text с переносами строк
          между абзацами). Используется для чтения, поиска, превью и оценки
          времени чтения.
        * ``author`` - автор статьи или ``None``.
        * ``date`` - дата публикации (строка в формате, который вернула
          trafilatura) или ``None``.
        * ``description`` - краткое описание страницы (обычно из
          ``meta description``) или ``None``.
        * ``sitename`` - название сайта-источника или ``None``.
        * ``image`` - URL обложки статьи (обычно из ``og:image``,
          может быть относительным) или ``None``.

    Raises:
        ValueError: Если страницу не удалось скачать, её тип содержимого
            не похож на HTML, или из HTML не получилось извлечь текст статьи.
    """
    content, content_type = _fetch(url)

    mime = Message()
    mime["content-type"] = content_type
    declared_type = mime.get_content_type()
    if content_type and declared_type not in _HTML_CONTENT_TYPES:
        raise ValueError(
            f"Страница имеет неподдерживаемый тип содержимого "
            f"({declared_type}): {url}"
        )
    charset = mime.get_param("charset", "utf-8") if content_type else "utf-8"
    html = content.decode(charset, errors="replace")

    doc = trafilatura.extract_with_metadata(
        html, url=url,
        include_comments=False, include_links=True, favor_recall=True,
    )
    if doc is None or not doc.text:
        raise ValueError(f"Не удалось извлечь текст статьи: {url}")

    return {
        "title": doc.title,
        "content": _strip_frontmatter(doc.text),
        "author": doc.author,
        "date": doc.date,
        "description": doc.description,
        "sitename": doc.sitename,
        "image": doc.image,
    }


def fetch_image(
        image_url: str, page_url: str, timeout: float = FETCH_TIMEOUT
) -> tuple[bytes, str] | None:
    """Скачивает обложку статьи. Никогда не бросает исключений.

    Обложка - необязательное дополнение к статье, поэтому любая причина
    неудачи (сеть, неподдерживаемый тип содержимого, слишком большой файл)
    приводит к ``None``, а не к ошибке: отсутствие обложки не должно
    мешать сохранению самой статьи.

    Args:
        image_url: URL обложки из метаданных страницы (``og:image`` и
            подобные - часто относительный).
        page_url: URL самой статьи, относительно которого разрешается
            относительный ``image_url``.

    Returns:
        Кортеж из сырых байт изображения и его MIME-типа, либо ``None``.
    """
    resolved = urllib.parse.urljoin(page_url, image_url)
    try:
        content, content_type = _fetch(resolved, timeout=timeout, max_bytes=MAX_IMAGE_BYTES)
    except ValueError as e:
        logger.warning("Не удалось скачать обложку %s: %s", resolved, e)
        return None

    mime = Message()
    mime["content-type"] = content_type
    declared_type = mime.get_content_type()
    if not declared_type.startswith("image/"):
        logger.warning(
            "Обложка %s имеет неожиданный тип содержимого (%s)",
            resolved, declared_type,
        )
        return None

    return content, declared_type
