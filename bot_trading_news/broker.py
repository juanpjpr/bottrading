from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import requests

from bot_trading_news.config import BotConfig
from bot_trading_news.storage import append_activity_snapshot_sqlite, load_bot_activity_sqlite, sync_managed_positions_sqlite
from bot_trading_news.strategy import Signal, infer_session_tag, infer_setup_tag


@dataclass(slots=True)
class PaperOrder:
    symbol: str
    side: str
    notional_usd: float
    score: float
    confidence: float
    created_at: str
    reasons: list[str]


@dataclass(slots=True)
class BrokerOrder:
    symbol: str
    side: str
    notional_usd: float
    score: float
    confidence: float
    created_at: str
    reasons: list[str]
    broker: str
    status: str
    broker_order_id: str | None = None
    detail: str | None = None
    pnl_usd: float | None = None
    setup_tag: str | None = None
    session_tag: str | None = None


@dataclass(slots=True)
class BrokerStatus:
    broker: str
    ok: bool
    account_id: str | None
    account_number: str | None
    status: str
    currency: str | None
    buying_power: str | None
    equity: str | None
    cash: str | None
    is_paper: bool
    detail: str | None = None


@dataclass(slots=True)
class ClockStatus:
    is_open: bool
    timestamp: str
    next_open: str | None
    next_close: str | None
    within_window: bool
    detail: str


class Broker(Protocol):
    def execute(self, signals: list[Signal]) -> list[BrokerOrder]:
        ...

    def check_status(self) -> BrokerStatus:
        ...

    def get_positions_snapshot(self) -> dict[str, dict]:
        ...

    def refresh_orders(self, orders: list[dict]) -> list[dict]:
        ...

    def close_position(
        self,
        symbol: str,
        reason: str | None = None,
        pnl_usd: float | None = None,
        setup_tag: str | None = None,
        session_tag: str | None = None,
    ) -> BrokerOrder:
        ...


class PaperBroker:
    def __init__(self, config: BotConfig, output_file: str = "paper_orders.json") -> None:
        self.config = config
        self.output_file = Path(output_file)
        self.activity_file = Path("bot_activity.json")

    def execute(self, signals: list[Signal]) -> list[BrokerOrder]:
        selected = signals[: self.config.max_daily_trades]
        orders: list[BrokerOrder] = []

        for signal in selected:
            risk_budget = _position_notional(self.config, signal)
            setup_tag = infer_setup_tag(signal.action, signal.factor_scores, signal.article_count, "medium")
            session_tag = infer_session_tag(self.config)
            order = BrokerOrder(
                symbol=signal.symbol,
                side=signal.action,
                notional_usd=round(risk_budget, 2),
                score=signal.score,
                confidence=signal.confidence,
                created_at=datetime.now(UTC).isoformat(),
                reasons=signal.reasons,
                broker="paper",
                status="simulated",
                setup_tag=setup_tag,
                session_tag=session_tag,
            )
            orders.append(order)

        self._persist(orders)
        self._append_activity(orders, self.check_status())
        return orders

    def _persist(self, orders: list[BrokerOrder]) -> None:
        payload = [asdict(order) for order in orders]
        self.output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def check_status(self) -> BrokerStatus:
        return BrokerStatus(
            broker="paper",
            ok=True,
            account_id=None,
            account_number=None,
            status="simulated",
            currency="USD",
            buying_power=str(round(self.config.balance, 2)),
            equity=str(round(self.config.balance, 2)),
            cash=str(round(self.config.balance, 2)),
            is_paper=True,
            detail="Modo simulacion local activo.",
        )

    def get_positions_snapshot(self) -> dict[str, dict]:
        return {}

    def refresh_orders(self, orders: list[dict]) -> list[dict]:
        return orders

    def close_position(
        self,
        symbol: str,
        reason: str | None = None,
        pnl_usd: float | None = None,
        setup_tag: str | None = None,
        session_tag: str | None = None,
    ) -> BrokerOrder:
        order = BrokerOrder(
            symbol=symbol,
            side="SELL",
            notional_usd=0.0,
            score=0.0,
            confidence=100.0,
            created_at=datetime.now(UTC).isoformat(),
            reasons=[reason or "cierre simulado"],
            broker="paper",
            status="simulated_exit",
            detail=reason or "cierre simulado",
            pnl_usd=pnl_usd,
            setup_tag=setup_tag,
            session_tag=session_tag,
        )
        self._append_activity([order], self.check_status())
        return order

    def _append_activity(self, orders: list[BrokerOrder], status: BrokerStatus) -> None:
        append_activity_snapshot(self.activity_file, orders, status)


