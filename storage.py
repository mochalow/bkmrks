"""Файловое хранилище статей в формате JSON.

Каждая статья - отдельный файл ``data/articles/<uuid>.json``.
Модуль не знает о бизнес-логике API: принимает и возвращает обычные
словари Python, сериализуемые в JSON.

Используется только из :mod:`main`. Публичные функции:
:func:`save`, :func:`load`, :func:`load_all`, :func:`delete`,
:func:`add_tag`, :func:`remove_tag`, функции работы с обложками.

Каталоги ``data/articles`` и ``data/images`` создаются автоматически.
"""

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data" / "articles"
"""Каталог, в котором лежат JSON-файлы статей.

При первом сохранении создаётся автоматически (``parents=True``).
Путь абсолютный относительно расположения модуля, чтобы не зависеть от cwd.
В Docker том монтируется в /app/data.
"""

IMAGES_DIR = Path(__file__).resolve().parent / "data" / "images"
"""Каталог, в котором лежат скачанные обложки статей."""

_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _is_valid_record(data: object) -> bool:
    """Проверяет, что словарь содержит обязательные поля статьи."""
    return (
            isinstance(data, dict)
            and isinstance(data.get("id"), str)
            and isinstance(data.get("url"), str)
            and data.get("saved_at") is not None
            and data.get("content") is not None
    )


def _normalize_tags(tags: object) -> list[str]:
    """Убирает дубликаты тегов, сохраняя порядок первого вхождения."""
    if not isinstance(tags, list):
        return []
    return list(dict.fromkeys(tags))


def _normalize_record(data: dict) -> dict:
    """Гарантирует инварианты записи статьи (уникальный список тегов).

    Также удаляет устаревшие поля из старых записей.
    """
    data["tags"] = _normalize_tags(data.get("tags"))
    data.pop("text_plain", None)
    return data


def add_tag(article: dict, tag: str) -> bool:
    """Добавляет тег к статье.

    Предполагает, что ``article`` пришёл из :func:`load` / :func:`load_all`
    или уже прошёл через :func:`_normalize_record`. Повторное добавление
    идемпотентно.

    Вызывающий код (в :mod:`main`) отвечает за последующий :func:`save`.

    Returns:
        ``True``, если список тегов изменился.
    """
    tags = article["tags"]
    if tag in tags:
        return False
    tags.append(tag)
    return True


def remove_tag(article: dict, tag: str) -> bool:
    """Удаляет тег из статьи.

    Идемпотентно: если тега нет - возвращает ``False`` и не меняет данные.

    Returns:
        ``True``, если список тегов изменился.
    """
    tags = article["tags"]
    if tag not in tags:
        return False
    article["tags"] = [t for t in tags if t != tag]
    return True


def _is_valid_id(article_id: str) -> bool:
    """Проверяет, что идентификатор - валидный UUID.

    Используется перед тем, как подставить ``article_id`` в путь к файлу:
    вызывающий код (сейчас - маршруты FastAPI с типом ``uuid.UUID``) уже
    валидирует это, но модуль не должен полагаться на вызывающую сторону.
    """
    try:
        uuid.UUID(article_id)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def save_article(
        article: dict,
        cover: tuple[bytes, str] | None = None,
        *,
        image_ref: str | None = None,
) -> bool:
    """Сохраняет статью и опционально её обложку.

    Обложка записывается до JSON-файла статьи; при сбое записи JSON
    откатывается. Если обложка сохранена и передан ``image_ref``, поле
    ``image`` в словаре статьи заполняется этим значением перед записью.

    Args:
        article: Словарь статьи с обязательным ключом ``id``.
        cover: Сырые байты и MIME-тип обложки, либо ``None``.
        image_ref: Значение для поля ``image`` в JSON, если обложка
            сохранена (обычно API-путь - задаёт вызывающий код).

    Returns:
        ``True``, если обложка записана на диск.
    """
    article_id = article["id"]
    cover_saved = False
    if cover is not None:
        content, content_type = cover
        cover_saved = save_image(article_id, content, content_type)
    if cover_saved and image_ref is not None:
        article = {**article, "image": image_ref}
    try:
        save(article)
    except OSError:
        if cover_saved:
            delete_image(article_id)
        raise
    return cover_saved


