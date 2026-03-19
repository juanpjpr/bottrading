from __future__ import annotations

from fastapi import APIRouter

from services.signal_engine.models import ComputeSignalsRequest
from services.signal_engine.service import SignalEngineService

router = APIRouter()
service = SignalEngineService()


@router.get("/health")
def health() -> dict:
    return service.health()


@router.post("/compute")
def compute_signals(payload: ComputeSignalsRequest) -> dict:
    return service.compute(payload)
