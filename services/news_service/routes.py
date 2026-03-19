from __future__ import annotations

from fastapi import APIRouter, Query

from services.news_service.service import NewsService

router = APIRouter()
service = NewsService()


@router.get("/health")
def health() -> dict:
    return service.health()


@router.get("/latest")
def latest(
    news_file: str = Query(default="sample_news.json"),
    fetch_news: bool = Query(default=False),
    query: str | None = Query(default=None),
) -> dict:
    return service.latest(news_file=news_file, fetch_news=fetch_news, query=query)
