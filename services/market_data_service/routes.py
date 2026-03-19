from __future__ import annotations

from fastapi import APIRouter, Query

from services.market_data_service.service import MarketDataService

router = APIRouter()
service = MarketDataService()


@router.get("/health")
def health() -> dict:
    return service.health()


@router.get("/snapshots")
def get_snapshots(
    symbols: str | None = Query(default=None),
    days: int = Query(default=10, ge=6, le=60),
    market_file: str | None = Query(default="sample_market_data.json"),
) -> dict:
    symbol_list = symbols.split(",") if symbols else None
    return service.get_snapshots(symbol_list, days=days, market_file=market_file)


@router.get("/factors")
def get_factors(
    symbols: str | None = Query(default=None),
    days: int = Query(default=10, ge=6, le=60),
    market_file: str | None = Query(default="sample_market_data.json"),
) -> dict:
    symbol_list = symbols.split(",") if symbols else None
    return service.get_factors(symbol_list, days=days, market_file=market_file)
