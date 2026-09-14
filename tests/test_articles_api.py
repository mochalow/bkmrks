"""Контракт создания, чтения, списка и удаления статей.

Тесты ходят через HTTP и ничего не знают о том, где лежат данные.
"""

import uuid

import pytest

from tests.conftest import raising


def test_creates_article_with_201(client, parsed_page):
    """Новая статья создаётся со статусом 201 и разобранными полями."""
    parsed_page(title="Заголовок", content="Текст статьи.")

    response = client.post("/api/articles", json={"url": "https://example.com/a"})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Заголовок"
    assert body["content"] == "Текст статьи."
    assert body["tags"] == []
    assert body["image"] is None
    uuid.UUID(body["id"])


def test_keeps_original_url_not_the_dedup_key(client, parsed_page):
    """Сохраняется исходный адрес, а не нормализованный ключ дедупликации.

    Ключ дедупликации выбрасывает трекинг-метки и фрагмент; в самой
    статье они остаются - иначе ссылка перестала бы быть той, которую
    сохранил пользователь.

    Адрес проходит через ``HttpUrl``, а pydantic приводит схему и хост к
    нижнему регистру и добавляет ``/`` к пустому пути. То есть «как есть»
    относится к пути, параметрам и фрагменту, но не к регистру хоста.
    """
    parsed_page()

    body = client.post(
        "/api/articles", json={"url": "https://WWW.Example.com/Path?utm_source=x#top"}
    ).json()

    assert body["url"] == "https://www.example.com/Path?utm_source=x#top"


def test_duplicate_returns_200_and_same_id(client, parsed_page):
    """Повторный POST того же URL возвращает 200 и ту же статью."""
    parsed_page()
    first = client.post("/api/articles", json={"url": "https://example.com/a"})

    second = client.post("/api/articles", json={"url": "https://example.com/a"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get("/api/articles").json()) == 1


def test_duplicate_is_recognized_without_downloading_the_page(client, parsed_page, monkeypatch):
    """Повторное сохранение не качает страницу заново.

    Проверка дублей стоит дважды: быстрая - до скачивания, и настоящая -
    под блокировкой записи. Снятие быстрой не ломает ни одного утверждения
    о теле ответа: код и статья те же, их вернёт вторая проверка. Разница
    только в проделанной впустую работе.

    Отсутствие работы наблюдаемо единственным способом - утверждением,
    что вызова не было.
    """
    import parser

    parsed_page()
    first = client.post("/api/articles", json={"url": "https://example.com/a"}).json()
    downloads = []
    stub = parser.parse
    monkeypatch.setattr(parser, "parse", lambda url: downloads.append(url) or stub(url))

    second = client.post("/api/articles", json={"url": "https://example.com/a"})

    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert downloads == []


def test_normalized_url_is_recognized_as_duplicate(client, parsed_page):
    """Адреса, различающиеся только оформлением, не плодят копий.

    Одна статья, расшаренная в разных местах
    с разными трекинг-метками, сохраняется один раз.
    """
    parsed_page()
    first = client.post("/api/articles", json={"url": "https://www.Example.com/a/"})

    second = client.post(
        "/api/articles", json={"url": "http://example.com//a?utm_source=x#fragment"}
    )

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get("/api/articles").json()) == 1


def test_different_urls_create_different_articles(client, parsed_page):
    """Значимо разные адреса дают две отдельные статьи."""
    parsed_page()
    first = client.post("/api/articles", json={"url": "https://example.com/a?page=1"})
    second = client.post("/api/articles", json={"url": "https://example.com/a?page=2"})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(client.get("/api/articles").json()) == 2


def test_rejects_non_url_payload(client, parsed_page):
    """Строка, не являющаяся адресом, отсекается валидацией с 422."""
    parsed_page()

    response = client.post("/api/articles", json={"url": "не адрес"})

    assert response.status_code == 422


