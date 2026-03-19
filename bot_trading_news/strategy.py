from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from bot_trading_news.config import BotConfig
from bot_trading_news.market import MarketFactors
from bot_trading_news.news import NewsArticle
from bot_trading_news.smart_money import SmartMoneySignal
from bot_trading_news.storage import load_setup_stats_sqlite

POSITIVE_WORDS = {
    "beat",
    "beats",
    "surge",
    "surges",
    "growth",
    "record",
    "profit",
    "bullish",
    "approval",
    "breakout",
    "upgrade",
    "strong",
    "partnership",
    "rally",
}

NEGATIVE_WORDS = {
    "miss",
    "misses",
    "drop",
    "drops",
    "lawsuit",
    "fraud",
    "weak",
    "downgrade",
    "cut",
    "fall",
    "falls",
    "bearish",
    "risk",
    "delay",
    "probe",
}

SYMBOL_ALIASES = {
    "AAPL": {"apple", "aapl", "iphone"},
    "MSFT": {"microsoft", "msft", "azure"},
    "NVDA": {"nvidia", "nvda", "gpu"},
    "TSLA": {"tesla", "tsla", "elon musk"},
    "SPY": {"s&p 500", "spy", "market"},
    "BTC": {"bitcoin", "btc", "crypto"},
    "AMZN": {"amazon", "amzn", "aws"},
    "GOOGL": {"google", "alphabet", "googl", "youtube"},
    "META": {"meta", "facebook", "instagram"},
    "AMD": {"amd", "advanced micro devices", "ryzen"},
    "NFLX": {"netflix", "nflx", "streaming"},
    "QQQ": {"qqq", "nasdaq 100", "nasdaq"},
    "IWM": {"iwm", "russell 2000", "small caps"},
    "COIN": {"coinbase", "coin", "crypto exchange"},
    "MSTR": {"microstrategy", "mstr"},
    "XOM": {"exxon", "xom", "oil major"},
    "GLD": {"gold", "gld", "bullion"},
    "TLT": {"tlt", "treasury bonds", "long bonds"},
    "JPM": {"jpmorgan", "jpm", "banking"},
    "BA": {"boeing", "ba", "aviation"},
}

GEOPOLITICAL_THEMES = {
    "war": {"direction": -1.0, "assets": {"SPY": 1.3, "BTC": -0.2, "NVDA": -0.3, "TSLA": -0.2}},
    "missile": {"direction": -1.0, "assets": {"SPY": 1.2, "BTC": -0.2}},
    "attack": {"direction": -0.9, "assets": {"SPY": 1.0, "BTC": -0.1}},
    "sanctions": {"direction": -0.7, "assets": {"SPY": 0.9, "NVDA": -0.5, "AAPL": -0.4, "MSFT": -0.2}},
    "tariff": {"direction": -0.8, "assets": {"SPY": 1.0, "AAPL": -0.6, "NVDA": -0.7, "TSLA": -0.4}},
    "trade war": {"direction": -1.0, "assets": {"SPY": 1.1, "AAPL": -0.8, "NVDA": -0.9, "TSLA": -0.7}},
    "china": {"direction": -0.3, "assets": {"AAPL": -0.4, "NVDA": -0.5, "TSLA": -0.4}},
    "taiwan": {"direction": -0.6, "assets": {"NVDA": -1.0, "AAPL": -0.5, "SPY": 0.6}},
    "middle east": {"direction": -0.6, "assets": {"SPY": 0.8, "BTC": 0.2}},
    "russia": {"direction": -0.5, "assets": {"SPY": 0.7, "BTC": 0.1}},
    "ukraine": {"direction": -0.6, "assets": {"SPY": 0.8, "BTC": 0.1}},
    "iran": {"direction": -0.5, "assets": {"SPY": 0.7, "BTC": 0.2}},
    "israel": {"direction": -0.4, "assets": {"SPY": 0.6, "BTC": 0.1}},
    "opec": {"direction": -0.4, "assets": {"SPY": 0.5, "TSLA": -0.2}},
    "oil": {"direction": -0.3, "assets": {"SPY": 0.4, "TSLA": -0.3}},
    "fed": {"direction": -0.2, "assets": {"SPY": 0.8, "BTC": 0.4, "TSLA": 0.2, "NVDA": 0.2}},
    "interest rates": {"direction": -0.5, "assets": {"SPY": 0.9, "BTC": 0.5, "TSLA": 0.4, "NVDA": 0.4}},
    "inflation": {"direction": -0.5, "assets": {"SPY": 0.8, "BTC": 0.2, "TSLA": 0.3}},
    "election": {"direction": -0.2, "assets": {"SPY": 0.5, "BTC": 0.2}},
    "regulation": {"direction": -0.5, "assets": {"BTC": -0.9, "MSFT": -0.1, "AAPL": -0.1}},
}

