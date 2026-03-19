from __future__ import annotations

import argparse

from bot_trading_news.broker import build_broker
from bot_trading_news.config import load_config
from bot_trading_news.dashboard import render_dashboard
from bot_trading_news.live import run_live_dashboard
from bot_trading_news.market import load_market_snapshots_for_symbols
from bot_trading_news.orchestrator import (
    apply_ai_filter_any,
    compute_signals_any,
    load_articles_any,
    load_execution_snapshot_any,
    load_market_factors_any,
)
from bot_trading_news.research import build_research_report
from bot_trading_news.smart_money import load_smart_money_signals
from bot_trading_news.storage import evaluate_predictions_sqlite, record_predictions_sqlite
from bot_trading_news.tui import launch_terminal_alpha_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bot de trading por noticias.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Analiza noticias y ejecuta paper trading.")
    _add_news_inputs(run_parser)

    subparsers.add_parser(
        "broker-check",
        help="Verifica conexion, saldo y estado del broker configurado sin enviar ordenes.",
    )

    analyze_parser = subparsers.add_parser("analyze", help="Analiza noticias sin operar.")
    _add_news_inputs(analyze_parser)

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Genera un dashboard HTML con mercados, senales y noticias.",
    )
    _add_news_inputs(dashboard_parser)
    dashboard_parser.add_argument(
        "--output",
        default="dashboard.html",
        help="Ruta del archivo HTML a generar.",
    )
    dashboard_parser.add_argument(
        "--auto-refresh",
        type=int,
        default=0,
        help="Refresca automaticamente el HTML cada N segundos.",
    )

    live_parser = subparsers.add_parser(
        "live",
        help="Regenera el dashboard en bucle y deja auto-refresh en el navegador.",
    )
    _add_news_inputs(live_parser)
    live_parser.add_argument(
        "--output",
        default="dashboard.html",
        help="Ruta del archivo HTML a generar.",
    )
    live_parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=5,
        help="Cada cuantos segundos se vuelve a generar el dashboard.",
    )

    research_parser = subparsers.add_parser(
        "research",
        help="Genera un reporte de research con breakdown cuantitativo de senales.",
    )
    _add_news_inputs(research_parser)
    research_parser.add_argument(
        "--output",
        default="research_report.json",
        help="Ruta del archivo JSON a generar.",
    )

    eval_parser = subparsers.add_parser(
        "evaluate-predictions",
        help="Evalua predicciones guardadas contra el mercado real segun el horizonte.",
    )
    eval_parser.add_argument(
        "--market-file",
        default="sample_market_data.json",
        help="Archivo fallback de mercado para evaluar si Alpaca no responde.",
    )

    tui_parser = subparsers.add_parser(
        "tui",
        help="Abre una terminal interactiva tipo trader desk.",
    )
    _add_news_inputs(tui_parser)
    tui_parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=10,
        help="Cada cuantos segundos refresca la TUI.",
    )
    tui_parser.add_argument(
        "--fast",
        action="store_true",
        help="Modo rapido para TUI: menos noticias, menos IA y caches mas largas.",
    )

    return parser


