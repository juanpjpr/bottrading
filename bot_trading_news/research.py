from __future__ import annotations

import json
from pathlib import Path

from bot_trading_news.market import MarketFactors
from bot_trading_news.news import NewsArticle
from bot_trading_news.smart_money import SmartMoneySignal
from bot_trading_news.strategy import Signal


def build_research_report(
    signals: list[Signal],
    articles: list[NewsArticle],
    market_factors: dict[str, MarketFactors] | None = None,
    smart_money_signals: dict[str, SmartMoneySignal] | None = None,
    output_path: str = "research_report.json",
) -> Path:
    report_path = Path(output_path)
    validation = _build_validation_summary(market_factors or {})
    payload = {
        "summary": {
            "signal_count": len(signals),
            "article_count": len(articles),
            "top_signal": signals[0].symbol if signals else None,
            "average_confidence": round(
                sum(signal.confidence for signal in signals) / len(signals), 1
            ) if signals else 0.0,
        },
        "validation": validation,
        "smart_money": _build_smart_money_summary(smart_money_signals or {}),
        "signals": [
            {
                "symbol": signal.symbol,
                "action": signal.action,
                "score": signal.score,
                "confidence": signal.confidence,
                "expected_return_per_100": signal.expected_return_per_100,
                "article_count": signal.article_count,
                "factor_scores": signal.factor_scores,
                "factor_notes": signal.factor_notes,
                "reasons": signal.reasons,
            }
            for signal in signals
        ],
        "articles": [
            {
                "source": article.source,
                "title": article.title,
                "published_at": article.published_at,
                "url": article.url,
            }
            for article in articles[:20]
        ],
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return report_path


def _build_validation_summary(market_factors: dict[str, MarketFactors]) -> dict:
    if not market_factors:
        return {
            "assets_analyzed": 0,
            "avg_hit_rate": 0.0,
            "avg_return": 0.0,
        }

    values = list(market_factors.values())
    return {
        "assets_analyzed": len(values),
        "avg_hit_rate": round(sum(item.backtest_hit_rate for item in values) / len(values), 1),
        "avg_return": round(sum(item.backtest_avg_return for item in values) / len(values), 2),
    }


def _build_smart_money_summary(smart_money_signals: dict[str, SmartMoneySignal]) -> dict:
    if not smart_money_signals:
        return {
            "assets_covered": 0,
            "avg_conviction": 0.0,
            "top_managers": [],
        }

    values = list(smart_money_signals.values())
    managers: list[str] = []
    for item in values[:5]:
        managers.extend(item.top_managers[:2])
    return {
        "assets_covered": len(values),
        "avg_conviction": round(sum(item.conviction_score for item in values) / len(values), 2),
        "top_managers": managers[:8],
    }
