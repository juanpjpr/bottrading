from __future__ import annotations

from dataclasses import asdict

from bot_trading_news.ai_filter import apply_ai_news_filter
from bot_trading_news.config import BotConfig, load_config
from bot_trading_news.news import NewsArticle

from services.ai_filter_service.models import ArticleInput


class AIFilterService:
    """Servicio batch para enriquecer y filtrar noticias con heuristica u OpenAI."""

    def __init__(self, config: BotConfig | None = None) -> None:
        self.config = config or load_config()

    def health(self) -> dict:
        return {
            "ok": True,
            "service": "ai_filter_service",
            "mode": self.config.ai_filter_mode,
            "model": self.config.ai_filter_model or "gpt-4.1-mini",
            "openai_enabled": bool(self.config.openai_api_key and self.config.ai_filter_mode == "openai"),
            "min_relevance": self.config.ai_min_relevance,
        }

    def filter_articles(self, articles: list[ArticleInput]) -> dict:
        article_models = [self._to_article(item) for item in articles]
        filtered = apply_ai_news_filter(article_models, self.config)
        filtered_urls = {article.url for article in filtered if article.url}

        enriched_articles = []
        for article in filtered:
            enriched_articles.append(asdict(article))

        return {
            "mode": self.config.ai_filter_mode,
            "input_count": len(article_models),
            "filtered_count": len(filtered),
            "accepted_urls": sorted(filtered_urls),
            "articles": enriched_articles,
        }

    def _to_article(self, article: ArticleInput) -> NewsArticle:
        return NewsArticle(
            title=article.title,
            description=article.description,
            source=article.source,
            published_at=article.published_at,
            url=article.url,
        )
