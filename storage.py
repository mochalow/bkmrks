"""Файловое хранилище статей в формате JSON.

Каждая статья - отдельный файл ``data/articles/<uuid>.json``.
Модуль не знает о бизнес-логике API: принимает и возвращает обычные
словари Python, сериализуемые в JSON.

"""

import json
from pathlib import Path

DATA_DIR = Path("data/articles")
"""Каталог, в котором лежат JSON-файлы статей.

При первом сохранении создаётся автоматически (``parents=True``).
В Docker том монтируется в этот путь, чтобы данные переживали
пересборку контейнера.
"""


def save(article: dict) -> None:
    """Сохраняет или перезаписывает статью на диск.

    Имя файла берётся из поля ``id`` словаря. Сериализация выполняется
    с ``ensure_ascii=False`` (кириллица остаётся читаемой) и отступом
    в два пробела для удобства ручного просмотра.

    Args:
        article: Словарь статьи. Обязательно должен содержать ключ
            ``id`` - UUID в строковом виде.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{article['id']}.json"
    path.write_text(
        json.dumps(article, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load(article_id: str) -> dict | None:
    """Загружает одну статью по идентификатору.

    Args:
        article_id: UUID статьи (имя файла без расширения ``.json``).

    Returns:
        Словарь с полями статьи или ``None``, если файл не существует.
    """
    path = DATA_DIR / f"{article_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_all() -> list[dict]:
    """Возвращает все сохранённые статьи.

    Читает каждый ``*.json`` в :data:`DATA_DIR`. Порядок файлов
    не гарантируется - сортировку выполняет вызывающий код (API
    сортирует по ``saved_at``).

    Returns:
        Список словарей статей. Пустой список, если каталог ещё
        не создан.
    """
    if not DATA_DIR.exists():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in DATA_DIR.glob("*.json")
    ]


def delete(article_id: str) -> bool:
    """Удаляет файл статьи с диска.

    Args:
        article_id: UUID статьи.

    Returns:
        ``True``, если файл существовал и был удалён.
        ``False``, если статья не найдена.
    """
    path = DATA_DIR / f"{article_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
