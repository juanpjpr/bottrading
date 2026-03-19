from __future__ import annotations

from fastapi import APIRouter

from services.ai_filter_service.models import FilterNewsRequest
from services.ai_filter_service.service import AIFilterService

router = APIRouter()
service = AIFilterService()


@router.get("/health")
def health() -> dict:
    return service.health()


@router.post("/filter")
def filter_news(payload: FilterNewsRequest) -> dict:
    return service.filter_articles(payload.articles)
