from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bot_trading_news.config import BotConfig
from bot_trading_news.news import NewsArticle
from bot_trading_news.strategy import Signal


def render_dashboard(
    config: BotConfig,
    articles: list[NewsArticle],
    signals: list[Signal],
    horizon: str = "medium",
    output_path: str = "dashboard.html",
    auto_refresh_seconds: int | None = None,
) -> Path:
    dashboard_path = Path(output_path)
    payload = build_dashboard_payload(config, articles, signals, horizon=horizon)
    html = render_dashboard_html(payload, auto_refresh_seconds=auto_refresh_seconds)
    dashboard_path.write_text(html, encoding="utf-8")
    return dashboard_path


def build_dashboard_payload(config: BotConfig, articles: list[NewsArticle], signals: list[Signal], horizon: str = "medium") -> dict:
    top_signals = signals[:8]
    positive = sum(1 for signal in signals if signal.action == "BUY")
    negative = sum(1 for signal in signals if signal.action == "SELL")
    avg_confidence = round(
        sum(signal.confidence for signal in signals) / len(signals), 1
    ) if signals else 0.0
    avg_score = round(sum(abs(signal.score) for signal in signals) / len(signals), 2) if signals else 0.0

    market_rows = []
    for index, signal in enumerate(signals, start=1):
        market_rows.append(
            {
                "rank": index,
                "symbol": signal.symbol,
                "action": signal.action,
                "score": signal.score,
                "confidence": signal.confidence,
                "expected_return_per_100": signal.expected_return_per_100,
                "bias": _market_bias(signal),
                "momentum": _momentum_points(signal.score),
                "headline": signal.reasons[0] if signal.reasons else "No source linked",
                "headline_url": _find_article_url(signal.reasons[0] if signal.reasons else "", articles),
                "articles": signal.article_count,
                "factor_note": signal.factor_notes[0] if signal.factor_notes else "No factor note",
                "factors": signal.factor_scores,
                "setup_tag": signal.setup_tag,
                "session_tag": signal.session_tag,
                "setup_edge": signal.factor_scores.get("setup_edge", 0.0),
                "regime": _regime_label(signal),
                "chart_points": _chart_points(signal),
            }
        )

    article_rows = []
    for article in articles[:10]:
        article_rows.append(
            {
                "source": article.source,
                "title": article.title,
                "url": article.url,
                "published_at": article.published_at,
            }
        )

    macro_cards = _build_macro_cards(signals)
    factor_rows = _build_factor_rows(top_signals)

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "watchlist_size": len(config.watchlist),
        "signals_count": len(signals),
        "positive_count": positive,
        "negative_count": negative,
        "avg_confidence": avg_confidence,
        "avg_score": avg_score,
        "balance_base": round(config.balance, 2),
        "paper_budget": round(config.balance * config.risk_per_trade, 2),
        "max_daily_trades": config.max_daily_trades,
        "analysis_mode": "MULTI-FACTOR NEWS MODEL",
        "data_source": "sample",
        "smart_money_source": "sample",
        "macro_cards": macro_cards,
        "factor_rows": factor_rows,
        "market_rows": market_rows,
        "article_rows": article_rows,
        "hero": _build_hero(top_signals),
        "hero_items": _build_hero_items(top_signals),
        "smart_money_panel": _build_smart_money_panel(signals),
        "bot_activity": {"balance": {}, "orders": []},
        "broker_status": {"broker": "paper", "status": "simulated", "detail": "Sin actividad registrada."},
        "broker_positions": {},
        "horizon": {
            "key": horizon,
            "label": {"short": "Corto Plazo", "medium": "Medio Plazo", "long": "Largo Plazo"}.get(horizon, "Medio Plazo"),
            "window_label": {"short": "24h - 72h", "medium": "1 - 4 semanas", "long": "1 - 6 meses"}.get(horizon, "1 - 4 semanas"),
            "options": [
                {"key": "short", "label": "Corto Plazo", "window_label": "24h - 72h"},
                {"key": "medium", "label": "Medio Plazo", "window_label": "1 - 4 semanas"},
                {"key": "long", "label": "Largo Plazo", "window_label": "1 - 6 meses"},
            ],
        },
    }


def _build_hero(signals: list[Signal]) -> dict:
    if not signals:
        return {
            "title": "Sin prediccion activa",
            "subtitle": "El motor necesita un flujo de noticias mas fuerte antes de emitir una recomendacion.",
            "dominant_action": "ESPERAR",
        }

    best = signals[0]
    direction = "sesgo alcista" if best.action == "BUY" else "sesgo bajista"
    return {
        "title": f"{best.symbol} {direction}",
        "subtitle": f"Conviccion {best.confidence}% con score de senal {best.score}.",
        "dominant_action": "COMPRA" if best.action == "BUY" else "VENTA",
    }


def _build_hero_items(signals: list[Signal]) -> list[dict]:
    if not signals:
        return [
            {
                "title": "Sin prediccion activa",
                "subtitle": "El motor necesita un flujo de noticias mas fuerte antes de emitir una recomendacion.",
                "dominant_action": "ESPERAR",
                "signals_count": 0,
                "avg_confidence": 0,
                "paper_budget": 0,
            }
        ]

    items = []
    for signal in signals[:5]:
        direction = "sesgo alcista" if signal.action == "BUY" else "sesgo bajista"
        items.append(
            {
                "title": f"{signal.symbol} {direction}",
                "subtitle": f"Conviccion {signal.confidence}% con score de senal {signal.score}.",
                "dominant_action": "COMPRA" if signal.action == "BUY" else "VENTA",
                "symbol": signal.symbol,
                "score": signal.score,
                "confidence": signal.confidence,
                "chart_points": _chart_points(signal),
                "factor_scores": signal.factor_scores,
                "factor_notes": signal.factor_notes,
                "article_count": signal.article_count,
                "regime": _regime_label(signal),
                "expected_return_per_100": signal.expected_return_per_100,
            }
        )
    return items


def _market_bias(signal: Signal) -> str:
    if signal.confidence >= 90:
        return "Alta Conviccion"
    if signal.confidence >= 75:
        return "Momentum Creciendo"
    return "Especulativa"


def _momentum_points(score: float) -> list[int]:
    base = min(max(int(abs(score) * 12), 18), 96)
    return [max(8, min(100, base - 18)), max(12, min(100, base - 4)), max(16, min(100, base + 10))]


def _chart_points(signal: Signal) -> list[int]:
    price_factor = signal.factor_scores.get("price", 0.0)
    regime_factor = signal.factor_scores.get("regime", 0.0)
    smart_money_factor = signal.factor_scores.get("smart_money", 0.0)
    base = 40 + int(signal.score * 4)
    offsets = [-10, -4, 2, 8, 14, 10, 18]
    raw_points = [
        base + offset + int(price_factor * 6) + int(regime_factor * 5) + int(smart_money_factor * 4)
        for offset in offsets
    ]
    return [max(12, min(96, value)) for value in raw_points]


def _build_macro_cards(signals: list[Signal]) -> list[dict]:
    if not signals:
        return [
            {"label": "Regimen de Riesgo", "value": "Neutral", "tone": "cyan", "detail": "No hay presion dominante entre activos"},
            {"label": "Presion Geo", "value": "0.00", "tone": "amber", "detail": "No hay impulso geopolitico fuerte"},
            {"label": "Cobertura News", "value": "0", "tone": "green", "detail": "No hay activos rankeados activos"},
        ]

    geo_total = round(sum(signal.factor_scores.get("geopolitical", 0.0) for signal in signals), 2)
    sentiment_total = round(sum(signal.factor_scores.get("sentiment", 0.0) for signal in signals), 2)
    breadth = len(signals)
    risk_regime = "Risk-Off" if geo_total < -0.8 else "Risk-On" if sentiment_total > 1.5 else "Mixto"
    risk_tone = "red" if risk_regime == "Risk-Off" else "green" if risk_regime == "Risk-On" else "amber"
    geo_tone = "red" if geo_total < 0 else "green" if geo_total > 0 else "amber"
    smart_total = round(sum(signal.factor_scores.get("smart_money", 0.0) for signal in signals), 2)
    smart_tone = "green" if smart_total > 0.5 else "red" if smart_total < -0.5 else "amber"

    return [
        {"label": "Regimen de Riesgo", "value": risk_regime, "tone": risk_tone, "detail": "Inferido desde la mezcla de senales"},
        {"label": "Presion Geo", "value": f"{geo_total:+.2f}", "tone": geo_tone, "detail": "Factor geopolitico cross-asset"},
        {"label": "Cobertura News", "value": str(breadth), "tone": "cyan", "detail": "Activos con conviccion operable"},
        {"label": "Smart Money", "value": f"{smart_total:+.2f}", "tone": smart_tone, "detail": "Presion institucional agregada"},
    ]


