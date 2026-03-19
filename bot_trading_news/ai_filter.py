from __future__ import annotations

import json
from dataclasses import replace

import requests

from bot_trading_news.config import BotConfig
from bot_trading_news.news import NewsArticle
from bot_trading_news.strategy import NEGATIVE_WORDS, POSITIVE_WORDS, SYMBOL_ALIASES

FINANCE_KEYWORDS = {
    "earnings",
    "guidance",
    "inflation",
    "fed",
    "rates",
    "oil",
    "tariffs",
    "stocks",
    "bitcoin",
    "crypto",
    "etf",
    "market",
    "recession",
    "gdp",
    "treasury",
    "merger",
    "acquisition",
    "downgrade",
    "upgrade",
    "profit",
    "revenue",
    "share",
}

NOISE_SOURCES = {
    "github.com",
    "pypi.org",
    "jalopnik",
    "blizzardwatch",
    "times of india",
    "asymco.com",
}

HIGH_SIGNAL_SOURCES = {
    "reuters",
    "bloomberg",
    "wall street journal",
    "financial times",
    "cnbc",
    "marketwatch",
    "yahoo finance",
    "associated press",
    "ap news",
}


def apply_ai_news_filter(articles: list[NewsArticle], config: BotConfig) -> list[NewsArticle]:
    mode = config.ai_filter_mode
    if mode == "off":
        return articles

    filtered: list[NewsArticle] = []
    openai_available = bool(mode == "openai" and config.openai_api_key)
    prioritized_articles = _prioritize_articles_for_ai(articles, config)
    openai_urls = {
        article.url
        for article in prioritized_articles[: max(config.ai_max_openai_articles, 0)]
        if article.url
    }

    for article in prioritized_articles:
        if openai_available:
            should_use_openai = bool(article.url and article.url in openai_urls)
            if should_use_openai:
                try:
                    enriched = _classify_with_openai(article, config)
                except requests.RequestException:
                    openai_available = False
                    enriched = _classify_with_heuristic(article, config)
                except (ValueError, KeyError, TypeError):
                    enriched = _classify_with_heuristic(article, config)
            else:
                enriched = _classify_with_heuristic(article, config)
        else:
            enriched = _classify_with_heuristic(article, config)
        if enriched.ai_tradable:
            filtered.append(enriched)

    return filtered if filtered else articles


def _classify_with_heuristic(article: NewsArticle, config: BotConfig) -> NewsArticle:
    text = article.combined_text.lower()
    source = article.source.lower()
    relevance = 0.12
    impact = 0.08
    reasons: list[str] = []

    if any(keyword in text for keyword in FINANCE_KEYWORDS):
        relevance += 0.34
        impact += 0.18
        reasons.append("tema financiero claro")

    mentioned_symbols = _mentioned_symbols(text, config.watchlist)
    if mentioned_symbols:
        relevance += 0.22
        impact += 0.14
        reasons.append("activo identificado")

    if any(name in source for name in HIGH_SIGNAL_SOURCES):
        relevance += 0.24
        impact += 0.12
        reasons.append("fuente fuerte")

    strict_blacklist = set(config.source_blacklist) | NOISE_SOURCES
    strict_whitelist = set(config.source_whitelist) | HIGH_SIGNAL_SOURCES

    if any(name in source for name in strict_blacklist):
        relevance -= 0.46
        impact -= 0.18
        reasons.append("fuente ruidosa")
    elif config.strict_free_mode and not any(name in source for name in strict_whitelist):
        relevance -= 0.22
        impact -= 0.08
        reasons.append("fuente no validada")

    positive_hits = sum(1 for word in POSITIVE_WORDS if word in text)
    negative_hits = sum(1 for word in NEGATIVE_WORDS if word in text)
    direction = 0.0
    if positive_hits > negative_hits:
        direction = min((positive_hits - negative_hits) * 0.28, 1.0)
        reasons.append("sesgo alcista")
    elif negative_hits > positive_hits:
        direction = -min((negative_hits - positive_hits) * 0.28, 1.0)
        reasons.append("sesgo bajista")

    if any(term in text for term in ("war", "missile", "sanctions", "middle east", "iran", "israel", "tariff", "fed", "inflation")):
        relevance += 0.18
        impact += 0.22
        reasons.append("catalizador macro")

    if config.strict_free_mode and any(term in text for term in ("class action", "investigation", "law firm", "shareholder alert")):
        relevance -= 0.55
        impact -= 0.25
        reasons.append("tema legal/ruido")

    relevance = max(0.0, min(relevance, 1.0))
    impact = max(0.0, min(impact, 1.0))
    tradable = relevance >= config.ai_min_relevance and (impact >= 0.22 or bool(mentioned_symbols))
    if config.strict_free_mode:
        tradable = tradable and impact >= 0.3 and bool(mentioned_symbols or any(term in text for term in ("fed", "inflation", "earnings", "guidance", "tariff", "oil")))
    summary = ", ".join(reasons[:3]) if reasons else "senal debil"
    return replace(
        article,
        ai_relevance=round(relevance, 2),
        ai_impact=round(impact, 2),
        ai_direction=round(direction, 2),
        ai_summary=summary,
        ai_tradable=tradable,
    )