def _add_news_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--news-file", help="Archivo JSON local con noticias.")
    parser.add_argument(
        "--market-file",
        default="sample_market_data.json",
        help="Archivo JSON local con series de precio y volumen para factores de mercado.",
    )
    parser.add_argument(
        "--fetch-news",
        action="store_true",
        help="Consulta noticias del dia desde la API configurada.",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Consulta opcional para filtrar noticias al usar --fetch-news.",
    )
    parser.add_argument(
        "--horizon",
        choices=("short", "medium", "long"),
        default="medium",
        help="Horizonte de analisis y ejecucion.",
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()

    if args.command == "live":
        run_live_dashboard(
            config,
            news_file=args.news_file,
            market_file=args.market_file,
            fetch_news=args.fetch_news,
            query=args.query,
            horizon=args.horizon,
            output_path=args.output,
            refresh_seconds=max(args.refresh_seconds, 1),
        )
        return

    if args.command == "tui":
        launch_terminal_alpha_tui(
            config=config,
            news_file=args.news_file,
            market_file=args.market_file,
            fetch_news=args.fetch_news,
            query=args.query,
            horizon=args.horizon,
            refresh_seconds=max(args.refresh_seconds, 5),
            fast_mode=args.fast,
        )
        return

    if args.command == "broker-check":
        status = build_broker(config).check_status()
        if config.execution_service_url:
            try:
                remote_status = load_execution_snapshot_any(config)["broker_status"]
                for field in (
                    "broker",
                    "ok",
                    "account_id",
                    "account_number",
                    "status",
                    "currency",
                    "buying_power",
                    "equity",
                    "cash",
                    "is_paper",
                    "detail",
                ):
                    if field in remote_status:
                        setattr(status, field, remote_status[field])
            except Exception:
                pass
        print(f"Broker: {status.broker}")
        print(f"OK: {'si' if status.ok else 'no'}")
        print(f"Modo paper: {'si' if status.is_paper else 'no'}")
        print(f"Estado cuenta: {status.status}")
        if status.account_id:
            print(f"Account ID: {status.account_id}")
        if status.account_number:
            print(f"Account Number: {status.account_number}")
        if status.currency:
            print(f"Moneda: {status.currency}")
        if status.buying_power:
            print(f"Buying Power: {status.buying_power}")
        if status.equity:
            print(f"Equity: {status.equity}")
        if status.cash:
            print(f"Cash: {status.cash}")
        if status.detail:
            print(f"Detalle: {status.detail}")
        return

    if args.command == "evaluate-predictions":
        symbols = list(dict.fromkeys(config.market_universe + config.watchlist))
        snapshots = load_market_snapshots_for_symbols(config, symbols, market_file=args.market_file, days=35)
        summary = evaluate_predictions_sqlite(snapshots)
        print(f"Predicciones evaluadas: {summary['evaluated']}")
        print(f"Ganadoras: {summary['winners']}")
        print(f"Perdedoras: {summary['losers']}")
        return

    articles = load_articles_any(
        config,
        news_file=args.news_file or "sample_news.json",
        fetch_news=args.fetch_news,
        query=args.query,
    )
    articles = apply_ai_filter_any(config, articles)
    market_factors = load_market_factors_any(config, args.market_file)
    smart_money_signals = load_smart_money_signals(config)
    signals = compute_signals_any(
        config,
        articles,
        market_factors=market_factors,
        smart_money_signals=smart_money_signals,
        horizon=args.horizon,
    )
    snapshots = load_market_snapshots_for_symbols(
        config,
        [signal.symbol for signal in signals],
        market_file=args.market_file,
        days=35 if args.horizon == "medium" else 10,
    )
    if signals:
        created = record_predictions_sqlite(signals, snapshots, args.horizon)
        if created:
            print(f"Predicciones registradas: {created}")

    if not signals:
        if args.command == "dashboard":
            output_path = render_dashboard(
                config,
                articles,
                signals,
                horizon=args.horizon,
                output_path=args.output,
                auto_refresh_seconds=args.auto_refresh or None,
            )
            print(f"Dashboard generado en: {output_path}")
            return
        print("No se encontraron senales con suficiente puntaje.")
        return

    print("Senales detectadas:")
    for signal in signals:
        print(
            f"- {signal.symbol}: {signal.action} | score={signal.score} | "
            f"confidence={signal.confidence}% | exp_usd100={signal.expected_return_per_100} | "
            f"articles={signal.article_count}"
        )
        print(f"  factores: {signal.factor_scores}")
        market_factor = market_factors.get(signal.symbol)
        if market_factor:
            print(
                f"  mercado: momentum={market_factor.price_momentum} | volumen={market_factor.volume_trend} | "
                f"volatilidad={market_factor.volatility} | regimen={market_factor.regime_label} | "
                f"hit_rate={market_factor.backtest_hit_rate}%"
            )
        for note in signal.factor_notes:
            print(f"  nota: {note}")
        for reason in signal.reasons:
            print(f"  razon: {reason}")

    if args.command == "run":
        if config.execution_service_url:
            try:
                import requests

                response = requests.post(
                    f"{config.execution_service_url}/execute",
                    json={
                        "signals": [
                            {
                                "symbol": signal.symbol,
                                "action": signal.action,
                                "score": signal.score,
                                "confidence": signal.confidence,
                                "expected_return_per_100": signal.expected_return_per_100,
                                "article_count": signal.article_count,
                                "factor_scores": signal.factor_scores,
                                "reasons": signal.reasons,
                                "factor_notes": signal.factor_notes,
                            }
                            for signal in signals
                        ]
                    },
                    timeout=6,
                )
                response.raise_for_status()
                orders = response.json().get("orders", [])
                print("")
                print("Ordenes ejecutadas:")
                for order in orders:
                    print(
                        f"- {order.get('side')} {order.get('symbol')} por USD {order.get('notional_usd')} | "
                        f"score={order.get('score')} | confidence={order.get('confidence')}% | "
                        f"broker={order.get('broker')} | status={order.get('status')}"
                    )
                    if order.get("broker_order_id"):
                        print(f"  order_id: {order.get('broker_order_id')}")
                    if order.get("detail"):
                        print(f"  detalle: {order.get('detail')}")
                return
            except Exception:
                pass

        broker = build_broker(config)
        orders = broker.execute(signals)
        print("")
        print("Ordenes ejecutadas:")
        for order in orders:
            print(
                f"- {order.side} {order.symbol} por USD {order.notional_usd} | "
                f"score={order.score} | confidence={order.confidence}% | "
                f"broker={order.broker} | status={order.status}"
            )
            if order.broker_order_id:
                print(f"  order_id: {order.broker_order_id}")
            if order.detail:
                print(f"  detalle: {order.detail}")
    elif args.command == "dashboard":
        output_path = render_dashboard(
            config,
            articles,
            signals,
            horizon=args.horizon,
            output_path=args.output,
            auto_refresh_seconds=args.auto_refresh or None,
        )
        print(f"Dashboard generado en: {output_path}")
    elif args.command == "research":
        output_path = build_research_report(
            signals,
            articles,
            market_factors=market_factors,
            smart_money_signals=smart_money_signals,
            output_path=args.output,
        )
        print(f"Reporte de research generado en: {output_path}")
if __name__ == "__main__":
    main()
