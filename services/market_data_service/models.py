from __future__ import annotations

from pydantic import BaseModel, Field


class MarketQuery(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    days: int = 10
    market_file: str | None = "sample_market_data.json"