def _classify_with_openai(article: NewsArticle, config: BotConfig) -> NewsArticle:
    prompt = (
        "Analiza esta noticia para trading. Devuelve solo JSON con claves: "
        "relevance(0..1), impact(0..1), direction(-1..1), tradable(true/false), summary. "
        "Criterio: relevancia financiera real, impacto probable en precio y si sirve para trading corto/medio plazo."
    )
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.ai_filter_model or "gpt-4.1-mini",
            "input": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Fuente: {article.source}\nTitulo: {article.title}\nDescripcion: {article.description}",
                },
            ],
        },
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    output_text = payload.get("output_text")
    if not output_text:
        output = payload.get("output", [])
        for item in output:
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    output_text = content["text"]
                    break
            if output_text:
                break

    try:
        parsed = json.loads(output_text or "{}")
    except json.JSONDecodeError:
        return _classify_with_heuristic(article, config)

    relevance = max(0.0, min(float(parsed.get("relevance", 0.0)), 1.0))
    impact = max(0.0, min(float(parsed.get("impact", 0.0)), 1.0))
    direction = max(-1.0, min(float(parsed.get("direction", 0.0)), 1.0))
    tradable = bool(parsed.get("tradable", False)) and relevance >= config.ai_min_relevance
    summary = str(parsed.get("summary", "")).strip()
    return replace(
        article,
        ai_relevance=round(relevance, 2),
        ai_impact=round(impact, 2),
        ai_direction=round(direction, 2),
        ai_summary=summary,
        ai_tradable=tradable,
    )


def _mentioned_symbols(text: str, watchlist: list[str]) -> list[str]:
    matches: list[str] = []
    for symbol in watchlist:
        aliases = SYMBOL_ALIASES.get(symbol, {symbol.lower()})
        if any(alias in text for alias in aliases):
            matches.append(symbol)
    return matches


def _prioritize_articles_for_ai(articles: list[NewsArticle], config: BotConfig) -> list[NewsArticle]:
    def priority(article: NewsArticle) -> tuple[int, int, int]:
        text = article.combined_text.lower()
        source = article.source.lower()
        strict_whitelist = set(config.source_whitelist) | HIGH_SIGNAL_SOURCES
        high_signal_source = 1 if any(name in source for name in strict_whitelist) else 0
        mentions_symbol = 1 if _mentioned_symbols(text, config.watchlist) else 0
        macro_trigger = 1 if any(
            term in text for term in ("earnings", "fed", "inflation", "war", "sanctions", "tariff", "oil", "bitcoin")
        ) else 0
        return (high_signal_source, mentions_symbol, macro_trigger)

    return sorted(articles, key=priority, reverse=True)
