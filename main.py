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

import io
import json
import logging
import re
import threading
import urllib.parse
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path as PathlibPath

from fastapi import FastAPI, HTTPException, Response, APIRouter, Query, Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

import storage
import parser

logging.basicConfig(level=logging.INFO)

tags_metadata = [
    {
        "name": "articles",
        "description": (
            "Сохранение, чтение, поиск, экспорт и удаление статей. "
            "При создании страница скачивается и очищается через trafilatura, "
            "результат записывается в JSON-файл. Поддерживается дедупликация "
            "по нормализованному URL."
        ),
    },
    {
        "name": "tags",
        "description": (
            "Управление тегами конкретной статьи. "
            "Теги нормализуются в нижний регистр (:func:`_normalize_tag`). "
            "Дубликаты не создаются. Операции идемпотентны."
        ),
    },
    {
        "name": "service",
        "description": "Служебные эндпоинты для мониторинга и health-check.",
    },
]

app = FastAPI(
    title="bkmrks",
    version="0.2.0",
    description=(
        "Инструмент для сохранения и чтения статей из интернета.\n\n"
        "**Как это работает:**\n"
        "1. Клиент отправляет URL страницы.\n"
        "2. Сервер скачивает HTML и извлекает основной текст (trafilatura).\n"
        "3. Статья сохраняется в ``data/articles/<uuid>.json``.\n"
        "4. К статье можно добавлять теги, искать по подстроке и фильтровать.\n\n"
        "Фронтенд - Vue 3  в каталоге ``static/``. "
        "Обращается к API через префикс ``/api``.\n\n"
    ),
    contact={"name": "bkmrks GitHub", "url": "https://github.com/mochalow/bkmrks"},
    license_info={"name": "MIT"},
    openapi_tags=tags_metadata,
)