def save(article: dict) -> None:
    """Сохраняет или перезаписывает статью на диск.

    Имя файла берётся из поля ``id`` словаря. Сериализация выполняется
    с ``ensure_ascii=False`` (кириллица остаётся читаемой) и отступом
    в два пробела для удобства ручного просмотра.

    Запись атомарна: сначала данные пишутся во временный файл в том же
    каталоге, затем он переименовывается в целевой файл через
    :func:`os.replace`. Это исключает ситуацию, когда падение процесса
    посреди записи оставляет на диске битый, наполовину записанный файл.

    Перед сохранением применяет :func:`_normalize_record`.

    Args:
        article: Словарь статьи. Обязательно должен содержать ключ
            ``id`` - UUID в строковом виде.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    article = _normalize_record({**article})
    path = DATA_DIR / f"{article['id']}.json"

    fd, tmp_name = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(article, ensure_ascii=False, indent=2))
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise


def load(article_id: str) -> dict | None:
    """Загружает одну статью по идентификатору.

    Валидирует ``article_id`` как UUID, читает файл, проверяет
    минимальную структуру через :func:`_is_valid_record`, затем
    нормализует.

    Args:
        article_id: UUID статьи (имя файла без расширения ``.json``).

    Returns:
        Словарь с полями статьи или ``None``, если файл не существует,
        ``article_id`` невалиден или данные повреждены/неполны.
    """
    if not _is_valid_id(article_id):
        return None
    path = DATA_DIR / f"{article_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Не удалось прочитать статью %s: %s", article_id, e)
        return None
    if not _is_valid_record(data):
        logger.warning("Пропущена статья с неполными данными: %s", path.name)
        return None
    return _normalize_record(data)


def load_all() -> list[dict]:
    """Возвращает все сохранённые статьи.

    Читает каждый ``*.json`` в :data:`DATA_DIR`. Порядок файлов
    не гарантируется - сортировку выполняет вызывающий код (API
    сортирует по ``saved_at``). Файлы с повреждённым JSON пропускаются
    с записью предупреждения в лог, а не роняют весь запрос.

    Каждая запись проходит :func:`_normalize_record`.

    Returns:
        Список словарей статей. Пустой список, если каталог ещё
        не создан.
    """
    if not DATA_DIR.exists():
        return []

    articles = []
    for path in DATA_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Пропущен повреждённый файл статьи: %s", path.name)
            continue
        if not _is_valid_record(data):
            logger.warning("Пропущена статья с неполными данными: %s", path.name)
            continue
        articles.append(_normalize_record(data))
    return articles


def delete(article_id: str) -> bool:
    """Удаляет файл статьи (и её обложку, если она есть) с диска.

    Args:
        article_id: UUID статьи.

    Returns:
        ``True``, если файл существовал и был удалён.
        ``False``, если статья не найдена или ``article_id`` не является
        валидным UUID.
    """
    if not _is_valid_id(article_id):
        return False
    path = DATA_DIR / f"{article_id}.json"
    if not path.exists():
        return False
    path.unlink()

    delete_image(article_id)

    return True


def save_image(article_id: str, content: bytes, content_type: str) -> bool:
    """Сохраняет обложку статьи на диск.

    Args:
        article_id: UUID статьи, к которой относится обложка.
        content: Сырые байты изображения.
        content_type: MIME-тип изображения - определяет расширение файла.

    Returns:
        ``True``, если обложка сохранена. ``False``, если тип содержимого
        не поддерживается или ``article_id`` не является валидным UUID.
    """
    ext = _IMAGE_EXTENSIONS.get(content_type)
    if ext is None or not _is_valid_id(article_id):
        return False
    delete_image(article_id)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGES_DIR / f"{article_id}{ext}").write_bytes(content)
    return True


def delete_image(article_id: str) -> None:
    """Удаляет все файлы обложки статьи, если они есть."""
    if not _is_valid_id(article_id) or not IMAGES_DIR.exists():
        return
    for path in IMAGES_DIR.glob(f"{article_id}.*"):
        path.unlink()


def image_path(article_id: str) -> Path | None:
    """Находит файл обложки статьи на диске, независимо от расширения.

    Args:
        article_id: UUID статьи.

    Returns:
        Путь к файлу обложки, либо ``None``, если обложки нет или
        ``article_id`` не является валидным UUID.
    """
    if not _is_valid_id(article_id) or not IMAGES_DIR.exists():
        return None
    matches = list(IMAGES_DIR.glob(f"{article_id}.*"))
    return matches[0] if matches else None
