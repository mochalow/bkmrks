import trafilatura

def parse(url: str) -> dict:
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        raise ValueError(f"Не удалось скачать страницу: {url}")

    content = trafilatura.extract(downloaded, include_comments=False)
    if content is None:
        raise ValueError(f"Не удалось извлечь текст статьи: {url}")

    metadata = trafilatura.extract_metadata(downloaded)
    if metadata:
        title = metadata.title
    else:
        title = None

    return {"title": title, "content": content}