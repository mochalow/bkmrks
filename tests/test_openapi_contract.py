"""Сверка опубликованной схемы OpenAPI с тем, что приложение делает.

Коды ответов в ``responses={...}`` - не комментарий, а контракт: по нему
пишут клиентов. При этом на поведение он
не влияет никак, поэтому разойтись с приложением может молча.

Проверки смотрят в разные стороны:

* :func:`test_returned_status_is_documented` - от реальности к
  документации: код, который маршрут действительно вернул, объявлен.
* :func:`test_published_responses_are_frozen` - от документации к
  реальности: набор объявленных кодов не растёт молча.
* :func:`test_published_set_of_routes_is_frozen` - то же про сам список
  маршрутов.
* :func:`test_article_schema_matches_the_frozen_record` и
  :func:`test_article_body_carries_exactly_the_frozen_fields` - про
  полезную нагрузку.

Оговорка: часть ``422`` в схеме добавляет сам
FastAPI за валидацию параметров, и у ``GET /api/articles`` такой код
недостижим - параметры там строковые и невалидными не бывают. Вторая
проверка фиксирует набор как он есть, а не утверждает достижимость
каждого кода.
"""

import json
import uuid
from pathlib import Path

import pytest

import main

# --- От реальности к документации ---

_SCENARIOS = [
    (lambda c, a: c.post("/api/articles", json={"url": "https://example.com/другая"}),
     "post", "/api/articles", 201),
    (lambda c, a: c.post("/api/articles", json={"url": "https://example.com/a"}),
     "post", "/api/articles", 200),
    (lambda c, a: c.post("/api/articles", json={"url": "не адрес"}),
     "post", "/api/articles", 422),
    (lambda c, a: c.get("/api/articles"), "get", "/api/articles", 200),
    (lambda c, a: c.get("/api/export"), "get", "/api/export", 200),
    (lambda c, a: c.get("/api/export", params={"format": "xml"}), "get", "/api/export", 422),
    (lambda c, a: c.get(f"/api/articles/{a}"), "get", "/api/articles/{article_id}", 200),
    (lambda c, a: c.get(f"/api/articles/{uuid.uuid4()}"),
     "get", "/api/articles/{article_id}", 404),
    (lambda c, a: c.get(f"/api/articles/{a}/image"),
     "get", "/api/articles/{article_id}/image", 404),
    (lambda c, a: c.delete(f"/api/articles/{a}"), "delete", "/api/articles/{article_id}", 204),
    (lambda c, a: c.delete(f"/api/articles/{uuid.uuid4()}"),
     "delete", "/api/articles/{article_id}", 404),
    (lambda c, a: c.get("/api/tags"), "get", "/api/tags", 200),
    (lambda c, a: c.post(f"/api/articles/{a}/tags", json={"tag": "python"}),
     "post", "/api/articles/{article_id}/tags", 200),
    (lambda c, a: c.post(f"/api/articles/{uuid.uuid4()}/tags", json={"tag": "python"}),
     "post", "/api/articles/{article_id}/tags", 404),
    (lambda c, a: c.post(f"/api/articles/{a}/tags", json={"tag": "a/b"}),
     "post", "/api/articles/{article_id}/tags", 422),
    (lambda c, a: c.delete(f"/api/articles/{a}/tags/python"),
     "delete", "/api/articles/{article_id}/tags/{tag}", 200),
    (lambda c, a: c.delete(f"/api/articles/{uuid.uuid4()}/tags/python"),
     "delete", "/api/articles/{article_id}/tags/{tag}", 404),
    (lambda c, a: c.get("/api/health"), "get", "/api/health", 200),
]


