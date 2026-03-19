from __future__ import annotations

from fastapi import FastAPI

from services.market_data_service.routes import router

app = FastAPI(
    title="Market Data Service",
    version="0.1.0",
    description="Microservicio inicial para snapshots y factores cuantitativos de mercado.",
)
app.include_router(router)
