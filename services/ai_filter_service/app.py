from __future__ import annotations

from fastapi import FastAPI

from services.ai_filter_service.routes import router

app = FastAPI(
    title="AI Filter Service",
    version="0.1.0",
    description="Microservicio inicial para filtrar y enriquecer noticias con heuristica u OpenAI.",
)
app.include_router(router)