class AlpacaPaperBroker:
    def __init__(self, config: BotConfig, timeout_seconds: int = 12) -> None:
        if not config.alpaca_api_key or not config.alpaca_secret_key:
            raise ValueError("Faltan ALPACA_API_KEY o ALPACA_SECRET_KEY en la configuracion.")

        self.config = config
        self.timeout_seconds = timeout_seconds
        self.base_url = config.alpaca_base_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "APCA-API-KEY-ID": config.alpaca_api_key,
                "APCA-API-SECRET-KEY": config.alpaca_secret_key,
                "Content-Type": "application/json",
            }
        )

    def check_status(self) -> BrokerStatus:
        response = self.session.get(f"{self.base_url}/v2/account", timeout=self.timeout_seconds)
        if not response.ok:
            try:
                detail = response.json().get("message") or response.text
            except ValueError:
                detail = response.text
            return BrokerStatus(
                broker="alpaca-paper",
                ok=False,
                account_id=None,
                account_number=None,
                status="error",
                currency=None,
                buying_power=None,
                equity=None,
                cash=None,
                is_paper="paper-api" in self.base_url,
                detail=detail,
            )

        body = response.json()
        return BrokerStatus(
            broker="alpaca-paper",
            ok=True,
            account_id=body.get("id"),
            account_number=body.get("account_number"),
            status=body.get("status", "unknown"),
            currency=body.get("currency"),
            buying_power=body.get("buying_power"),
            equity=body.get("equity"),
            cash=body.get("cash"),
            is_paper="paper-api" in self.base_url,
            detail=f"Cuenta conectada en {self.base_url}",
        )

    def check_clock(self) -> ClockStatus:
        response = self.session.get(f"{self.base_url}/v2/clock", timeout=self.timeout_seconds)
        if not response.ok:
            return ClockStatus(
                is_open=False,
                timestamp=datetime.now(UTC).isoformat(),
                next_open=None,
                next_close=None,
                within_window=False,
                detail="No se pudo consultar el reloj de mercado.",
            )

        body = response.json()
        timestamp = body.get("timestamp") or datetime.now(UTC).isoformat()
        current_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(
            ZoneInfo(self.config.execution_timezone)
        )
        within_window = self._is_within_window(current_time)
        return ClockStatus(
            is_open=bool(body.get("is_open")),
            timestamp=timestamp,
            next_open=body.get("next_open"),
            next_close=body.get("next_close"),
            within_window=within_window,
            detail=f"Reloj OK en {self.config.execution_timezone}. Ventana activa: {'si' if within_window else 'no'}",
        )

    def get_positions_snapshot(self) -> dict[str, dict]:
        response = self.session.get(f"{self.base_url}/v2/positions", timeout=self.timeout_seconds)
        if not response.ok:
            return {}
        try:
            positions = response.json()
        except ValueError:
            return {}

        snapshot: dict[str, dict] = {}
        for item in positions:
            symbol = str(item.get("symbol", "")).upper()
            if not symbol:
                continue
            snapshot[symbol] = {
                "qty": item.get("qty"),
                "side": item.get("side"),
                "market_value": _to_float(item.get("market_value")),
                "avg_entry_price": _to_float(item.get("avg_entry_price")),
                "unrealized_pl": _to_float(item.get("unrealized_pl")),
                "unrealized_plpc": _to_ratio(item.get("unrealized_plpc")),
                "change_today": _to_ratio(item.get("change_today")),
            }
        return snapshot

    def refresh_orders(self, orders: list[dict]) -> list[dict]:
        refreshed: list[dict] = []
        terminal_statuses = {"blocked", "rejected", "canceled", "filled", "simulated"}
        for order in orders:
            updated = dict(order)
            broker_order_id = updated.get("broker_order_id")
            status = str(updated.get("status", ""))
            if not broker_order_id or status in terminal_statuses:
                refreshed.append(updated)
                continue

            try:
                response = self.session.get(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    timeout=min(self.timeout_seconds, 6),
                )
                if response.ok:
                    body = response.json()
                    updated["status"] = body.get("status", updated.get("status"))
                    if body.get("filled_avg_price"):
                        updated["detail"] = f"filled avg {body.get('filled_avg_price')}"
                    elif body.get("asset_class"):
                        updated["detail"] = body.get("asset_class")
                refreshed.append(updated)
            except requests.RequestException:
                refreshed.append(updated)
        return refreshed

    def execute(self, signals: list[Signal]) -> list[BrokerOrder]:
        selected = signals[: self.config.max_daily_trades]
        base_risk_budget = round(self.config.balance * self.config.risk_per_trade, 2)
        account_status = self.check_status()
        clock_status = self.check_clock()
        orders: list[BrokerOrder] = []

        if not account_status.ok:
            orders = [
                self._blocked_order(
                    signal,
                    base_risk_budget,
                    f"Broker no disponible: {account_status.detail or account_status.status}",
                )
                for signal in selected
            ]
            self._append_activity(orders, account_status)
            return orders

        daily_loss_limit = self._daily_loss_limit(account_status)
        if daily_loss_limit is not None and self._current_daily_loss(account_status) >= daily_loss_limit:
            orders = [
                self._blocked_order(
                    signal,
                    base_risk_budget,
                    f"Kill switch activo por perdida diaria. Limite {daily_loss_limit:.2f} USD.",
                )
                for signal in selected
            ]
            self._append_activity(orders, account_status)
            return orders

        if not clock_status.is_open:
            orders = [
                self._blocked_order(signal, base_risk_budget, "Mercado cerrado segun Alpaca.")
                for signal in selected
            ]
            self._append_activity(orders, account_status)
            return orders

        if not clock_status.within_window:
            orders = [
                self._blocked_order(
                    signal,
                    base_risk_budget,
                    f"Fuera de ventana operativa {self.config.trading_window_start}-{self.config.trading_window_end} {self.config.execution_timezone}.",
                )
                for signal in selected
            ]
            self._append_activity(orders, account_status)
            return orders

        for signal in selected:
            risk_budget = _position_notional(self.config, signal)
            setup_tag = infer_setup_tag(signal.action, signal.factor_scores, signal.article_count, "short")
            session_tag = infer_session_tag(self.config)
            reentry_reason = self._check_existing_exposure(signal.symbol)
            if reentry_reason:
                orders.append(self._blocked_order(signal, risk_budget, reentry_reason))
                continue
            intraday = self._intraday_confirmation(signal.symbol) if self.config.strict_free_mode else None
            signal_block_reason = self._validate_signal(signal, intraday=intraday)
            if signal_block_reason:
                orders.append(self._blocked_order(signal, risk_budget, signal_block_reason))
                continue

            if signal.symbol == "BTC":
                symbol = "BTC/USD"
            else:
                symbol = signal.symbol

            payload = {
                "symbol": symbol,
                "side": "buy" if signal.action == "BUY" else "sell",
                "type": "market",
                "time_in_force": "day",
                "notional": f"{risk_budget:.2f}",
            }
            response = self.session.post(
                f"{self.base_url}/v2/orders",
                json=payload,
                timeout=self.timeout_seconds,
            )

            detail = None
            broker_order_id = None
            status = "submitted"
            if response.ok:
                body = response.json()
                broker_order_id = body.get("id")
                status = body.get("status", "submitted")
                detail = body.get("asset_class")
                if intraday and intraday.get("ok"):
                    detail = (
                        f"intradia ok 5m={intraday['price_change_5m']:.2f}% "
                        f"vol={intraday['volume_ratio']:.2f} "
                        f"vwap={'si' if intraday['above_vwap'] else 'no'}"
                    )
            else:
                try:
                    detail = response.json().get("message") or response.text
                except ValueError:
                    detail = response.text
                status = "rejected"

            orders.append(
                BrokerOrder(
                    symbol=symbol,
                    side=signal.action,
                    notional_usd=risk_budget,
                    score=signal.score,
                    confidence=signal.confidence,
                    created_at=datetime.now(UTC).isoformat(),
                    reasons=signal.reasons,
                    broker="alpaca-paper",
                    status=status,
                    broker_order_id=broker_order_id,
                    detail=detail,
                    setup_tag=setup_tag,
                    session_tag=session_tag,
                )
            )
        self._append_activity(orders, self.check_status())
        return orders

    def close_position(
        self,
        symbol: str,
        reason: str | None = None,
        pnl_usd: float | None = None,
        setup_tag: str | None = None,
        session_tag: str | None = None,
    ) -> BrokerOrder:
        normalized = "BTC/USD" if symbol.upper() == "BTC" else symbol.upper()
        response = self.session.delete(
            f"{self.base_url}/v2/positions/{normalized}",
            timeout=self.timeout_seconds,
        )
        detail = reason or "cierre solicitado"
        broker_order_id = None
        status = "rejected"
        if response.ok:
            try:
                body = response.json()
            except ValueError:
                body = {}
            broker_order_id = body.get("id") or body.get("order_id")
            status = body.get("status", "close_submitted")
            detail = reason or body.get("asset_class") or detail
        else:
            try:
                detail = response.json().get("message") or response.text
            except ValueError:
                detail = response.text
        order = BrokerOrder(
            symbol=normalized,
            side="SELL",
            notional_usd=0.0,
            score=0.0,
            confidence=100.0,
            created_at=datetime.now(UTC).isoformat(),
            reasons=[reason or "auto-exit"],
            broker="alpaca-paper",
            status=status,
            broker_order_id=broker_order_id,
            detail=detail,
            pnl_usd=pnl_usd,
            setup_tag=setup_tag,
            session_tag=session_tag,
        )
        self._append_activity([order], self.check_status())
        return order

    def _validate_signal(self, signal: Signal, intraday: dict[str, float | bool] | None = None) -> str | None:
        if signal.confidence < self.config.min_auto_confidence:
            return f"Conviccion insuficiente para auto-trade: {signal.confidence}% < {self.config.min_auto_confidence}%."

        if not self.config.require_trend_alignment:
            return None

        price = signal.factor_scores.get("price", 0.0)
        regime = signal.factor_scores.get("regime", 0.0)
        volume = signal.factor_scores.get("volume", 0.0)
        validation = signal.factor_scores.get("validation", 0.0)
        source_quality = signal.factor_scores.get("source_quality", 0.0)
        ai_relevance = signal.factor_scores.get("ai_relevance", 0.0)
        impact = signal.factor_scores.get("impact", 0.0)

        if self.config.strict_free_mode:
            if signal.article_count < 1:
                return "Operacion bloqueada: sin articulos reales vinculados."
            if source_quality < 0.5:
                return "Operacion bloqueada: fuente demasiado debil para modo estricto."
            if ai_relevance < 0.24:
                return "Operacion bloqueada: relevancia IA insuficiente para modo estricto."
            if abs(impact) < 0.35 and abs(signal.factor_scores.get("geopolitical", 0.0)) < 0.35:
                return "Operacion bloqueada: catalizador demasiado debil para corto plazo."
            intraday = intraday or self._intraday_confirmation(signal.symbol)
            if not intraday.get("ok"):
                return "Operacion bloqueada: sin confirmacion intradia disponible."

        if signal.action == "BUY":
            if price <= 0 and regime <= 0:
                return "BUY bloqueada: precio y regimen no confirman tendencia corta."
            if self.config.strict_free_mode and (price <= 0.05 or volume <= 0.05 or regime <= 0.05):
                return "BUY bloqueada: falta confirmacion intradia/flujo en modo estricto."
            if self.config.strict_free_mode:
                if intraday["price_change_5m"] <= 0 or intraday["volume_ratio"] < 0.95 or not intraday["above_vwap"]:
                    return (
                        "BUY bloqueada: intradia no confirma "
                        f"(5m={intraday['price_change_5m']:.2f}%, vol={intraday['volume_ratio']:.2f}, vwap={'si' if intraday['above_vwap'] else 'no'})."
                    )
            if validation < -0.35:
                return "BUY bloqueada: validacion historica demasiado debil."
        else:
            if price >= 0 and regime >= 0:
                return "SELL bloqueada: precio y regimen no confirman presion bajista."
            if self.config.strict_free_mode and (price >= -0.05 or volume >= -0.02 and regime >= -0.05):
                return "SELL bloqueada: falta confirmacion bajista en modo estricto."
            if self.config.strict_free_mode:
                if intraday["price_change_5m"] >= 0 or intraday["volume_ratio"] < 0.9 or intraday["above_vwap"]:
                    return (
                        "SELL bloqueada: intradia no confirma "
                        f"(5m={intraday['price_change_5m']:.2f}%, vol={intraday['volume_ratio']:.2f}, vwap={'si' if intraday['above_vwap'] else 'no'})."
                    )
            if validation > 0.55:
                return "SELL bloqueada: validacion historica demasiado alcista."

        if volume < -0.9:
            return "Operacion bloqueada: volumen demasiado debil para ejecutar corto plazo."
        return None

    def _blocked_order(self, signal: Signal, risk_budget: float, detail: str) -> BrokerOrder:
        symbol = "BTC/USD" if signal.symbol == "BTC" else signal.symbol
        return BrokerOrder(
            symbol=symbol,
            side=signal.action,
            notional_usd=risk_budget,
            score=signal.score,
            confidence=signal.confidence,
            created_at=datetime.now(UTC).isoformat(),
            reasons=signal.reasons,
            broker="alpaca-paper",
            status="blocked",
            detail=detail,
            setup_tag=infer_setup_tag(signal.action, signal.factor_scores, signal.article_count, "short"),
            session_tag=infer_session_tag(self.config),
        )

    def _check_existing_exposure(self, symbol: str) -> str | None:
        normalized = "BTC/USD" if symbol.upper() == "BTC" else symbol.upper()
        positions = self.get_positions_snapshot()
        if normalized in positions:
            return f"Operacion bloqueada: {normalized} ya tiene posicion abierta."
        history = load_bot_activity()
        latest = next(
            (
                order
                for order in history.get("orders", [])
                if str(order.get("symbol", "")).upper() == normalized and str(order.get("status", "")).lower() not in {"blocked", "rejected", "canceled"}
            ),
            None,
        )
        if latest:
            created_at = _parse_dt(latest.get("created_at"))
            if created_at:
                minutes = (datetime.now(UTC) - created_at).total_seconds() / 60
                if minutes < self.config.reentry_cooldown_minutes:
                    return f"Cooldown activo en {normalized}: {minutes:.0f}m < {self.config.reentry_cooldown_minutes}m."
        return None

    def _intraday_confirmation(self, symbol: str) -> dict[str, float | bool]:
        normalized = "BTC/USD" if symbol.upper() == "BTC" else symbol.upper()
        end = datetime.now(UTC)
        start = end - timedelta(minutes=75)
        try:
            if normalized == "BTC/USD":
                response = self.session.get(
                    f"{self.config.alpaca_data_url}/v1beta3/crypto/us/bars",
                    params={
                        "symbols": normalized,
                        "timeframe": "1Min",
                        "start": start.isoformat().replace("+00:00", "Z"),
                        "end": end.isoformat().replace("+00:00", "Z"),
                        "limit": 20,
                    },
                    timeout=min(self.timeout_seconds, 6),
                )
                response.raise_for_status()
                bars = response.json().get("bars", {}).get(normalized, [])
            else:
                response = self.session.get(
                    f"{self.config.alpaca_data_url}/v2/stocks/bars",
                    params={
                        "symbols": normalized,
                        "timeframe": "1Min",
                        "start": start.isoformat().replace("+00:00", "Z"),
                        "end": end.isoformat().replace("+00:00", "Z"),
                        "limit": 20,
                        "adjustment": "raw",
                    },
                    timeout=min(self.timeout_seconds, 6),
                )
                response.raise_for_status()
                bars = response.json().get("bars", {}).get(normalized, [])
        except requests.RequestException:
            return {"ok": False, "price_change_5m": 0.0, "volume_ratio": 0.0, "above_vwap": False}

        if len(bars) < 10:
            return {"ok": False, "price_change_5m": 0.0, "volume_ratio": 0.0, "above_vwap": False}

        closes = [float(item.get("c", 0.0)) for item in bars if float(item.get("c", 0.0)) > 0]
        volumes = [float(item.get("v", 0.0)) for item in bars]
        if len(closes) < 10 or len(volumes) < 10:
            return {"ok": False, "price_change_5m": 0.0, "volume_ratio": 0.0, "above_vwap": False}

        recent_close = closes[-1]
        past_close = closes[-6]
        price_change_5m = ((recent_close - past_close) / past_close) * 100 if past_close else 0.0
        recent_volume = sum(volumes[-5:]) / 5
        baseline_volume = sum(volumes[-10:-5]) / 5 if sum(volumes[-10:-5]) else 0.0
        volume_ratio = (recent_volume / baseline_volume) if baseline_volume else 0.0
        latest_bar = bars[-1]
        vwap = float(latest_bar.get("vw", recent_close) or recent_close)
        above_vwap = recent_close >= vwap
        return {
            "ok": True,
            "price_change_5m": round(price_change_5m, 2),
            "volume_ratio": round(volume_ratio, 2),
            "above_vwap": above_vwap,
        }

    def _is_within_window(self, current_time: datetime) -> bool:
        current_hhmm = current_time.strftime("%H:%M")
        return self.config.trading_window_start <= current_hhmm <= self.config.trading_window_end

    def _daily_loss_limit(self, status: BrokerStatus) -> float | None:
        if not status.equity:
            return None
        try:
            equity = float(status.equity)
        except ValueError:
            return None
        return equity * (self.config.max_daily_loss_pct / 100)

    def _current_daily_loss(self, status: BrokerStatus) -> float:
        response = self.session.get(f"{self.base_url}/v2/account", timeout=self.timeout_seconds)
        if not response.ok:
            return 0.0
        body = response.json()
        try:
            equity = float(body.get("equity", 0) or 0)
            last_equity = float(body.get("last_equity", equity) or equity)
        except ValueError:
            return 0.0
        return max(0.0, last_equity - equity)

    def _append_activity(self, orders: list[BrokerOrder], status: BrokerStatus) -> None:
        append_activity_snapshot(Path("bot_activity.json"), orders, status)


