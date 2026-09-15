"""Служебные эндпоинты и контракт монтирования приложения."""

import subprocess
import sys
import warnings

import pytest
import uvicorn

import main


def test_health_returns_ok(client):
    """``/api/health`` отвечает 200 и телом ``{"status": "ok"}``."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_response_forbids_content_type_sniffing(client):
    """Middleware ставит ``X-Content-Type-Options`` на любой ответ."""
    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_cover_response_forbids_content_type_sniffing(client, parsed_page):
    """Заголовок стоит и на обложке - ради неё middleware и написан.

    Проверки на ``/api/health`` мало: она закрепляет только путь JSON.
    """
    parsed_page(image="https://example.com/cover.jpg", cover=(b"\xff\xd8binary", "image/jpeg"))
    created = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    response = client.get(created["image"])

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_unknown_api_path_returns_json_404(client):
    """Несуществующий ``/api/*`` отдаёт 404 с полем ``detail``.

    Статика смонтирована в корень последней и ловит всё, что не совпало
    с роутером, - но наружу это выглядит как обычная 404 с JSON-телом
    ``{"detail": "Not Found"}``, а не как отдача файла.

    Форма ответа важна для фронтенда: ``extractDetail`` в ``api.js``
    разбирает именно ``detail`` и показывает его пользователю.
    """
    response = client.get("/api/nonexistent")

    assert response.status_code == 404
    assert response.json()["detail"]


def test_root_serves_library_page(client):
    """Корень отдаёт страницу библиотеки (``StaticFiles(html=True)``).

    Проверка ``id="app"`` - не про вёрстку: это точка монтирования Vue,
    без которой фронтенд не запускается вообще. Утверждение отвечает на
    вопрос «отдали ли index.html приложения».
    """
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="app"' in response.text


def test_server_loads_no_websocket_implementation():
    """Прод-запуск не тянет реализацию WebSocket, тем более устаревшую.

    ``uvicorn main:app`` из ``CMD`` в Dockerfile поднимается с
    умолчанием ``ws="auto"``: при установленном пакете ``websockets``
    uvicorn импортирует ``websockets.legacy``, объявленный устаревшим.

    Приложение WebSocket не обслуживает ни одним маршрутом, поэтому
    правильное состояние - реализации нет вовсе. Утверждение фиксирует
    именно его; вернувшаяся в зависимости библиотека уронит этот тест.
    """
    config = uvicorn.Config(main.app)

    config.load()

    assert config.ws_protocol_class is None


@pytest.mark.parametrize(
    "category",
    [
        pytest.param(DeprecationWarning, id="устаревание"),
        pytest.param(ResourceWarning, id="незакрытый ресурс"),
    ],
)
def test_warnings_are_errors(category):
    """Предупреждение внутри теста поднимает исключение, а не пишется в отчёт.

    Правило живёт в ``pytest.ini`` одной строкой. Сторож адресует действие правила, а не
    текст конфига.

    Классы взяты не любые, а те два, на которые ссылаются живые
    докстринги: ``DeprecationWarning`` - устаревание ``websockets.legacy``
    у соседнего теста, ``ResourceWarning`` - незакрытый сокет в
    ``tests/e2e/conftest.py``. Сужение правила до ``error::UserWarning``
    оставило бы сторожа зелёным, а обоих зависимых - без защиты.
    """
    with pytest.raises(category):
        warnings.warn("сторож правила filterwarnings", category)


def test_the_anyio_deprecation_still_needs_its_exception():
    """Исключение в ``pytest.ini`` всё ещё покрывает живое устаревание.

    В ``filterwarnings`` стоит одна строка ``ignore`` - на сообщение, которое
    печатает ``starlette.testclient``, обращаясь к устаревшему псевдониму
    ``anyio.abc.BlockingPortal``. Чужой код чинить здесь нечем, поэтому
    исключение записано поимённо, а не классом целиком.

    Главный риск такой строки - молчаливо пережить свою причину: когда
    starlette перестанет печатать это сообщение, ``ignore`` останется и
    начнёт глушить чужое устаревание с тем же текстом. Ослабление правила
    из временного станет постоянным, и заметить это будет негде. Сторож
    делает момент громким: он краснеет ровно тогда, когда строку пора убрать.

    Импорт идёт отдельным процессом: в текущем ``starlette.testclient`` уже
    загружен конфтестом, а предупреждение печатается один раз - при первом
    импорте.
    """
    finished = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", "import starlette.testclient"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert finished.returncode != 0, (
        "starlette.testclient больше не трогает устаревший псевдоним anyio: "
        "уберите строку ignore из filterwarnings в pytest.ini вместе с этим сторожем"
    )
    assert "anyio.abc.BlockingPortal alias is deprecated" in finished.stderr, (
        "импорт starlette.testclient падает на другом устаревании, а не на том, "
        "под которое написано исключение в pytest.ini"
    )
