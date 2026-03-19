from __future__ import annotations

import requests

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from bot_trading_news.config import load_config
from bot_trading_news.dashboard import build_dashboard_payload, render_dashboard_html
from bot_trading_news.market import MarketFactors
from bot_trading_news.news import NewsArticle
from bot_trading_news.orchestrator import (
    apply_ai_filter_any,
    compute_signals_any,
    load_articles_any,
    load_execution_snapshot_any,
    load_market_factors_any,
)
from bot_trading_news.research import build_research_report
from bot_trading_news.smart_money import load_smart_money_signals
from bot_trading_news.strategy import HORIZON_PRESETS, Signal, normalize_horizon

app = FastAPI(title="Trading News Terminal", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def dashboard_page() -> str:
    horizon = "medium"
    payload = _compute_payload(
        news_file="sample_news.json",
        market_file="sample_market_data.json",
        fetch_news=False,
        query=None,
        horizon=horizon,
    )
    return render_dashboard_html(
        payload,
        api_endpoint=f"/api/dashboard?horizon={horizon}&fetch_news=false",
    )


@app.get("/api/dashboard")
def dashboard_data(
    news_file: str = Query(default="sample_news.json"),
    market_file: str = Query(default="sample_market_data.json"),
    fetch_news: bool = Query(default=False),
    query: str | None = Query(default=None),
    horizon: str = Query(default="medium"),
) -> dict:
    return _compute_payload(
        news_file=news_file,
        market_file=market_file,
        fetch_news=fetch_news,
        query=query,
        horizon=horizon,
    )


@app.get("/api/signals")
def signals_data(
    news_file: str = Query(default="sample_news.json"),
    market_file: str = Query(default="sample_market_data.json"),
    fetch_news: bool = Query(default=False),
    query: str | None = Query(default=None),
    horizon: str = Query(default="medium"),
) -> dict:
    config = load_config()
    articles = load_articles_any(config, news_file=news_file, fetch_news=fetch_news, query=query)
    articles = apply_ai_filter_any(config, articles)
    market_factors = load_market_factors_any(config, market_file)
    smart_money_signals = load_smart_money_signals(config)
    signals = compute_signals_any(
        config,
        articles,
        market_factors=market_factors,
        smart_money_signals=smart_money_signals,
        horizon=normalize_horizon(horizon),
    )
    report_path = build_research_report(
        signals,
        articles,
        market_factors=market_factors,
        output_path="research_report.json",
    )
    return {
        "signals": [
            {
                "symbol": signal.symbol,
                "action": signal.action,
                "score": signal.score,
                "confidence": signal.confidence,
                "article_count": signal.article_count,
                "factor_scores": signal.factor_scores,
                "factor_notes": signal.factor_notes,
                "reasons": signal.reasons,
            }
            for signal in signals
        ],
        "report_file": str(report_path),
    }


@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.get("/health/stack")
def health_stack() -> dict:
    config = load_config()
    execution_snapshot = load_execution_snapshot_any(config)
    activity = execution_snapshot.get("bot_activity", {})
    services = {
        "news_service": _probe_service(config.news_service_url),
        "ai_filter_service": _probe_service(config.ai_filter_service_url),
        "market_data_service": _probe_service(config.market_data_service_url),
        "signal_engine": _probe_service(config.signal_engine_url),
        "execution_service": _probe_service(config.execution_service_url),
    }
    return {
        "status": "ok",
        "app": "trading_news_terminal",
        "services": services,
        "broker_status": execution_snapshot.get("broker_status", {}),
        "activity": {
            "orders_count": len(activity.get("orders", [])),
            "balance_updated_at": activity.get("balance", {}).get("updated_at"),
            "pnl_total": activity.get("pnl_total"),
        },
    }


@app.get("/api/monitor")
def monitor_data() -> dict:
    config = load_config()
    execution_snapshot = load_execution_snapshot_any(config)
    activity = execution_snapshot.get("bot_activity", {})
    orders = activity.get("orders", [])
    balance = activity.get("balance", {})
    return {
        "services": {
            "news": _probe_service(config.news_service_url),
            "ai_filter": _probe_service(config.ai_filter_service_url),
            "market_data": _probe_service(config.market_data_service_url),
            "signal_engine": _probe_service(config.signal_engine_url),
            "execution": _probe_service(config.execution_service_url),
        },
        "bot": {
            "equity": balance.get("equity"),
            "initial_equity": balance.get("initial_equity"),
            "cash": balance.get("cash"),
            "buying_power": balance.get("buying_power"),
            "updated_at": balance.get("updated_at"),
            "orders_count": len(orders),
            "last_order": orders[0] if orders else None,
            "pnl_total": activity.get("pnl_total"),
        },
    }


def _compute_payload(
    news_file: str,
    market_file: str,
    fetch_news: bool,
    query: str | None,
    horizon: str,
) -> dict:
    config = load_config()
    articles = load_articles_any(config, news_file=news_file, fetch_news=fetch_news, query=query)
    articles = apply_ai_filter_any(config, articles)
    market_factors = load_market_factors_any(config, market_file)
    horizon_key = normalize_horizon(horizon)
    smart_money_signals = load_smart_money_signals(config)
    signals = compute_signals_any(
        config,
        articles,
        market_factors=market_factors,
        smart_money_signals=smart_money_signals,
        horizon=horizon_key,
    )
    payload = build_dashboard_payload(config, articles, signals, horizon=horizon_key)
    payload["data_source"] = "api" if fetch_news and config.news_api_key and len(articles) > 4 else "sample"
    payload["smart_money_source"] = config.smart_money_mode
    execution_snapshot = load_execution_snapshot_any(config)
    payload["bot_activity"] = execution_snapshot["bot_activity"]
    payload["broker_status"] = execution_snapshot["broker_status"]
    payload["broker_positions"] = execution_snapshot["broker_positions"]
    payload["horizon"] = {
        "key": horizon_key,
        "label": HORIZON_PRESETS[horizon_key]["label"],
        "window_label": HORIZON_PRESETS[horizon_key]["window_label"],
        "options": [
            {
                "key": key,
                "label": preset["label"],
                "window_label": preset["window_label"],
            }
            for key, preset in HORIZON_PRESETS.items()
        ],
    }
    return payload


def _probe_service(base_url: str | None) -> dict:
    if not base_url:
        return {"mode": "local", "ok": True}
    try:
        response = requests.get(f"{base_url}/health", timeout=1.5)
        response.raise_for_status()
        payload = response.json()
        return {
            "mode": "remote",
            "ok": True,
            "url": base_url,
            "payload": payload,
        }
    except Exception as exc:
        return {
            "mode": "remote",
            "ok": False,
            "url": base_url,
            "error": str(exc),
        }
