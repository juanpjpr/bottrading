from __future__ import annotations

from dataclasses import asdict
from time import time

from bot_trading_news.config import BotConfig, load_config
from bot_trading_news.market import (
    analyze_market_snapshots,
    fetch_alpaca_market_snapshots,
    load_market_snapshots,
)


class MarketDataService:
    """Servicio fino para traer snapshots y factores con una cache corta en memoria."""

    def __init__(self, config: BotConfig | None = None, ttl_seconds: int = 45) -> None:
        self.config = config or load_config()
        self.ttl_seconds = ttl_seconds
        self._snapshot_cache: dict[tuple, tuple[float, dict]] = {}
        self._factor_cache: dict[tuple, tuple[float, dict]] = {}

    def health(self) -> dict:
        return {
            "ok": True,
            "service": "market_data_service",
            "data_url": self.config.alpaca_data_url,
            "watchlist_size": len(self.config.watchlist),
            "alpaca_enabled": bool(self.config.alpaca_api_key and self.config.alpaca_secret_key),
        }

    def get_snapshots(self, symbols: list[str] | None = None, days: int = 10, market_file: str | None = None) -> dict:
        normalized_symbols = self._normalize_symbols(symbols)
        cache_key = (tuple(normalized_symbols), days, market_file or "")
        cached = self._get_cached(self._snapshot_cache, cache_key)
        if cached is not None:
            return {"source": "cache", "snapshots": cached}

        snapshots = self._load_snapshots(normalized_symbols, days, market_file)
        payload = {symbol: asdict(snapshot) for symbol, snapshot in snapshots.items()}
        self._snapshot_cache[cache_key] = (time(), payload)
        source = "alpaca" if payload and self.config.alpaca_api_key and self.config.alpaca_secret_key else "sample"
        return {"source": source, "snapshots": payload}

    def get_factors(self, symbols: list[str] | None = None, days: int = 10, market_file: str | None = None) -> dict:
        normalized_symbols = self._normalize_symbols(symbols)
        cache_key = (tuple(normalized_symbols), days, market_file or "")
        cached = self._get_cached(self._factor_cache, cache_key)
        if cached is not None:
            return {"source": "cache", "factors": cached}

        snapshots = self._load_snapshots(normalized_symbols, days, market_file)
        factors = analyze_market_snapshots(snapshots)
        payload = {symbol: asdict(factor) for symbol, factor in factors.items()}
        self._factor_cache[cache_key] = (time(), payload)
        source = "alpaca" if payload and self.config.alpaca_api_key and self.config.alpaca_secret_key else "sample"
        return {"source": source, "factors": payload}

    def _load_snapshots(self, symbols: list[str], days: int, market_file: str | None) -> dict:
        snapshots = {}
        if self.config.alpaca_api_key and self.config.alpaca_secret_key:
            try:
                snapshots = fetch_alpaca_market_snapshots(self.config, symbols, days=days)
            except Exception:
                snapshots = {}

        if not snapshots and market_file:
            try:
                local_snapshots = load_market_snapshots(market_file)
                snapshots = {symbol: snapshot for symbol, snapshot in local_snapshots.items() if symbol in symbols}
            except Exception:
                snapshots = {}

        return snapshots

    def _normalize_symbols(self, symbols: list[str] | None) -> list[str]:
        raw = symbols or self.config.watchlist
        normalized = [symbol.strip().upper() for symbol in raw if str(symbol).strip()]
        return normalized or self.config.watchlist

    def _get_cached(self, bucket: dict[tuple, tuple[float, dict]], key: tuple) -> dict | None:
        item = bucket.get(key)
        if not item:
            return None
        created_at, payload = item
        if time() - created_at > self.ttl_seconds:
            bucket.pop(key, None)
            return None
        return payload