@app.middleware("http")
async def _security_headers(request, call_next):
    """Запрещает браузеру угадывать тип содержимого (защита в глубину).

    Устанавливает заголовок ``X-Content-Type-Options: nosniff``.
    Это страхует на случай отдачи обложек с несоответствующим
    Content-Type (браузер не попытается угадать тип по содержимому).
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class ArticleIn(BaseModel):
    """Тело запроса на сохранение новой статьи (POST /api/articles)."""

    url: HttpUrl = Field(
        description=(
            "Адрес страницы, которую нужно скачать и сохранить. "
            "Поддерживаются http/https. После сохранения URL нормализуется "
            "для дедупликации (см. :func:`_normalize_url`)."
        ),
        examples=["https://example.com/article"],
    )


class TagIn(BaseModel):
    """Тело запроса на добавление тега к статье (POST /api/articles/{id}/tags)."""

    tag: str = Field(
        min_length=1,
        description=(
            "Произвольная метка для группировки статей. "
            "Пробелы по краям обрезаются, регистр приводится к нижнему "
            "(:func:`_normalize_tag`). Символ ``/`` запрещён (ломает "
            "DELETE-маршрут)."
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
        description="Очищенный текст статьи (plain text с переносами строк между абзацами).",
        examples=["Первый абзац текста.\n\nВторой абзац."],
    )
    author: str | None = Field(
        default=None,
        description="Автор статьи, извлечённый из метаданных страницы.",
        examples=["Иван Иванов"],
    )
    date: str | None = Field(
        default=None,
        description="Дата публикации статьи, извлечённая из метаданных страницы.",
        examples=["2026-07-01"],
    )
    description: str | None = Field(
        default=None,
        description="Краткое описание страницы (обычно из meta description).",
        examples=["Статья о том, как..."],
    )
    sitename: str | None = Field(
        default=None,
        description="Название сайта-источника, извлечённое из метаданных страницы.",
        examples=["Example News"],
    )
    image: str | None = Field(
        default=None,
        description=(
            "Адрес обложки статьи, скачанной и сохранённой локально "
            "(см. ``GET /articles/{id}/image``). ``null``, если обложки нет."
        ),
        examples=["/api/articles/3f2a1b4c-5d6e-7f8a-9b0c-1d2e3f4a5b6c/image"],
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Список тегов в нижнем регистре, уникальных в рамках статьи.",
        examples=[["python", "tutorial"]],
    )


# Ручки объявляются на роутере без префикса
router = APIRouter()

# Блокируем все записи, чтобы не создавать дубли и не терять теги
# при одновременных запросах (один читает — другой пишет).
#
# Работает только внутри одного процесса. Если запустить uvicorn
# с несколькими воркерами — защита не сработает.
# Обычный запуск (uvicorn main:app или docker) — однопроцессный,
# поэтому всё в порядке.
_write_lock = threading.Lock()


@router.post(
    "/articles",
    status_code=201,
    summary="Сохранить статью по URL",
    description=(
            "Скачивает страницу, извлекает читаемый текст через trafilatura, "
            "сохраняет результат и опционально обложку. "
            "Если статья с эквивалентным URL уже существует - возвращает её "
            "со статусом 200 (идемпотентность)."
    ),
    tags=["articles"],
    response_description="Созданная или существующая статья.",
    responses={
        200: {
            "description": (
                    "Статья с таким URL (после нормализации через :func:`_normalize_url`) "
                    "уже сохранена - возвращена существующая статья, новая не создавалась."
            ),
        },
        201: {"description": "Статья успешно скачана и сохранена."},
        422: {
            "description": (
                    "Не удалось скачать страницу или извлечь из неё текст. "
                    "Типичные причины: неверный/непубличный URL, страница без основного "
                    "контента, блокировка, таймаут, слишком большой ответ."
            ),
        },
    },
)
def create_article(payload: ArticleIn, response: Response) -> Article:
    """Скачивает страницу, очищает её и сохраняет как новую статью.

    Если статья с таким же URL (после нормализации) уже сохранена,
    новая копия не создаётся - возвращается существующая статья со
    статусом 200 вместо 201.

    Генерирует UUID4 и фиксирует время сохранения в UTC.
    Теги при создании всегда пустые - их добавляют отдельными запросами
    (``POST /api/articles/{article_id}/tags``).
    """
    normalized_url = _normalize_url(str(payload.url))
    page_url = str(payload.url)

    # Быстрая проверка до скачивания: если статья с таким URL уже есть —
    # сразу возвращаем её, не тратим время на парсинг и загрузку картинки.
    #
    # Настоящая проверка под блокировкой будет чуть ниже.
    # Эта — просто оптимизация на частый случай «человек сохраняет повторно».
    if existing := _find_existing_by_url(normalized_url):
        response.status_code = 200
        return _article_from_storage(existing)

    parsed = _parse_page(page_url)
    fetched_image = _fetch_cover_image(parsed["image"], page_url)

    with _write_lock:
        if existing := _find_existing_by_url(normalized_url):
            response.status_code = 200
            return _article_from_storage(existing)
        return _persist_new_article(payload, parsed, fetched_image)


def _article_from_storage(data: dict) -> Article:
    """Собирает модель :class:`Article` из словаря, загруженного хранилищем.

    Используется всеми обработчиками, которые читают данные из
    :mod:`storage` и возвращают их клиенту.
    """
    return Article(
        id=data["id"],
        url=data["url"],
        saved_at=data["saved_at"],
        title=data.get("title"),
        content=data.get("content"),
        author=data.get("author"),
        date=data.get("date"),
        description=data.get("description"),
        sitename=data.get("sitename"),
        image=data.get("image"),
        tags=data.get("tags", []),
    )


def _normalize(value: str | None) -> str:
    """Приводит строку к нижнему регистру, обрезая пробелы по краям.

    Используется для поиска, тегов и сравнения URL-дублей.
    Пустое значение трактуется как пустая строка.
    """
    return (value or "").strip().lower()


def _normalize_tag(value: str | None) -> str:
    """Нормализует тег и отклоняет символ ``/`` (ломает DELETE-маршрут).

    Пустой тег после нормализации не отбрасывается
    здесь - это делает вызывающий код (чтобы вернуть точную 422 с
    понятным текстом).

    Raises:
        HTTPException: 422, если после нормализации тег содержит ``/``.
    """
    tag = _normalize(value)
    if "/" in tag:
        raise HTTPException(status_code=422, detail="Тег не может содержать символ /")
    return tag


def _matches_query(article: dict, query: str) -> bool:
    """Проверяет, встречается ли подстрока ``query`` в заголовке или тексте.

    Регистр не учитывается (``query`` уже нормализован вызывающим кодом).
    Используется в :func:`list_articles`.
    """
    title = (article.get("title") or "").lower()
    content = (article.get("content") or "").lower()
    return query in title or query in content


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "yclid",
}


def _find_existing_by_url(normalized_url: str) -> dict | None:
    """Возвращает сохранённую статью с каноническим URL или ``None``.

    Сканирует все статьи через :func:`storage.load_all`.
    Используется для дедупликации при создании.
    """
    for existing in storage.load_all():
        if _normalize_url(existing["url"]) == normalized_url:
            return existing
    return None


def _parse_page(url: str) -> dict:
    """Скачивает страницу через :mod:`parser` и превращает ошибки в HTTP 422.

    См. :func:`parser.parse`.
    """
    try:
        return parser.parse(url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _fetch_cover_image(
        image_url: str | None, page_url: str,
) -> tuple[bytes, str] | None:
    """Скачивает обложку до принятия решения о создании статьи.

    Обёртка над :func:`parser.fetch_image`. Возвращает ``None``, если
    ``image_url`` отсутствует. Ошибки внутри парсера не пробрасываются -
    отсутствие обложки не должно мешать сохранению статьи.
    """
    if not image_url:
        return None
    return parser.fetch_image(image_url, page_url)


def _cover_image_url(article_id: str) -> str:
    """Возвращает API-путь к обложке статьи (используется в JSON и ссылках)."""
    return f"/api/articles/{article_id}/image"


def _article_from_parsed(
        payload: ArticleIn,
        article_id: str,
        saved_at: datetime,
        parsed: dict,
        image_url: str | None,
) -> Article:
    """Собирает модель :class:`Article` из результата :func:`parser.parse`.

    Используется внутри :func:`_persist_new_article`. Теги на этом этапе
    всегда пустые.
    """
    return Article(
        id=article_id,
        url=payload.url,
        saved_at=saved_at,
        title=parsed["title"],
        content=parsed["content"],
        author=parsed["author"],
        date=parsed["date"],
        description=parsed["description"],
        sitename=parsed["sitename"],
        image=image_url,
        tags=[],
    )


def _persist_new_article(
        payload: ArticleIn,
        parsed: dict,
        fetched_image: tuple[bytes, str] | None,
) -> Article:
    """Создаёт статью под блокировкой дедупликации и передаёт запись в хранилище.

    Генерирует новый UUID, вызывает :func:`storage.save_article` (которая
    может сохранить обложку). Возвращает модель статьи.
    """
    article_id = str(uuid.uuid4())
    saved_at = datetime.now(timezone.utc).replace(microsecond=0)
    article = _article_from_parsed(payload, article_id, saved_at, parsed, image_url=None)
    cover_saved = storage.save_article(
        article.model_dump(mode="json"),
        fetched_image,
        image_ref=_cover_image_url(article_id),
    )
    if cover_saved:
        article.image = _cover_image_url(article_id)
    return article


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalize_url(url: str) -> str:
    """Делает из URL простой ключ, по которому можно понять,
    что это одна и та же статья.

    Нормализованный URL используется только для поиска дублей.
    Саму статью мы сохраняем с оригинальным адресом.

    Поэтому чистим:

    - домен в нижнем регистре, без www
    - http и https считаем одинаковыми
    - убираем порты :80 и :443
    - схлопываем лишние слэши, убираем финальный слэш
    - сортируем параметры запроса (чтобы порядок не влиял)
    - выкидываем utm_*, fbclid и другие метки трекеров
    - отбрасываем #фрагмент

    Это нужно, чтобы одна статья, расшаренная в разных местах
    с разными трекинг-ссылками, не сохранялась по нескольку раз.
    """
    parts = urllib.parse.urlsplit(url)

    query = urllib.parse.urlencode(sorted(
        (key, value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ))

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if parts.port is not None and parts.port != _DEFAULT_PORTS.get(parts.scheme.lower()):
        netloc = f"{host}:{parts.port}"

    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")

    return urllib.parse.urlunsplit(("http", netloc, path, query, ""))


@router.get(
    "/articles",
    summary="Список статей с поиском и фильтром",
    description=(
            "Возвращает статьи, отсортированные по дате сохранения (новые первыми). "
            "Поддерживает поиск по подстроке (в заголовке и контенте) и фильтр по тегу. "
            "Фильтры комбинируются (сначала тег, потом поиск)."
    ),
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
        articles = [
            a for a in articles
            if needle in a.get("tags", [])
        ]

    if q:
        needle = _normalize(q)
        articles = [a for a in articles if _matches_query(a, needle)]

    articles.sort(key=lambda a: a["saved_at"], reverse=True)
    return [_article_from_storage(a) for a in articles]


@router.get(
    "/export",
    summary="Экспорт всей библиотеки",
    description=(
            "Возвращает все статьи в указанном формате. "
            "``zip`` включает оригинальные JSON и скачанные изображения. "
            "``json`` - только метаданные и текст (без обложек)."
    ),
    tags=["articles"],
    response_description="Архив (zip) или JSON-массив всех статей.",
    responses={
        200: {
            "description": (
                    "Успешный экспорт. При ``format=zip`` - архив "
                    "с заголовком Content-Disposition. При ``format=json`` — "
                    "массив объектов Article."
            ),
        },
    },
)
def export_articles(
        format: str = Query(
            default="zip",
            pattern="^(zip|json)$",
            description=(
                    "``zip`` - каждая статья и обложка отдельным файлом, "
                    "точная копия структуры на диске. ``json`` - один массив "
                    "статей без обложек, компактный вариант для обработки."
            ),
        ),
):
    """Экспортирует всю библиотеку для резервной копии или переноса."""
    raw = storage.load_all()
    raw.sort(key=lambda a: a["saved_at"], reverse=True)
    articles = [_article_from_storage(a) for a in raw]

    if format == "json":
        return [a.model_dump(mode="json") for a in articles]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for article in articles:
            zf.writestr(
                f"articles/{article.id}.json",
                json.dumps(article.model_dump(mode="json"), ensure_ascii=False, indent=2),
            )
            image = storage.image_path(article.id)
            if image is not None:
                zf.write(image, f"images/{image.name}")

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=bkmrks-export.zip"},
    )


@router.get(
    "/articles/{article_id}",
    summary="Получить статью по id",
    description="Возвращает полную статью, включая очищенный текст в поле ``content``.",
    tags=["articles"],
    response_description="Полная статья, включая текст.",
    responses={404: {"description": "Статья с таким id не найдена в хранилище."}},
)
def read_article(
        article_id: uuid.UUID = Path(
            description="UUID статьи из поля ``id``.",
            examples=["3f2a1b4c-5d6e-7f8a-9b0c-1d2e3f4a5b6c"],
        ),
) -> Article:
    """Загружает одну статью по UUID из :mod:`storage`."""
    data = storage.load(str(article_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return _article_from_storage(data)


@router.get(
    "/articles/{article_id}/image",
    summary="Получить обложку статьи",
    tags=["articles"],
    response_description="Файл изображения обложки.",
    responses={404: {"description": "У статьи нет обложки, либо статья не найдена."}},
)
def read_article_image(article_id: uuid.UUID) -> FileResponse:
    """Отдаёт локально сохранённую обложку статьи, если она была скачана при сохранении."""
    path = storage.image_path(str(article_id))
    if path is None:
        raise HTTPException(status_code=404, detail="У статьи нет обложки")
    return FileResponse(path)


@router.delete(
    "/articles/{article_id}",
    status_code=204,
    summary="Удалить статью",
    description="Безвозвратно удаляет JSON-файл и (при наличии) обложку статьи.",
    tags=["articles"],
    responses={
        204: {"description": "Статья удалена. Тело ответа пустое."},
        404: {"description": "Статья с таким id не найдена."},
    },
)
def delete_article(article_id: uuid.UUID) -> Response:
    """Безвозвратно удаляет JSON-файл статьи с диска (и обложку, если есть).

    Операция выполняется под :data:`_write_lock`.
    """
    with _write_lock:
        if not storage.delete(str(article_id)):
            raise HTTPException(status_code=404, detail="Статья не найдена")
    return Response(status_code=204)


@router.get(
    "/tags",
    summary="Список тегов со счётчиками",
    description="Собирает все теги, встречающиеся хотя бы в одной статье, с количеством статей.",
    tags=["tags"],
    response_description="Теги и количество статей с каждым из них, по алфавиту.",
)
def list_tags() -> dict[str, int]:
    """Собирает теги по всем статьям, без скачивания их полного текста."""
    counts = Counter()
    for article in storage.load_all():
        counts.update(article.get("tags", []))
    return dict(sorted(counts.items(), key=lambda item: item[0]))


@router.post(
    "/articles/{article_id}/tags",
    summary="Добавить тег к статье",
    description="Нормализует тег и добавляет его к статье (без дубликатов).",
    tags=["tags"],
    response_description="Статья с обновлённым списком тегов.",
    responses={
        404: {"description": "Статья не найдена."},
        422: {
            "description": (
                    "Тег пустой после нормализации (только пробелы) "
                    "или содержит запрещённый символ ``/``."
            ),
        },
    },
)
def add_tag(article_id: uuid.UUID, payload: TagIn) -> Article:
    """Добавляет тег, если его ещё нет у статьи.

    Повторный запрос с тем же тегом идемпотентен: список не меняется,
    но статья возвращается в актуальном виде.

    Нормализация выполняется в :func:`_normalize_tag`.
    """
    tag = _normalize_tag(payload.tag)
    if not tag:
        raise HTTPException(status_code=422, detail="Тег не может быть пустым")

    with _write_lock:
        data = storage.load(str(article_id))
        if data is None:
            raise HTTPException(status_code=404, detail="Статья не найдена")
        if storage.add_tag(data, tag):
            storage.save(data)
        return _article_from_storage(data)


@router.delete(
    "/articles/{article_id}/tags/{tag}",
    summary="Удалить тег у статьи",
    description="Удаляет указанный тег (идемпотентно: если тега не было - ничего не меняется).",
    tags=["tags"],
    response_description="Статья с обновлённым списком тегов.",
    responses={404: {"description": "Статья не найдена."}},
)
def remove_tag(article_id: uuid.UUID, tag: str) -> Article:
    """Удаляет тег из статьи.

    Если тега нет, операция считается успешной - возвращается статья
    без изменений (идемпотентное поведение).

    Нормализация — через :func:`_normalize_tag`.
    """
    needle = _normalize_tag(tag)

    with _write_lock:
        data = storage.load(str(article_id))
        if data is None:
            raise HTTPException(status_code=404, detail="Статья не найдена")
        if storage.remove_tag(data, needle):
            storage.save(data)
        return _article_from_storage(data)


@router.get(
    "/health",
    summary="Проверка состояния сервиса",
    description="Используется Docker healthcheck.",
    tags=["service"],
    response_description="Сервис отвечает на запросы.",
)
def health() -> dict[str, str]:
    """Простой health-check. Возвращает ``{"status": "ok"}``."""
    return {"status": "ok"}


# Копирует маршруты, существующие на роутере в момент вызова
app.include_router(router, prefix="/api")

# Статика монтируется последней (абсолютный путь - корректный импорт из любой директории)
STATIC_DIR = PathlibPath(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
