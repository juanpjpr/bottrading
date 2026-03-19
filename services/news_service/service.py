from __future__ import annotations

from dataclasses import asdict
from time import time

from bot_trading_news.config import BotConfig, load_config
from bot_trading_news.news import NewsArticle, fetch_daily_news, load_news_from_file


class NewsService:
    """Ingesta de noticias con cache corta y deduplicacion basica."""

    def __init__(self, config: BotConfig | None = None, ttl_seconds: int = 45) -> None:
        self.config = config or load_config()
        self.ttl_seconds = ttl_seconds
        self._cache: dict[tuple, tuple[float, dict]] = {}

    def health(self) -> dict:
        return {
            "ok": True,
            "service": "news_service",
            "news_api_enabled": bool(self.config.news_api_key),
            "news_api_url": self.config.news_api_url,
        }

    def latest(self, news_file: str = "sample_news.json", fetch_news: bool = False, query: str | None = None) -> dict:
        cache_key = (news_file, fetch_news, query or "")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return {"source": "cache", **cached}

        if fetch_news and self.config.news_api_key:
            try:
                articles = fetch_daily_news(self.config, query=query)
                source = "api"
            except Exception:
                articles = load_news_from_file(news_file)
                source = "sample"
        else:
            articles = load_news_from_file(news_file)
            source = "sample"

        deduped = self._dedupe_articles(articles)
        payload = {
            "count": len(deduped),
            "source": source,
            "articles": [asdict(article) for article in deduped],
            "sources": sorted({article.source for article in deduped if article.source}),
        }
        self._cache[cache_key] = (time(), payload)
        return payload

    def _dedupe_articles(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        seen: set[str] = set()
        unique: list[NewsArticle] = []
        for article in articles:
            key = (article.url or f"{article.source}|{article.title}").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(article)
        return unique

    def _get_cached(self, key: tuple) -> dict | None:
        item = self._cache.get(key)
        if not item:
            return None
        created_at, payload = item
        if time() - created_at > self.ttl_seconds:
            self._cache.pop(key, None)
            return None
        return payload
