"""HTTP API и раздача статики для приложения.

Точка входа - объект :data:`app`. Маршруты API объявлены на
:data:`router` с префиксом ``/api``. Статические файлы фронтенда
монтируются в корень ``/``.

Запуск локально::

    uvicorn main:app --reload

Интерактивная документация OpenAPI:

* Swagger UI - ``/docs``
* ReDoc - ``/redoc``
* JSON-схема - ``/openapi.json``
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path as PathlibPath

from fastapi import FastAPI, HTTPException, Response, APIRouter, Query, Path
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

import storage
import parser

tags_metadata = [
    {
        "name": "articles",
        "description": (
            "Сохранение, чтение, поиск и удаление статей. "
            "При создании страница скачивается и очищается через trafilatura, "
            "результат записывается в JSON-файл."
        ),
    },
    {
        "name": "tags",
        "description": (
            "Управление тегами конкретной статьи. "
            "Теги нормализуются в нижний регистр. Дубликаты не создаются."
        ),
    },
    {
        "name": "service",
        "description": "Служебные эндпоинты для мониторинга и health-check.",
    },
]

app = FastAPI(
    title="bkmrks",
    version="0.1.0",
    description=(
        "Инструмент для сохранения и чтения статей из интернета.\n\n"
        "**Как это работает:**\n"
        "1. Клиент отправляет URL страницы.\n"
        "2. Сервер скачивает HTML и извлекает основной текст (trafilatura).\n"
        "3. Статья сохраняется в ``data/articles/<uuid>.json``.\n"
        "4. К статье можно добавлять теги, искать по подстроке и фильтровать.\n\n"
        "Фронтенд - Vue 3 в каталоге ``static/``. Обращается к API "
        "через префикс ``/api``."
    ),
    contact={"name": "bkmrks GitHub", "url": "https://github.com/mochalow/bkmrks"},
    license_info={"name": "MIT"},
    openapi_tags=tags_metadata,
)


class ArticleIn(BaseModel):
    """Тело запроса на сохранение новой статьи."""

    url: HttpUrl = Field(
        description="Адрес страницы, которую нужно скачать и сохранить.",
        examples=["https://example.com/article"],
    )


class TagIn(BaseModel):
    """Тело запроса на добавление тега к статье."""

    tag: str = Field(
        min_length=1,
        description=(
            "Произвольная метка для группировки статей. "
            "Пробелы по краям обрезаются, регистр приводится к нижнему."
        ),
        examples=["python", "news"],
    )


class Article(BaseModel):
    """Полное представление сохранённой статьи.

    Возвращается всеми эндпоинтами, работающими со статьями.
    Поле ``content`` может быть объёмным - при списке статей
    клиент обычно показывает только заголовок и превью.
    """

    id: str = Field(
        description="Уникальный идентификатор статьи (UUID4).",
        examples=["3f2a1b4c-5d6e-7f8a-9b0c-1d2e3f4a5b6c"],
    )
    url: HttpUrl = Field(
        description="Исходный адрес сохранённой страницы.",
        examples=["https://example.com/article"],
    )
    saved_at: datetime = Field(
        description="Момент сохранения статьи в UTC (ISO 8601).",
        examples=["2026-07-06T12:00:00+00:00"],
    )
    title: str | None = Field(
        default=None,
        description="Заголовок, извлечённый парсером из метаданных страницы.",
        examples=["Пример статьи"],
    )
    content: str | None = Field(
        default=None,
        description="Очищенный текст статьи (plain text, абзацы через ``\\n``).",
        examples=["Первый абзац текста.\n\nВторой абзац."],
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Список тегов в нижнем регистре, уникальных в рамках статьи.",
        examples=[["python", "tutorial"]],
    )


# Ручки объявляются на роутере без префикса
router = APIRouter()


@router.post(
    "/articles",
    status_code=201,
    summary="Сохранить статью по URL",
    tags=["articles"],
    response_description="Созданная статья с извлечённым текстом.",
    responses={
        201: {"description": "Статья успешно скачана и сохранена."},
        422: {
            "description": (
                    "Не удалось скачать страницу или извлечь из неё текст. "
                    "Типичные причины: неверный URL, страница без основного контента, "
                    "блокировка со стороны сайта."
            ),
        },
    },
)
def create_article(payload: ArticleIn) -> Article:
    """Скачивает страницу, очищает её и сохраняет как новую статью.

    Генерирует UUID4 и фиксирует время сохранения в UTC.
    Теги при создании всегда пустые - их добавляют отдельными запросами.
    """
    article_id = str(uuid.uuid4())
    saved_at = datetime.now(timezone.utc).replace(microsecond=0)

    try:
        parsed = parser.parse(str(payload.url))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    article = Article(
        id=article_id,
        url=payload.url,
        saved_at=saved_at,
        title=parsed["title"],
        content=parsed["content"],
        tags=[],
    )

    storage.save(article.model_dump(mode="json"))

    return article


def _normalize(value: str | None) -> str:
    """Приводит строку к нижнему регистру, обрезая пробелы по краям."""
    return (value or "").strip().lower()


def _matches_query(article: dict, query: str) -> bool:
    """Проверяет, встречается ли подстрока ``query`` в заголовке или тексте."""
    title = (article.get("title") or "").lower()
    content = (article.get("content") or "").lower()
    return query in title or query in content


@router.get(
    "/articles",
    summary="Список статей с поиском и фильтром",
    tags=["articles"],
    response_description="Статьи, отсортированные по дате сохранения (новые первыми).",
)
def list_articles(
        q: str | None = Query(
            default=None,
            description=(
                    "Подстрока для поиска. Регистр не учитывается. "
                    "Ищет одновременно в заголовке и полном тексте статьи."
            ),
            examples=["python", "машинное обучение"],
        ),
        tag: str | None = Query(
            default=None,
            description=(
                    "Вернуть только статьи, у которых есть этот тег. "
                    "Сравнение после нормализации (нижний регистр, пробелы в начале/конце)."
            ),
            examples=["news"],
        ),
) -> list[Article]:
    """Возвращает все статьи с опциональной фильтрацией.

    Фильтры можно комбинировать: сначала отбираются статьи по тегу,
    затем из результата ищется подстрока ``q``. Без параметров
    возвращается полная библиотека.
    """
    articles = storage.load_all()

    if tag:
        needle = _normalize(tag)
        articles = [a for a in articles if needle in a.get("tags", [])]

    if q:
        needle = _normalize(q)
        articles = [a for a in articles if _matches_query(a, needle)]

    articles.sort(key=lambda a: a["saved_at"], reverse=True)
    return [Article(**a) for a in articles]


@router.get(
    "/articles/{article_id}",
    summary="Получить статью по id",
    tags=["articles"],
    response_description="Полная статья, включая текст.",
    responses={404: {"description": "Статья с таким id не найдена в хранилище."}},
)
def read_article(
        article_id: str = Path(
            description="UUID статьи из поля ``id``.",
            examples=["3f2a1b4c-5d6e-7f8a-9b0c-1d2e3f4a5b6c"],
        ),
) -> Article:
    """Загружает одну статью по UUID."""
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return Article(**data)


@router.delete(
    "/articles/{article_id}",
    status_code=204,
    summary="Удалить статью",
    tags=["articles"],
    responses={
        204: {"description": "Статья удалена. Тело ответа пустое."},
        404: {"description": "Статья с таким id не найдена."},
    },
)
def delete_article(article_id: str) -> Response:
    """Безвозвратно удаляет JSON-файл статьи с диска."""
    if not storage.delete(article_id):
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return Response(status_code=204)


@router.post(
    "/articles/{article_id}/tags",
    summary="Добавить тег к статье",
    tags=["tags"],
    response_description="Статья с обновлённым списком тегов.",
    responses={
        404: {"description": "Статья не найдена."},
        422: {"description": "Тег пустой после нормализации (только пробелы)."},
    },
)
def add_tag(article_id: str, payload: TagIn) -> Article:
    """Добавляет тег, если его ещё нет у статьи.

    Повторный запрос с тем же тегом идемпотентен: список не меняется,
    но статья возвращается в актуальном виде.
    """
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    tag = _normalize(payload.tag)
    if not tag:
        raise HTTPException(status_code=422, detail="Тег не может быть пустым")

    if tag not in data["tags"]:
        data["tags"].append(tag)
        storage.save(data)

    return Article(**data)


@router.delete(
    "/articles/{article_id}/tags/{tag}",
    summary="Удалить тег у статьи",
    tags=["tags"],
    response_description="Статья с обновлённым списком тегов.",
    responses={404: {"description": "Статья не найдена."}},
)
def remove_tag(article_id: str, tag: str) -> Article:
    """Удаляет тег из статьи.

    Если тега нет, операция считается успешной - возвращается статья
    без изменений (идемпотентное поведение).
    """
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    needle = _normalize(tag)
    if needle in data["tags"]:
        data["tags"].remove(needle)
        storage.save(data)

    return Article(**data)


@router.get(
    "/health",
    summary="Проверка состояния сервиса",
    tags=["service"],
    response_description="Сервис отвечает на запросы.",
)
def health() -> dict[str, str]:
    """Простой health-check."""
    return {"status": "ok"}


# Копирует маршруты, существующие на роутере в момент вызова
app.include_router(router, prefix="/api")

# Статика монтируется последней (абсолютный путь - корректный импорт из любой директории)
STATIC_DIR = PathlibPath(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
