"""Контракт поиска и фильтрации библиотеки."""


def test_search_ignores_case(client, stored_article):
    """Поиск не учитывает регистр ни запроса, ни текста."""
    stored_article(title="Машинное обучение", content="Текст.")
    stored_article(title="Кулинария", content="Текст.")

    body = client.get("/api/articles", params={"q": "МАШИННОЕ"}).json()

    assert [a["title"] for a in body] == ["Машинное обучение"]


def test_search_ignores_case_in_content(client, stored_article):
    """Регистр не учитывается и в тексте статьи, а не только в заголовке.

    Зеркало теста выше. Тот меняет регистр запроса против заголовка и
    остаётся зелёным, если перестать приводить к нижнему регистру
    ``content``: совпадение находится в заголовке и до текста дело не
    доходит. Здесь совпадения в заголовке нет вовсе, поэтому обе стороны
    - запрос и текст - обязаны быть приведены.
    """
    stored_article(title="Без ключевого слова", content="Внутри есть МАШИННОЕ обучение.")
    stored_article(title="Кулинария", content="Текст.")

    body = client.get("/api/articles", params={"q": "МаШиННое"}).json()

    assert [a["title"] for a in body] == ["Без ключевого слова"]


def test_search_looks_into_content(client, stored_article):
    """Подстрока ищется и в полном тексте, а не только в заголовке."""
    stored_article(title="Без ключевого слова", content="Внутри есть python.")
    stored_article(title="Другая", content="Ничего похожего.")

    body = client.get("/api/articles", params={"q": "python"}).json()

    assert [a["title"] for a in body] == ["Без ключевого слова"]


def test_search_without_matches_returns_empty_list(client, stored_article):
    """Ненайденный запрос - пустой список, а не 404."""
    stored_article(title="Статья", content="Текст.")

    response = client.get("/api/articles", params={"q": "ничего-такого-нет"})

    assert response.status_code == 200
    assert response.json() == []


def test_filters_by_tag(client, stored_article):
    """Фильтр по тегу оставляет только помеченные статьи.

    Статья с тегом ``python3`` нужна, чтобы отличить точное совпадение
    от вхождения подстроки. Без неё фильтр можно превратить в поиск
    подстроки, и набор останется зелёным - а человек, отфильтровавший
    библиотеку по ``python``, получит вперемешку и другие теги,
    начинающиеся так же.
    """
    stored_article(title="С тегом", tags=["python"])
    stored_article(title="С похожим тегом", tags=["python3"])
    stored_article(title="Без тега", tags=[])

    body = client.get("/api/articles", params={"tag": "python"}).json()

    assert [a["title"] for a in body] == ["С тегом"]


def test_tag_filter_normalizes_input(client, stored_article):
    """Тег фильтра нормализуется так же, как при сохранении."""
    stored_article(title="С тегом", tags=["python"])

    body = client.get("/api/articles", params={"tag": "  PYTHON  "}).json()

    assert [a["title"] for a in body] == ["С тегом"]


def test_tag_and_query_combine(client, stored_article):
    """Фильтры комбинируются: сначала тег, затем поиск внутри результата."""
    stored_article(title="Нужная", content="про python", tags=["работа"])
    stored_article(title="Тот же тег", content="про кулинарию", tags=["работа"])
    stored_article(title="Тот же текст", content="про python", tags=["дом"])

    body = client.get("/api/articles", params={"tag": "работа", "q": "python"}).json()

    assert [a["title"] for a in body] == ["Нужная"]


def test_filtered_list_keeps_sort_order(client, stored_article, storage_in_worst_order):
    """Отфильтрованный список тоже отсортирован по дате, новые первыми."""
    old = stored_article(saved_at="2026-01-01T12:00:00Z", tags=["python"])
    new = stored_article(saved_at="2026-03-01T12:00:00Z", tags=["python"])

    body = client.get("/api/articles", params={"tag": "python"}).json()

    assert [a["id"] for a in body] == [new["id"], old["id"]]


def test_empty_filters_return_whole_library(client, stored_article):
    """Пустые значения фильтров равносильны их отсутствию."""
    stored_article()
    stored_article()

    body = client.get("/api/articles", params={"q": "", "tag": ""}).json()

    assert len(body) == 2


def test_search_survives_article_without_title(client, stored_article):
    """Статья без заголовка не роняет поиск.

    ``title`` необязателен: парсер мог не найти его в метаданных.
    """
    stored_article(title=None, content="есть только текст")

    body = client.get("/api/articles", params={"q": "только"}).json()

    assert len(body) == 1
