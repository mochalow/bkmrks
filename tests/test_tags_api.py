"""Контракт операций с тегами: нормализация, идемпотентность, запреты."""

import uuid


def _create(client, url="https://example.com/a"):
    """Создаёт статью и возвращает её идентификатор."""
    return client.post("/api/articles", json={"url": url}).json()["id"]


def test_normalizes_tag_to_lowercase_and_trims(client, parsed_page):
    """Тег приводится к нижнему регистру, пробелы по краям обрезаются."""
    parsed_page()
    article_id = _create(client)

    response = client.post(f"/api/articles/{article_id}/tags", json={"tag": "  Python  "})

    assert response.status_code == 200
    assert response.json()["tags"] == ["python"]


def test_tag_survives_reread(client, parsed_page):
    """Добавленный тег записан на диск, а не только в ответ."""
    parsed_page()
    article_id = _create(client)
    client.post(f"/api/articles/{article_id}/tags", json={"tag": "python"})

    body = client.get(f"/api/articles/{article_id}").json()

    assert body["tags"] == ["python"]


def test_accepts_single_character_tag(client, parsed_page):
    """Тег из одной буквы законен и схемой не отсекается.

    ``min_length=1`` - именно граница, а не круглое число рядом с нулём:
    однобуквенные теги осмысленны («с», «r», «π»). Сдвиг границы на
    единицу начал бы отвечать на них 422, и заметить это было бы некому -
    остальные тесты берут теги подлиннее.
    """
    parsed_page()
    article_id = _create(client)

    response = client.post(f"/api/articles/{article_id}/tags", json={"tag": "с"})

    assert response.status_code == 200
    assert response.json()["tags"] == ["с"]


def test_adding_same_tag_twice_is_idempotent(client, parsed_page):
    """Повторное добавление тега не создаёт дубликата."""
    parsed_page()
    article_id = _create(client)
    client.post(f"/api/articles/{article_id}/tags", json={"tag": "python"})

    response = client.post(f"/api/articles/{article_id}/tags", json={"tag": "PYTHON"})

    assert response.status_code == 200
    assert response.json()["tags"] == ["python"]


def test_removes_tag(client, parsed_page):
    """Удаление тега убирает его из статьи."""
    parsed_page()
    article_id = _create(client)
    client.post(f"/api/articles/{article_id}/tags", json={"tag": "python"})
    client.post(f"/api/articles/{article_id}/tags", json={"tag": "news"})

    response = client.delete(f"/api/articles/{article_id}/tags/python")

    assert response.status_code == 200
    assert response.json()["tags"] == ["news"]


def test_tag_removal_survives_reread(client, parsed_page):
    """Удалённый тег убран с диска, а не только из ответа.

    Зеркало ``test_tag_survives_reread``. Тело ответа собирается из словаря,
    уже изменённого в памяти, поэтому пропущенный ``storage.save``
    выглядит успехом - тег исчезает из ответа и остаётся на диске.
    """
    parsed_page()
    article_id = _create(client)
    client.post(f"/api/articles/{article_id}/tags", json={"tag": "python"})
    client.delete(f"/api/articles/{article_id}/tags/python")

    body = client.get(f"/api/articles/{article_id}").json()

    assert body["tags"] == []


def test_removing_absent_tag_is_idempotent(client, parsed_page):
    """Удаление отсутствующего тега считается успехом, а не 404."""
    parsed_page()
    article_id = _create(client)

    response = client.delete(f"/api/articles/{article_id}/tags/несуществующий")

    assert response.status_code == 200
    assert response.json()["tags"] == []


def test_rejects_tag_with_slash(client, parsed_page):
    """Символ ``/`` в теге запрещён: он ломает маршрут удаления.

    Проверяется код и форма тела, а не формулировка: у 422 от схемы
    ``detail`` - список объектов ошибок, у 422 от обработчика - строка.
    Это и отличает наш отказ от отказа pydantic, а текст сообщения
    свободен меняться без правки теста.
    """
    parsed_page()
    article_id = _create(client)

    response = client.post(f"/api/articles/{article_id}/tags", json={"tag": "a/b"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_rejects_empty_tag(client, parsed_page):
    """Пустая строка отсекается валидацией схемы (``min_length=1``)."""
    parsed_page()
    article_id = _create(client)

    response = client.post(f"/api/articles/{article_id}/tags", json={"tag": ""})

    assert response.status_code == 422


def test_rejects_whitespace_only_tag(client, parsed_page):
    """Строка из пробелов проходит схему и отсекается уже обработчиком.

    Обе ветки дают 422, но тела разные: у схемы ``detail`` - список
    объектов ошибок, у обработчика - строка. Именно по этому и отличаем,
    не завязываясь ни на формулировку, ни на структуру тела pydantic.
    """
    parsed_page()
    article_id = _create(client)

    response = client.post(f"/api/articles/{article_id}/tags", json={"tag": "   "})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_tag_on_missing_article_returns_404(client):
    """Тег к несуществующей статье - 404."""
    response = client.post(f"/api/articles/{uuid.uuid4()}/tags", json={"tag": "python"})

    assert response.status_code == 404


def test_invalid_tag_is_rejected_before_article_lookup(client):
    """Валидация тега идёт раньше поиска статьи: 422, а не 404.

    Порядок неочевидный и легко «чинится» при рефакторинге: в ``add_tag``
    нормализация тега вызывается до обращения к хранилищу.
    """
    response = client.post(f"/api/articles/{uuid.uuid4()}/tags", json={"tag": "a/b"})

    assert response.status_code == 422


def test_encoded_slash_in_delete_route_is_unreachable(client, parsed_page):
    """Тег со слэшем через DELETE недостижим - маршрут не совпадает.

    ``%2F`` декодируется в ``/`` до маршрутизации, поэтому проверка на
    ``/`` внутри ``remove_tag`` фактически недостижима: защита работает
    только на входе в ``add_tag``.

    Наблюдаемый код - 405, а не 404: несовпавший путь достаётся статике,
    смонтированной в корень, а она отвечает на любой метод кроме
    ``GET``/``HEAD`` отказом по методу.
    """
    parsed_page()
    article_id = _create(client)

    response = client.delete(f"/api/articles/{article_id}/tags/a%2Fb")

    assert response.status_code == 405


def test_lists_tags_with_counts_sorted(client, stored_article):
    """``GET /api/tags`` отдаёт счётчики по алфавиту.

    Данные подобраны так, чтобы порядок без сортировки отличался от
    алфавитного при любом обходе каталога.

    Устройство данных. Теги в первой статье перечислены задом наперёд
    относительно алфавита (латиница сортируется раньше кириллицы), а
    вторая статья повторяет тот тег, который в алфавите последний.
    Поэтому какую бы статью хранилище ни отдало первой, без сортировки
    ``новости`` окажутся впереди - то есть заведомо не по алфавиту.
    """
    stored_article(tags=["новости", "vue", "python"])
    stored_article(tags=["новости"])

    response = client.get("/api/tags")

    assert response.status_code == 200
    assert list(response.json().items()) == [("python", 1), ("vue", 1), ("новости", 2)]


def test_lists_no_tags_for_empty_library(client):
    """Без статей список тегов пуст."""
    assert client.get("/api/tags").json() == {}


def test_removing_tag_from_missing_article_returns_404(client):
    """Удаление тега у несуществующей статьи - 404."""
    response = client.delete(f"/api/articles/{uuid.uuid4()}/tags/python")

    assert response.status_code == 404
