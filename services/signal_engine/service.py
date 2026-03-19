from __future__ import annotations

from dataclasses import asdict

from bot_trading_news.config import BotConfig, load_config
from bot_trading_news.market import MarketFactors
from bot_trading_news.news import NewsArticle
from bot_trading_news.smart_money import SmartMoneySignal, load_smart_money_signals
from bot_trading_news.strategy import HORIZON_PRESETS, analyze_articles, normalize_horizon

from services.signal_engine.models import (
    ArticleInput,
    ComputeSignalsRequest,
    MarketFactorInput,
    SmartMoneyInput,
)


class SignalEngineService:
    """Motor de señales desacoplado para consumir noticias ya enriquecidas y factores externos."""

    def __init__(self, config: BotConfig | None = None) -> None:
        self.config = config or load_config()

    def health(self) -> dict:
        return {
            "ok": True,
            "service": "signal_engine",
            "watchlist_size": len(self.config.watchlist),
            "horizons": list(HORIZON_PRESETS.keys()),
            "smart_money_mode": self.config.smart_money_mode,
        }

    def compute(self, payload: ComputeSignalsRequest) -> dict:
        horizon_key = normalize_horizon(payload.horizon)
        articles = [self._to_article(article) for article in payload.articles]
        market_factors = self._to_market_factors(payload.market_factors)
        smart_money_signals = self._to_smart_money(payload.smart_money_signals)

        if not smart_money_signals:
            smart_money_signals = load_smart_money_signals(self.config)

        signals = analyze_articles(
            articles,
            self.config,
            market_factors=market_factors or None,
            smart_money_signals=smart_money_signals or None,
            horizon=horizon_key,
        )

        return {
            "horizon": {
                "key": horizon_key,
                "label": HORIZON_PRESETS[horizon_key]["label"],
                "window_label": HORIZON_PRESETS[horizon_key]["window_label"],
            },
            "count": len(signals),
            "signals": [asdict(signal) for signal in signals],
        }

    def _to_article(self, article: ArticleInput) -> NewsArticle:
        return NewsArticle(
            title=article.title,
            description=article.description,
            source=article.source,
            published_at=article.published_at,
            url=article.url,
            ai_relevance=article.ai_relevance,
            ai_impact=article.ai_impact,
            ai_direction=article.ai_direction,
            ai_summary=article.ai_summary,
            ai_tradable=article.ai_tradable,
        )

    def _to_market_factors(self, items: list[MarketFactorInput]) -> dict[str, MarketFactors]:
        mapped: dict[str, MarketFactors] = {}
        for item in items:
            mapped[item.symbol.upper()] = MarketFactors(
                symbol=item.symbol.upper(),
                price_momentum=item.price_momentum,
                volume_trend=item.volume_trend,
                volatility=item.volatility,
                regime_score=item.regime_score,
                regime_label=item.regime_label,
                backtest_hit_rate=item.backtest_hit_rate,
                backtest_avg_return=item.backtest_avg_return,
                relative_strength=item.relative_strength,
                benchmark_momentum=item.benchmark_momentum,
                benchmark_symbol=item.benchmark_symbol,
                market_breadth=item.market_breadth,
                sector_breadth=item.sector_breadth,
                sector_relative_strength=item.sector_relative_strength,
                sector_group=item.sector_group,
            )
        return mapped

    def _to_smart_money(self, items: list[SmartMoneyInput]) -> dict[str, SmartMoneySignal]:
        mapped: dict[str, SmartMoneySignal] = {}
        for item in items:
            mapped[item.symbol.upper()] = SmartMoneySignal(
                symbol=item.symbol.upper(),
                conviction_score=item.conviction_score,
                manager_count=item.manager_count,
                crowding_risk=item.crowding_risk,
                top_managers=item.top_managers,
                source=item.source,
            )
        return mapped
