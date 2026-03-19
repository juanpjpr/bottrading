from __future__ import annotations

import time
from pathlib import Path

from bot_trading_news.config import BotConfig
from bot_trading_news.ai_filter import apply_ai_news_filter
from bot_trading_news.dashboard import render_dashboard
from bot_trading_news.market import load_market_factors
from bot_trading_news.news import fetch_daily_news, load_news_from_file
from bot_trading_news.smart_money import load_smart_money_signals
from bot_trading_news.strategy import analyze_articles


def run_live_dashboard(
    config: BotConfig,
    news_file: str | None,
    market_file: str | None,
    fetch_news: bool,
    query: str | None,
    horizon: str,
    output_path: str,
    refresh_seconds: int,
) -> None:
    destination = Path(output_path)
    print(f"Modo live activo. Regenerando dashboard cada {refresh_seconds} segundos en: {destination}")
    print("Corta con Ctrl+C.")

    try:
        while True:
            articles = _load_articles(config, news_file=news_file, fetch_news=fetch_news, query=query)
            articles = apply_ai_news_filter(articles, config)
            market_factors = load_market_factors(config, market_file)
            smart_money_signals = load_smart_money_signals(config)
            signals = analyze_articles(
                articles,
                config,
                market_factors=market_factors,
                smart_money_signals=smart_money_signals,
                horizon=horizon,
            )
            render_dashboard(
                config,
                articles,
                signals,
                output_path=str(destination),
                auto_refresh_seconds=refresh_seconds,
            )
            print(f"[live] dashboard actualizado: {destination}")
            time.sleep(refresh_seconds)
    except KeyboardInterrupt:
        print("Modo live detenido.")


def _load_articles(
    config: BotConfig, news_file: str | None, fetch_news: bool, query: str | None
):
    if news_file:
        return load_news_from_file(news_file)
    if fetch_news:
        return fetch_daily_news(config, query=query)
    raise SystemExit("Debes usar --news-file o --fetch-news.")