def _build_factor_rows(signals: list[Signal]) -> list[dict]:
    rows = []
    for signal in signals[:5]:
        rows.append(
            {
                "symbol": signal.symbol,
                "action": signal.action,
                "sentiment": signal.factor_scores.get("sentiment", 0.0),
                "impact": signal.factor_scores.get("impact", 0.0),
                "geopolitical": signal.factor_scores.get("geopolitical", 0.0),
                "ai_relevance": signal.factor_scores.get("ai_relevance", 0.0),
                "price": signal.factor_scores.get("price", 0.0),
                "relative_strength": signal.factor_scores.get("relative_strength", 0.0),
                "sector_relative_strength": signal.factor_scores.get("sector_relative_strength", 0.0),
                "sector_breadth": signal.factor_scores.get("sector_breadth", 0.0),
                "recency": signal.factor_scores.get("recency", 0.0),
                "source_quality": signal.factor_scores.get("source_quality", 0.0),
                "consensus": signal.factor_scores.get("consensus", 0.0),
                "regime": signal.factor_scores.get("regime", 0.0),
                "validation": signal.factor_scores.get("validation", 0.0),
                "smart_money": signal.factor_scores.get("smart_money", 0.0),
            }
        )
    return rows


def _find_article_url(reason: str, articles: list[NewsArticle]) -> str:
    if not reason:
        return ""
    for article in articles:
        candidate = f"{article.source}: {article.title}".strip()
        if candidate == reason:
            return article.url
    return ""


def _build_smart_money_panel(signals: list[Signal]) -> dict:
    ranked = sorted(
        [signal for signal in signals if abs(signal.factor_scores.get("smart_money", 0.0)) > 0],
        key=lambda item: abs(item.factor_scores.get("smart_money", 0.0)),
        reverse=True,
    )
    top_items = []
    for signal in ranked[:5]:
        top_items.append(
            {
                "symbol": signal.symbol,
                "score": round(signal.factor_scores.get("smart_money", 0.0), 2),
                "note": next(
                    (note for note in signal.factor_notes if "smart money" in note.lower()),
                    "sin detalle institucional",
                ),
            }
        )

    return {
        "coverage": len(ranked),
        "leaders": top_items,
    }


def _regime_label(signal: Signal) -> str:
    regime_value = signal.factor_scores.get("regime", 0.0)
    if regime_value >= 0.8:
        return "Tendencia"
    if regime_value <= -0.8:
        return "Defensivo"
    return "Mixto"


