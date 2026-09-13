"""Модульные тесты файлового хранилища.

Единственный файл, привязанный к текущей реализации: он проверяет диск,
а не HTTP-контракт.
"""

import json
import os
import uuid
from types import SimpleNamespace

import pytest

import storage

# Файл целиком проверяет диск, а не HTTP-контракт: помечен модульно.
pytestmark = pytest.mark.json_storage


def _os_that_cannot_replace(die):
    """Подделка модуля ``os`` для :mod:`storage`, у которой ломается только подмена файла.

    Причина та же, что у :func:`_json_that_cannot_serialize` ниже:
    ``storage.os`` - это общий модуль ``os``, и подмена его ``replace``
    действовала бы на весь процесс, включая уборку временных файлов
    самого pytest. Подменяется имя внутри модуля, а не атрибут общего
    объекта.

    Остальное настоящее: ``storage.save`` открывает дескриптор через
    ``os.fdopen`` и убирает временный файл через ``os.unlink``.
    """
    return SimpleNamespace(fdopen=os.fdopen, replace=die, unlink=os.unlink)


def _json_that_cannot_serialize():
    """Подделка модуля ``json``, у которой ломается только запись.

    Подменять предстоит имя внутри :mod:`storage`, а не атрибут общего
    модуля.

    Чтение остаётся настоящим намеренно:
    ``test_failed_save_keeps_previous_version`` вызывает ``storage.load``,
    пока подмена ещё действует.
    """

    def refuse(*args, **kwargs):
        raise ValueError("сбой")

    return SimpleNamespace(
        dumps=refuse, loads=json.loads, JSONDecodeError=json.JSONDecodeError
    )


# --- Атомарность записи ---


def test_save_creates_directory(data_dir, article_record):
    """Каталог хранилища создаётся при первом сохранении."""
    article = article_record()

    storage.save(article)

    assert (storage.DATA_DIR / f"{article['id']}.json").exists()


def test_save_creates_missing_parent_directories(tmp_path, monkeypatch, article_record):
    """Первое сохранение создаёт всё дерево каталогов, а не последний уровень.

    В проде ``DATA_DIR`` лежит на два уровня вглубь (``data/articles``), и на
    чистой установке каталога ``data`` ещё нет. Фикстура ``data_dir`` этого не
    воспроизводит - она кладёт хранилище на один уровень под ``tmp_path``, у
    которого родитель существует всегда, поэтому ``parents=True`` не нужен.
    """
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data" / "articles")
    article = article_record()

    storage.save(article)

    assert (storage.DATA_DIR / f"{article['id']}.json").exists()


def test_failed_save_leaves_no_temporary_file(data_dir, monkeypatch, article_record):
    """Сбой посреди записи не оставляет временных файлов.

    Прерванная запись - главный сценарий, ради которого сохранение идёт
    через временный файл и ``os.replace``: полуфайла на диске остаться
    не должно.
    """
    article = article_record()
    monkeypatch.setattr(storage, "json", _json_that_cannot_serialize())

    with pytest.raises(ValueError):
        storage.save(article)

    assert list(storage.DATA_DIR.iterdir()) == []


def test_failed_save_keeps_previous_version(data_dir, monkeypatch, article_record):
    """Сбой перезаписи не портит уже сохранённую статью."""
    article = article_record(title="Первая версия")
    storage.save(article)
    monkeypatch.setattr(storage, "json", _json_that_cannot_serialize())

    with pytest.raises(ValueError):
        storage.save(article | {"title": "Вторая версия"})

    assert storage.load(article["id"])["title"] == "Первая версия"


def test_save_keeps_cyrillic_readable(data_dir, article_record):
    """JSON пишется без экранирования: файл читается человеком без приложения."""
    article = article_record(title="Кириллица")

    storage.save(article)

    raw = (storage.DATA_DIR / f"{article['id']}.json").read_text(encoding="utf-8")
    assert "Кириллица" in raw


