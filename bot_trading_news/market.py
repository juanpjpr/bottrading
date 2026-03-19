from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from bot_trading_news.config import BotConfig


@dataclass(slots=True)
class MarketSnapshot:
    symbol: str
    close_prices: list[float]
    volumes: list[float]


@dataclass(slots=True)
class MarketFactors:
    symbol: str
    price_momentum: float
    volume_trend: float
    volatility: float
    regime_score: float
    regime_label: str
    backtest_hit_rate: float
    backtest_avg_return: float
    relative_strength: float
    benchmark_momentum: float
    benchmark_symbol: str
    market_breadth: float
    sector_breadth: float
    sector_relative_strength: float
    sector_group: str


def load_market_snapshots(file_path: str) -> dict[str, MarketSnapshot]:
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    snapshots: dict[str, MarketSnapshot] = {}
    for item in payload:
        symbol = str(item["symbol"]).upper()
        snapshots[symbol] = MarketSnapshot(
            symbol=symbol,
            close_prices=[float(value) for value in item.get("close_prices", [])],
            volumes=[float(value) for value in item.get("volumes", [])],
        )
    return snapshots


def load_market_snapshots_for_symbols(
    config: BotConfig,
    symbols: list[str],
    market_file: str | None = None,
    days: int = 10,
) -> dict[str, MarketSnapshot]:
    snapshots: dict[str, MarketSnapshot] = {}
    normalized_symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if str(symbol).strip()))

    if config.alpaca_api_key and config.alpaca_secret_key:
        try:
            snapshots = fetch_alpaca_market_snapshots(config, normalized_symbols, days=days)
        except requests.RequestException:
            snapshots = {}

    if not snapshots and market_file:
        try:
            local_snapshots = load_market_snapshots(market_file)
            snapshots = {symbol: snapshot for symbol, snapshot in local_snapshots.items() if symbol in normalized_symbols}
        except FileNotFoundError:
            snapshots = {}

    return snapshots


def fetch_alpaca_market_snapshots(
    config: BotConfig,
    symbols: list[str],
    days: int = 10,
) -> dict[str, MarketSnapshot]:
    if not config.alpaca_api_key or not config.alpaca_secret_key:
        return {}

    session = requests.Session()
    session.headers.update(
        {
            "APCA-API-KEY-ID": config.alpaca_api_key,
            "APCA-API-SECRET-KEY": config.alpaca_secret_key,
        }
    )

    end = datetime.now(UTC)
    start = end - timedelta(days=max(days * 2, 14))
    snapshots: dict[str, MarketSnapshot] = {}

    stock_symbols = [symbol for symbol in symbols if symbol != "BTC"]
    crypto_symbols = ["BTC/USD"] if "BTC" in symbols else []

    if stock_symbols:
        params = {
            "symbols": ",".join(stock_symbols),
            "timeframe": "1Day",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "limit": days,
            "adjustment": "raw",
        }
        response = session.get(
            f"{config.alpaca_data_url}/v2/stocks/bars",
            params=params,
            timeout=12,
        )
        response.raise_for_status()
        for symbol, bars in response.json().get("bars", {}).items():
            snapshots[symbol] = _snapshot_from_bars(symbol, bars)

    if crypto_symbols:
        params = {
            "symbols": ",".join(crypto_symbols),
            "timeframe": "1Day",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "limit": days,
        }
        response = session.get(
            f"{config.alpaca_data_url}/v1beta3/crypto/us/bars",
            params=params,
            timeout=12,
        )
        response.raise_for_status()
        for symbol, bars in response.json().get("bars", {}).items():
            normalized_symbol = "BTC" if symbol == "BTC/USD" else symbol
            snapshots[normalized_symbol] = _snapshot_from_bars(normalized_symbol, bars)

    return {
        symbol: snapshot
        for symbol, snapshot in snapshots.items()
        if len(snapshot.close_prices) >= 6 and len(snapshot.volumes) >= 6
    }