def test_reports_parse_failure_as_422(client, monkeypatch):
    """Сообщение парсера доходит до клиента как 422 с человеческим текстом.

    Здесь сравнение точное. Дословная передача причины
    наружу и есть контракт: пользователь должен увидеть «Сайт не ответил»,
    а не «Ошибка обработки».
    """
    import parser

    monkeypatch.setattr(parser, "parse", raising(ValueError("Сайт не ответил")))

    response = client.post("/api/articles", json={"url": "https://example.com/a"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Сайт не ответил"


def test_reads_article_by_id(client, parsed_page):
    """``GET /api/articles/{id}`` отдаёт полную статью вместе с текстом."""
    parsed_page(content="Полный текст.")
    created = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    response = client.get(f"/api/articles/{created['id']}")

    assert response.status_code == 200
    assert response.json()["content"] == "Полный текст."


def test_missing_article_returns_404(client):
    """Несуществующий, но валидный UUID даёт 404."""
    response = client.get(f"/api/articles/{uuid.uuid4()}")

    assert response.status_code == 404


def test_malformed_id_returns_422_not_404(client):
    """Невалидный UUID в пути отсекается валидацией: 422, а не 404.

    Тип параметра ``uuid.UUID`` проверяется pydantic
    до входа в обработчик. Смена типа на ``str`` превратила бы это в 404.
    """
    response = client.get("/api/articles/не-uuid")

    assert response.status_code == 422


def test_deletes_article(client, parsed_page):
    """Удаление отдаёт 204, повторное удаление - 404."""
    parsed_page()
    created = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    deleted = client.delete(f"/api/articles/{created['id']}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.delete(f"/api/articles/{created['id']}").status_code == 404
    assert client.get("/api/articles").json() == []


def test_list_is_sorted_by_saved_at_descending(client, stored_article, storage_in_worst_order):
    """Список отсортирован по дате сохранения, новые первыми.

    Статьи кладутся напрямую в хранилище с явными метками времени:
    через API ``saved_at`` имеет разрешение в секунду, и порядок
    определялся бы порядком обхода каталога файловой системой.
    """
    old = stored_article(saved_at="2026-01-01T12:00:00Z", title="Старая")
    new = stored_article(saved_at="2026-03-01T12:00:00Z", title="Новая")

    body = client.get("/api/articles").json()

    assert [a["id"] for a in body] == [new["id"], old["id"]]


@pytest.mark.json_storage
def test_all_writers_store_saved_at_in_one_format(client, parsed_page, stored_article):
    """Приложение и фикстура пишут время одним и тем же способом.

    ``list_articles`` сравнивает ``saved_at`` как строки, а не как даты.
    Это верно ровно до тех пор, пока формат один: у записей с разным
    смещением (``Z`` против ``+03:00``) лексикографический порядок и
    хронологический расходятся. Утверждение закрепляет саму предпосылку,
    потому что порядок её нарушения через HTTP не виден - ответ уже
    разобран pydantic и нормализован.

    Сравнивать порядок двух статей для этого бесполезно: даты в тесте
    различаются задолго до символа смещения, и такое утверждение зелено
    при любом сочетании форматов.

    Единственный тест здесь, заглядывающий в саму запись, - отсюда и
    маркер: вместе с файловым хранилищем он теряет смысл.
    """
    import storage

    stored = stored_article()
    parsed_page()
    created = client.post("/api/articles", json={"url": "https://example.com/new"}).json()

    assert stored["saved_at"].endswith("Z")
    assert storage.load(created["id"])["saved_at"].endswith("Z")


def test_empty_library_returns_empty_list(client):
    """Пустая библиотека - это пустой список, а не ошибка."""
    response = client.get("/api/articles")

    assert response.status_code == 200
    assert response.json() == []


def test_saves_and_serves_cover_image(client, parsed_page):
    """Скачанная обложка отдаётся по API-пути из поля ``image``."""
    parsed_page(image="https://example.com/cover.jpg", cover=(b"\xff\xd8binary", "image/jpeg"))

    created = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    assert created["image"] == f"/api/articles/{created['id']}/image"
    response = client.get(created["image"])
    assert response.status_code == 200
    assert response.content == b"\xff\xd8binary"


def test_article_without_cover_has_no_image(client, parsed_page):
    """Без обложки поле ``image`` пустое, а её эндпоинт отдаёт 404."""
    parsed_page()

    created = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    assert created["image"] is None
    assert client.get(f"/api/articles/{created['id']}/image").status_code == 404


def test_cover_is_not_downloaded_when_page_has_no_image(client, parsed_page, monkeypatch):
    """Без адреса обложки скачивание не запускается вовсе.

    Проверка ``if not image_url`` невидима остальным тестам: фикстура
    ``parsed_page`` подменяет ``parser.fetch_image`` безусловно, и её снятие
    ничего не ломает. Между тем ``urljoin(страница, None)`` не бросает,
    а возвращает адрес самой страницы - без проверки за каждой статьёй
    без картинки уезжал бы второй запрос за уже скачанным HTML.

    Утверждение о том, что вызова не было, - единственная форма, в
    которой отсутствие работы вообще наблюдаемо.
    """
    import parser

    parsed_page(image=None)
    calls = []
    monkeypatch.setattr(parser, "fetch_image", lambda *args, **kwargs: calls.append(args))

    created = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    assert created["image"] is None
    assert calls == []


def test_deleting_article_removes_cover(client, parsed_page):
    """Удаление статьи уносит с собой и файл обложки."""
    parsed_page(image="https://example.com/cover.jpg", cover=(b"\xff\xd8binary", "image/jpeg"))
    created = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    client.delete(f"/api/articles/{created['id']}")

    assert client.get(f"/api/articles/{created['id']}/image").status_code == 404


def test_duplicate_appearing_during_download_is_detected(
    client, monkeypatch, data_dir, article_record
):
    """Дубль, появившийся пока скачивалась страница, не создаёт вторую статью.

    Проверка на дубль делается дважды: быстро до скачивания и повторно
    под блокировкой записи. Здесь имитируется гонка - конкурирующий
    запрос успевает сохранить ту же статью, пока текущий ждёт ответа
    сайта. Сработать должна вторая проверка.
    """
    import parser
    import storage

    # Адрес задан явно: он обязан совпасть с тем, который сохраняет
    # текущий запрос, иначе дублем эта статья не будет.
    competing = article_record(
        url="https://example.com/a", title="Сохранена конкурирующим запросом"
    )

    def parse_and_race(url):
        """Пока «скачивается» страница, ту же статью сохраняет кто-то ещё."""
        storage.save(competing)
        return {
            "title": "Наш разбор",
            "content": "Текст.",
            "author": None,
            "date": None,
            "description": None,
            "sitename": None,
            "image": None,
        }

    monkeypatch.setattr(parser, "parse", parse_and_race)
    monkeypatch.setattr(parser, "fetch_image", lambda *a, **kw: None)

    response = client.post("/api/articles", json={"url": "https://example.com/a"})

    assert response.status_code == 200
    assert response.json()["id"] == competing["id"]
    assert len(client.get("/api/articles").json()) == 1