def test_interrupted_swap_leaves_previous_version_intact(data_dir, monkeypatch, article_record):
    """Сбой ровно в момент подмены файла оставляет прежнюю версию целой.

    Два теста выше ломают сериализацию, то есть падают до открытия файла:
    диска они не касаются и остаются зелёными даже если убрать временный
    файл и ``os.replace`` совсем. Здесь проверяется сам инвариант
    атомарности - на диске либо старая версия целиком, либо новая
    целиком, но никогда не половина.

    Тест не знает, как это сделано.
    """
    article = article_record(title="Первая версия")
    storage.save(article)
    path = storage.DATA_DIR / f"{article['id']}.json"
    before = path.read_bytes()

    def die(src, dst):
        raise OSError("питание кончилось ровно здесь")

    monkeypatch.setattr(storage, "os", _os_that_cannot_replace(die))

    with pytest.raises(OSError):
        storage.save(article | {"title": "Вторая версия"})

    after = path.read_bytes()
    assert after == before
    assert json.loads(after)["title"] == "Первая версия"
    assert list(storage.DATA_DIR.iterdir()) == [path]


# --- Инварианты записи ---


def test_save_deduplicates_tags(data_dir, article_record):
    """Повторяющиеся теги схлопываются с сохранением порядка."""
    article = article_record(tags=["python", "news", "python"])

    storage.save(article)

    assert storage.load(article["id"])["tags"] == ["python", "news"]


def test_save_drops_legacy_field(data_dir, article_record):
    """Устаревшее поле старых записей выбрасывается при сохранении."""
    article = article_record(text_plain="старое поле")

    storage.save(article)

    assert "text_plain" not in storage.load(article["id"])


def test_save_repairs_broken_tags_field(data_dir, article_record):
    """Не-список в поле тегов заменяется пустым списком, а не роняет чтение."""
    article = article_record(tags="не список")

    storage.save(article)

    assert storage.load(article["id"])["tags"] == []


def test_save_does_not_mutate_caller_dict(data_dir, article_record):
    """Нормализация не меняет словарь вызывающего кода."""
    article = article_record(tags=["python", "python"])

    storage.save(article)

    assert article["tags"] == ["python", "python"]


# --- Чтение ---


def test_load_rejects_non_uuid_id(data_dir, article_record):
    """Невалидный идентификатор не превращается в путь к файлу.

    Хранилище не полагается на то, что вызывающий код уже проверил ввод.

    Цель обхода делается настоящей - и файл, и каталог хранилища, через
    который идёт ``..``. Без них ``load`` вернёт ``None`` просто потому,
    что читать нечего, и утверждение останется зелёным даже со снятой
    проверкой UUID.
    """
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    outsider = data_dir / "secret.json"
    outsider.write_text(
        json.dumps(article_record(content="ЧУЖИЕ ДАННЫЕ")), encoding="utf-8"
    )

    assert storage.load("../secret") is None


def test_load_returns_none_for_missing_file(data_dir):
    """Отсутствующая статья - ``None``, а не исключение."""
    assert storage.load(str(uuid.uuid4())) is None


def test_load_returns_none_for_incomplete_record(data_dir):
    """Запись без обязательных полей не отдаётся как статья."""
    article_id = str(uuid.uuid4())
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (storage.DATA_DIR / f"{article_id}.json").write_text(
        json.dumps({"id": article_id}), encoding="utf-8"
    )

    assert storage.load(article_id) is None


def test_load_all_returns_empty_list_without_directory(data_dir):
    """До первого сохранения библиотека пуста, а не сломана."""
    assert storage.load_all() == []


# --- Удаление ---


def test_delete_rejects_non_uuid_id(data_dir, article_record):
    """Удаление по невалидному идентификатору ничего не делает.

    Цель обхода существует, как и в ``test_load_rejects_non_uuid_id``:
    иначе ``False`` возвращался бы за отсутствием файла, а не за отказом.
    """
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    outsider = data_dir / "secret.json"
    outsider.write_text(json.dumps(article_record()), encoding="utf-8")

    assert storage.delete("../secret") is False
    assert outsider.exists()


def test_delete_returns_false_for_missing_article(data_dir):
    """Удаление несуществующей статьи - ``False``, а не исключение."""
    assert storage.delete(str(uuid.uuid4())) is False


# --- Теги ---


def test_add_tag_reports_change():
    """Добавление тега сообщает, изменился ли список."""
    article = {"tags": []}

    assert storage.add_tag(article, "python") is True
    assert storage.add_tag(article, "python") is False
    assert article["tags"] == ["python"]


