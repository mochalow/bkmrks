import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response, APIRouter
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

import storage
import parser

tags_metadata = [
    {"name": "articles",
     "description": "Сохранение, чтение, поиск и удаление статей."},

    {"name": "tags",
     "description": "Управление тегами конкретной статьи."},

    {"name": "service",
     "description": "Служебные эндпоинты."}
]

app = FastAPI(
    title="bkmrks",
    description=("Инструмент для сохранения и чтения статей. "
                 "Сохраняет URL, очищает страницу через trafilatura и хранит "
                 "результат в JSON-файлах. Поддерживает теги, поиск и фильтрацию по тегам. "),
    openapi_tags=tags_metadata)


class ArticleIn(BaseModel):
    url: HttpUrl = Field(description="Адрес страницы, которую нужно скачать и сохранить.",
                         examples=["https://example.com/article"])


class TagIn(BaseModel):
    tag: str = Field(description="Тег для добавления. Нормализуется в нижний регистр.",
                     examples=["python"])


class Article(BaseModel):
    id: str = Field(description="Уникальный идентификатор статьи (UUID4).")
    url: HttpUrl = Field(description="Исходный адрес сохранённой страницы.")
    saved_at: datetime = Field(description="Момент сохранения статьи (ISO 8601).")
    title: str | None = Field(
        default=None,
        description="Заголовок статьи, извлечённый парсером. Может отсутствовать.")
    content: str | None = Field(
        default=None,
        description="Очищенный текст статьи.")
    tags: list[str] = Field(
        default_factory=list,
        description="Список тегов статьи в нижнем регистре.")


# Ручки объявляются на роутере без префикса
router = APIRouter()


@router.post("/articles", status_code=201, summary="Сохранить статью по URL", tags=["articles"],
             responses={422: {"description": "Не удалось скачать или извлечь текст страницы"}})
def create_article(payload: ArticleIn) -> Article:
    article_id = str(uuid.uuid4())
    saved_at = datetime.now(timezone.utc).replace(microsecond=0)

    # Скачиваем страницу и очищаем её от мусора
    try:
        parsed = parser.parse(str(payload.url))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Создаём объект статьи
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
    return (value or "").strip().lower()


def _matches_query(article: dict, query: str) -> bool:
    title = (article.get("title") or "").lower()
    content = (article.get("content") or "").lower()
    return query in title or query in content


@router.get("/articles", summary="Список статей с поиском и фильтром", tags=["articles"])
def list_articles(q: str | None = None, tag: str | None = None) -> list[Article]:
    articles = storage.load_all()

    # Фильтр по тегу
    if tag:
        needle = _normalize(tag)
        articles = [a for a in articles if needle in a.get("tags", [])]

    # Поиск: подстрока в заголовке или тексте
    if q:
        needle = _normalize(q)
        articles = [a for a in articles if _matches_query(a, needle)]

    articles.sort(key=lambda a: a["saved_at"], reverse=True)
    return [Article(**a) for a in articles]


@router.get("/articles/{article_id}", summary="Получить статью по id", tags=["articles"],
            responses={404: {"description": "Статья не найдена"}})
def read_article(article_id: str) -> Article:
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return Article(**data)


@router.delete("/articles/{article_id}", status_code=204, summary="Удалить статью", tags=["articles"],
               responses={204: {"description": "Статья удалена"}, 404: {"description": "Статья не найдена"}})
def delete_article(article_id: str) -> Response:
    if not storage.delete(article_id):
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return Response(status_code=204)


@router.post("/articles/{article_id}/tags", summary="Добавить тег к статье", tags=["tags"],
             responses={404: {"description": "Статья не найдена"}, 422: {"description": "Тег пустой"}})
def add_tag(article_id: str, payload: TagIn) -> Article:
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


@router.delete("/articles/{article_id}/tags/{tag}", summary="Удалить тег у статьи", tags=["tags"],
               responses={404: {"description": "Статья не найдена"}})
def remove_tag(article_id: str, tag: str) -> Article:
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    # Если тега нет, просто возвращаем статью без изменений
    needle = _normalize(tag)
    if needle in data["tags"]:
        data["tags"].remove(needle)
        storage.save(data)

    return Article(**data)


@router.get("/health", summary="Проверка состояния сервиса", tags=["service"])
def health():
    return {"status": "ok"}


# Копирует маршруты, существующие на роутере в момент вызова
app.include_router(router, prefix="/api")

# Статика монтируется последней
app.mount("/", StaticFiles(directory="static", html=True), name="static")