def analyze_market_snapshots(snapshots: dict[str, MarketSnapshot]) -> dict[str, MarketFactors]:
    raw_metrics: dict[str, dict] = {}
    for symbol, snapshot in snapshots.items():
        if len(snapshot.close_prices) < 6 or len(snapshot.volumes) < 6:
            continue

        momentum = _price_momentum(snapshot.close_prices)
        volume_trend = _volume_trend(snapshot.volumes)
        volatility = _volatility(snapshot.close_prices)
        regime_score, regime_label = _regime(momentum, volatility, volume_trend)
        hit_rate, avg_return = _historical_validation(snapshot.close_prices)
        raw_metrics[symbol] = {
            "momentum": momentum,
            "volume_trend": volume_trend,
            "volatility": volatility,
            "regime_score": regime_score,
            "regime_label": regime_label,
            "hit_rate": hit_rate,
            "avg_return": avg_return,
        }

    factors: dict[str, MarketFactors] = {}
    market_breadth = _market_breadth(raw_metrics)
    sector_breadth_map = _sector_breadth(raw_metrics)
    sector_strength_map = _sector_relative_strength(raw_metrics)
    for symbol, metrics in raw_metrics.items():
        benchmark_symbol = _benchmark_for_symbol(symbol)
        benchmark_momentum = raw_metrics.get(benchmark_symbol, {}).get("momentum", 0.0)
        relative_strength = metrics["momentum"] - benchmark_momentum
        sector_group = _sector_for_symbol(symbol)

        factors[symbol] = MarketFactors(
            symbol=symbol,
            price_momentum=round(metrics["momentum"], 2),
            volume_trend=round(metrics["volume_trend"], 2),
            volatility=round(metrics["volatility"], 2),
            regime_score=round(metrics["regime_score"], 2),
            regime_label=metrics["regime_label"],
            backtest_hit_rate=round(metrics["hit_rate"], 1),
            backtest_avg_return=round(metrics["avg_return"], 2),
            relative_strength=round(relative_strength, 2),
            benchmark_momentum=round(benchmark_momentum, 2),
            benchmark_symbol=benchmark_symbol,
            market_breadth=round(market_breadth, 2),
            sector_breadth=round(sector_breadth_map.get(sector_group, 0.0), 2),
            sector_relative_strength=round(sector_strength_map.get(sector_group, 0.0), 2),
            sector_group=sector_group,
        )
    return factors


def load_market_factors(
    config: BotConfig,
    market_file: str | None = None,
) -> dict[str, MarketFactors]:
    symbols = list(dict.fromkeys(config.market_universe + config.watchlist))
    snapshots = load_market_snapshots_for_symbols(config, symbols, market_file=market_file)
    return analyze_market_snapshots(snapshots)


def _snapshot_from_bars(symbol: str, bars: list[dict]) -> MarketSnapshot:
    ordered_bars = bars[-10:]
    return MarketSnapshot(
        symbol=symbol,
        close_prices=[float(item.get("c", 0.0)) for item in ordered_bars],
        volumes=[float(item.get("v", 0.0)) for item in ordered_bars],
    )


def _price_momentum(prices: list[float]) -> float:
    short_window = prices[-3:]
    long_window = prices[:3]
    short_avg = sum(short_window) / len(short_window)
    long_avg = sum(long_window) / len(long_window)
    if long_avg == 0:
        return 0.0
    return ((short_avg - long_avg) / long_avg) * 10


def _volume_trend(volumes: list[float]) -> float:
    latest = sum(volumes[-3:]) / 3
    baseline = sum(volumes[:3]) / 3
    if baseline == 0:
        return 0.0
    return ((latest - baseline) / baseline) * 5


def _volatility(prices: list[float]) -> float:
    returns = []
    for previous, current in zip(prices, prices[1:]):
        if previous == 0:
            continue
        returns.append((current - previous) / previous)
    if not returns:
        return 0.0

    mean_return = sum(returns) / len(returns)
    variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
    return (variance ** 0.5) * 100


def _regime(momentum: float, volatility: float, volume_trend: float) -> tuple[float, str]:
    regime_score = momentum + volume_trend - (volatility * 0.4)
    if regime_score >= 1.4:
        return regime_score, "Tendencia Fuerte"
    if regime_score >= 0.2:
        return regime_score, "Riesgo Controlado"
    if regime_score <= -1.0:
        return regime_score, "Defensivo"
    return regime_score, "Mixto"


