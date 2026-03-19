from __future__ import annotations

from fastapi import FastAPI

from services.signal_engine.routes import router

app = FastAPI(
    title="Signal Engine",
    version="0.1.0",
    description="Microservicio inicial para generar señales desde noticias, mercado y smart money.",
)
app.include_router(router)
