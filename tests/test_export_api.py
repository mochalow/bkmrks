"""Контракт экспорта библиотеки.

Проверяется право забрать свои данные, т. е. содержимое архива, а не только код ответа.
"""

import io
import json
import zipfile


def test_zip_contains_article_json(client, stored_article):
    """ZIP повторяет структуру хранилища: ``articles/<id>.json``."""
    article = stored_article(title="Заголовок")

    response = client.get("/api/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [f"articles/{article['id']}.json"]
        saved = json.loads(archive.read(f"articles/{article['id']}.json"))
    assert saved["title"] == "Заголовок"
    assert saved["id"] == article["id"]


def test_zip_contains_cover_image(client, parsed_page):
    """Обложка попадает в архив под ``images/<id>.<ext>``."""
    parsed_page(image="https://example.com/cover.jpg", cover=(b"\xff\xd8binary", "image/jpeg"))
    article = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    response = client.get("/api/export")

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert f"images/{article['id']}.jpg" in archive.namelist()
        assert archive.read(f"images/{article['id']}.jpg") == b"\xff\xd8binary"


def test_zip_offers_download_filename(client, stored_article):
    """Заголовок ``Content-Disposition`` задаёт имя файла для браузера."""
    stored_article()

    response = client.get("/api/export")

    assert response.headers["content-disposition"] == "attachment; filename=bkmrks-export.zip"


def test_json_format_returns_array(client, stored_article):
    """``format=json`` отдаёт массив статей со всеми полями."""
    stored_article(title="Первая")

    response = client.get("/api/export", params={"format": "json"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Первая"
    assert body[0]["content"] is not None


def test_export_is_sorted_by_saved_at_descending(client, stored_article, storage_in_worst_order):
    """Экспорт сортируется так же, как список: новые первыми."""
    old = stored_article(saved_at="2026-01-01T12:00:00Z")
    new = stored_article(saved_at="2026-03-01T12:00:00Z")

    body = client.get("/api/export", params={"format": "json"}).json()

    assert [a["id"] for a in body] == [new["id"], old["id"]]


def test_unknown_format_is_rejected(client):
    """Неподдерживаемый формат отсекается схемой запроса."""
    response = client.get("/api/export", params={"format": "xml"})

    assert response.status_code == 422


def test_empty_library_exports_empty_archive(client):
    """Экспорт пустой библиотеки - валидный пустой результат, а не ошибка."""
    zip_response = client.get("/api/export")
    json_response = client.get("/api/export", params={"format": "json"})

    assert json_response.json() == []
    with zipfile.ZipFile(io.BytesIO(zip_response.content)) as archive:
        assert archive.namelist() == []

