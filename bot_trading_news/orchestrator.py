from __future__ import annotations

from dataclasses import asdict

import requests

from bot_trading_news.ai_filter import apply_ai_news_filter
from bot_trading_news.broker import build_broker, load_bot_activity, load_live_bot_activity
from bot_trading_news.market import MarketFactors, load_market_factors
from bot_trading_news.news import NewsArticle, fetch_daily_news, load_news_from_file
from bot_trading_news.strategy import Signal, analyze_articles


def load_articles_any(config, news_file: str, fetch_news: bool, query: str | None) -> list[NewsArticle]:
    return load_articles_with_status(config, news_file, fetch_news, query)[0]


def load_articles_with_status(config, news_file: str, fetch_news: bool, query: str | None) -> tuple[list[NewsArticle], dict]:
    if config.news_service_url:
        try:
            articles = _load_articles_remote(config.news_service_url, news_file, fetch_news, query)
            return articles, {"module": "news", "mode": "remote", "ok": True, "detail": f"news_service activo, articulos={len(articles)}"}
        except Exception as exc:
            remote_error = str(exc)
    else:
        remote_error = None
    if fetch_news and config.news_api_key:
        try:
            articles = fetch_daily_news(config, query=query)
            if articles:
                detail = f"NewsAPI directo, articulos={len(articles)}"
                if remote_error:
                    detail += f" | fallback remote: {remote_error}"
                return articles, {"module": "news", "mode": "local", "ok": True, "detail": detail}
        except Exception as exc:
            local_error = str(exc)
    else:
        local_error = None
    articles = load_news_from_file(news_file)
    detail = f"archivo local {news_file}, articulos={len(articles)}"
    if remote_error:
        detail += f" | fallback remote: {remote_error}"
    if local_error:
        detail += f" | fallback api: {local_error}"
    return articles, {"module": "news", "mode": "local", "ok": True, "detail": detail}


def apply_ai_filter_any(config, articles: list[NewsArticle]) -> list[NewsArticle]:
    return apply_ai_filter_with_status(config, articles)[0]


def apply_ai_filter_with_status(config, articles: list[NewsArticle]) -> tuple[list[NewsArticle], dict]:
    if config.ai_filter_service_url:
        try:
            filtered = _apply_ai_filter_remote(config.ai_filter_service_url, articles)
            return filtered, {"module": "ai_filter", "mode": "remote", "ok": True, "detail": f"ai_filter_service activo, quedaron={len(filtered)}"}
        except Exception as exc:
            remote_error = str(exc)
    else:
        remote_error = None
    try:
        filtered = apply_ai_news_filter(articles, config)
        detail = f"filtro local {config.ai_filter_mode}, quedaron={len(filtered)}"
        if remote_error:
            detail += f" | fallback remote: {remote_error}"
        return filtered, {"module": "ai_filter", "mode": "local", "ok": True, "detail": detail}
    except Exception as exc:
        return articles, {"module": "ai_filter", "mode": "local", "ok": False, "detail": f"filtro IA fallo, se sigue sin filtrar: {exc}"}


def load_market_factors_any(config, market_file: str) -> dict[str, MarketFactors]:
    return load_market_factors_with_status(config, market_file)[0]


def load_market_factors_with_status(config, market_file: str) -> tuple[dict[str, MarketFactors], dict]:
    if config.market_data_service_url:
        try:
            factors = _load_market_factors_remote(config.market_data_service_url, market_file, config.watchlist)
            return factors, {"module": "market", "mode": "remote", "ok": True, "detail": f"market_data_service activo, factores={len(factors)}"}
        except Exception as exc:
            remote_error = str(exc)
    else:
        remote_error = None
    factors = load_market_factors(config, market_file)
    detail = f"market local, factores={len(factors)}"
    if remote_error:
        detail += f" | fallback remote: {remote_error}"
    return factors, {"module": "market", "mode": "local", "ok": True, "detail": detail}


def compute_signals_any(
    config,
    articles: list[NewsArticle],
    market_factors: dict[str, MarketFactors],
    smart_money_signals,
    horizon: str,
) -> list[Signal]:
    return compute_signals_with_status(config, articles, market_factors, smart_money_signals, horizon)[0]


