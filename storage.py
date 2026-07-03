import json
from pathlib import Path

DATA_DIR = Path("data/articles")


def save(article: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{article['id']}.json"
    path.write_text(
        json.dumps(article, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load(article_id: str) -> dict | None:
    path = DATA_DIR / f"{article_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_all() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in DATA_DIR.glob("*.json")
    ]


def delete(article_id: str) -> bool:
    path = DATA_DIR / f"{article_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True