"""Фикстуры тестов.

Единственное место, где тесты знают про файловое хранилище. При переезде
на PostgreSQL меняется только этот файл: сами
тесты работают через HTTP-контракт и остаются как есть.

Сеть в тестах не используется нигде: ``parser.parse`` подменяется
фикстурой :func:`parsed_page`, а тесты защиты от SSRF работают на IP-литералах,
которые не требуют обращения к DNS.
"""

import socket
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
import parser
import storage


def raising(error):
    """Заглушка, которая на любой вызов поднимает ``error``.

    Функция модуля, а не фикстура: состояния у неё нет и разбирать после
    теста нечего, а фикстура заставила бы четыре теста объявлять лишний
    параметр. Имя ``raising``, а не ``raises``, намеренно: в тех же
    файлах несколькими строками ниже стоит ``pytest.raises``, и два
    похожих имени с противоположным смыслом - ловушка.

    Args:
        error: Исключение, которое поднимает заглушка.

    Returns:
        Функцию, принимающую любые аргументы и поднимающую ``error``.
    """
    def _raise(*args, **kwargs):
        raise error

    return _raise


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Изолирует хранилище: тесты не видят и не трогают реальные данные.

    Подмена работает потому, что :mod:`storage` читает ``DATA_DIR`` и
    ``IMAGES_DIR`` как глобалы модуля в момент вызова, а не захватывает
    их значения при импорте.

    ``autouse`` здесь осознанный: без подмены ``storage.DATA_DIR``
    указывает на ``<проект>/data/articles``, то есть на настоящую
    библиотеку пользователя. Тесты, которым хранилище нужно, продолжают
    запрашивать фикстуру явно: параметр документирует зависимость.

    Returns:
        Корневой каталог, внутри которого лежат ``articles`` и ``images``.
    """
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "articles")
    monkeypatch.setattr(storage, "IMAGES_DIR", tmp_path / "images")
    return tmp_path


@pytest.fixture
def client(data_dir):
    """HTTP-клиент поверх приложения с изолированным хранилищем."""
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def parsed_page(monkeypatch):
    """Подменяет сеть: ``parser.parse`` возвращает готовый словарь.

    Перехват вешается на модуль :mod:`parser`, а не на :mod:`main`, потому
    что ``main`` делает ``import parser`` и ищет атрибут ``parse`` в момент
    вызова - подмена атрибута модуля этот вызов и перехватывает.

    Returns:
        Функцию-настройщик. Именованный аргумент ``cover`` задаёт, что
        вернёт ``parser.fetch_image`` (кортеж «байты, MIME-тип» или
        ``None``); остальные именованные аргументы переопределяют поля
        разобранной страницы.
    """

    def configure(cover=None, **overrides):
        parsed = {
            "title": "Тестовая статья",
            "content": "Первый абзац.\n\nВторой абзац.",
            "author": None,
            "date": None,
            "description": None,
            "sitename": None,
            "image": None,
        } | overrides
        monkeypatch.setattr(parser, "parse", lambda url: dict(parsed))
        monkeypatch.setattr(parser, "fetch_image", lambda *args, **kwargs: cover)
        return parsed

    return configure


@pytest.fixture
def resolver(monkeypatch):
    """Подменяет разрешение имён внутри :mod:`parser`, не трогая общий ``socket``.

    Подменяется имя ``socket`` в модуле, а не атрибут самого модуля.
    ``parser.socket`` - это и есть стандартный ``socket``, один на весь
    процесс, поэтому ``setattr(parser.socket, "getaddrinfo", ...)``
    заменял бы разрешение имён всем: и плагину отчётности, и фоновому
    потоку тестового сервера, - а падение приписали бы коду, который к
    тесту отношения не имеет.

    Прокладка отдаёт всё, чем :mod:`parser` пользуется: сам
    ``getaddrinfo``, константу ``SOCK_STREAM`` из его вызова и
    ``gaierror`` из обработчика рядом. Неполная прокладка покрасила бы
    тест по причине, которой он не проверяет.

    Returns:
        Функцию-настройщик: принимает подставной ``getaddrinfo``.
    """

    def configure(getaddrinfo):
        monkeypatch.setattr(
            parser,
            "socket",
            SimpleNamespace(
                getaddrinfo=getaddrinfo,
                SOCK_STREAM=socket.SOCK_STREAM,
                gaierror=socket.gaierror,
            ),
        )

    return configure


@pytest.fixture
def storage_in_worst_order(monkeypatch):
    """Заставляет хранилище отдавать статьи в заведомо неверном порядке.

    Порядок ``storage.load_all`` задаёт обход каталога файловой системой и
    от прогона к прогону он разный. Тест сортировки, молча на него
    опирающийся, проходит по жребию.

    Фикстура убирает жребий: хранилище всегда отдаёт статьи по
    возрастанию времени, то есть ровно наоборот тому, что обязан вернуть
    маршрут. Пропавшая сортировка видна всегда.

    Подменяется вход, а не предмет утверждения: сортировку в ``main``
    никто не трогает, ей просто подают заведомо худшие данные.
    """
    real_load_all = storage.load_all
    monkeypatch.setattr(
        storage, "load_all", lambda: sorted(real_load_all(), key=lambda a: a["saved_at"])
    )


@pytest.fixture
def article_record():
    """Строит запись статьи, ничего не сохраняя.

    Одна форма записи на весь набор. Сама по себе
    запись ничего не знает про диск, поэтому годится и тем тестам,
    которые сохраняют её сами.

    Returns:
        Функцию-фабрику. ``saved_at`` сдвигается на минуту вперёд с
        каждым вызовом, а адрес получает свой номер: порядок и
        различимость записей заданы явно, а не жребием.
    """
    built = []

    def build(**overrides):
        saved_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc) + timedelta(
            minutes=len(built)
        )
        record = {
            "id": str(uuid.uuid4()),
            "url": f"https://example.com/article-{len(built)}",
            "saved_at": saved_at.isoformat().replace("+00:00", "Z"),
            "title": "Тестовая статья",
            "content": "Первый абзац.\n\nВторой абзац.",
            "author": None,
            "date": None,
            "description": None,
            "sitename": None,
            "image": None,
            "tags": [],
        } | overrides
        built.append(record)
        return record

    return build


@pytest.fixture
def stored_article(data_dir, article_record):
    """Кладёт статью в хранилище напрямую, минуя API.

    Нужна там, где важен порядок или точное содержимое записи.
    Через API этого добиться нельзя: ``saved_at`` там имеет разрешение в
    одну секунду, поэтому статьи, созданные подряд, получают одинаковую
    метку времени, а их взаимный порядок начинает определять порядок
    обхода каталога файловой системой.

    Время пишется в том же виде, что и приложение: ``model_dump(mode="json")``
    у pydantic даёт ``...T12:00:00Z``, а не ``+00:00``. Разница не
    косметическая - ``list_articles`` сортирует по строке ``saved_at``, и
    такая сортировка верна ровно до тех пор, пока все записи оформлены
    одинаково.

    Returns:
        Функцию-фабрику. Возвращает словарь сохранённой статьи; ``saved_at``
        по умолчанию сдвигается на минуту вперёд с каждым вызовом, чтобы
        порядок был задан явно и воспроизводимо.
    """
    def create(**overrides):
        article = article_record(**overrides)
        storage.save(article)
        return article

    return create