def render_dashboard_html(
    payload: dict,
    auto_refresh_seconds: int | None = None,
    api_endpoint: str | None = None,
) -> str:
    payload_json = json.dumps(payload)
    refresh_meta = (
        f'  <meta http-equiv="refresh" content="{auto_refresh_seconds}">\n'
        if auto_refresh_seconds and auto_refresh_seconds > 0 and not api_endpoint
        else ""
    )
    api_endpoint_json = json.dumps(api_endpoint) if api_endpoint else "null"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
{refresh_meta}  <title>Terminal de Noticias de Trading</title>
  <style>
    :root {{
      --bg: #07111a;
      --bg-soft: #0c1823;
      --bg-elevated: #0f2030;
      --panel: rgba(9, 20, 32, 0.9);
      --panel-border: rgba(120, 167, 197, 0.14);
      --text: #dce7ef;
      --muted: #6f8597;
      --green: #2dde98;
      --red: #ff6b6b;
      --amber: #f7b733;
      --cyan: #66e3ff;
      --grid: rgba(94, 128, 151, 0.12);
      --shadow: 0 18px 60px rgba(0, 0, 0, 0.35);
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Consolas, "SFMono-Regular", Menlo, Monaco, monospace;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(47, 221, 152, 0.13), transparent 28%),
        radial-gradient(circle at top right, rgba(102, 227, 255, 0.12), transparent 22%),
        linear-gradient(180deg, #04090d 0%, var(--bg) 42%, #040a10 100%);
      min-height: 100vh;
    }}

    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(var(--grid) 1px, transparent 1px),
        linear-gradient(90deg, var(--grid) 1px, transparent 1px);
      background-size: 36px 36px;
      opacity: 0.28;
    }}

    .shell {{
      width: min(1480px, calc(100% - 24px));
      margin: 18px auto 28px;
      position: relative;
      z-index: 1;
    }}

    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 12px 16px;
      background: rgba(6, 12, 18, 0.9);
      border: 1px solid var(--panel-border);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      box-shadow: var(--shadow);
    }}

    .topbar-actions {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .toggle-btn {{
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 8px 10px;
      font: inherit;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      cursor: pointer;
    }}

    .brand {{
      font-size: 1.2rem;
      color: white;
      font-weight: 700;
    }}

    .terminal-grid {{
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      gap: 18px;
      margin-top: 18px;
    }}

    .terminal-grid.sidebar-collapsed {{
      grid-template-columns: minmax(0, 1fr);
    }}

    .sidebar {{
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      min-height: 100%;
    }}

    .terminal-grid.sidebar-collapsed .sidebar {{
      display: none;
    }}

    .nav-block {{
      padding: 14px;
      background: rgba(255, 255, 255, 0.025);
      border: 1px solid rgba(255, 255, 255, 0.05);
    }}

    .nav-label {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.68rem;
      margin-bottom: 10px;
    }}

    .nav-list {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .nav-item {{
        display: block;
        padding: 10px 12px;
        background: rgba(255,255,255,0.03);
        border-left: 2px solid transparent;
        color: var(--text);
        text-decoration: none;
      }}

    #monitor-alpha,
    #riesgo-macro,
    #matriz-senales,
    #flujo-noticias {{
        scroll-margin-top: 92px;
      }}

    .nav-item.active {{
      border-left-color: var(--cyan);
      background: linear-gradient(90deg, rgba(102, 227, 255, 0.12), rgba(255,255,255,0.02));
    }}

    .workspace {{
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}

    .hero {{
      display: grid;
      grid-template-columns: 1.7fr 1fr;
      gap: 18px;
    }}

    .panel {{
      background: var(--panel);
      border: 1px solid var(--panel-border);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }}

    .hero-card {{
      padding: 26px;
      min-height: 220px;
      position: relative;
      overflow: hidden;
    }}

    .hero-card::after {{
      content: "";
      position: absolute;
      inset: auto -90px -90px auto;
      width: 220px;
      height: 220px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(45, 222, 152, 0.22), transparent 68%);
    }}

    .eyebrow {{
      color: var(--cyan);
      text-transform: uppercase;
      letter-spacing: 0.2em;
      font-size: 0.72rem;
    }}

    h1 {{
      margin: 14px 0 8px;
      font-size: clamp(2rem, 4vw, 3.6rem);
      line-height: 1;
      text-transform: uppercase;
    }}

    .subtitle {{
      color: #99b1c3;
      font-size: 1rem;
      max-width: 60ch;
    }}

    .hero-stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-top: 28px;
    }}

    .hero-chart-wrap {{
      margin-top: 20px;
      padding: 14px 16px 10px;
      border: 1px solid rgba(255,255,255,0.05);
      background: rgba(255,255,255,0.025);
    }}

    .hero-chart-label {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.68rem;
      margin-bottom: 10px;
    }}

    .hero-visual {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 14px;
      min-height: 136px;
    }}

    .factor-stack {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      justify-content: center;
    }}

    .factor-row {{
      display: grid;
      grid-template-columns: 84px 1fr 52px;
      gap: 10px;
      align-items: center;
      font-size: 0.76rem;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .factor-bar {{
      position: relative;
      height: 10px;
      border: 1px solid rgba(255,255,255,0.06);
      background: rgba(255,255,255,0.03);
      overflow: hidden;
    }}

    .factor-fill {{
      height: 100%;
      background: linear-gradient(90deg, #66e3ff 0%, #2dde98 100%);
      box-shadow: 0 0 18px rgba(102, 227, 255, 0.2);
    }}

    .factor-value {{
      color: var(--text);
      text-align: right;
      font-size: 0.78rem;
    }}

    .scanner-panel {{
      position: relative;
      min-height: 136px;
      border: 1px solid rgba(255,255,255,0.05);
      background:
        linear-gradient(rgba(102, 227, 255, 0.08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(102, 227, 255, 0.08) 1px, transparent 1px),
        rgba(4, 14, 22, 0.65);
      background-size: 20px 20px, 20px 20px, auto;
      overflow: hidden;
    }}

    .scanner-sweep {{
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, transparent 0%, rgba(45, 222, 152, 0.12) 45%, transparent 100%);
      animation: sweepMove 3.4s linear infinite;
      pointer-events: none;
    }}

    .scanner-ring {{
      position: absolute;
      border: 1px solid rgba(102, 227, 255, 0.24);
      border-radius: 50%;
      inset: 18px auto auto 50%;
      transform: translateX(-50%);
    }}

    .scanner-ring.r1 {{ width: 44px; height: 44px; top: 24px; }}
    .scanner-ring.r2 {{ width: 80px; height: 80px; top: 6px; }}
    .scanner-ring.r3 {{ width: 116px; height: 116px; top: -12px; }}

    .scanner-crosshair::before,
    .scanner-crosshair::after {{
      content: "";
      position: absolute;
      background: rgba(102, 227, 255, 0.18);
    }}

    .scanner-crosshair::before {{
      width: 1px;
      height: 100%;
      left: 50%;
      top: 0;
    }}

    .scanner-crosshair::after {{
      height: 1px;
      width: 100%;
      left: 0;
      top: 50%;
    }}

    .scanner-readout {{
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 10px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 0.72rem;
      color: #9ad6e6;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}

    .scanner-line {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    @keyframes sweepMove {{
      0% {{ transform: translateY(-100%); }}
      100% {{ transform: translateY(140%); }}
    }}

    .hero-carousel-controls {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 18px;
    }}

    .hero-dots {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .hero-dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 1px solid rgba(102, 227, 255, 0.35);
      background: rgba(255,255,255,0.08);
      cursor: pointer;
    }}

    .hero-dot.active {{
      background: var(--cyan);
      box-shadow: 0 0 12px rgba(102, 227, 255, 0.45);
    }}

    .hero-nav {{
      display: inline-flex;
      gap: 8px;
    }}

    .hero-nav button {{
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 6px 10px;
      font: inherit;
      cursor: pointer;
      text-transform: uppercase;
      font-size: 0.68rem;
      letter-spacing: 0.08em;
    }}

    .stat {{
      padding: 16px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.05);
    }}

    .stat-label {{
      color: var(--muted);
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.12em;
    }}

    .stat-value {{
      margin-top: 8px;
      font-size: 1.7rem;
      font-weight: 700;
    }}

    .side-card {{
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}

    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border: 1px solid rgba(255,255,255,0.08);
      color: var(--text);
      background: rgba(255,255,255,0.03);
      width: fit-content;
    }}

    .horizon-switcher {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}

    .horizon-btn {{
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.03);
        color: var(--text);
      padding: 8px 12px;
      font: inherit;
      cursor: pointer;
      text-transform: uppercase;
      letter-spacing: 0.08em;
        font-size: 0.72rem;
      }}

    .horizon-btn.active {{
        border-color: rgba(102, 227, 255, 0.45);
        color: var(--cyan);
        background: rgba(102, 227, 255, 0.09);
      }}

    .horizon-window {{
        display: block;
        margin-top: 4px;
        color: var(--text-soft);
        font-size: 0.68rem;
        letter-spacing: 0.08em;
      }}

    .chip::before {{
      content: "";
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 20px rgba(45, 222, 152, 0.75);
    }}

    .macro-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }}

    .macro-card {{
      padding: 14px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.05);
    }}

    .macro-value {{
      margin-top: 10px;
      font-size: 1.4rem;
      font-weight: 700;
    }}

    .macro-detail {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.78rem;
      line-height: 1.4;
    }}

    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 18px;
    }}

    .metric-card {{
        padding: 18px;
        min-height: 120px;
      }}

    .ops-layout {{
        display: grid;
        grid-template-columns: 0.95fr 1.05fr;
        gap: 18px;
      }}

    .ops-card {{
        padding: 18px;
      }}

    .ops-balance-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-top: 14px;
      }}

    .ops-mini {{
        padding: 14px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.05);
      }}

    .ops-mini-value {{
        margin-top: 8px;
        font-size: 1.35rem;
        font-weight: 700;
      }}

    .ops-pnl-card {{
        margin-top: 14px;
        padding: 16px 18px;
        border: 1px solid rgba(102, 227, 255, 0.18);
        background: linear-gradient(135deg, rgba(14, 35, 53, 0.92), rgba(10, 24, 36, 0.98));
        box-shadow: inset 0 0 0 1px rgba(102, 227, 255, 0.05);
      }}

    .ops-pnl-value {{
        margin-top: 8px;
        font-size: 2rem;
        font-weight: 800;
        letter-spacing: 0.03em;
      }}

    .ops-history {{
        display: flex;
        flex-direction: column;
        gap: 10px;
        max-height: 340px;
        overflow-y: auto;
        padding-right: 6px;
      }}

    .ops-row {{
        display: grid;
        grid-template-columns: 86px 90px 1fr 86px 96px;
        gap: 12px;
        align-items: start;
        padding: 12px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.05);
      }}

    .ops-detail {{
        color: var(--muted);
        font-size: 0.76rem;
        line-height: 1.45;
      }}

    .ops-time {{
        margin-top: 6px;
        color: #9ad6e6;
        font-size: 0.73rem;
        letter-spacing: 0.03em;
      }}

    .metric-value {{
      margin-top: 22px;
      font-size: 2rem;
      font-weight: 700;
    }}

    .green {{ color: var(--green); }}
    .red {{ color: var(--red); }}
    .amber {{ color: var(--amber); }}
    .cyan {{ color: var(--cyan); }}

    .layout {{
      display: grid;
      grid-template-columns: 1.4fr 0.9fr;
      gap: 18px;
      align-items: start;
    }}

    .layout.right-collapsed {{
      grid-template-columns: 1fr;
    }}

    .layout.right-collapsed .feed-panel {{
      display: none;
    }}

    .research-layout {{
        display: grid;
        grid-template-columns: 1.05fr 0.95fr;
        gap: 18px;
        align-items: start;
      }}

    .table-panel, .feed-panel, .factor-panel, .notes-panel {{
        padding: 18px;
      }}

    .feed-panel {{
        height: fit-content;
        max-height: 760px;
        overflow: hidden;
      }}

    .factor-panel, .notes-panel {{
        height: fit-content;
        align-self: start;
      }}

    .table-panel {{
      height: fit-content;
    }}

    .section-title {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      font-size: 0.78rem;
    }}

    .table-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }}

    .table-controls {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}

    .table-controls select {{
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 6px 8px;
      font: inherit;
    }}

    .table-pager {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}

    .pager-btn {{
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 6px 10px;
      font: inherit;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      cursor: pointer;
    }}

    .pager-btn:disabled {{
      opacity: 0.45;
      cursor: default;
    }}

    .pager-label {{
      color: var(--muted);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      min-width: 110px;
      text-align: center;
    }}

    .title-main {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}

    .info-tip {{
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      border: 1px solid rgba(102, 227, 255, 0.35);
      color: var(--cyan);
      background: rgba(102, 227, 255, 0.08);
      font-size: 0.68rem;
      font-weight: 700;
      cursor: help;
      text-transform: none;
    }}

    .info-tip::after {{
      content: attr(data-tip);
      position: absolute;
      left: 50%;
      bottom: calc(100% + 10px);
      transform: translateX(-50%);
      width: 220px;
      padding: 10px 12px;
      border: 1px solid rgba(102, 227, 255, 0.18);
      background: rgba(5, 13, 20, 0.96);
      color: var(--text);
      line-height: 1.45;
      font-size: 0.74rem;
      letter-spacing: normal;
      text-transform: none;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.15s ease, transform 0.15s ease;
      z-index: 20;
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
    }}

    .info-tip:hover::after,
    .info-tip:focus-visible::after {{
      opacity: 1;
      transform: translateX(-50%) translateY(-2px);
    }}

    .floating-tip {{
      position: fixed;
      max-width: 260px;
      padding: 10px 12px;
      border: 1px solid rgba(102, 227, 255, 0.2);
      background: rgba(5, 13, 20, 0.98);
      color: var(--text);
      line-height: 1.45;
      font-size: 0.76rem;
      z-index: 9999;
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
      pointer-events: none;
      display: none;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}

    th, td {{
      padding: 10px 8px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      text-align: left;
      vertical-align: middle;
    }}

    th {{
      color: var(--muted);
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.14em;
      font-weight: 600;
    }}

    .compact-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}

    .compact-table th, .compact-table td {{
      padding: 10px 8px;
    }}

    .market-table th:nth-child(1),
    .market-table td:nth-child(1) {{
      width: 48px;
    }}

    .market-table th:nth-child(2),
    .market-table td:nth-child(2) {{
      width: 88px;
    }}

    .market-table th:nth-child(3),
    .market-table td:nth-child(3) {{
      width: 92px;
    }}

    .market-table th:nth-child(4),
    .market-table td:nth-child(4) {{
      width: 82px;
    }}

    .market-table th:nth-child(5),
    .market-table td:nth-child(5) {{
      width: 100px;
    }}

    .market-table th:nth-child(6),
    .market-table td:nth-child(6) {{
      width: 104px;
    }}

    .market-table th:nth-child(7),
    .market-table td:nth-child(7) {{
      width: 108px;
    }}

    .market-table th:nth-child(8),
    .market-table td:nth-child(8) {{
      width: 132px;
    }}

    .market-table th:nth-child(9),
    .market-table td:nth-child(9) {{
      width: 86px;
    }}

    .market-table th:nth-child(10),
    .market-table td:nth-child(10) {{
      min-width: 320px;
    }}

    .asset-cell {{
      font-weight: 700;
      letter-spacing: 0.04em;
    }}

    .driver-cell {{
      line-height: 1.3;
      color: #c6d3dc;
      font-size: 0.82rem;
      max-width: 360px;
      overflow: hidden;
    }}

    .driver-main {{
      display: block;
      color: var(--text);
      font-weight: 600;
      margin-bottom: 4px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .driver-sub {{
      display: -webkit-box;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }}

    .driver-link {{
      display: block;
      color: inherit;
      text-decoration: none;
    }}

    .driver-link.disabled {{
      pointer-events: none;
      cursor: default;
    }}

    .driver-link:hover .driver-main,
    .driver-link:hover .driver-sub {{
      color: var(--cyan);
    }}

    .article-link {{
      color: var(--cyan);
      text-decoration: none;
      border-bottom: 1px dashed rgba(102, 227, 255, 0.35);
      padding-bottom: 1px;
    }}

    .article-link:hover {{
      color: white;
      border-bottom-color: rgba(255, 255, 255, 0.45);
    }}

    .score-cell,
    .confidence-cell,
    .articles-cell {{
      white-space: nowrap;
    }}

    .pill {{
      display: inline-block;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }}

    .pill-buy {{
      background: rgba(45, 222, 152, 0.14);
      color: var(--green);
    }}

    .pill-sell {{
      background: rgba(255, 107, 107, 0.14);
      color: var(--red);
    }}

    .spark {{
      display: flex;
      align-items: end;
      gap: 5px;
      min-width: 92px;
      height: 34px;
    }}

    .spark span {{
      display: block;
      width: 12px;
      background: linear-gradient(180deg, rgba(102, 227, 255, 0.2), rgba(45, 222, 152, 0.95));
      border-radius: 3px 3px 0 0;
    }}

    .feed-item {{
        padding: 14px 0;
        border-bottom: 1px solid rgba(255,255,255,0.06);
      }}

    #feed {{
        max-height: 660px;
        overflow-y: auto;
        padding-right: 6px;
      }}

    .feed-source {{
      color: var(--cyan);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.68rem;
    }}

    .feed-title {{
      margin-top: 8px;
      font-size: 0.96rem;
      line-height: 1.45;
    }}

    .feed-time {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.78rem;
    }}

    .insight-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}

    .insight-item {{
      padding: 12px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.05);
      line-height: 1.45;
    }}

    .insight-kicker {{
      color: var(--cyan);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.68rem;
      margin-bottom: 8px;
    }}

    .footer {{
      padding: 14px 18px;
      color: var(--muted);
      font-size: 0.82rem;
      border: 1px solid var(--panel-border);
      background: rgba(5, 11, 17, 0.88);
    }}

    a {{
      color: inherit;
      text-decoration: none;
    }}

    html {{
      scroll-behavior: smooth;
    }}

    @media (max-width: 980px) {{
      .terminal-grid, .hero, .layout, .metrics, .macro-grid, .research-layout, .ops-layout {{
          grid-template-columns: 1fr;
        }}

        .hero-stats {{
          grid-template-columns: 1fr;
        }}

        .ops-balance-grid {{
          grid-template-columns: 1fr 1fr;
        }}

      .sidebar {{
        order: 2;
      }}

      table {{
        font-size: 0.84rem;
      }}

      th:nth-child(6),
      td:nth-child(6) {{
        display: none;
      }}

      .market-table th:nth-child(9),
      .market-table td:nth-child(9) {{
        min-width: 220px;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div class="brand">terminal alpha news</div>
      <div class="topbar-actions">
        <button class="toggle-btn" id="toggle-sidebar" type="button">Ocultar Menu</button>
        <button class="toggle-btn" id="toggle-right-panel" type="button">Ocultar Noticias</button>
        <div id="generated-at">inteligencia de mercado | modelo multifactor | generado {payload["generated_at"]}</div>
      </div>
    </div>

    <section class="terminal-grid" id="terminal-grid">
      <aside class="panel sidebar">
        <div class="nav-block">
          <div class="nav-label">Espacio</div>
          <div class="nav-list">
            <a class="nav-item active" href="#monitor-alpha">Monitor Alpha</a>
            <a class="nav-item" href="#riesgo-macro">Riesgo Macro</a>
            <a class="nav-item" href="#matriz-senales">Matriz de Senales</a>
            <a class="nav-item" href="#flujo-noticias">Flujo de Noticias</a>
          </div>
        </div>

        <div class="nav-block">
          <div class="nav-label">Ejecucion</div>
          <div class="chip">Modo simulacion en tiempo real</div>
        </div>

        <div class="nav-block">
          <div class="nav-label">Cobertura</div>
          <div class="subtitle">{payload["watchlist_size"]} activos monitoreados con maximo de {payload["max_daily_trades"]} trades rankeados por dia.</div>
        </div>

        <div class="nav-block">
          <div class="nav-label">Modelo</div>
          <div class="subtitle">{payload["analysis_mode"]}</div>
          <div class="nav-label" style="margin-top:12px;">Fuente</div>
          <div class="subtitle" id="data-source-label">{payload["data_source"]}</div>
          <div class="nav-label" style="margin-top:12px;">Smart Money</div>
          <div class="subtitle" id="smart-money-source-label">{payload["smart_money_source"]}</div>
          <div class="nav-label" style="margin-top:12px;">Horizonte</div>
          <div class="subtitle" id="current-horizon-label">{payload["horizon"]["label"]}</div>
          <div class="subtitle" id="current-horizon-window">{payload["horizon"]["window_label"]}</div>
          <div class="horizon-switcher" id="horizon-switcher"></div>
        </div>
      </aside>

      <div class="workspace">
        <section class="hero" id="monitor-alpha">
          <article class="panel hero-card">
            <div class="eyebrow">Motor de Prediccion</div>
            <h1 id="hero-title">{payload["hero"]["title"]}</h1>
            <div class="subtitle" id="hero-subtitle">{payload["hero"]["subtitle"]}</div>
            <div class="hero-carousel-controls">
              <div class="hero-dots" id="hero-dots"></div>
              <div class="hero-nav">
                <button id="hero-prev" type="button">Prev</button>
                <button id="hero-next" type="button">Next</button>
              </div>
            </div>
            <div class="hero-chart-wrap">
              <div class="hero-chart-label">Escaner de senal</div>
              <div class="hero-visual">
                <div class="factor-stack" id="hero-factor-stack"></div>
                <div class="scanner-panel">
                  <div class="scanner-sweep"></div>
                  <div class="scanner-crosshair">
                    <div class="scanner-ring r1"></div>
                    <div class="scanner-ring r2"></div>
                    <div class="scanner-ring r3"></div>
                  </div>
                  <div class="scanner-readout" id="hero-scanner-readout"></div>
                </div>
              </div>
            </div>
            <div class="hero-stats">
              <div class="stat">
                <div class="stat-label">Senales Activas</div>
                <div class="stat-value" id="signals-count">{payload["signals_count"]}</div>
              </div>
              <div class="stat">
                <div class="stat-label">Conviccion Promedio</div>
                <div class="stat-value" id="avg-confidence">{payload["avg_confidence"]}%</div>
              </div>
              <div class="stat">
                <div class="stat-label">Presupuesto Riesgo</div>
                <div class="stat-value" id="paper-budget">${payload["paper_budget"]}</div>
              </div>
              <div class="stat">
                <div class="stat-label">USD100 Esperado</div>
                <div class="stat-value" id="hero-expected-return">${payload["hero_items"][0]["expected_return_per_100"] if payload["hero_items"] else 0}</div>
                <div class="subtitle" id="hero-expected-window" style="font-size:0.78rem;margin-top:6px;">{payload["horizon"]["window_label"]}</div>
              </div>
            </div>
          </article>

          <aside class="panel side-card" id="riesgo-macro">
            <div>
              <div class="section-title"><span class="title-main">Estado del Desk <span class="info-tip" tabindex="0" data-tip="Mira aca el contexto general del motor: sesgo dominante, lectura macro y si el entorno parece mas alcista, bajista o mixto.">i</span></span><span id="dominant-action">{payload["hero"]["dominant_action"]}</span></div>
              <div class="subtitle">Este stack rankea ideas con sentimiento, recencia, calidad de fuente, impacto de evento, geopolitica y consenso entre articulos.</div>
            </div>
            <div class="macro-grid" id="macro-grid"></div>
          </aside>
        </section>

        <section class="metrics">
          <article class="panel metric-card">
            <div class="stat-label">Picks Alcistas</div>
            <div class="metric-value green" id="positive-count">{payload["positive_count"]}</div>
          </article>
          <article class="panel metric-card">
            <div class="stat-label">Picks Bajistas</div>
            <div class="metric-value red" id="negative-count">{payload["negative_count"]}</div>
          </article>
          <article class="panel metric-card">
            <div class="stat-label">Score Promedio</div>
            <div class="metric-value amber" id="avg-score">{payload["avg_score"]}</div>
          </article>
          <article class="panel metric-card">
            <div class="stat-label">Salud del Sistema</div>
            <div class="metric-value cyan">EN LINEA</div>
          </article>
        </section>

        <section class="ops-layout">
          <article class="panel ops-card">
            <div class="section-title">
              <span class="title-main">Balance del Bot <span class="info-tip" tabindex="0" data-tip="Resumen de la cuenta paper y del rendimiento acumulado del bot. Mira equity, cash, buying power y PnL contra el balance base configurado.">i</span></span>
              <span id="broker-badge">{payload["broker_status"].get("broker", "paper")}</span>
            </div>
            <div class="subtitle" id="broker-status-line">{payload["broker_status"].get("detail", "Sin estado de broker.")}</div>
              <div class="ops-balance-grid">
                <div class="ops-mini">
                <div class="stat-label">Equity <span class="info-tip" tabindex="0" data-tip="Valor total actual de la cuenta paper. Si sube, el bot va ganando; si baja, va perdiendo.">i</span></div>
                 <div class="ops-mini-value" id="ops-equity">$0.00</div>
                </div>
                <div class="ops-mini">
                <div class="stat-label">Cash <span class="info-tip" tabindex="0" data-tip="Efectivo libre en la cuenta. Es la parte que no esta comprometida en posiciones abiertas.">i</span></div>
                  <div class="ops-mini-value" id="ops-cash">$0.00</div>
                </div>
                <div class="ops-mini">
                <div class="stat-label">Buying Power <span class="info-tip" tabindex="0" data-tip="Capacidad operativa disponible segun el broker. Te marca cuanto puede seguir usando el bot para nuevas entradas.">i</span></div>
                  <div class="ops-mini-value" id="ops-buying-power">$0.00</div>
                </div>
                <div class="ops-mini">
                <div class="stat-label">PnL Bot <span class="info-tip" tabindex="0" data-tip="Ganancia o perdida estimada del bot contra el balance base configurado. Positivo es arriba, negativo es abajo.">i</span></div>
                  <div class="ops-mini-value" id="ops-pnl">$0.00</div>
                </div>
              </div>
              <div class="ops-pnl-card">
                <div class="stat-label">Ganancia / Perdida Total del Bot <span class="info-tip" tabindex="0" data-tip="Este es el resultado total acumulado del bot frente al balance base configurado. Verde suma, rojo resta.">i</span></div>
                <div class="ops-pnl-value" id="ops-pnl-total">$0.00</div>
              </div>
            </article>

          <article class="panel ops-card">
            <div class="section-title">
              <span class="title-main">Historial de Operaciones <span class="info-tip" tabindex="0" data-tip="Ultimas operaciones enviadas por el bot. Vas a ver simbolo, lado, estado, monto y el detalle devuelto por el broker.">i</span></span>
              <span>ultimas 80 <span class="info-tip" tabindex="0" data-tip="Aca se guardan envios recientes del bot: pending, blocked, rejected o filled si el broker lo confirma mas adelante.">i</span></span>
            </div>
            <div class="ops-history" id="ops-history"></div>
          </article>
        </section>

        <section class="layout" id="main-layout">
          <article class="panel table-panel">
            <div class="section-title">
              <span class="title-main">Recomendaciones de Mercado <span class="info-tip" tabindex="0" data-tip="Esta tabla muestra los activos mas interesantes del momento. Busca score alto, conviccion alta y drivers claros para entender por que el modelo los destaca.">i</span></span>
              <span>ordenadas por fuerza de senal</span>
            </div>
            <div class="table-toolbar">
              <div class="table-controls">
                <span>Mostrar</span>
                <select id="page-size-select">
                  <option value="10">Top 10</option>
                  <option value="20">Top 20</option>
                  <option value="50">Top 50</option>
                </select>
              </div>
              <div class="table-pager">
                <button class="pager-btn" id="pager-prev" type="button">Prev</button>
                <div class="pager-label" id="pager-label">Pagina 1 / 1</div>
                <button class="pager-btn" id="pager-next" type="button">Next</button>
              </div>
            </div>
            <div style="overflow-x:auto;">
            <table class="market-table">
              <thead>
                <tr>
                  <th><span class="title-main"># <span class="info-tip" tabindex="0" data-tip="Posicion del activo en el ranking. El numero 1 es la oportunidad mas fuerte segun el modelo actual.">i</span></span></th>
                  <th><span class="title-main">Activo <span class="info-tip" tabindex="0" data-tip="Ticker o simbolo del activo evaluado. Te dice sobre que mercado aplica la recomendacion.">i</span></span></th>
                  <th><span class="title-main">Pick <span class="info-tip" tabindex="0" data-tip="Direccion sugerida por el modelo: compra si espera sesgo alcista o venta si detecta presion bajista.">i</span></span></th>
                  <th><span class="title-main">Score <span class="info-tip" tabindex="0" data-tip="Fuerza total de la senal. Cuanto mas lejos de cero, mas fuerte es la combinacion de factores a favor o en contra.">i</span></span></th>
                  <th><span class="title-main">Conviccion <span class="info-tip" tabindex="0" data-tip="Que tan confiable parece la senal. Sube cuando varios factores coinciden y no depende solo de una noticia aislada.">i</span></span></th>
                  <th><span class="title-main">Momentum <span class="info-tip" tabindex="0" data-tip="Mini visual de fuerza relativa. Sirve para ver rapido si el score esta tibio o si viene con empuje.">i</span></span></th>
                  <th><span class="title-main"><span id="usd100-header-text">USD100 / {payload["horizon"]["window_label"]}</span> <span class="info-tip" tabindex="0" data-tip="Estimacion interna de ganancia esperada por cada 100 USD asignados dentro del horizonte activo. Es una proyeccion del modelo, no una garantia real.">i</span></span></th>
                  <th><span class="title-main">Sesgo <span class="info-tip" tabindex="0" data-tip="Lectura corta del tipo de oportunidad: alta conviccion, momentum creciendo o idea mas especulativa.">i</span></span></th>
                  <th><span class="title-main">Articulos <span class="info-tip" tabindex="0" data-tip="Cantidad de noticias que empujan ese activo. Mas articulos no siempre es mejor, pero ayuda a medir amplitud y consenso.">i</span></span></th>
                  <th><span class="title-main">Driver <span class="info-tip" tabindex="0" data-tip="Motivo principal detras de la senal. Mira aca que factor domina, el regimen de mercado y cual fue el titular que disparo la idea.">i</span></span></th>
                </tr>
              </thead>
              <tbody id="market-body"></tbody>
            </table>
            </div>
          </article>

          <aside class="panel feed-panel" id="flujo-noticias">
            <div class="section-title">
              <span class="title-main">Feed de Noticias <span class="info-tip" tabindex="0" data-tip="Aca ves las noticias crudas que alimentan el analisis. Sirve para validar si el ranking tiene sentido o si una senal parece sobreinterpretada.">i</span></span>
              <span>inteligencia de fuentes</span>
            </div>
            <div id="feed"></div>
          </aside>
        </section>

        <section class="research-layout">
          <article class="panel factor-panel" id="matriz-senales">
            <div class="section-title">
              <span class="title-main">Matriz de Factores <span class="info-tip" tabindex="0" data-tip="Desglose numerico del modelo. Mira que factor explica cada activo: sentimiento, impacto, geopolitica, recencia, calidad de fuente y consenso.">i</span></span>
              <span>activos mejor rankeados</span>
            </div>
            <table class="compact-table">
              <thead>
                <tr>
                  <th><span class="title-main">Activo <span class="info-tip" tabindex="0" data-tip="Ticker y direccion sugerida para ese activo.">i</span></span></th>
                  <th><span class="title-main">Sent <span class="info-tip" tabindex="0" data-tip="Sentimiento textual. Positivo si el lenguaje de las noticias favorece suba, negativo si sugiere baja.">i</span></span></th>
                  <th><span class="title-main">Imp <span class="info-tip" tabindex="0" data-tip="Impacto del evento. Mide si la noticia trae catalizadores potentes como earnings, guidance, ETF o litigios.">i</span></span></th>
                  <th><span class="title-main">Geo <span class="info-tip" tabindex="0" data-tip="Factor geopolitico. Captura guerra, sanciones, tension regional, tasas, inflacion y otros shocks macro.">i</span></span></th>
                  <th><span class="title-main">Rec <span class="info-tip" tabindex="0" data-tip="Recencia. Pesa mas una noticia reciente que una vieja.">i</span></span></th>
                  <th><span class="title-main">Fte <span class="info-tip" tabindex="0" data-tip="Calidad de fuente. Reuters o Bloomberg suelen pesar mas que fuentes menos confiables.">i</span></span></th>
                  <th><span class="title-main">Cons <span class="info-tip" tabindex="0" data-tip="Consenso entre articulos. Sube cuando varias noticias apuntan en la misma direccion.">i</span></span></th>
                  <th><span class="title-main">SM <span class="info-tip" tabindex="0" data-tip="Smart Money. Resume conviccion institucional estimada usando carteras reportadas o muestra sample institucional.">i</span></span></th>
                  <th><span class="title-main">Reg <span class="info-tip" tabindex="0" data-tip="Regimen de mercado. Resume si el activo parece estar en tendencia, mixto o defensivo segun precio, volumen y volatilidad.">i</span></span></th>
                  <th><span class="title-main">Val <span class="info-tip" tabindex="0" data-tip="Validacion historica simple. Refuerza la senal si la serie reciente tuvo mejor comportamiento direccional.">i</span></span></th>
                </tr>
              </thead>
              <tbody id="factor-body"></tbody>
            </table>
          </article>

          <aside class="panel notes-panel">
            <div class="section-title">
              <span class="title-main">Notas del Desk <span class="info-tip" tabindex="0" data-tip="Resumen interpretativo para leer la pantalla mas rapido. Te orienta sobre riesgo, geopolitica y proximos upgrades del modelo.">i</span></span>
              <span>interpretacion rapida</span>
            </div>
            <div class="insight-list">
              <div class="insight-item">
                <div class="insight-kicker">Smart Money</div>
                <div id="smart-money-summary">Cobertura institucional 0 activos.</div>
              </div>
              <div class="insight-item">
                <div class="insight-kicker">Lectura de Riesgo</div>
                Los mejores picks se ordenan por score total, pero la conviccion sube cuando varios factores coinciden y no cuando domina uno solo.
              </div>
              <div class="insight-item">
                <div class="insight-kicker">Lente Geopolitica</div>
                Los titulares geopoliticos pueden mover activos incluso sin mencionar tickers de forma directa, especialmente `SPY`, `NVDA`, `AAPL`, `TSLA` y `BTC`.
              </div>
              <div class="insight-item">
                <div class="insight-kicker">Siguiente Upgrade</div>
                La mejora mas fuerte desde aca es sumar precio, volumen, volatilidad, deteccion de regimen y validacion historica real.
              </div>
            </div>
          </aside>
        </section>

        <div class="footer">
          Construido para simulacion y research. El ranking actual mezcla sentimiento, recencia, calidad de fuente, impacto de catalizadores, geopolitica y consenso. El siguiente salto es sumar microestructura y factores basados en precio.
        </div>
      </div>
    </section>
  </div>

  <script>
    let payload = {payload_json};
    const apiEndpoint = {api_endpoint_json};
    let currentHorizon = payload.horizon?.key || "medium";
    let sidebarCollapsed = false;
    let rightPanelCollapsed = false;
    let heroIndex = 0;
    let heroTimer = null;
    let pageSize = 10;
    let currentPage = 1;
    let activeFloatingTip = null;

    if ("scrollRestoration" in window.history) {{
      window.history.scrollRestoration = "manual";
    }}

    function renderSummary() {{
      const heroItems = payload.hero_items && payload.hero_items.length ? payload.hero_items : [payload.hero];
      if (heroIndex >= heroItems.length) {{
        heroIndex = 0;
      }}
      const currentHero = heroItems[heroIndex];
      document.getElementById("generated-at").textContent =
        `inteligencia de mercado | modelo multifactor | generado ${{payload.generated_at}}`;
      document.getElementById("hero-title").textContent = currentHero.title;
      document.getElementById("hero-subtitle").textContent = currentHero.subtitle;
      document.getElementById("dominant-action").textContent = currentHero.dominant_action;
      document.getElementById("signals-count").textContent = payload.signals_count;
      document.getElementById("avg-confidence").textContent = `${{payload.avg_confidence}}%`;
      document.getElementById("paper-budget").textContent = `$${{payload.paper_budget}}`;
      document.getElementById("hero-expected-return").textContent = `$${{(currentHero.expected_return_per_100 || 0).toFixed(2)}}`;
      document.getElementById("positive-count").textContent = payload.positive_count;
      document.getElementById("negative-count").textContent = payload.negative_count;
      document.getElementById("avg-score").textContent = payload.avg_score;
        document.getElementById("data-source-label").textContent =
          payload.data_source === "api" ? "Noticias Reales" : "Sample / Fallback";
        document.getElementById("smart-money-source-label").textContent =
          payload.smart_money_source === "fmp"
            ? "FMP / 13F"
            : payload.smart_money_source === "sec"
              ? "SEC / 13F"
              : "Sample Institucional";
        document.getElementById("current-horizon-label").textContent = payload.horizon.label;
        document.getElementById("current-horizon-window").textContent = payload.horizon.window_label;
        document.getElementById("hero-expected-window").textContent = payload.horizon.window_label;
        document.getElementById("usd100-header-text").textContent = `USD100 / ${{payload.horizon.window_label}}`;
        renderBotOperations();
        const smartCoverage = payload.smart_money_panel?.coverage || 0;
      const smartLeaders = (payload.smart_money_panel?.leaders || [])
        .map((item) => `${{item.symbol}} (${{item.score}})`)
        .slice(0, 3)
        .join(", ");
      document.getElementById("smart-money-summary").textContent =
        smartCoverage > 0
          ? `Cobertura institucional ${{smartCoverage}} activos. Lideres: ${{smartLeaders}}.`
          : "Sin cobertura institucional para los activos rankeados.";
      renderHorizonButtons();
      renderHeroDots();
      renderHeroVisual(currentHero);
      syncLayoutButtons();
    }}

    function renderHeroVisual(hero) {{
      const factors = hero.factor_scores || {{}};
      const rows = [
        ["Sent", factors.sentiment || 0],
        ["Geo", factors.geopolitical || 0],
        ["Price", factors.price || 0],
        ["Reg", factors.regime || 0],
        ["Smart", factors.smart_money || 0],
      ];

      const stack = document.getElementById("hero-factor-stack");
      stack.innerHTML = rows.map(([label, value]) => {{
        const normalized = Math.max(6, Math.min(100, 50 + (Number(value) * 18)));
        return `
          <div class="factor-row">
            <div>${{label}}</div>
            <div class="factor-bar"><div class="factor-fill" style="width:${{normalized}}%"></div></div>
            <div class="factor-value">${{Number(value).toFixed(2)}}</div>
          </div>
        `;
      }}).join("");

      const notes = hero.factor_notes && hero.factor_notes.length
        ? hero.factor_notes
        : ["sin notas", "sin drivers", "sin contexto"];
      const readout = document.getElementById("hero-scanner-readout");
      readout.innerHTML = `
        <div class="scanner-line">activo :: ${{hero.symbol || "N/A"}}</div>
        <div class="scanner-line">regimen :: ${{hero.regime || "Mixto"}}</div>
        <div class="scanner-line">articulos :: ${{hero.article_count || 0}}</div>
        <div class="scanner-line">conviccion :: ${{hero.confidence || 0}}%</div>
        <div class="scanner-line">driver_1 :: ${{notes[0] || "sin nota"}}</div>
        <div class="scanner-line">driver_2 :: ${{notes[1] || "sin nota"}}</div>
      `;
    }}

    function renderHeroDots() {{
      const heroItems = payload.hero_items && payload.hero_items.length ? payload.hero_items : [payload.hero];
      const node = document.getElementById("hero-dots");
      node.innerHTML = heroItems.map((_, index) => `
        <button
          class="hero-dot ${{index === heroIndex ? "active" : ""}}"
          data-hero-index="${{index}}"
          type="button"
          aria-label="Ir a prediccion ${{index + 1}}"
        ></button>
      `).join("");

      node.querySelectorAll(".hero-dot").forEach((button) => {{
        button.addEventListener("click", () => {{
          heroIndex = Number(button.dataset.heroIndex || 0);
          renderSummary();
          restartHeroTimer();
        }});
      }});
    }}

    function moveHero(direction) {{
      const heroItems = payload.hero_items && payload.hero_items.length ? payload.hero_items : [payload.hero];
      if (!heroItems.length) {{
        return;
      }}
      heroIndex = (heroIndex + direction + heroItems.length) % heroItems.length;
      renderSummary();
      restartHeroTimer();
    }}

    function restartHeroTimer() {{
      if (heroTimer) {{
        window.clearInterval(heroTimer);
      }}
      const heroItems = payload.hero_items && payload.hero_items.length ? payload.hero_items : [payload.hero];
      if (heroItems.length <= 1) {{
        return;
      }}
      heroTimer = window.setInterval(() => {{
        moveHero(1);
      }}, 4500);
    }}

    function syncLayoutButtons() {{
      const sidebarButton = document.getElementById("toggle-sidebar");
      const rightButton = document.getElementById("toggle-right-panel");
      sidebarButton.textContent = sidebarCollapsed ? "Mostrar Menu" : "Ocultar Menu";
      rightButton.textContent = rightPanelCollapsed ? "Mostrar Noticias" : "Ocultar Noticias";
    }}

    function applyLayoutState() {{
      const terminalGrid = document.getElementById("terminal-grid");
      const mainLayout = document.getElementById("main-layout");
      terminalGrid.classList.toggle("sidebar-collapsed", sidebarCollapsed);
      mainLayout.classList.toggle("right-collapsed", rightPanelCollapsed);
      syncLayoutButtons();
    }}

    function renderHorizonButtons() {{
      const node = document.getElementById("horizon-switcher");
        node.innerHTML = payload.horizon.options.map((option) => `
          <button
            class="horizon-btn ${{option.key === currentHorizon ? "active" : ""}}"
            data-horizon="${{option.key}}"
            type="button"
          >
            ${{option.label}}
            <span class="horizon-window">${{option.window_label}}</span>
          </button>
        `).join("");

      node.querySelectorAll(".horizon-btn").forEach((button) => {{
        button.addEventListener("click", () => {{
          currentHorizon = button.dataset.horizon || "medium";
          refreshPayload(true);
        }});
      }});
    }}

    function renderRows() {{
      const body = document.getElementById("market-body");
      const totalRows = payload.market_rows || [];
      const totalPages = Math.max(1, Math.ceil(totalRows.length / pageSize));
      if (currentPage > totalPages) {{
        currentPage = totalPages;
      }}
      const start = (currentPage - 1) * pageSize;
      const pagedRows = totalRows.slice(start, start + pageSize);
      body.innerHTML = pagedRows.map((row) => {{
        const pillClass = row.action === "BUY" ? "pill pill-buy" : "pill pill-sell";
        const bars = row.momentum.map((value) => `<span style="height:${{value}}%"></span>`).join("");
        return `
          <tr>
            <td>${{row.rank}}</td>
            <td class="asset-cell">${{row.symbol}}</td>
            <td><span class="${{pillClass}}">${{row.action === "BUY" ? "COMPRA" : "VENTA"}}</span></td>
            <td class="score-cell">${{row.score}}</td>
            <td class="confidence-cell">${{row.confidence}}%</td>
            <td><div class="spark">${{bars}}</div></td>
            <td class="score-cell">$${{Number(row.expected_return_per_100 || 0).toFixed(2)}}</td>
            <td>${{row.bias}}</td>
            <td class="articles-cell">
              ${{row.headline_url ? `<a class="article-link" href="${{row.headline_url}}" target="_blank" rel="noreferrer">${{row.articles}}</a>` : row.articles}}
            </td>
            <td class="driver-cell">
              <a class="driver-link ${{row.headline_url ? '' : 'disabled'}}" href="${{row.headline_url || '#'}}" target="_blank" rel="noreferrer">
                <span class="driver-main">${{row.factor_note}}</span>
                <span class="driver-sub">Regimen ${{row.regime}} | Abrir noticia: ${{row.headline}}</span>
              </a>
            </td>
          </tr>
        `;
      }}).join("");
      renderPager(totalPages, totalRows.length);
    }}

    function renderPager(totalPages, totalRows) {{
      document.getElementById("pager-label").textContent = `Pagina ${{currentPage}} / ${{totalPages}}`;
      document.getElementById("pager-prev").disabled = currentPage <= 1;
      document.getElementById("pager-next").disabled = currentPage >= totalPages;

      const select = document.getElementById("page-size-select");
      if (select.value !== String(pageSize)) {{
        select.value = String(pageSize);
      }}
      select.disabled = totalRows === 0;
    }}

    function renderMacro() {{
      const node = document.getElementById("macro-grid");
      node.innerHTML = payload.macro_cards.map((card) => `
        <article class="macro-card">
          <div class="stat-label">${{card.label}}</div>
          <div class="macro-value ${{card.tone}}">${{card.value}}</div>
          <div class="macro-detail">${{card.detail}}</div>
        </article>
      `).join("");
    }}

    function renderFactorMatrix() {{
      const body = document.getElementById("factor-body");
      body.innerHTML = payload.factor_rows.map((row) => `
        <tr>
          <td><strong>${{row.symbol}}</strong> / ${{row.action === "BUY" ? "COMPRA" : "VENTA"}}</td>
          <td>${{row.sentiment.toFixed(2)}}</td>
          <td>${{row.impact.toFixed(2)}}</td>
          <td>${{row.geopolitical.toFixed(2)}}</td>
          <td>${{row.recency.toFixed(2)}}</td>
          <td>${{row.source_quality.toFixed(2)}}</td>
          <td>${{row.consensus.toFixed(2)}}</td>
          <td>${{(row.smart_money || 0).toFixed(2)}}</td>
          <td>${{row.regime.toFixed(2)}}</td>
          <td>${{row.validation.toFixed(2)}}</td>
        </tr>
      `).join("");
    }}

    function renderFeed() {{
      const feed = document.getElementById("feed");
      feed.innerHTML = payload.article_rows.map((item) => `
        <article class="feed-item">
          <div class="feed-source">${{item.source}}</div>
          <div class="feed-title">
            <a href="${{item.url}}" target="_blank" rel="noreferrer">${{item.title}}</a>
          </div>
          <div class="feed-time">${{item.published_at}}</div>
        </article>
        `).join("");
      }}

    function renderBotOperations() {{
      const balance = payload.bot_activity?.balance || {{}};
      const equity = Number(balance.equity || 0);
      const cash = Number(balance.cash || 0);
      const buyingPower = Number(balance.buying_power || 0);
        const initialEquity = Number(balance.initial_equity || equity || 0);
        const pnl = equity ? equity - initialEquity : 0;
      document.getElementById("ops-equity").textContent = `$${{equity.toFixed(2)}}`;
      document.getElementById("ops-cash").textContent = `$${{cash.toFixed(2)}}`;
      document.getElementById("ops-buying-power").textContent = `$${{buyingPower.toFixed(2)}}`;
      document.getElementById("ops-pnl").textContent = `${{pnl >= 0 ? "+" : ""}}$${{pnl.toFixed(2)}}`;
      const totalPnlNode = document.getElementById("ops-pnl-total");
      totalPnlNode.textContent = `${{pnl >= 0 ? "+" : ""}}$${{pnl.toFixed(2)}}`;
      totalPnlNode.style.color = pnl >= 0 ? "#2dde98" : "#ff6b6b";
      document.getElementById("broker-badge").textContent = payload.broker_status?.broker || "paper";
      document.getElementById("broker-status-line").textContent =
        payload.broker_status?.detail || "Sin estado de broker.";

      const history = document.getElementById("ops-history");
      const orders = payload.bot_activity?.orders || [];
      const positions = payload.broker_positions || {{}};
      history.innerHTML = orders.length
        ? orders.map((order) => `
            <article class="ops-row">
              <div><strong>${{order.symbol}}</strong><div class="ops-detail">${{order.side}}</div></div>
              <div><span class="pill ${{order.side === "BUY" ? "pill-buy" : "pill-sell"}}">${{order.status}}</span></div>
              <div class="ops-detail">${{order.detail || "Sin detalle"}}<div class="ops-time">hora operacion: ${{formatOperationTime(order.created_at)}}</div></div>
              <div style="text-align:right;"><strong>$${{Number(order.notional_usd || 0).toFixed(2)}}</strong></div>
              <div style="text-align:right;"><strong>${{formatPositionPnl(order, positions)}}</strong><div class="ops-detail">ganancia</div></div>
            </article>
          `).join("")
        : `<div class="ops-detail">Todavia no hay operaciones registradas por el bot.</div>`;
    }}

    function formatPositionPnl(order, positions) {{
      const symbol = String(order.symbol || "").toUpperCase();
      const position = positions[symbol];
      if (!position || position.unrealized_pl === null || position.unrealized_pl === undefined) {{
        return "N/D";
      }}
      const pnl = Number(position.unrealized_pl || 0);
      return `${{pnl >= 0 ? "+" : ""}}$${{pnl.toFixed(2)}}`;
    }}

    function formatOperationTime(value) {{
      if (!value) {{
        return "sin hora";
      }}
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {{
        return value;
      }}
      return date.toLocaleString("es-AR", {{
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }});
    }}

    function renderAll() {{
      renderSummary();
      renderMacro();
      renderRows();
      renderFactorMatrix();
      renderFeed();
    }}

    function initializeInfoTips() {{
      document.querySelectorAll(".info-tip").forEach((node) => {{
        const tip = node.getAttribute("data-tip");
        if (tip) {{
          node.setAttribute("title", tip);
          node.setAttribute("aria-label", tip);
          node.onclick = (event) => {{
            event.preventDefault();
            event.stopPropagation();
            toggleFloatingTip(node, tip);
          }};
        }}
      }});
    }}

    function initializeNavLinks() {{
      document.querySelectorAll('.nav-item[href^="#"]').forEach((node) => {{
        node.addEventListener("click", (event) => {{
          event.preventDefault();
          const targetSelector = node.getAttribute("href");
          if (!targetSelector) {{
            return;
          }}
          const target = document.querySelector(targetSelector);
          if (!target) {{
            return;
          }}
          target.scrollIntoView({{ behavior: "smooth", block: "start" }});
        }});
      }});
    }}

    function ensureFloatingTip() {{
      if (activeFloatingTip) {{
        return activeFloatingTip;
      }}
      const node = document.createElement("div");
      node.className = "floating-tip";
      document.body.appendChild(node);
      activeFloatingTip = node;
      return node;
    }}

    function toggleFloatingTip(target, text) {{
      const tip = ensureFloatingTip();
      const isSameTarget = tip.dataset.targetId === (target.dataset.tipId || "");
      if (tip.style.display === "block" && isSameTarget) {{
        hideFloatingTip();
        return;
      }}

      if (!target.dataset.tipId) {{
        target.dataset.tipId = Math.random().toString(36).slice(2);
      }}

      tip.dataset.targetId = target.dataset.tipId;
      tip.textContent = text;
      tip.style.display = "block";

      const rect = target.getBoundingClientRect();
      const top = Math.max(12, rect.bottom + 10);
      const left = Math.min(window.innerWidth - 280, Math.max(12, rect.left - 20));
      tip.style.top = `${{top}}px`;
      tip.style.left = `${{left}}px`;
    }}

    function hideFloatingTip() {{
      if (!activeFloatingTip) {{
        return;
      }}
      activeFloatingTip.style.display = "none";
      activeFloatingTip.dataset.targetId = "";
    }}

    async function refreshPayload(forceHorizon = false) {{
      if (!apiEndpoint) {{
        return;
      }}

      try {{
        const baseUrl = new URL(apiEndpoint, window.location.origin);
        if (forceHorizon || currentHorizon) {{
          baseUrl.searchParams.set("horizon", currentHorizon);
        }}
        const response = await fetch(baseUrl.toString(), {{ cache: "no-store" }});
        if (!response.ok) {{
          return;
        }}

        payload = await response.json();
        currentHorizon = payload.horizon?.key || currentHorizon;
        currentPage = 1;
        renderAll();
      }} catch (error) {{
        console.error("No se pudo actualizar el dashboard", error);
      }}
    }}

    renderAll();
    applyLayoutState();
    restartHeroTimer();
    initializeInfoTips();
    initializeNavLinks();

    document.addEventListener("click", () => {{
      hideFloatingTip();
    }});

    window.addEventListener("load", () => {{
      window.scrollTo(0, 0);
    }});

    document.getElementById("toggle-sidebar").addEventListener("click", () => {{
      sidebarCollapsed = !sidebarCollapsed;
      applyLayoutState();
    }});

    document.getElementById("toggle-right-panel").addEventListener("click", () => {{
      rightPanelCollapsed = !rightPanelCollapsed;
      applyLayoutState();
    }});

    document.getElementById("hero-prev").addEventListener("click", () => {{
      moveHero(-1);
    }});

    document.getElementById("hero-next").addEventListener("click", () => {{
      moveHero(1);
    }});

    document.getElementById("page-size-select").addEventListener("change", (event) => {{
      pageSize = Number(event.target.value || 10);
      currentPage = 1;
      renderRows();
    }});

    document.getElementById("pager-prev").addEventListener("click", () => {{
      currentPage = Math.max(1, currentPage - 1);
      renderRows();
    }});

    document.getElementById("pager-next").addEventListener("click", () => {{
      const totalPages = Math.max(1, Math.ceil((payload.market_rows || []).length / pageSize));
      currentPage = Math.min(totalPages, currentPage + 1);
      renderRows();
    }});

    if (apiEndpoint) {{
      window.setInterval(refreshPayload, 5000);
    }}
  </script>
</body>
</html>
"""
