# bkmrks

Приложение для сохранения, очистки и удобной организации статей из интернета.  
Сохраняете URL -> приложение скачивает страницу, убирает рекламу, навигацию и мусор, сохраняет чистый читаемый текст.
Добавляйте теги вручную, ищите по словам и фильтруйте библиотеку.

<div>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Vue.js](https://img.shields.io/badge/Vue.js-3-4FC08D?logo=vuedotjs&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

</div>

## Возможности

- Сохранение статьи по URL с автоматической очисткой через **trafilatura**
- Обложки статей: скачивание при сохранении, локальное хранение, отдача через API
- Хранение данных в JSON-файлах на диске (`data/articles/`, `data/images/`)
- Поиск по ключевым словам в заголовке и содержимом
- Фильтрация статей по тегам
- Добавление и удаление тегов
- Экспорт всей библиотеки в ZIP (со статьями и обложками) или JSON (только метаданные и текст)
- Читалка с масштабированием шрифта, сохранением выбора в браузере
- Светлая и тёмная тема (следует системной настройке или явному выбору)
- Горячая клавиша `/` для фокуса на поиске в библиотеке

### Экспорт

| Формат               | Содержимое                                                                                                                               |
|----------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `zip` (по умолчанию) | `articles/<uuid>.json` - по файлу на статью, как на диске, `images/<uuid>.<ext>` - обложки, если есть. Точная копия структуры хранилища. |
| `json`               | Один JSON со всеми статьями. Компактный вариант для обработки, **без обложек** (в поле `image` остаётся API-путь).                       |

## Технологии

| Компонент        | Технология             |
|------------------|------------------------|
| Веб-фреймворк    | `FastAPI` + `Uvicorn`  |
| Парсинг статей   | `trafilatura`          |
| Хранение файлов  | `JSON`                 |
| Контейнеризация  | `Docker`               |
| Валидация данных | `Pydantic`             |
| Язык             | `Python`               |
| Фронтенд         | `Vue 3` + `HTML`+`CSS` |

## Требования

- `Docker` и `Docker Compose` **или**
- `Python 3.12` для локального запуска без контейнера.

## Запуск

### В контейнере

```bash
git clone https://github.com/mochalow/bkmrks
cd bkmrks
docker compose up --build
```

Приложение поднимется на `http://localhost:8000`. Данные живут в именованном
томе `bkmrks-data`.

### Без контейнера

```bash
git clone https://github.com/mochalow/bkmrks
cd bkmrks
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Приложение поднимется на `http://localhost:8000`. Данные живут в `data/articles/` рядом
с кодом.

## Документация

Проект документирован в трёх форматах: **OpenAPI** (FastAPI), **Sphinx** (Python) и **JSDoc** (JavaScript).

### OpenAPI / Swagger (FastAPI)

Интерактивная документация API генерируется автоматически.

| Ресурс     | Адрес                                | Что это                                                           |
|------------|--------------------------------------|-------------------------------------------------------------------|
| Swagger UI | `http://localhost:8000/docs`         | Интерактивная документация. Ручки можно дёргать прямо из браузера |
| ReDoc      | `http://localhost:8000/redoc`        | Альтернативное представление того же API                          |
| OpenAPI    | `http://localhost:8000/openapi.json` | Машиночитаемое описание API                                       |

### Sphinx (Python) и JSDoc (JavaScript)

Статическая документация: Python-модули (`main`, `parser`, `storage`) и клиентский JavaScript (`api`, `format`,
`library`, `reader` в `static/js/`).

```bash
# 1. Системные пакеты: Python, venv, Node.js, make, git
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm make git

# 2. Клонирование
git clone https://github.com/mochalow/bkmrks
cd bkmrks

# 3. Python-окружение: сначала зависимости проекта (нужны autodoc), потом Sphinx
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # Без этого import main упадёт при сборке
pip install -r docs/requirements.txt   # Sphinx, тема Furo и MyST

# 4. Node.js-зависимости (нужны для JSDoc)
cd docs && npm install && cd ..

# 5. Сборка
make -C docs docs          # Всё: Sphinx + JSDoc
make -C docs docs-py       # Только Sphinx (Python)
make -C docs docs-js       # Только JSDoc (JavaScript)
make -C docs docs-clean    # Удалить docs/_build/Как
```

| Формат             | Результат                     |
|--------------------|-------------------------------|
| Sphinx (Python)    | `docs/_build/html/index.html` |
| JSDoc (JavaScript) | `docs/_build/js/index.html`   |