def compute_signals_with_status(
    config,
    articles: list[NewsArticle],
    market_factors: dict[str, MarketFactors],
    smart_money_signals,
    horizon: str,
) -> tuple[list[Signal], dict]:
    if config.signal_engine_url:
        try:
            signals = _compute_signals_remote(
                config.signal_engine_url,
                articles,
                market_factors,
                smart_money_signals,
                horizon,
            )
            return signals, {"module": "signal_engine", "mode": "remote", "ok": True, "detail": f"signal_engine activo, senales={len(signals)}"}
        except Exception as exc:
            remote_error = str(exc)
    else:
        remote_error = None
    signals = analyze_articles(
        articles,
        config,
        market_factors=market_factors,
        smart_money_signals=smart_money_signals,
        horizon=horizon,
    )
    detail = f"engine local, senales={len(signals)}"
    if remote_error:
        detail += f" | fallback remote: {remote_error}"
    return signals, {"module": "signal_engine", "mode": "local", "ok": True, "detail": detail}


def load_execution_snapshot_any(config) -> dict:
    return load_execution_snapshot_with_status(config)[0]


def load_execution_snapshot_with_status(config) -> tuple[dict, dict]:
    if config.execution_service_url:
        try:
            snapshot = _load_execution_snapshot_remote(config.execution_service_url)
            return snapshot, {"module": "execution", "mode": "remote", "ok": True, "detail": "execution_service activo"}
        except Exception as exc:
            remote_error = str(exc)
    else:
        remote_error = None
    snapshot = _load_execution_snapshot_local(config)
    detail = "execution local"
    if remote_error:
        detail += f" | fallback remote: {remote_error}"
    return snapshot, {"module": "execution", "mode": "local", "ok": True, "detail": detail}


def _load_articles_remote(base_url: str, news_file: str, fetch_news: bool, query: str | None) -> list[NewsArticle]:
    response = requests.get(
        f"{base_url}/latest",
        params={
            "news_file": news_file,
            "fetch_news": str(fetch_news).lower(),
            "query": query,
        },
        timeout=4,
    )
    response.raise_for_status()
    payload = response.json()
    return [_news_article_from_dict(item) for item in payload.get("articles", [])]


def _apply_ai_filter_remote(base_url: str, articles: list[NewsArticle]) -> list[NewsArticle]:
    response = requests.post(
        f"{base_url}/filter",
        json={
            "articles": [
                {
                    "title": article.title,
                    "description": article.description,
                    "source": article.source,
                    "published_at": article.published_at,
                    "url": article.url,
                }
                for article in articles
            ]
        },
        timeout=4,
    )
    response.raise_for_status()
    payload = response.json()
    enriched = payload.get("articles", [])
    if not enriched:
        return articles
    return [_news_article_from_dict(item) for item in enriched]


def _load_market_factors_remote(base_url: str, market_file: str, watchlist: list[str]) -> dict[str, MarketFactors]:
    response = requests.get(
        f"{base_url}/factors",
        params={
            "symbols": ",".join(watchlist),
            "market_file": market_file,
        },
        timeout=4,
    )
    response.raise_for_status()
    payload = response.json()
    factors = payload.get("factors", {})
    return {
        symbol.upper(): MarketFactors(
            symbol=symbol.upper(),
            price_momentum=float(item.get("price_momentum", 0.0)),
            volume_trend=float(item.get("volume_trend", 0.0)),
            volatility=float(item.get("volatility", 0.0)),
            regime_score=float(item.get("regime_score", 0.0)),
            regime_label=str(item.get("regime_label", "Mixto")),
            backtest_hit_rate=float(item.get("backtest_hit_rate", 0.0)),
            backtest_avg_return=float(item.get("backtest_avg_return", 0.0)),
            relative_strength=float(item.get("relative_strength", 0.0)),
            benchmark_momentum=float(item.get("benchmark_momentum", 0.0)),
            benchmark_symbol=str(item.get("benchmark_symbol", "SPY")),
            market_breadth=float(item.get("market_breadth", 0.0)),
            sector_breadth=float(item.get("sector_breadth", 0.0)),
            sector_relative_strength=float(item.get("sector_relative_strength", 0.0)),
            sector_group=str(item.get("sector_group", "broad_market")),
        )
        for symbol, item in factors.items()
    }


