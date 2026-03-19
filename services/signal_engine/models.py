from __future__ import annotations

from pydantic import BaseModel, Field


class ArticleInput(BaseModel):
    title: str = ""
    description: str = ""
    source: str = "unknown"
    published_at: str = ""
    url: str = ""
    ai_relevance: float = 1.0
    ai_impact: float = 0.0
    ai_direction: float = 0.0
    ai_summary: str = ""
    ai_tradable: bool = True


class MarketFactorInput(BaseModel):
    symbol: str
    price_momentum: float = 0.0
    volume_trend: float = 0.0
    volatility: float = 0.0
    regime_score: float = 0.0
    regime_label: str = "Mixto"
    backtest_hit_rate: float = 0.0
    backtest_avg_return: float = 0.0
    relative_strength: float = 0.0
    benchmark_momentum: float = 0.0
    benchmark_symbol: str = "SPY"
    market_breadth: float = 0.0
    sector_breadth: float = 0.0
    sector_relative_strength: float = 0.0
    sector_group: str = "broad_market"


class SmartMoneyInput(BaseModel):
    symbol: str
    conviction_score: float = 0.0
    manager_count: int = 0
    crowding_risk: float = 0.0
    top_managers: list[str] = Field(default_factory=list)
    source: str = "sample"


class ComputeSignalsRequest(BaseModel):
    articles: list[ArticleInput] = Field(default_factory=list)
    horizon: str = "medium"
    market_factors: list[MarketFactorInput] = Field(default_factory=list)
    smart_money_signals: list[SmartMoneyInput] = Field(default_factory=list)
