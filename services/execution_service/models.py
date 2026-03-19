from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExecuteSignalRequest(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL"]
    score: float
    confidence: float
    expected_return_per_100: float = 0.0
    article_count: int = 0
    factor_scores: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    factor_notes: list[str] = Field(default_factory=list)


class ExecuteSignalsRequest(BaseModel):
    signals: list[ExecuteSignalRequest] = Field(default_factory=list)