def _compute_signals_remote(
    base_url: str,
    articles: list[NewsArticle],
    market_factors: dict[str, MarketFactors],
    smart_money_signals,
    horizon: str,
) -> list[Signal]:
    response = requests.post(
        f"{base_url}/compute",
        json={
            "articles": [
                {
                    "title": article.title,
                    "description": article.description,
                    "source": article.source,
                    "published_at": article.published_at,
                    "url": article.url,
                    "ai_relevance": article.ai_relevance,
                    "ai_impact": article.ai_impact,
                    "ai_direction": article.ai_direction,
                    "ai_summary": article.ai_summary,
                    "ai_tradable": article.ai_tradable,
                }
                for article in articles
            ],
            "horizon": horizon,
            "market_factors": [
                {
                    "symbol": factor.symbol,
                    "price_momentum": factor.price_momentum,
                    "volume_trend": factor.volume_trend,
                    "volatility": factor.volatility,
                    "regime_score": factor.regime_score,
                    "regime_label": factor.regime_label,
                    "backtest_hit_rate": factor.backtest_hit_rate,
                    "backtest_avg_return": factor.backtest_avg_return,
                    "relative_strength": factor.relative_strength,
                    "benchmark_momentum": factor.benchmark_momentum,
                    "benchmark_symbol": factor.benchmark_symbol,
                    "market_breadth": factor.market_breadth,
                    "sector_breadth": factor.sector_breadth,
                    "sector_relative_strength": factor.sector_relative_strength,
                    "sector_group": factor.sector_group,
                }
                for factor in market_factors.values()
            ],
            "smart_money_signals": [
                {
                    "symbol": signal.symbol,
                    "conviction_score": signal.conviction_score,
                    "manager_count": signal.manager_count,
                    "crowding_risk": signal.crowding_risk,
                    "top_managers": signal.top_managers,
                    "source": signal.source,
                }
                for signal in smart_money_signals.values()
            ],
        },
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    return [_signal_from_dict(item) for item in payload.get("signals", [])]


def _load_execution_snapshot_remote(base_url: str) -> dict:
    activity_response = requests.get(f"{base_url}/activity", timeout=2.5)
    activity_response.raise_for_status()
    positions_response = requests.get(f"{base_url}/positions", timeout=2.5)
    positions_response.raise_for_status()
    account_response = requests.get(f"{base_url}/account", timeout=2.5)
    account_response.raise_for_status()

    activity_payload = activity_response.json()
    positions_payload = positions_response.json()
    account_payload = account_response.json()

    broker_status = dict(account_payload)
    detail = broker_status.get("detail") or "Estado recibido desde execution_service."
    broker_status["detail"] = f"{detail} | via execution_service"

    return {
        "bot_activity": {
            "balance": activity_payload.get("balance", {}),
            "orders": activity_payload.get("orders", []),
            "managed_positions": activity_payload.get("managed_positions", {}),
            "performance": activity_payload.get("performance", {}),
            "alerts": activity_payload.get("alerts", []),
            "pnl_total": activity_payload.get("pnl_total"),
        },
        "broker_status": broker_status,
        "broker_positions": positions_payload.get("positions", {}),
    }


def _load_execution_snapshot_local(config) -> dict:
    try:
        bot_activity, broker_positions, broker_status_obj = load_live_bot_activity(config)
        broker_status = asdict(broker_status_obj)
    except Exception as exc:
        bot_activity = load_bot_activity()
        broker_status = {"broker": config.broker_mode, "status": "error", "detail": str(exc)}
        broker_positions = {}

    return {
        "bot_activity": bot_activity,
        "broker_status": broker_status,
        "broker_positions": broker_positions,
    }


def _news_article_from_dict(item: dict) -> NewsArticle:
    return NewsArticle(
        title=str(item.get("title", "")),
        description=str(item.get("description", "")),
        source=str(item.get("source", "unknown")),
        published_at=str(item.get("published_at", "")),
        url=str(item.get("url", "")),
        ai_relevance=float(item.get("ai_relevance", 1.0)),
        ai_impact=float(item.get("ai_impact", 0.0)),
        ai_direction=float(item.get("ai_direction", 0.0)),
        ai_summary=str(item.get("ai_summary", "")),
        ai_tradable=bool(item.get("ai_tradable", True)),
    )


def _signal_from_dict(item: dict) -> Signal:
    return Signal(
        symbol=str(item.get("symbol", "")).upper(),
        score=float(item.get("score", 0.0)),
        action=str(item.get("action", "BUY")).upper(),
        confidence=float(item.get("confidence", 0.0)),
        expected_return_per_100=float(item.get("expected_return_per_100", 0.0)),
        article_count=int(item.get("article_count", 0)),
        factor_scores={str(key): float(value) for key, value in item.get("factor_scores", {}).items()},
        reasons=[str(value) for value in item.get("reasons", [])],
        factor_notes=[str(value) for value in item.get("factor_notes", [])],
    )
