from __future__ import annotations

from fastapi import APIRouter

from services.execution_service.models import ExecuteSignalsRequest
from services.execution_service.service import ExecutionService

router = APIRouter()
service = ExecutionService()


@router.get("/health")
def health() -> dict:
    return service.health()


@router.get("/account")
def get_account() -> dict:
    return service.get_account()


@router.get("/positions")
def get_positions() -> dict:
    return service.get_positions()


@router.get("/activity")
def get_activity() -> dict:
    return service.get_activity()


@router.post("/execute")
def execute_orders(payload: ExecuteSignalsRequest) -> dict:
    return service.execute(payload.signals)
