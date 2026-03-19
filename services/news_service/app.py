from __future__ import annotations

from fastapi import FastAPI

from services.news_service.routes import router

app = FastAPI(
    title="News Service",
    version="0.1.0",
    description="Microservicio inicial para ingesta, deduplicacion y cache de noticias.",
)
app.include_router(router)
