from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class BotConfig:
    news_api_key: str | None
    news_api_url: str
    news_service_url: str | None
    fmp_api_key: str | None
    smart_money_mode: str
    sec_user_agent: str
    broker_mode: str
    ai_filter_service_url: str | None
    market_data_service_url: str | None
    signal_engine_url: str | None
    execution_service_url: str | None
    alpaca_api_key: str | None
    alpaca_secret_key: str | None
    alpaca_base_url: str
    alpaca_data_url: str
    ai_filter_mode: str
    ai_filter_model: str
    ai_min_relevance: float
    ai_max_openai_articles: int
    openai_api_key: str | None
    strict_free_mode: bool
    source_whitelist: list[str]
    source_blacklist: list[str]
    execution_timezone: str
    trading_window_start: str
    trading_window_end: str
    max_daily_loss_pct: float
    min_auto_confidence: float
    require_trend_alignment: bool
    stop_loss_pct: float
    take_profit_pct: float
    trailing_stop_pct: float
    trailing_activation_pct: float
    max_hold_minutes: int
    reentry_cooldown_minutes: int
    balance: float
    risk_per_trade: float
    max_daily_trades: int
    min_signal_score: float
    watchlist: list[str]
    market_universe: list[str]
    dynamic_watchlist_size: int


def load_config() -> BotConfig:
    _load_local_dotenv()

    watchlist_raw = os.getenv(
        "BOT_WATCHLIST",
        "AAPL,MSFT,NVDA,TSLA,SPY,BTC,AMZN,GOOGL,META,AMD,NFLX,QQQ,IWM,COIN,MSTR,XOM,GLD,TLT,JPM,BA",
    )
    watchlist = [item.strip().upper() for item in watchlist_raw.split(",") if item.strip()]
    market_universe_raw = os.getenv(
        "BOT_MARKET_UNIVERSE",
        "AAPL,MSFT,NVDA,TSLA,SPY,BTC,AMZN,GOOGL,META,AMD,NFLX,QQQ,IWM,COIN,MSTR,XOM,GLD,TLT,JPM,BA,"
        "AVGO,PLTR,SMCI,INTC,MU,ARM,ORCL,CRM,UBER,SHOP,PYPL,SQ,SNOW,ADBE,PANW,CRWD,MRVL,DIS,GOOG,XLF,XLE,SLV",
    )
    market_universe = [item.strip().upper() for item in market_universe_raw.split(",") if item.strip()]
    source_whitelist = [
        item.strip().lower()
        for item in os.getenv(
            "BOT_SOURCE_WHITELIST",
            "reuters,bloomberg,wall street journal,financial times,cnbc,marketwatch,yahoo finance,associated press,ap news,benzinga,barrons,the economist",
        ).split(",")
        if item.strip()
    ]
    source_blacklist = [
        item.strip().lower()
        for item in os.getenv(
            "BOT_SOURCE_BLACKLIST",
            "globenewswire,accesswire,pr newswire,business wire,class action,law firm,globe newswire,jalopnik,blizzardwatch,pypi.org,github.com,asymco.com",
        ).split(",")
        if item.strip()
    ]

    return BotConfig(
        news_api_key=os.getenv("NEWS_API_KEY"),
        news_api_url=os.getenv("NEWS_API_URL", "https://newsapi.org/v2/everything"),
        news_service_url=_normalize_optional_url(os.getenv("NEWS_SERVICE_URL")),
        fmp_api_key=os.getenv("FMP_API_KEY"),
        smart_money_mode=os.getenv("SMART_MONEY_MODE", "sample").strip().lower(),
        sec_user_agent=os.getenv("SEC_USER_AGENT", "bottrading research contact@example.com"),
        broker_mode=os.getenv("BROKER_MODE", "paper").strip().lower(),
        ai_filter_service_url=_normalize_optional_url(os.getenv("AI_FILTER_SERVICE_URL")),
        market_data_service_url=_normalize_optional_url(os.getenv("MARKET_DATA_SERVICE_URL")),
        signal_engine_url=_normalize_optional_url(os.getenv("SIGNAL_ENGINE_URL")),
        execution_service_url=_normalize_optional_url(os.getenv("EXECUTION_SERVICE_URL")),
        alpaca_api_key=os.getenv("ALPACA_API_KEY"),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY"),
        alpaca_base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/"),
        alpaca_data_url=os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets").rstrip("/"),
        ai_filter_mode=os.getenv("AI_FILTER_MODE", "heuristic").strip().lower(),
        ai_filter_model=os.getenv("AI_FILTER_MODEL", ""),
        ai_min_relevance=float(os.getenv("AI_MIN_RELEVANCE", "0.42")),
        ai_max_openai_articles=int(os.getenv("AI_MAX_OPENAI_ARTICLES", "6")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        strict_free_mode=os.getenv("BOT_STRICT_FREE_MODE", "true").strip().lower() in {"1", "true", "yes", "si"},
        source_whitelist=source_whitelist,
        source_blacklist=source_blacklist,
        execution_timezone=os.getenv("EXECUTION_TIMEZONE", "America/New_York"),
        trading_window_start=os.getenv("TRADING_WINDOW_START", "09:40"),
        trading_window_end=os.getenv("TRADING_WINDOW_END", "15:30"),
        max_daily_loss_pct=float(os.getenv("BOT_MAX_DAILY_LOSS_PCT", "1.5")),
        min_auto_confidence=float(os.getenv("BOT_MIN_AUTO_CONFIDENCE", "78")),
        require_trend_alignment=os.getenv("BOT_REQUIRE_TREND_ALIGNMENT", "true").strip().lower() in {"1", "true", "yes", "si"},
        stop_loss_pct=float(os.getenv("BOT_STOP_LOSS_PCT", "2.0")),
        take_profit_pct=float(os.getenv("BOT_TAKE_PROFIT_PCT", "3.5")),
        trailing_stop_pct=float(os.getenv("BOT_TRAILING_STOP_PCT", "1.2")),
        trailing_activation_pct=float(os.getenv("BOT_TRAILING_ACTIVATION_PCT", "1.8")),
        max_hold_minutes=int(os.getenv("BOT_MAX_HOLD_MINUTES", "180")),
        reentry_cooldown_minutes=int(os.getenv("BOT_REENTRY_COOLDOWN_MINUTES", "30")),
        balance=float(os.getenv("BOT_BALANCE", "10000")),
        risk_per_trade=float(os.getenv("BOT_RISK_PER_TRADE", "0.01")),
        max_daily_trades=int(os.getenv("BOT_MAX_DAILY_TRADES", "3")),
        min_signal_score=float(os.getenv("BOT_MIN_SIGNAL_SCORE", "2.5")),
        watchlist=watchlist,
        market_universe=market_universe,
        dynamic_watchlist_size=int(os.getenv("BOT_DYNAMIC_WATCHLIST_SIZE", "18")),
    )


def _load_local_dotenv() -> None:
    project_root = Path(__file__).resolve().parent.parent
    dotenv_path = project_root / ".env"

    if not dotenv_path.exists():
        return

    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            load_dotenv(dotenv_path=dotenv_path, encoding=encoding, override=False)
            return
        except UnicodeDecodeError:
            continue


def _normalize_optional_url(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().rstrip("/")
    return normalized or None
