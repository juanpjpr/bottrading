from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from bot_trading_news.config import BotConfig


@dataclass(slots=True)
class NewsArticle:
    title: str
    description: str
    source: str
    published_at: str
    url: str
    ai_relevance: float = 1.0
    ai_impact: float = 0.0
    ai_direction: float = 0.0
    ai_summary: str = ""
    ai_tradable: bool = True

    @property
    def combined_text(self) -> str:
        return f"{self.title} {self.description}".strip()

    @property
    def published_datetime(self) -> datetime | None:
        if not self.published_at:
            return None

        normalized = self.published_at.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None


def load_news_from_file(file_path: str) -> list[NewsArticle]:
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    return [_build_article(item) for item in payload]


def fetch_daily_news(config: BotConfig, query: str | None = None) -> list[NewsArticle]:
    if not config.news_api_key:
        raise ValueError("Falta NEWS_API_KEY para consultar noticias desde la API.")

    now = datetime.now(UTC)
    from_date = (now - timedelta(days=2)).date().isoformat()
    params = {
        "q": query or "(stock market OR stocks OR bitcoin OR earnings OR fed OR inflation OR tariffs OR oil)",
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 50,
        "apiKey": config.news_api_key,
    }
    response = requests.get(config.news_api_url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    articles = data.get("articles", [])
    return [_build_article(item) for item in articles]


def _build_article(item: dict) -> NewsArticle:
    source = item.get("source")
    if isinstance(source, dict):
        source_name = source.get("name", "unknown")
    else:
        source_name = str(source or "unknown")

    return NewsArticle(
        title=str(item.get("title", "")),
        description=str(item.get("description", "")),
        source=source_name,
        published_at=str(item.get("publishedAt", "")),
        url=str(item.get("url", "")),
    )