@pytest.mark.parametrize(
    "request_, method, path, expected",
    _SCENARIOS,
    ids=[
        "создание - 201", "повторное создание - 200", "не адрес - 422",
        "список - 200", "экспорт - 200", "неизвестный формат - 422",
        "чтение статьи - 200", "чужой id - 404", "нет обложки - 404",
        "удаление - 204", "удаление чужого id - 404", "теги - 200",
        "добавление тега - 200", "тег к чужой статье - 404", "тег со слэшем - 422",
        "удаление тега - 200", "удаление тега у чужой статьи - 404", "health - 200",
    ],
)
def test_returned_status_is_documented(client, parsed_page, request_, method, path, expected):
    """Код, который маршрут действительно вернул, объявлен в схеме.

    Два утверждения намеренно стоят рядом: первое ловит расхождение
    приложения с ожиданием, второе - расхождение схемы с приложением.
    Порознь они проверяли бы каждое свою половину и не заметили бы, что
    половины разъехались.
    """
    parsed_page()
    article_id = client.post("/api/articles", json={"url": "https://example.com/a"}).json()["id"]

    response = request_(client, article_id)

    assert response.status_code == expected
    documented = main.app.openapi()["paths"][path][method]["responses"]
    assert str(expected) in documented


# --- От документации к реальности ---

_PUBLISHED = [
    ("post", "/api/articles", {"200", "201", "422"}),
    ("get", "/api/articles", {"200", "422"}),
    ("get", "/api/export", {"200", "422"}),
    ("get", "/api/articles/{article_id}", {"200", "404", "422"}),
    ("delete", "/api/articles/{article_id}", {"204", "404", "422"}),
    ("get", "/api/articles/{article_id}/image", {"200", "404", "422"}),
    ("get", "/api/tags", {"200"}),
    ("post", "/api/articles/{article_id}/tags", {"200", "404", "422"}),
    ("delete", "/api/articles/{article_id}/tags/{tag}", {"200", "404", "422"}),
    ("get", "/api/health", {"200"}),
]


@pytest.mark.parametrize(
    "method, path, expected",
    _PUBLISHED,
    ids=[f"{m.upper()} {p}" for m, p, _ in _PUBLISHED],
)
def test_published_responses_are_frozen(method, path, expected):
    """Набор объявленных кодов у маршрута не меняется молча.

    Равенство, а не вхождение: лишний объявленный код - такой же дефект
    документации, как пропущенный.

    Тест умышленно краснеет на любом изменении контракта - он на то и
    поставлен.
    """
    assert set(main.app.openapi()["paths"][path][method]["responses"]) == expected


def test_published_set_of_routes_is_frozen():
    """Список маршрутов не растёт молча.

    Проверка выше морозит коды у каждого перечисленного маршрута, но не
    сам перечень: она параметризована по :data:`_PUBLISHED`, поэтому
    маршрут, которого в списке нет, просто не попадает в параметризацию.
    Ни один сценарий его тоже не зовёт. Новый эндпоинт таким образом
    добавлялся в замороженный контракт при двух зелёных тестах.

    Сравнивается полный список.
    """
    published = sorted(
        (method, path)
        for path, operations in main.app.openapi()["paths"].items()
        for method in operations
    )

    assert published == sorted((method, path) for method, path, _ in _PUBLISHED)


# --- Запись Article ---

_ARTICLE_FIELDS = (
    "id", "url", "saved_at", "title", "content", "author",
    "date", "description", "sitename", "image", "tags",
)

_ARTICLE_REQUIRED = {"id", "url", "saved_at"}
_ARTICLE_NULLABLE = {"title", "content", "author", "date", "description", "sitename", "image"}