HORIZON_PRESETS = {
    "short": {
        "label": "Corto Plazo",
        "window_label": "24h - 72h",
        "min_signal_multiplier": 0.85,
        "recency_multiplier": 1.35,
        "news_multiplier": 1.1,
        "price_multiplier": 0.45,
        "volume_multiplier": 0.35,
        "volatility_multiplier": 0.24,
        "regime_multiplier": 0.22,
        "validation_multiplier": 0.35,
        "smart_money_multiplier": 0.15,
    },
    "medium": {
        "label": "Medio Plazo",
        "window_label": "1 - 4 semanas",
        "min_signal_multiplier": 1.0,
        "recency_multiplier": 1.0,
        "news_multiplier": 1.0,
        "price_multiplier": 0.35,
        "volume_multiplier": 0.25,
        "volatility_multiplier": 0.18,
        "regime_multiplier": 0.45,
        "validation_multiplier": 0.8,
        "smart_money_multiplier": 0.55,
    },
    "long": {
        "label": "Largo Plazo",
        "window_label": "1 - 6 meses",
        "min_signal_multiplier": 1.15,
        "recency_multiplier": 0.7,
        "news_multiplier": 0.8,
        "price_multiplier": 0.25,
        "volume_multiplier": 0.12,
        "volatility_multiplier": 0.12,
        "regime_multiplier": 0.7,
        "validation_multiplier": 1.15,
        "smart_money_multiplier": 0.95,
    },
}


@dataclass(slots=True)
class Signal:
    symbol: str
    score: float
    action: str
    confidence: float
    expected_return_per_100: float
    article_count: int
    factor_scores: dict[str, float]
    reasons: list[str]
    factor_notes: list[str] = field(default_factory=list)
    setup_tag: str = ""
    session_tag: str = ""


def normalize_horizon(horizon: str | None) -> str:
    if not horizon:
        return "medium"
    normalized = horizon.strip().lower()
    return normalized if normalized in HORIZON_PRESETS else "medium"


