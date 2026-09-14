"""Инвариант ``main._write_lock``: одновременные записи.

``main.py`` объявляет рядом с блокировкой: одновременные запросы не
создают дублей и не теряют теги.
Соседний ``test_duplicate_appearing_during_download_is_detected``
разыгрывает гонку однопоточно - побочным эффектом внутри подменённого
``parser.parse``, - и потому доказывает лишь то, что повторная проверка
под блокировкой существует.

Гонка здесь настоящая: FastAPI отправляет ``def``-обработчики в пул
потоков, а ``TestClient`` не сериализует запросы - блокирующим оказывается
поток вызывающего, а не цикл событий сервера.

Окно между чтением и записью расширяется задержкой в той функции
хранилища, через которую идёт чтение. Барьер на это место не годится:
остановить потоки внутри критической секции - значит получить
взаимоблокировку на исправном коде, то есть красный там, где всё
правильно.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import storage

RACERS = 5
"""Сколько запросов идёт одновременно."""

WINDOW = 0.05
"""На сколько расширяется окно между чтением и записью, секунды.

С блокировкой запросы выстраиваются в очередь и прогон стоит
``RACERS * WINDOW``; без неё все читают одно и то же состояние.
"""


def test_concurrent_creation_of_one_url_yields_one_article(client, parsed_page, monkeypatch):
    """Пять одновременных сохранений одного адреса дают одну статью.

    Дедупликация - главный кандидат на регрессию,
    и единственное, что защищает её при одновременных запросах, - это
    повторная проверка под блокировкой.
    """
    parsed_page()
    read_all = storage.load_all

    def slow_read_all():
        found = read_all()
        time.sleep(WINDOW)
        return found

    monkeypatch.setattr(storage, "load_all", slow_read_all)

    with ThreadPoolExecutor(max_workers=RACERS) as pool:
        statuses = sorted(
            response.status_code
            for response in pool.map(
                lambda _: client.post("/api/articles", json={"url": "https://example.com/a"}),
                range(RACERS),
            )
        )

    # Ровно один запрос создал статью, остальные получили её же.
    assert statuses == [200] * (RACERS - 1) + [201]
    assert len(client.get("/api/articles").json()) == 1


def test_concurrent_tag_additions_do_not_lose_each_other(client, stored_article, monkeypatch):
    """Пять одновременных тегов сохраняются все, а не последний.

    ``add_tag`` читает статью, дописывает тег в список и сохраняет
    целиком. Без блокировки это классическое потерянное обновление: все
    пятеро читают статью без тегов, каждый добавляет свой и записывает
    поверх соседа.
    """
    article = stored_article()
    read = storage.load

    def slow_read(article_id):
        found = read(article_id)
        time.sleep(WINDOW)
        return found

    monkeypatch.setattr(storage, "load", slow_read)

    tags = [f"тег{number}" for number in range(RACERS)]
    with ThreadPoolExecutor(max_workers=RACERS) as pool:
        list(pool.map(
            lambda tag: client.post(f"/api/articles/{article['id']}/tags", json={"tag": tag}),
            tags,
        ))

    saved = client.get(f"/api/articles/{article['id']}").json()["tags"]
    assert sorted(saved) == sorted(tags)
