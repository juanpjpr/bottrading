from __future__ import annotations

from fastapi import FastAPI

from services.execution_service.routes import router

app = FastAPI(
    title="Execution Service",
    version="0.1.0",
    description="Microservicio inicial para cuenta, posiciones, actividad y ejecucion de ordenes.",
)
app.include_router(router)