def analyze_articles(
    articles: list[NewsArticle],
    config: BotConfig,
    market_factors: dict[str, MarketFactors] | None = None,
    smart_money_signals: dict[str, SmartMoneySignal] | None = None,
    horizon: str = "medium",
) -> list[Signal]:
    horizon_key = normalize_horizon(horizon)
    horizon_preset = HORIZON_PRESETS[horizon_key]
    session_tag = infer_session_tag(config)
    setup_stats = load_setup_stats_sqlite()
    active_watchlist = build_dynamic_watchlist(
        config,
        articles,
        market_factors or {},
        smart_money_signals or {},
    )
    aggregate: dict[str, dict] = {
        symbol: {
            "sentiment": 0.0,
            "impact": 0.0,
            "geopolitical": 0.0,
            "ai_relevance": 0.0,
            "ai_impact": 0.0,
            "recency": 0.0,
            "source_quality": 0.0,
            "consensus_hits": 0,
            "article_count": 0,
            "reasons": [],
        }
        for symbol in active_watchlist
    }

    for article in articles:
        article_text = article.combined_text.lower()
        sentiment_score = _score_text(article_text)
        impact_score = _impact_score(article_text)
        geopolitical_scores = _geopolitical_scores(article_text, active_watchlist)
        recency_weight = _recency_weight(article, horizon_key)
        source_quality = _source_quality(article.source)
        mentioned_symbols = set(_extract_symbols(article_text, active_watchlist))
        mentioned_symbols.update(symbol for symbol, value in geopolitical_scores.items() if value != 0)
        for symbol in mentioned_symbols:
            aggregate[symbol]["sentiment"] += sentiment_score * recency_weight
            aggregate[symbol]["impact"] += impact_score
            aggregate[symbol]["geopolitical"] += geopolitical_scores.get(symbol, 0.0)
            aggregate[symbol]["ai_relevance"] += article.ai_relevance * recency_weight
            aggregate[symbol]["ai_impact"] += article.ai_impact * (
                article.ai_direction if article.ai_direction != 0 else (1 if sentiment_score >= 0 else -1)
            )
            aggregate[symbol]["recency"] += recency_weight
            aggregate[symbol]["source_quality"] += source_quality
            aggregate[symbol]["article_count"] += 1
            if sentiment_score != 0 or geopolitical_scores.get(symbol, 0.0) != 0:
                aggregate[symbol]["consensus_hits"] += 1
            summary = f"{article.source}: {article.title}".strip()
            aggregate[symbol]["reasons"].append(summary)

    signals: list[Signal] = []
    for symbol, data in aggregate.items():
        market_factor = market_factors.get(symbol) if market_factors else None
        smart_money_signal = smart_money_signals.get(symbol) if smart_money_signals else None
        if data["article_count"] == 0 and not market_factor and not smart_money_signal:
            continue

        factor_scores = _combine_factors(
            data,
            market_factor,
            smart_money_signal,
            horizon_preset,
            session_tag=session_tag,
        )
        setup_tag = infer_setup_tag(
            _inferred_action_from_scores(factor_scores),
            factor_scores,
            data["article_count"],
            horizon_key,
        )
        factor_scores["setup_edge"] = _setup_edge_score(setup_stats.get(setup_tag))
        net_score = sum(factor_scores.values())
        min_signal_score = config.min_signal_score * horizon_preset["min_signal_multiplier"]
        if abs(net_score) < min_signal_score:
            continue

        directional_score = factor_scores["sentiment"] + factor_scores["geopolitical"]
        directional_score += factor_scores.get("ai_impact", 0.0)
        if directional_score == 0 and market_factor:
            directional_score = (
                factor_scores.get("price", 0.0)
                + factor_scores.get("volume", 0.0)
                + factor_scores.get("regime", 0.0)
                + factor_scores.get("validation", 0.0)
            )
        if directional_score == 0 and smart_money_signal:
            directional_score = factor_scores.get("smart_money", 0.0) - factor_scores.get("crowding", 0.0)
        action = "BUY" if directional_score >= 0 else "SELL"
        signals.append(
            Signal(
                symbol=symbol,
                score=round(net_score, 2),
                action=action,
                confidence=_calculate_confidence(net_score, factor_scores, min_signal_score),
                expected_return_per_100=_expected_return_per_100(
                    net_score,
                    factor_scores,
                    horizon_key,
                ),
                article_count=data["article_count"],
                factor_scores={key: round(value, 2) for key, value in factor_scores.items()},
                factor_notes=_factor_notes(data, factor_scores),
                reasons=data["reasons"][:3],
                setup_tag=setup_tag,
                session_tag=session_tag,
            )
        )

    signals.sort(key=lambda item: abs(item.score), reverse=True)
    return signals


def build_dynamic_watchlist(
    config: BotConfig,
    articles: list[NewsArticle],
    market_factors: dict[str, MarketFactors],
    smart_money_signals: dict[str, SmartMoneySignal],
) -> list[str]:
    details = build_dynamic_watchlist_details(config, articles, market_factors, smart_money_signals)
    return [item["symbol"] for item in details]


