"""Извлечение чистого текста статьи из веб-страницы.

Модуль оборачивает библиотеку *trafilatura*: скачивает HTML по URL,
убирает навигацию, рекламу и служебную разметку, возвращает заголовок
и основной текст. Используется при сохранении новой статьи через API.

Пример::

    from parser import parse

    result = parse("https://example.com/article")
    print(result["title"], len(result["content"]))
"""

import trafilatura


def parse(url: str) -> dict:
    """Скачивает страницу и извлекает из неё читаемый текст.

    Args:
        url: Полный HTTP(S)-адрес страницы.

    Returns:
        Словарь с ключами:

        * ``title`` - заголовок из метаданных страницы или ``None``,
          если trafilatura его не нашла.
        * ``content`` - очищенный текст статьи в виде plain text
          с переносами строк между абзацами.

    Raises:
        ValueError: Если страницу не удалось скачать или из HTML
            не получилось извлечь содержимое статьи.
    """
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        raise ValueError(f"Не удалось скачать страницу: {url}")

    content = trafilatura.extract(downloaded, include_comments=False)
    if content is None:
        raise ValueError(f"Не удалось извлечь текст статьи: {url}")

    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata else None

    return {"title": title, "content": content}
