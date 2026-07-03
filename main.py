import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl

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

    return article

@app.get("/health")
def health():
    return {"status": "ok"}