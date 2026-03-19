from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
import time

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from bot_trading_news.config import BotConfig
from bot_trading_news.dashboard import build_dashboard_payload
from bot_trading_news.orchestrator import (
    apply_ai_filter_with_status,
    compute_signals_with_status,
    load_articles_with_status,
    load_execution_snapshot_with_status,
    load_market_factors_with_status,
)
from bot_trading_news.smart_money import load_smart_money_signals
from bot_trading_news.strategy import (
    HORIZON_PRESETS,
    build_dynamic_watchlist,
    build_dynamic_watchlist_details,
)


class TradingDeskTui(App):
    CSS = """
    Screen {
        background: #07111a;
        color: #dce7ef;
    }

    #shell {
        layout: vertical;
        padding: 1;
    }

    .panel {
        border: solid #1d4158;
        padding: 1;
        margin-right: 1;
        background: #0a1824;
    }

    .section-title {
        border: solid #1d4158;
        padding: 0 1;
        margin-right: 1;
        height: 3;
        background: #0a1824;
    }

    #pnl-total {
        margin-top: 0;
        border: solid #2a8f77;
        padding: 1;
        background: #0d1f2d;
        height: 8;
    }

    #body {
        height: 1fr;
        layout: horizontal;
    }

    #left, #right {
        width: 1fr;
    }

    #signals-section, #orders-section {
        height: 1fr;
    }

    #closed-section {
        height: 1fr;
    }

    #closed-section.compact {
        height: 4;
    }

    #logs-panel {
        height: 1fr;
    }

    DataTable {
        height: 1fr;
    }

    #logs {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Salir"),
        ("r", "refresh", "Actualizar"),
        ("1", "set_horizon('short')", "Corto"),
        ("2", "set_horizon('medium')", "Medio"),
        ("3", "set_horizon('long')", "Largo"),
        ("c", "clear_logs", "Limpiar Logs"),
        ("pageup", "logs_page_up", "Logs Arriba"),
        ("pagedown", "logs_page_down", "Logs Abajo"),
    ]

    def __init__(
        self,
        config: BotConfig,
        news_file: str | None,
        market_file: str | None,
        fetch_news: bool,
        query: str | None,
        horizon: str,
        refresh_seconds: int,
        fast_mode: bool,
    ) -> None:
        super().__init__()
        self.config = config
        self.news_file = news_file
        self.market_file = market_file
        self.fetch_news = fetch_news
        self.query = query
        self.horizon = horizon
        self.refresh_seconds = refresh_seconds
        self.fast_mode = fast_mode
        self.log_lines: deque[str] = deque(maxlen=14)
        self.last_refresh_at = "-"
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="terminal-alpha")
        self.refresh_future: Future | None = None
        self.loading = False
        self.last_payload: dict | None = None
        self.module_statuses: dict[str, dict] = {}
        self.seen_order_keys: set[str] = set()
        self.order_status_by_key: dict[str, str] = {}
        self._articles_cache: tuple[float, list] | None = None
        self._market_cache: tuple[float, dict] | None = None
        self._broker_cache: tuple[float, dict, dict, dict] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="shell"):
            yield Static("Ganancia / Perdida Total del Bot\n$0.00", id="pnl-total", classes="panel")
            with Horizontal(id="body"):
                with Vertical(id="left"):
                    with Vertical(id="signals-section"):
                        yield Static("Top Picks", id="signals-title", classes="section-title")
                        yield DataTable(id="signals-table")
                    with Vertical(id="closed-section", classes="panel"):
                        yield Static("Trades Cerrados", id="closed-title", classes="section-title")
                        yield Static("Sin metricas todavia.", id="closed-metrics")
                        yield DataTable(id="closed-table")
                with Vertical(id="right"):
                    with Vertical(id="orders-section"):
                        yield Static("Operaciones del Bot", id="orders-title", classes="section-title")
                        yield Static("Decision Engine", id="orders-metrics")
                        yield DataTable(id="orders-table")
                    with Vertical(id="logs-panel", classes="panel"):
                        yield Static("Logs del Bot", id="logs-title", classes="section-title")
                        yield RichLog(id="logs", auto_scroll=True, wrap=False, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        for table_id in ("#signals-table", "#orders-table", "#closed-table"):
            self.query_one(table_id, DataTable).cursor_type = "row"
        self._push_log("TUI iniciada.")
        self._push_log(f"Horizonte activo: {HORIZON_PRESETS[self.horizon]['label']}.")
        self._push_log(f"Modo TUI: {'fast' if self.fast_mode else 'normal'}.")
        self._render_section_titles()
        self._start_refresh("inicio")
        self.set_interval(max(self.refresh_seconds, 5), lambda: self._start_refresh("timer"))
        self.set_interval(0.35, self._poll_refresh_result)

    def action_refresh(self) -> None:
        self._start_refresh("manual")

    def action_set_horizon(self, horizon: str) -> None:
        if horizon not in HORIZON_PRESETS:
            return
        self.horizon = horizon
        self._push_log(f"Horizonte cambiado a {HORIZON_PRESETS[horizon]['label']}.")
        self._start_refresh("horizonte")

    def action_clear_logs(self) -> None:
        self.log_lines.clear()
        self._render_logs()

    def action_logs_page_up(self) -> None:
        log_widget = self.query_one("#logs", RichLog)
        log_widget.scroll_relative(y=-8)

    def action_logs_page_down(self) -> None:
        log_widget = self.query_one("#logs", RichLog)
        log_widget.scroll_relative(y=8)

    def _start_refresh(self, trigger: str) -> None:
        if self.refresh_future and not self.refresh_future.done():
            if trigger != "timer":
                self._push_log("La actualización anterior sigue corriendo.")
                self._render_logs()
            return
        self.loading = True
        self._set_loading_state(trigger)
        self.refresh_future = self.executor.submit(self._compute_payload)
        if trigger != "timer":
            self._push_log(f"Refresh {trigger} lanzado en background.")
            self._render_logs()

    def _poll_refresh_result(self) -> None:
        if not self.refresh_future or not self.refresh_future.done():
            return
        future = self.refresh_future
        self.refresh_future = None
        self.loading = False
        try:
            payload = future.result()
        except Exception as exc:
            self._push_log(f"Error al refrescar: {exc}")
            self._render_logs()
            return

        self.last_refresh_at = datetime.now().strftime("%H:%M:%S")
        self.last_payload = payload
        self.module_statuses = {
            status.get("module", "modulo"): status for status in payload.get("module_statuses", [])
        }
        self._render_section_titles()
        self._render_stats(payload)
        self._render_signals(payload)
        self._render_orders(payload)
        self._render_closed_trades(payload)
        self._log_new_orders(payload)
        for alert in payload.get("bot_activity", {}).get("alerts", []):
            self._push_log(alert)
        self._push_log(
            f"Actualizado {self.last_refresh_at} | señales={payload.get('signals_count', 0)} | broker={payload.get('broker_status', {}).get('status', '-')}"
        )
        for line in payload.get("module_logs", []):
            self._push_log(line)
        self._render_logs()

    def _compute_payload(self) -> dict:
        fast_config = replace(
            self.config,
            ai_filter_mode="heuristic" if self.fast_mode else self.config.ai_filter_mode,
            ai_max_openai_articles=0 if self.fast_mode else min(self.config.ai_max_openai_articles, 2),
        )
        desk_config = replace(
            fast_config,
            signal_engine_url=None,
            min_signal_score=max(0.8, fast_config.min_signal_score * 0.55),
        )
        module_logs: list[str] = []
        module_statuses: list[dict] = []
        raw_articles, news_status = self._load_articles_fast(fast_config)
        module_logs.append(_format_module_status(news_status))
        module_statuses.append(news_status)
        signal_articles, ai_status = apply_ai_filter_with_status(fast_config, raw_articles)
        module_logs.append(_format_module_status(ai_status))
        module_statuses.append(ai_status)
        market_factors, market_status = self._load_market_factors_fast(fast_config)
        module_logs.append(_format_module_status(market_status))
        module_statuses.append(market_status)
        smart_money_signals = load_smart_money_signals(fast_config)
        module_logs.append(f"[smart_money] ok mode={fast_config.smart_money_mode} | activos={len(smart_money_signals)}")
        active_watchlist_details = build_dynamic_watchlist_details(
            desk_config,
            signal_articles,
            market_factors,
            smart_money_signals,
        )
        active_watchlist = [item["symbol"] for item in active_watchlist_details]
        signals, signal_status = compute_signals_with_status(
            desk_config,
            signal_articles,
            market_factors=market_factors,
            smart_money_signals=smart_money_signals,
            horizon=self.horizon,
        )
        signal_status["detail"] += f" | umbral_tui={desk_config.min_signal_score:.2f}"
        module_logs.append(_format_module_status(signal_status))
        module_statuses.append(signal_status)
        payload = build_dashboard_payload(desk_config, raw_articles, signals, horizon=self.horizon)
        execution_snapshot, execution_status = self._load_broker_snapshot_fast(fast_config)
        module_logs.append(_format_module_status(execution_status))
        module_statuses.append(execution_status)
        payload["bot_activity"] = execution_snapshot["bot_activity"]
        payload["broker_status"] = execution_snapshot["broker_status"]
        payload["broker_positions"] = execution_snapshot["broker_positions"]
        payload["module_logs"] = module_logs[:8]
        payload["module_statuses"] = module_statuses
        payload["active_watchlist"] = active_watchlist[:12]
        payload["active_watchlist_details"] = active_watchlist_details[:6]
        return payload

    def _load_articles_fast(self, config: BotConfig):
        now = time.monotonic()
        if self._articles_cache and now - self._articles_cache[0] < (75 if self.fast_mode else 45):
            return self._articles_cache[1], {
                "module": "news",
                "mode": "cache",
                "ok": True,
                "detail": f"cache noticias activa, articulos={len(self._articles_cache[1])}",
            }
        articles, status = load_articles_with_status(
            config,
            news_file=self.news_file or "sample_news.json",
            fetch_news=self.fetch_news,
            query=self.query,
        )
        articles = articles[:8] if self.fast_mode else articles[:12]
        self._articles_cache = (now, articles)
        status["detail"] += f" | usados={len(articles)}"
        return articles, status

    def _load_market_factors_fast(self, config: BotConfig):
        now = time.monotonic()
        if self._market_cache and now - self._market_cache[0] < (120 if self.fast_mode else 90):
            return self._market_cache[1], {
                "module": "market",
                "mode": "cache",
                "ok": True,
                "detail": f"cache market activa, factores={len(self._market_cache[1])}",
            }
        market_factors, status = load_market_factors_with_status(config, self.market_file or "sample_market_data.json")
        self._market_cache = (now, market_factors)
        return market_factors, status

    def _load_broker_snapshot_fast(self, config: BotConfig) -> tuple[dict, dict]:
        now = time.monotonic()
        if self._broker_cache and now - self._broker_cache[0] < (18 if self.fast_mode else 12):
            return (
                {
                    "bot_activity": self._broker_cache[1],
                    "broker_status": self._broker_cache[2],
                    "broker_positions": self._broker_cache[3],
                },
                {
                    "module": "execution",
                    "mode": "cache",
                    "ok": True,
                    "detail": "cache broker activa",
                },
            )
        snapshot, status = load_execution_snapshot_with_status(config)
        self._broker_cache = (
            now,
            snapshot["bot_activity"],
            snapshot["broker_status"],
            snapshot["broker_positions"],
        )
        return snapshot, status

    def _set_loading_state(self, trigger: str) -> None:
        self._render_section_titles(loading=True)
        if self.last_payload:
            self._render_logs()
            return
        pnl_box = Text()
        pnl_box.append("Cargando datos...\n", style="bold yellow")
        pnl_box.append("Noticias, mercado, senales y broker en background.\n", style="white")
        pnl_box.append(f"Ultima actualizacion completa: {self.last_refresh_at}", style="dim")
        self.query_one("#pnl-total", Static).update(pnl_box)

    def _render_hero(self, payload: dict) -> None:
        return

    def _render_stats(self, payload: dict) -> None:
        balance = payload.get("bot_activity", {}).get("balance", {})
        equity = float(balance.get("equity") or 0)
        cash = float(balance.get("cash") or 0)
        realized = float(balance.get("realized_pnl") or 0)
        unrealized = float(balance.get("unrealized_pnl") or 0)
        performance = payload.get("bot_activity", {}).get("performance", {})
        pnl = round(realized + unrealized, 2)
        pnl_style = "bold green" if pnl >= 0 else "bold red"
        open_style = "bold green" if unrealized >= 0 else "bold red"
        realized_style = "bold green" if realized >= 0 else "bold red"
        pnl_box = Text()
        pnl_box.append("GANANCIA / PERDIDA TOTAL DEL BOT\n", style="bold cyan")
        pnl_box.append(
            f"PnL total {'+' if pnl >= 0 else ''}${pnl:.2f} | "
            f"PnL abierto {'+' if unrealized >= 0 else ''}${unrealized:.2f} | "
            f"PnL realizado {'+' if realized >= 0 else ''}${realized:.2f}\n",
            style="white",
        )
        pnl_box.append(f"Total: {'+' if pnl >= 0 else ''}${pnl:.2f}\n", style=pnl_style)
        pnl_box.append(f"Abierto: {'+' if unrealized >= 0 else ''}${unrealized:.2f}\n", style=open_style)
        pnl_box.append(f"Realizado: {'+' if realized >= 0 else ''}${realized:.2f}\n", style=realized_style)
        pnl_box.append(
            f"Equity ${equity:.2f} | Cash ${cash:.2f} | Open {performance.get('open_positions', 0)} | Fill {performance.get('filled_entries', 0)} | Exit {performance.get('filled_exits', 0)}",
            style="dim",
        )
        pnl_box.append(
            f"Win rate {performance.get('win_rate', 0)}% | W {performance.get('winners', 0)} / L {performance.get('losers', 0)} | Trail {self.config.trailing_activation_pct:.1f}/{self.config.trailing_stop_pct:.1f}% | Estado {payload.get('broker_status', {}).get('status', '-')}",
            style="dim",
        )
        pnl_box.append(
            f"Ganadores {performance.get('winners', 0)} | Perdedores {performance.get('losers', 0)} | Stop {performance.get('auto_exit_stop', 0)} | TP {performance.get('auto_exit_take_profit', 0)} | Trailing {performance.get('auto_exit_trailing', 0)}",
            style="dim",
        )
        active_watchlist = payload.get("active_watchlist", [])
        if active_watchlist:
            pnl_box.append(
                f"Watchlist activa: {', '.join(active_watchlist[:8])}\n",
                style="dim",
            )
        watchlist_details = payload.get("active_watchlist_details", [])
        if watchlist_details:
            detail_parts = []
            for item in watchlist_details[:4]:
                symbol = item.get("symbol", "?")
                drivers = "+".join(item.get("drivers", [])[:2]) or "base"
                detail_parts.append(f"{symbol}[{drivers}]")
            pnl_box.append(
                f"Por que entro: {', '.join(detail_parts)}",
                style="dim",
            )
        self.query_one("#pnl-total", Static).update(pnl_box)

    def _render_section_titles(self, loading: bool = False) -> None:
        mapping = {
            "signals-title": ("Top Picks", "signal_engine"),
            "orders-title": ("Operaciones del Bot", "execution"),
            "closed-title": ("Trades Cerrados", "execution"),
            "logs-title": ("Logs del Bot", None),
        }
        for widget_id, (label, module_key) in mapping.items():
            suffix = f" | act. {self.last_refresh_at}"
            if loading:
                suffix = " | actualizando..."
            elif module_key and self.module_statuses.get(module_key):
                status = self.module_statuses[module_key]
                state = "ok" if status.get("ok") else "error"
                mode = status.get("mode", "local")
                suffix = f" | {state}/{mode} | {self.last_refresh_at}"
            self.query_one(f"#{widget_id}", Static).update(f"{label}{suffix}")

    def _render_signals(self, payload: dict) -> None:
        table = self.query_one("#signals-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Activo", "Pick", "Score", "Conf", "Setup", "Edge")
        for row in payload.get("market_rows", [])[:10]:
            pick = Text("COMPRA", style="bold green") if row["action"] == "BUY" else Text("VENTA", style="bold red")
            score = Text(str(row["score"]), style="green" if row["score"] >= 0 else "red")
            edge = float(row.get("setup_edge", 0.0) or 0.0)
            edge_text = Text(f"{edge:+.2f}", style="green" if edge >= 0 else "red")
            table.add_row(
                row["symbol"],
                pick,
                score,
                f'{row["confidence"]}%',
                str(row.get("setup_tag") or "-")[:22],
                edge_text,
            )

    def _render_orders(self, payload: dict) -> None:
        self._render_order_metrics(payload)
        table = self.query_one("#orders-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Hora", "Activo", "Lado", "Modo", "Qty", "Estado", "Monto", "Gan/Perd")
        positions = payload.get("broker_positions", {})
        for order in payload.get("bot_activity", {}).get("orders", [])[:12]:
            symbol = str(order.get("symbol", "")).upper()
            position = positions.get(symbol, {})
            pnl = position.get("unrealized_pl")
            pnl_text = Text("N/D", style="dim")
            if isinstance(pnl, (int, float)):
                pnl_text = Text(f'{"+" if pnl >= 0 else ""}${pnl:.2f}', style="green" if pnl >= 0 else "red")
            side_text = Text(str(order.get("side", "")), style="green" if order.get("side") == "BUY" else "red")
            status_value = str(order.get("status", ""))
            status_style = "yellow"
            if status_value in {"filled", "accepted", "new", "pending_new"}:
                status_style = "green"
            elif status_value in {"blocked", "rejected", "canceled"}:
                status_style = "red"
            table.add_row(
                _format_time(order.get("created_at")),
                symbol,
                side_text,
                "notional",
                str(position.get("qty") or "-"),
                Text(status_value, style=status_style),
                f'${float(order.get("notional_usd", 0)):.2f}',
                pnl_text,
            )

    def _render_order_metrics(self, payload: dict) -> None:
        orders = payload.get("bot_activity", {}).get("orders", [])[:16]
        status_counts = {"filled": 0, "blocked": 0, "pending": 0}
        details: list[str] = []
        for order in orders:
            status = str(order.get("status", "")).lower()
            if status == "filled":
                status_counts["filled"] += 1
            elif status == "blocked":
                status_counts["blocked"] += 1
            elif status in {"new", "accepted", "pending_new"}:
                status_counts["pending"] += 1
            detail = str(order.get("detail", "") or "").strip()
            if detail and detail not in {"us_equity", "crypto"}:
                details.append(detail[:48])
        lines = [
            f"Llenas {status_counts['filled']} | Bloqueadas {status_counts['blocked']} | Pendientes {status_counts['pending']}",
        ]
        recent_order = orders[0] if orders else None
        if recent_order:
            lines.append(
                "Setup reciente: "
                f"{str(recent_order.get('setup_tag') or '-')} | "
                f"{str(recent_order.get('session_tag') or '-')}"
            )
        if details:
            lines.append(f"Ultimo filtro: {details[0]}")
        self.query_one("#orders-metrics", Static).update("\n".join(lines))

    def _log_new_orders(self, payload: dict) -> None:
        for order in reversed(payload.get("bot_activity", {}).get("orders", [])[:20]):
            order_key = _order_key(order)
            symbol = str(order.get("symbol", "")).upper() or "-"
            side = str(order.get("side", "")).upper() or "-"
            status = str(order.get("status", "")).lower() or "-"
            amount = float(order.get("notional_usd", 0) or 0)
            detail = str(order.get("detail", "") or "").strip()
            previous_status = self.order_status_by_key.get(order_key)

            if previous_status and previous_status != status:
                transition = f"[trade-status] {side} {symbol} | {previous_status} -> {status}"
                if detail and detail not in {"us_equity", "crypto"}:
                    transition += f" | {detail[:60]}"
                self._push_log(transition)

            self.order_status_by_key[order_key] = status
            if order_key in self.seen_order_keys:
                continue
            self.seen_order_keys.add(order_key)
            message = f"[trade] {side} {symbol} | {status} | ${amount:.2f}"
            setup_tag = str(order.get("setup_tag") or "").strip()
            session_tag = str(order.get("session_tag") or "").strip()
            if setup_tag or session_tag:
                message += f" | {setup_tag or '-'}@{session_tag or '-'}"
            if detail and detail not in {"us_equity", "crypto"}:
                message += f" | {detail[:60]}"
            self._push_log(message)

    def _render_news(self, payload: dict) -> None:
        table = self.query_one("#news-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Fuente", "Título")
        for item in payload.get("article_rows", [])[:12]:
            table.add_row(str(item["source"])[:18], str(item["title"])[:90])

    def _render_factors(self, payload: dict) -> None:
        table = self.query_one("#factors-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Activo", "Geo", "AI", "Price", "Reg", "Val")
        for row in payload.get("factor_rows", [])[:12]:
            table.add_row(
                row["symbol"],
                _factor_text(float(row["geopolitical"])),
                _factor_text(float(row.get("ai_relevance", 0.0))),
                _factor_text(float(row.get("price", 0.0))),
                _factor_text(float(row["regime"])),
                _factor_text(float(row["validation"])),
            )

    def _render_closed_trades(self, payload: dict) -> None:
        performance = payload.get("bot_activity", {}).get("performance", {})
        metrics = Text()
        closed_count = int(performance.get("filled_exits", 0) or 0)
        closed_section = self.query_one("#closed-section", Vertical)
        if closed_count == 0:
            closed_section.add_class("compact")
        else:
            closed_section.remove_class("compact")
        if closed_count == 0:
            metrics.append("Esperando el primer cierre del bot.", style="dim")
        metrics.append(
            f"Ganadores {performance.get('winners', 0)} | "
            f"Perdedores {performance.get('losers', 0)} | "
            f"Stop {performance.get('auto_exit_stop', 0)} | "
            f"TP {performance.get('auto_exit_take_profit', 0)} | "
            f"Trailing {performance.get('auto_exit_trailing', 0)} | "
            f"Win rate {performance.get('win_rate', 0)}%",
            style="dim",
        )
        self.query_one("#closed-metrics", Static).update(metrics)

        table = self.query_one("#closed-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Hora", "Activo", "Setup", "Salida", "PnL", "Motivo")
        if closed_count == 0:
            return
        closed_orders = [
            order
            for order in payload.get("bot_activity", {}).get("orders", [])
            if str(order.get("side", "")).upper() == "SELL"
            and str(order.get("status", "")).lower() in {"filled", "simulated_exit", "close_submitted"}
        ][:8]
        for order in closed_orders:
            pnl_value = float(order.get("pnl_usd") or 0.0)
            pnl_text = Text(f'{"+" if pnl_value >= 0 else ""}${pnl_value:.2f}', style="green" if pnl_value >= 0 else "red")
            motive = str(order.get("detail", "") or "")
            if "auto-exit" not in motive.lower():
                reasons = order.get("reasons", [])
                if reasons:
                    motive = str(reasons[0])
            table.add_row(
                _format_time(order.get("created_at")),
                str(order.get("symbol", "")).upper(),
                str(order.get("setup_tag") or "-")[:22],
                Text(str(order.get("status", "")), style="green"),
                pnl_text,
                motive[:72] if motive else "-",
            )

    def _push_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_lines.appendleft(f"[{timestamp}] {message}")

    def _render_logs(self) -> None:
        log_widget = self.query_one("#logs", RichLog)
        log_widget.clear()
        has_content = False
        for line in self.log_lines:
            style = "cyan"
            lowered = line.lower()
            if " mode=cache" in lowered or "fallback" in lowered or "[loading]" in lowered:
                style = "yellow"
            if " error " in lowered or "fallo" in lowered:
                style = "bold red"
            if " ok " in lowered:
                style = "green"
            log_widget.write(Text(line, style=style))
            has_content = True
        if self.loading:
            log_widget.write(Text("[loading] fetch en background activo", style="bold yellow"))
            has_content = True
        if not has_content:
            log_widget.write(Text("Sin eventos todavia.", style="dim"))

    def on_unmount(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


def _format_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return value.replace("T", " ")[11:16]


def _factor_text(value: float) -> Text:
    style = "green" if value > 0 else "red" if value < 0 else "white"
    prefix = "+" if value > 0 else ""
    return Text(f"{prefix}{value:.2f}", style=style)


def _format_module_status(status: dict) -> str:
    module = status.get("module", "modulo")
    mode = status.get("mode", "local")
    detail = status.get("detail", "")
    state = "ok" if status.get("ok", False) else "error"
    return f"[{module}] {state} mode={mode} | {detail}"


def launch_terminal_alpha_tui(
    config: BotConfig,
    news_file: str | None,
    market_file: str | None,
    fetch_news: bool,
    query: str | None,
    horizon: str,
    refresh_seconds: int = 10,
    fast_mode: bool = False,
) -> None:
    app = TradingDeskTui(
        config=config,
        news_file=news_file,
        market_file=market_file,
        fetch_news=fetch_news,
        query=query,
        horizon=horizon,
        refresh_seconds=refresh_seconds,
        fast_mode=fast_mode,
    )
    app.run()


def _order_key(order: dict) -> str:
    broker_order_id = str(order.get("broker_order_id") or "").strip()
    if broker_order_id:
        return broker_order_id
    return "|".join(
        [
            str(order.get("created_at", "")),
            str(order.get("symbol", "")),
            str(order.get("side", "")),
            str(order.get("status", "")),
            str(order.get("notional_usd", "")),
        ]
    )