def append_activity_snapshot(
    activity_file: Path,
    orders: list[BrokerOrder],
    status: BrokerStatus,
) -> None:
    append_activity_snapshot_sqlite(
        orders=orders,
        status=status,
        legacy_json_path=activity_file,
    )


def load_bot_activity(activity_file: Path | str = "bot_activity.json") -> dict:
    return load_bot_activity_sqlite(legacy_json_path=activity_file)


def load_live_bot_activity(
    config: BotConfig,
    activity_file: Path | str = "bot_activity.json",
) -> tuple[dict, dict[str, dict], BrokerStatus]:
    history = load_bot_activity(activity_file)
    broker = build_broker(config)
    status = broker.check_status()
    alerts: list[str] = []
    positions = broker.get_positions_snapshot()
    orders = broker.refresh_orders(history.get("orders", []))
    orders = _backfill_order_context(orders)
    managed_positions = _extract_managed_positions(orders, positions)
    managed_positions = sync_managed_positions_sqlite(managed_positions)
    positions, orders, managed_positions, exit_alerts = _apply_auto_exits(config, broker, positions, orders, managed_positions)
    orders = _backfill_order_context(orders)
    alerts.extend(exit_alerts)
    managed_positions = sync_managed_positions_sqlite(managed_positions)

    balance = dict(history.get("balance", {}))
    current_equity = _to_float(status.equity)
    current_cash = _to_float(status.cash)
    current_buying_power = _to_float(status.buying_power)
    initial_equity = balance.get("initial_equity")
    if initial_equity is None and current_equity is not None:
        initial_equity = current_equity

    unrealized_pnl = round(
        sum(float(item.get("unrealized_pl") or 0.0) for item in managed_positions.values()),
        2,
    )
    realized_pnl = round(
        sum(
            float(order.get("pnl_usd") or 0.0)
            for order in orders
            if str(order.get("side", "")).upper() == "SELL" and str(order.get("status", "")).lower() in {"filled", "simulated_exit"}
        ),
        2,
    )

    balance.update(
        {
            "broker": status.broker,
            "status": status.status,
            "currency": status.currency,
            "equity": current_equity if current_equity is not None else balance.get("equity"),
            "initial_equity": initial_equity,
            "cash": current_cash if current_cash is not None else balance.get("cash"),
            "buying_power": current_buying_power if current_buying_power is not None else balance.get("buying_power"),
            "is_paper": status.is_paper,
            "updated_at": datetime.now(UTC).isoformat(),
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "open_positions": len(managed_positions),
        }
    )
    performance = _build_performance_summary(orders, managed_positions)
    return {
        "balance": balance,
        "orders": orders,
        "managed_positions": managed_positions,
        "performance": performance,
        "alerts": alerts,
    }, positions, status


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except ValueError:
        return None