def test_remove_tag_reports_change():
    """Удаление тега сообщает, изменился ли список."""
    article = {"tags": ["python"]}

    assert storage.remove_tag(article, "python") is True
    assert storage.remove_tag(article, "python") is False
    assert article["tags"] == []


# --- Обложки ---


def test_save_image_rejects_unsupported_type(data_dir):
    """Неподдерживаемый тип изображения не сохраняется."""
    assert storage.save_image(str(uuid.uuid4()), b"data", "image/tiff") is False


def test_save_image_rejects_non_uuid_id(data_dir):
    """Обложка не пишется по невалидному идентификатору."""
    assert storage.save_image("../evil", b"data", "image/jpeg") is False


def test_save_image_replaces_previous_extension(data_dir):
    """Новая обложка вытесняет старую, даже если расширение изменилось."""
    article_id = str(uuid.uuid4())
    storage.save_image(article_id, b"old", "image/jpeg")

    storage.save_image(article_id, b"new", "image/png")

    assert storage.image_path(article_id).name == f"{article_id}.png"
    assert list(storage.IMAGES_DIR.glob(f"{article_id}.*")) == [storage.image_path(article_id)]


def test_save_image_creates_missing_parent_directories(tmp_path, monkeypatch):
    """Первая обложка тоже создаёт дерево целиком: у ``IMAGES_DIR`` та же форма.

    Отдельный тест, а не довесок к статье: ``save_article`` сохраняет обложку
    раньше JSON, поэтому один сценарий закрепил бы ``parents=True`` только у
    того вызова, который отработал первым.
    """
    monkeypatch.setattr(storage, "IMAGES_DIR", tmp_path / "data" / "images")
    article_id = str(uuid.uuid4())

    assert storage.save_image(article_id, b"\xff\xd8", "image/jpeg") is True
    assert (storage.IMAGES_DIR / f"{article_id}.jpg").exists()


def test_delete_image_rejects_non_uuid_id(data_dir):
    """Удаление обложки по невалидному идентификатору не трогает чужие файлы.

    Идентификатор попадает прямо в шаблон ``glob``, поэтому без проверки
    он работает не как имя, а как запрос.
    """
    keeper = str(uuid.uuid4())
    storage.save_image(keeper, b"cover", "image/jpeg")
    outsider = data_dir / "evil.jpg"
    outsider.write_bytes(b"outside")

    storage.delete_image("*")
    storage.delete_image("../evil")

    assert storage.image_path(keeper) is not None
    assert outsider.exists()


def test_image_path_rejects_non_uuid_id(data_dir):
    """Путь к обложке не выдаётся по невалидному идентификатору.

    Без проверки ``*`` вернул бы первую попавшуюся обложку - то есть
    картинку чужой статьи, а ``../`` - файл вне каталога изображений.
    Оба пути уходят в ``FileResponse`` из :func:`main.read_article_image`.
    """
    storage.save_image(str(uuid.uuid4()), b"cover", "image/jpeg")
    (data_dir / "evil.jpg").write_bytes(b"outside")

    assert storage.image_path("*") is None
    assert storage.image_path("../evil") is None


def test_image_path_returns_none_without_cover(data_dir):
    """Без обложки путь не находится."""
    assert storage.image_path(str(uuid.uuid4())) is None


def test_delete_image_is_safe_without_directory(data_dir):
    """Удаление обложки до создания каталога ничего не ломает."""
    storage.delete_image(str(uuid.uuid4()))


def test_save_article_writes_image_reference(data_dir, article_record):
    """Ссылка на обложку попадает в JSON только если обложка сохранена."""
    article = article_record()

    saved = storage.save_article(article, (b"\xff\xd8", "image/jpeg"), image_ref="/ref")

    assert saved is True
    assert storage.load(article["id"])["image"] == "/ref"


def test_save_article_without_cover_keeps_image_empty(data_dir, article_record):
    """Без обложки поле ``image`` не заполняется."""
    article = article_record()

    saved = storage.save_article(article, None, image_ref="/ref")

    assert saved is False
    assert storage.load(article["id"]).get("image") is None
