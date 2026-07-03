import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, HttpUrl

import storage
import parser


app = FastAPI()

class ArticleIn(BaseModel):
    url: HttpUrl

class TagIn(BaseModel):
    tag: str

class Article(BaseModel):
    id: str
    url: HttpUrl
    saved_at: datetime
    title: str | None = None
    content: str | None = None
    tags: list[str] = Field(default_factory=list)

@app.post("/articles", status_code=201)
def create_article(payload: ArticleIn) -> Article:

    article_id = str(uuid.uuid4())
    saved_at = datetime.now().replace(microsecond=0)

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

    # Готовим словарь для сохранения в JSON
    save_data = {
        "id": article.id,
        "url": str(article.url),
        "saved_at": article.saved_at.isoformat(),
        "title": article.title,
        "content": article.content,
        "tags": article.tags,
    }
    storage.save(save_data)

    return article


@app.get("/articles")
def list_articles(q: str | None = None, tag: str | None = None) -> list[Article]:
    articles = storage.load_all()

    # Фильтр по тегу
    if tag:
        search = tag.strip().lower()

        filtered_articles = []
        for article in articles:
            tags = article.get("tags", [])
            if search in tags:
                filtered_articles.append(article)

        articles = filtered_articles

    # Поиск: подстрока в заголовке или тексте
    if q:
        search = q.strip().lower()

        filtered_articles = []
        for article in articles:
            title = article.get("title") or ""
            content = article.get("content") or ""

            if search in title.lower() or search in content.lower():
                filtered_articles.append(article)

        articles = filtered_articles

    # Новые статьи сверху
    articles.sort(key=lambda a: a["saved_at"], reverse=True)

    return [Article(**a) for a in articles]

@app.get("/articles/{article_id}")
def read_article(article_id: str) -> Article:
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return Article(**data)


@app.delete("/articles/{article_id}", status_code=204)
def delete_article(article_id: str) -> Response:
    if not storage.delete(article_id):
        raise HTTPException(status_code=404, detail="Article not found")
    return Response(status_code=204)


@app.post("/articles/{article_id}/tags")
def add_tag(article_id: str, payload: TagIn) -> Article:
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Article not found")

    tag = payload.tag.strip().lower()
    if not tag:
        raise HTTPException(status_code=422, detail="Тег не может быть пустым")

    if tag not in data["tags"]:
        data["tags"].append(tag)
        storage.save(data)

    return Article(**data)


@app.delete("/articles/{article_id}/tags/{tag}")
def remove_tag(article_id: str, tag: str) -> Article:
    data = storage.load(article_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Article not found")

    # Если тега нет, просто возвращаем статью без изменений
    search = tag.strip().lower()
    if search in data["tags"]:
        data["tags"].remove(search)
        storage.save(data)

    return Article(**data)


@app.get("/health")
def health():
    return {"status": "ok"}