def _historical_validation(prices: list[float]) -> tuple[float, float]:
    one_step_returns = []
    for previous, current in zip(prices, prices[1:]):
        if previous == 0:
            continue
        one_step_returns.append(((current - previous) / previous) * 100)

    if not one_step_returns:
        return 0.0, 0.0

    positive = sum(1 for value in one_step_returns if value > 0)
    hit_rate = (positive / len(one_step_returns)) * 100
    avg_return = sum(one_step_returns) / len(one_step_returns)
    return hit_rate, avg_return


def _benchmark_for_symbol(symbol: str) -> str:
    crypto_cluster = {"BTC", "COIN", "MSTR"}
    tech_growth_cluster = {
        "QQQ",
        "AAPL",
        "MSFT",
        "NVDA",
        "TSLA",
        "AMZN",
        "GOOGL",
        "GOOG",
        "META",
        "AMD",
        "NFLX",
        "AVGO",
        "PLTR",
        "SMCI",
        "INTC",
        "MU",
        "ARM",
        "ORCL",
        "CRM",
        "UBER",
        "SHOP",
        "PYPL",
        "SQ",
        "SNOW",
        "ADBE",
        "PANW",
        "CRWD",
        "MRVL",
    }
    if symbol in crypto_cluster:
        return "BTC"
    if symbol in tech_growth_cluster:
        return "QQQ"
    if symbol == "SLV":
        return "GLD"
    if symbol == "XOM":
        return "XLE"
    if symbol in {"GLD", "TLT", "SPY", "XLE"}:
        return symbol
    return "SPY"


def _sector_for_symbol(symbol: str) -> str:
    sector_map = {
        "AAPL": "tech",
        "MSFT": "tech",
        "NVDA": "semis",
        "AMD": "semis",
        "AVGO": "semis",
        "MRVL": "semis",
        "MU": "semis",
        "INTC": "semis",
        "ARM": "semis",
        "SMCI": "infra",
        "ORCL": "software",
        "CRM": "software",
        "ADBE": "software",
        "PANW": "software",
        "CRWD": "software",
        "PLTR": "software",
        "SNOW": "software",
        "AMZN": "consumer_growth",
        "TSLA": "consumer_growth",
        "META": "internet",
        "GOOGL": "internet",
        "GOOG": "internet",
        "NFLX": "internet",
        "UBER": "internet",
        "SHOP": "internet",
        "PYPL": "fintech",
        "SQ": "fintech",
        "COIN": "crypto_equity",
        "MSTR": "crypto_equity",
        "BTC": "crypto",
        "JPM": "financials",
        "XLF": "financials",
        "XOM": "energy",
        "XLE": "energy",
        "GLD": "metals",
        "SLV": "metals",
        "TLT": "rates",
        "BA": "industrials",
        "IWM": "broad_market",
        "QQQ": "growth_index",
        "SPY": "broad_market",
        "DIS": "consumer_defensive",
    }
    return sector_map.get(symbol, "broad_market")


def _market_breadth(raw_metrics: dict[str, dict]) -> float:
    if not raw_metrics:
        return 0.0
    positives = 0
    total = 0
    for metrics in raw_metrics.values():
        total += 1
        if metrics["momentum"] > 0 and metrics["regime_score"] > -0.1:
            positives += 1
    return ((positives / total) * 2.0) - 1.0 if total else 0.0


def _sector_breadth(raw_metrics: dict[str, dict]) -> dict[str, float]:
    groups: dict[str, list[dict]] = {}
    for symbol, metrics in raw_metrics.items():
        groups.setdefault(_sector_for_symbol(symbol), []).append(metrics)
    result: dict[str, float] = {}
    for sector, items in groups.items():
        positives = sum(1 for item in items if item["momentum"] > 0 and item["regime_score"] > -0.1)
        result[sector] = ((positives / len(items)) * 2.0) - 1.0 if items else 0.0
    return result


def _sector_relative_strength(raw_metrics: dict[str, dict]) -> dict[str, float]:
    groups: dict[str, list[dict]] = {}
    for symbol, metrics in raw_metrics.items():
        groups.setdefault(_sector_for_symbol(symbol), []).append(metrics)
    broad_reference = raw_metrics.get("SPY", {}).get("momentum", 0.0)
    result: dict[str, float] = {}
    for sector, items in groups.items():
        avg_momentum = sum(item["momentum"] for item in items) / len(items) if items else 0.0
        result[sector] = avg_momentum - broad_reference
    return result