def test_article_schema_matches_the_frozen_record():
    """Схема ``Article``.

    Источник истины - таблица, а не модель: схему FastAPI выводит из
    модели, поэтому сверка схемы с моделью доказывала бы тождество самому
    себе. Переименование поля меняет обе стороны разом и осталось бы
    незамеченным - ``savedAt`` вместо ``saved_at``.

    Заморожены имена, обязательность и право быть пустым. Последнее -
    потому что расширение ``tags`` до ``list[str] | None`` не трогает ни
    имён, ни обязательности (умолчание у поля есть в обоих случаях), а
    контракт меняет: клиент, обещавший себе список, получает ``null``.
    """
    schema = main.app.openapi()["components"]["schemas"]["Article"]
    nullable = {
        name
        for name, field in schema["properties"].items()
        if {"type": "null"} in field.get("anyOf", [])
    }

    assert set(schema["properties"]) == set(_ARTICLE_FIELDS)
    assert set(schema["required"]) == _ARTICLE_REQUIRED
    assert nullable == _ARTICLE_NULLABLE


_ARTICLE_BODIES = [
    lambda c, a: c.post("/api/articles", json={"url": "https://example.com/третья"}).json(),
    lambda c, a: c.get("/api/articles").json()[0],
    lambda c, a: c.get(f"/api/articles/{a}").json(),
    lambda c, a: c.post(f"/api/articles/{a}/tags", json={"tag": "python"}).json(),
    lambda c, a: c.delete(f"/api/articles/{a}/tags/python").json(),
    lambda c, a: c.get("/api/export", params={"format": "json"}).json()[0],
]


@pytest.mark.parametrize(
    "request_",
    _ARTICLE_BODIES,
    ids=["создание", "список", "чтение", "добавление тега", "удаление тега", "экспорт"],
)
def test_article_body_carries_exactly_the_frozen_fields(client, parsed_page, request_):
    """Тело ответа несёт ровно те поля, что объявлены, - у каждого маршрута.

    Схема выше говорит, что обещано; здесь проверяется, что отдано.

    Там, где обработчик объявлен как ``-> Article``,
    тело собирает сама модель, и утверждение повторяет
    предыдущее. Самостоятельным оно становится там, где тело собрано
    руками, - сегодня это экспорт (``main.export_articles`` без
    return-аннотации, ``model_dump`` вызывается напрямую).
    """
    parsed_page()
    article_id = client.post("/api/articles", json={"url": "https://example.com/a"}).json()["id"]

    assert set(request_(client, article_id)) == set(_ARTICLE_FIELDS)


# --- Стык с браузерным клиентом ---

_PATHS_FIXTURE = Path(__file__).parent / "fixtures" / "api-paths.json"
"""Перечень путей схемы, который читает и клиентский тест.

Файл порождён из ``main.app.openapi()``, а не написан рукой: третьей
копией контракта он не становится, он её проекция.
"""

_REGENERATE = (
    '.venv/bin/python -c "import json, pathlib, main; '
    "pathlib.Path('tests/fixtures/api-paths.json').write_text("
    "json.dumps(sorted(main.app.openapi()['paths']), ensure_ascii=False, indent=2) + chr(10), "
    'encoding=\'utf-8\')"'
)
"""Команда перегенерации фикстуры - та же, что породила её впервые."""


def test_published_paths_match_the_shared_fixture():
    """Пути схемы совпадают с фикстурой, которую читает клиентский тест.

    Половина сторожа за стыком «браузерный клиент - сервер». Вторая
    половина - ``tests/js/api.test.mjs``: она требует, чтобы каждый путь,
    который ``static/js/api.js`` в самом деле строит, нашёлся в этой же
    фикстуре.

    Порознь наборы слепы.

    Через общую фикстуру расхождение проходит цепочкой: краснеет этот
    тест, фикстура перегенерируется - и краснеет клиентский, потому что
    клиент по-прежнему строит старый путь.
    """
    published = sorted(main.app.openapi()["paths"])

    # Пустая схема прошла бы сравнение с пустой фикстурой, ничего не
    # проверив.
    assert published, "в схеме не оказалось ни одного пути"
    assert published == json.loads(_PATHS_FIXTURE.read_text(encoding="utf-8")), (
        "схема разошлась с фикстурой, которую читает tests/js/api.test.mjs. "
        "Если маршрут изменён намеренно, перегенерируйте её:\n" + _REGENERATE
    )