def build_dynamic_watchlist_details(
    config: BotConfig,
    articles: list[NewsArticle],
    market_factors: dict[str, MarketFactors],
    smart_money_signals: dict[str, SmartMoneySignal],
) -> list[dict]:
    candidate_symbols = list(dict.fromkeys(config.market_universe + config.watchlist))
    article_mentions = {symbol: 0 for symbol in candidate_symbols}

    for article in articles:
        article_text = article.combined_text.lower()
        for symbol in _extract_symbols(article_text, candidate_symbols):
            article_mentions[symbol] += 1

    ranked: list[dict] = []
    for symbol in candidate_symbols:
        market_factor = market_factors.get(symbol)
        smart_money_signal = smart_money_signals.get(symbol)
        score = 0.0
        drivers: list[tuple[str, float]] = []
        if market_factor:
            momentum_component = abs(market_factor.price_momentum) * 1.6
            relative_component = max(market_factor.relative_strength, 0.0) * 1.4
            volume_component = max(market_factor.volume_trend, 0.0) * 1.0
            regime_component = max(market_factor.regime_score, 0.0) * 1.2
            validation_component = max((market_factor.backtest_hit_rate - 50) / 10, 0.0) * 0.7
            volatility_component = market_factor.volatility * 0.12
            benchmark_component = max(market_factor.benchmark_momentum, 0.0) * 0.55
            breadth_component = max(market_factor.market_breadth, 0.0) * 0.8
            sector_breadth_component = max(market_factor.sector_breadth, 0.0) * 0.95
            sector_relative_component = max(market_factor.sector_relative_strength, 0.0) * 1.05
            score += (
                momentum_component
                + relative_component
                + volume_component
                + regime_component
                + validation_component
                + benchmark_component
                + breadth_component
                + sector_breadth_component
                + sector_relative_component
                - volatility_component
            )
            drivers.extend(
                [
                    ("momentum", momentum_component),
                    ("relative", relative_component),
                    ("volumen", volume_component),
                    ("regime", regime_component),
                    ("breadth", breadth_component),
                    ("sector", sector_breadth_component + sector_relative_component),
                    ("validacion", validation_component),
                    ("benchmark", benchmark_component),
                ]
            )
        if smart_money_signal:
            smart_component = smart_money_signal.conviction_score * 0.8
            crowding_component = smart_money_signal.crowding_risk * 0.25
            score += smart_component - crowding_component
            drivers.append(("smart", smart_component))
        news_component = article_mentions.get(symbol, 0) * 2.2
        score += news_component
        drivers.append(("news", news_component))
        if symbol in config.watchlist:
            score += 0.35
        top_drivers = [name for name, value in sorted(drivers, key=lambda item: item[1], reverse=True) if value > 0][:2]
        ranked.append(
            {
                "symbol": symbol,
                "score": round(score, 2),
                "drivers": top_drivers or ["base"],
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    selected = [item for item in ranked if item["score"] > 0][: max(config.dynamic_watchlist_size, 8)]
    selected_symbols = {item["symbol"] for item in selected}
    fallback = [{"symbol": symbol, "score": 0.0, "drivers": ["base"]} for symbol in config.watchlist if symbol not in selected_symbols]
    return (selected + fallback)[: max(config.dynamic_watchlist_size, len(config.watchlist))]


def _score_text(text: str) -> float:
    score = 0.0
    words = text.split()
    for word in words:
        normalized = word.strip(".,:;!?()[]{}\"'")
        if normalized in POSITIVE_WORDS:
            score += 1.0
        if normalized in NEGATIVE_WORDS:
            score -= 1.0
    return score


def _extract_symbols(text: str, watchlist: list[str]) -> list[str]:
    matches: list[str] = []
    for symbol in watchlist:
        aliases = SYMBOL_ALIASES.get(symbol, {symbol.lower()})
        if any(alias in text for alias in aliases):
            matches.append(symbol)
    return matches


def _combine_factors(
    data: dict,
    market_factor: MarketFactors | None,
    smart_money_signal: SmartMoneySignal | None,
    horizon_preset: dict[str, float],
    session_tag: str,
) -> dict[str, float]:
    article_count = data["article_count"]
    avg_recency = data["recency"] / article_count if article_count else 0.0
    avg_source_quality = data["source_quality"] / article_count if article_count else 0.0
    consensus = min(data["consensus_hits"] / max(article_count, 1), 1.0)
    direction = 1 if data["sentiment"] >= 0 else -1

    scores = {
        "sentiment": data["sentiment"] * horizon_preset["news_multiplier"],
        "impact": data["impact"] * direction * horizon_preset["news_multiplier"],
        "geopolitical": data["geopolitical"] * horizon_preset["news_multiplier"],
        "ai_relevance": (data["ai_relevance"] / max(article_count, 1)) * horizon_preset["news_multiplier"],
        "ai_impact": data["ai_impact"] * horizon_preset["news_multiplier"],
        "recency": avg_recency * direction * horizon_preset["recency_multiplier"],
        "source_quality": avg_source_quality * direction * horizon_preset["news_multiplier"],
        "consensus": consensus * direction * horizon_preset["news_multiplier"],
    }
    if market_factor:
        scores["price"] = market_factor.price_momentum * horizon_preset["price_multiplier"]
        scores["relative_strength"] = market_factor.relative_strength * (horizon_preset["price_multiplier"] * 0.8)
        scores["volume"] = market_factor.volume_trend * horizon_preset["volume_multiplier"]
        scores["volatility"] = -market_factor.volatility * horizon_preset["volatility_multiplier"] * direction
        scores["regime"] = market_factor.regime_score * horizon_preset["regime_multiplier"]
        scores["market_breadth"] = market_factor.market_breadth * (horizon_preset["regime_multiplier"] * 0.55)
        scores["sector_breadth"] = market_factor.sector_breadth * (horizon_preset["regime_multiplier"] * 0.65)
        scores["sector_relative_strength"] = market_factor.sector_relative_strength * (horizon_preset["price_multiplier"] * 0.7)
        scores["validation"] = (
            ((market_factor.backtest_hit_rate - 50) / 50) * horizon_preset["validation_multiplier"]
        )
        scores["benchmark"] = market_factor.benchmark_momentum * (horizon_preset["regime_multiplier"] * 0.35)
        scores["alignment"] = _trend_alignment_score(
            data,
            market_factor,
            horizon_preset["news_multiplier"],
        )
        scores["time_regime"] = _time_regime_score(session_tag, market_factor, horizon_preset)
    if smart_money_signal:
        scores["smart_money"] = smart_money_signal.conviction_score * horizon_preset["smart_money_multiplier"]
        scores["crowding"] = -smart_money_signal.crowding_risk * (horizon_preset["smart_money_multiplier"] * 0.35)
    return scores


def _calculate_confidence(
    score: float, factor_scores: dict[str, float], min_signal_score: float
) -> float:
    if min_signal_score <= 0:
        return 50.0

    normalized_score = min(abs(score) / (min_signal_score * 2), 1.0)
    diversification_bonus = min(sum(abs(value) for value in factor_scores.values()) / 8, 1.0)
    confidence = 45 + normalized_score * 35 + diversification_bonus * 19
    return round(min(confidence, 99.0), 1)


def _impact_score(text: str) -> float:
    catalysts = {
        "earnings": 1.0,
        "guidance": 1.1,
        "fed": 0.9,
        "etf": 0.8,
        "merger": 1.2,
        "acquisition": 1.2,
        "lawsuit": 1.0,
        "approval": 0.8,
        "launch": 0.6,
        "tariff": 0.8,
    }
    return sum(weight for word, weight in catalysts.items() if word in text)


def _geopolitical_scores(text: str, watchlist: list[str]) -> dict[str, float]:
    scores = {symbol: 0.0 for symbol in watchlist}

    for theme, mapping in GEOPOLITICAL_THEMES.items():
        if theme not in text:
            continue

        direction = mapping["direction"]
        for symbol, sensitivity in mapping["assets"].items():
            if symbol in scores:
                scores[symbol] += direction * sensitivity

    return scores


def _recency_weight(article: NewsArticle, horizon: str) -> float:
    published = article.published_datetime
    if not published:
        return 0.35

    now = datetime.now(UTC)
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)

    hours_old = max((now - published).total_seconds() / 3600, 0.0)
    if horizon == "long":
        if hours_old <= 12:
            return 1.0
        if hours_old <= 48:
            return 0.9
        if hours_old <= 96:
            return 0.75
        return 0.45

    if horizon == "medium":
        if hours_old <= 4:
            return 1.25
        if hours_old <= 12:
            return 1.0
        if hours_old <= 24:
            return 0.75
        return 0.45

    if hours_old <= 2:
        return 1.4
    if hours_old <= 6:
        return 1.1
    if hours_old <= 16:
        return 0.8
    return 0.45


def _source_quality(source: str) -> float:
    source_map = {
        "reuters": 1.0,
        "bloomberg": 1.0,
        "wall street journal": 0.95,
        "financial times": 0.95,
        "cnbc": 0.8,
        "marketwatch": 0.72,
        "crypto desk": 0.58,
        "finance daily": 0.55,
        "market wire": 0.62,
    }
    lowered = source.lower()
    for key, value in source_map.items():
        if key in lowered:
            return value
    return 0.45


def _factor_notes(data: dict, factor_scores: dict[str, float]) -> list[str]:
    notes: list[str] = []
    notes.append(f"{data['article_count']} articulos vinculados")
    notes.append(f"sentiment factor {factor_scores['sentiment']:.2f}")
    notes.append(f"consensus factor {factor_scores['consensus']:.2f}")
    if abs(factor_scores.get("ai_relevance", 0.0)) > 0.3:
        notes.append(f"ai relevance {factor_scores['ai_relevance']:.2f}")
    if abs(factor_scores.get("ai_impact", 0.0)) > 0.3:
        notes.append(f"ai impact {factor_scores['ai_impact']:.2f}")
    if abs(factor_scores["geopolitical"]) > 0.35:
        notes.append(f"geopolitics factor {factor_scores['geopolitical']:.2f}")
    if abs(factor_scores["impact"]) > 0.5:
        notes.append(f"event impact {factor_scores['impact']:.2f}")
    if "regime" in factor_scores and abs(factor_scores["regime"]) > 0.25:
        notes.append(f"regime factor {factor_scores['regime']:.2f}")
    if "price" in factor_scores and abs(factor_scores["price"]) > 0.2:
        notes.append(f"price factor {factor_scores['price']:.2f}")
    if "relative_strength" in factor_scores and abs(factor_scores["relative_strength"]) > 0.18:
        notes.append(f"relative strength {factor_scores['relative_strength']:.2f}")
    if "sector_relative_strength" in factor_scores and abs(factor_scores["sector_relative_strength"]) > 0.18:
        notes.append(f"sector strength {factor_scores['sector_relative_strength']:.2f}")
    if "sector_breadth" in factor_scores and abs(factor_scores["sector_breadth"]) > 0.18:
        notes.append(f"sector breadth {factor_scores['sector_breadth']:.2f}")
    if "alignment" in factor_scores and abs(factor_scores["alignment"]) > 0.18:
        notes.append(f"alignment factor {factor_scores['alignment']:.2f}")
    if "setup_edge" in factor_scores and abs(factor_scores["setup_edge"]) > 0.12:
        notes.append(f"setup edge {factor_scores['setup_edge']:.2f}")
    if "smart_money" in factor_scores and abs(factor_scores["smart_money"]) > 0.2:
        notes.append(f"smart money factor {factor_scores['smart_money']:.2f}")
    return notes[:4]


def _expected_return_per_100(
    score: float,
    factor_scores: dict[str, float],
    horizon_key: str,
) -> float:
    horizon_multiplier = {
        "short": 0.9,
        "medium": 1.35,
        "long": 1.8,
    }.get(horizon_key, 1.35)
    quality_boost = (
        abs(factor_scores.get("price", 0.0))
        + abs(factor_scores.get("relative_strength", 0.0))
        + abs(factor_scores.get("sector_relative_strength", 0.0))
        + abs(factor_scores.get("regime", 0.0))
        + abs(factor_scores.get("time_regime", 0.0))
        + abs(factor_scores.get("smart_money", 0.0))
        + abs(factor_scores.get("validation", 0.0))
    ) * 0.28
    expected = abs(score) * horizon_multiplier + quality_boost
    return round(min(max(expected, 0.4), 18.0), 2)


def _trend_alignment_score(
    data: dict,
    market_factor: MarketFactors,
    news_multiplier: float,
) -> float:
    news_bias = data["sentiment"] + data["geopolitical"] + data["ai_impact"]
    market_bias = (
        market_factor.price_momentum
        + (market_factor.relative_strength * 0.9)
        + (market_factor.regime_score * 0.65)
    )
    if abs(news_bias) < 0.2 or abs(market_bias) < 0.15:
        return 0.0
    if news_bias * market_bias > 0:
        return min(abs(news_bias), abs(market_bias)) * 0.22 * news_multiplier
    return -min(abs(news_bias), abs(market_bias)) * 0.34 * news_multiplier


def infer_session_tag(config: BotConfig) -> str:
    now_local = datetime.now(UTC).astimezone(ZoneInfo(config.execution_timezone))
    hhmm = now_local.strftime("%H:%M")
    if hhmm < "10:30":
        return "open_drive"
    if hhmm < "12:30":
        return "morning_trend"
    if hhmm < "14:30":
        return "midday"
    if hhmm < "15:45":
        return "power_hour"
    return "late_session"


def infer_setup_tag(action: str, factor_scores: dict[str, float], article_count: int, horizon_key: str) -> str:
    if abs(factor_scores.get("geopolitical", 0.0)) > 0.8:
        return f"{horizon_key}_macro_geo"
    if article_count >= 2 and factor_scores.get("ai_relevance", 0.0) > 0.35 and factor_scores.get("price", 0.0) > 0:
        return f"{horizon_key}_news_momentum"
    if factor_scores.get("relative_strength", 0.0) > 0.3 and factor_scores.get("sector_relative_strength", 0.0) > 0.2:
        return f"{horizon_key}_sector_leader"
    if factor_scores.get("smart_money", 0.0) > 0.25 and factor_scores.get("validation", 0.0) > 0.2:
        return f"{horizon_key}_smart_validation"
    if factor_scores.get("price", 0.0) > 0 and factor_scores.get("volume", 0.0) > 0 and factor_scores.get("regime", 0.0) > 0:
        return f"{horizon_key}_trend_follow"
    return f"{horizon_key}_{action.lower()}_general"


def _time_regime_score(session_tag: str, market_factor: MarketFactors, horizon_preset: dict[str, float]) -> float:
    trend_strength = market_factor.price_momentum + market_factor.relative_strength + market_factor.regime_score
    if session_tag == "open_drive":
        return trend_strength * (horizon_preset["price_multiplier"] * 0.18)
    if session_tag == "morning_trend":
        return trend_strength * (horizon_preset["regime_multiplier"] * 0.16)
    if session_tag == "midday":
        return -abs(trend_strength) * (horizon_preset["price_multiplier"] * 0.06)
    if session_tag == "power_hour":
        return trend_strength * (horizon_preset["regime_multiplier"] * 0.14)
    return trend_strength * (horizon_preset["price_multiplier"] * 0.08)


def _setup_edge_score(stats: dict | None) -> float:
    if not stats:
        return 0.0
    trades = int(stats.get("trades", 0) or 0)
    if trades < 2:
        return 0.0
    win_rate = float(stats.get("win_rate", 0.0) or 0.0)
    avg_pnl = float(stats.get("avg_pnl", 0.0) or 0.0)
    edge = ((win_rate - 50.0) / 50.0) * 0.45 + max(min(avg_pnl / 5.0, 0.35), -0.35)
    sample_weight = min(trades / 8.0, 1.0)
    return round(edge * sample_weight, 3)


def _inferred_action_from_scores(factor_scores: dict[str, float]) -> str:
    directional = (
        factor_scores.get("sentiment", 0.0)
        + factor_scores.get("geopolitical", 0.0)
        + factor_scores.get("ai_impact", 0.0)
        + factor_scores.get("price", 0.0)
        + factor_scores.get("relative_strength", 0.0)
        + factor_scores.get("regime", 0.0)
    )
    return "BUY" if directional >= 0 else "SELL"