def _to_ratio(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except ValueError:
        return None


def _position_notional(config: BotConfig, signal: Signal) -> float:
    base = config.balance * config.risk_per_trade

    confidence_scale = 0.75 + max(0.0, min(signal.confidence, 100.0)) / 100.0
    expected_scale = 0.85 + min(abs(signal.expected_return_per_100) / 8.0, 0.35)

    price = signal.factor_scores.get("price", 0.0)
    volume = signal.factor_scores.get("volume", 0.0)
    regime = signal.factor_scores.get("regime", 0.0)
    validation = signal.factor_scores.get("validation", 0.0)
    volatility = abs(signal.factor_scores.get("volatility", 0.0))

    alignment_bonus = max(0.0, price) * 0.18 + max(0.0, volume) * 0.12 + max(0.0, regime) * 0.15
    validation_bonus = max(-0.15, min(validation * 0.18, 0.2))
    volatility_penalty = min(volatility * 0.6, 0.32)

    multiplier = confidence_scale * expected_scale
    multiplier *= 1.0 + alignment_bonus + validation_bonus - volatility_penalty
    multiplier = max(0.45, min(multiplier, 1.85))

    min_notional = max(25.0, base * 0.45)
    max_notional = base * 1.85
    return round(max(min_notional, min(base * multiplier, max_notional)), 2)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _extract_managed_positions(orders: list[dict], positions: dict[str, dict]) -> dict[str, dict]:
    managed: dict[str, dict] = {}
    active_statuses = {"new", "accepted", "filled", "partially_filled", "pending_new", "close_submitted"}
    for order in sorted(orders, key=lambda item: str(item.get("created_at", ""))):
        symbol = str(order.get("symbol", "")).upper()
        if not symbol:
            continue
        status = str(order.get("status", "")).lower()
        side = str(order.get("side", "")).upper()
        if side == "BUY" and status in active_statuses and symbol in positions:
            managed[symbol] = {
                "opened_at": order.get("created_at"),
                "entry_status": status,
                "entry_notional_usd": float(order.get("notional_usd", 0) or 0),
                "entry_order_id": order.get("broker_order_id"),
                "setup_tag": order.get("setup_tag"),
                "session_tag": order.get("session_tag"),
                **positions[symbol],
            }
        if side == "SELL" and symbol in managed:
            managed.pop(symbol, None)
    return managed


def _apply_auto_exits(
    config: BotConfig,
    broker: Broker,
    positions: dict[str, dict],
    orders: list[dict],
    managed_positions: dict[str, dict],
) -> tuple[dict[str, dict], list[dict], dict[str, dict], list[str]]:
    alerts: list[str] = []
    recent_exit_symbols = {
        str(order.get("symbol", "")).upper()
        for order in orders[:20]
        if str(order.get("side", "")).upper() == "SELL" and "auto-exit" in str(order.get("detail", "")).lower()
    }
    for symbol, position in managed_positions.items():
        if symbol in recent_exit_symbols:
            continue
        plpc = float(position.get("unrealized_plpc") or 0.0) * 100
        opened_at = _parse_dt(position.get("opened_at"))
        held_minutes = None
        if opened_at:
            held_minutes = (datetime.now(UTC) - opened_at).total_seconds() / 60
        peak_pnl_pct = float(position.get("peak_unrealized_pnl_pct") or plpc)

        exit_reason = None
        if plpc <= -abs(config.stop_loss_pct):
            exit_reason = f"auto-exit stop loss {plpc:.2f}% <= -{abs(config.stop_loss_pct):.2f}%"
        elif plpc >= abs(config.take_profit_pct):
            exit_reason = f"auto-exit take profit {plpc:.2f}% >= {abs(config.take_profit_pct):.2f}%"
        elif peak_pnl_pct >= abs(config.trailing_activation_pct) and plpc <= peak_pnl_pct - abs(config.trailing_stop_pct):
            exit_reason = (
                f"auto-exit trailing stop {plpc:.2f}% desde pico {peak_pnl_pct:.2f}% "
                f"(dist {abs(config.trailing_stop_pct):.2f}%)"
            )
        elif held_minutes is not None and held_minutes >= config.max_hold_minutes:
            exit_reason = f"auto-exit timeout {held_minutes:.0f}m >= {config.max_hold_minutes}m"

        if exit_reason:
            exit_order = broker.close_position(
                symbol,
                reason=exit_reason,
                pnl_usd=float(position.get("unrealized_pl") or 0.0),
                setup_tag=position.get("setup_tag"),
                session_tag=position.get("session_tag"),
            )
            orders.insert(0, asdict(exit_order))
            alerts.append(f"[alert] {symbol} {exit_reason}")
            positions.pop(symbol, None)
            managed_positions.pop(symbol, None)
    return positions, orders, managed_positions, alerts


def _build_performance_summary(orders: list[dict], managed_positions: dict[str, dict]) -> dict:
    filled_entries = [
        order for order in orders
        if str(order.get("side", "")).upper() == "BUY" and str(order.get("status", "")).lower() == "filled"
    ]
    filled_exits = [
        order for order in orders
        if str(order.get("side", "")).upper() == "SELL" and str(order.get("status", "")).lower() in {"filled", "simulated_exit"}
    ]
    blocked = [order for order in orders if str(order.get("status", "")).lower() == "blocked"]
    rejected = [order for order in orders if str(order.get("status", "")).lower() == "rejected"]
    open_pnl = round(sum(float(item.get("unrealized_pl") or 0.0) for item in managed_positions.values()), 2)
    open_winners = sum(1 for item in managed_positions.values() if float(item.get("unrealized_pl") or 0.0) > 0)
    open_losers = sum(1 for item in managed_positions.values() if float(item.get("unrealized_pl") or 0.0) < 0)
    realized_pnl = round(sum(float(order.get("pnl_usd") or 0.0) for order in filled_exits), 2)
    winners = sum(1 for order in filled_exits if float(order.get("pnl_usd") or 0.0) > 0)
    losers = sum(1 for order in filled_exits if float(order.get("pnl_usd") or 0.0) < 0)
    win_rate = round((winners / len(filled_exits)) * 100, 1) if filled_exits else 0.0
    auto_exit_stop = sum(1 for order in filled_exits if "auto-exit stop loss" in str(order.get("detail", "")).lower())
    auto_exit_take_profit = sum(1 for order in filled_exits if "auto-exit take profit" in str(order.get("detail", "")).lower())
    auto_exit_trailing = sum(1 for order in filled_exits if "auto-exit trailing stop" in str(order.get("detail", "")).lower())
    return {
        "filled_entries": len(filled_entries),
        "filled_exits": len(filled_exits),
        "blocked_orders": len(blocked),
        "rejected_orders": len(rejected),
        "open_positions": len(managed_positions),
        "open_pnl": open_pnl,
        "open_winners": open_winners,
        "open_losers": open_losers,
        "realized_pnl": realized_pnl,
        "winners": winners,
        "losers": losers,
        "win_rate": win_rate,
        "auto_exit_stop": auto_exit_stop,
        "auto_exit_take_profit": auto_exit_take_profit,
        "auto_exit_trailing": auto_exit_trailing,
    }


def _backfill_order_context(orders: list[dict]) -> list[dict]:
    context_by_symbol: dict[str, dict[str, str]] = {}
    enriched: list[dict] = []
    chronological = list(reversed(orders))

    for order in chronological:
        item = dict(order)
        symbol = str(item.get("symbol", "")).upper()
        side = str(item.get("side", "")).upper()
        setup_tag = str(item.get("setup_tag") or "").strip()
        session_tag = str(item.get("session_tag") or "").strip()

        if side == "BUY":
            if setup_tag or session_tag:
                context_by_symbol[symbol] = {
                    "setup_tag": setup_tag or context_by_symbol.get(symbol, {}).get("setup_tag", ""),
                    "session_tag": session_tag or context_by_symbol.get(symbol, {}).get("session_tag", ""),
                }
            elif symbol in context_by_symbol:
                item["setup_tag"] = context_by_symbol[symbol].get("setup_tag") or None
                item["session_tag"] = context_by_symbol[symbol].get("session_tag") or None
        elif symbol in context_by_symbol:
            if not setup_tag:
                item["setup_tag"] = context_by_symbol[symbol].get("setup_tag") or None
            if not session_tag:
                item["session_tag"] = context_by_symbol[symbol].get("session_tag") or None

        enriched.append(item)

    enriched.reverse()
    return enriched


def build_broker(config: BotConfig) -> Broker:
    if config.broker_mode == "alpaca":
        return AlpacaPaperBroker(config)
    return PaperBroker(config)
