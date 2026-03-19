from __future__ import annotations

from dataclasses import asdict

from bot_trading_news.broker import BrokerOrder, build_broker, load_live_bot_activity
from bot_trading_news.config import BotConfig, load_config
from bot_trading_news.strategy import Signal

from services.execution_service.models import ExecuteSignalRequest


class ExecutionService:
    """Fachada fina sobre el broker actual para migrar a microservicios sin romper el monolito."""

    def __init__(self, config: BotConfig | None = None) -> None:
        self.config = config or load_config()
        self.broker = build_broker(self.config)

    def health(self) -> dict:
        status = self.broker.check_status()
        return {
            "ok": True,
            "service": "execution_service",
            "broker_mode": self.config.broker_mode,
            "broker_ok": status.ok,
            "broker": status.broker,
            "paper": status.is_paper,
        }

    def get_account(self) -> dict:
        return asdict(self.broker.check_status())

    def get_positions(self) -> dict:
        return {
            "broker": self.config.broker_mode,
            "positions": self.broker.get_positions_snapshot(),
        }

    def get_activity(self) -> dict:
        history, _positions, _status = load_live_bot_activity(self.config)
        balance = history.get("balance", {})
        equity = balance.get("equity")
        initial_equity = balance.get("initial_equity")
        pnl_total = None
        if isinstance(equity, (int, float)) and isinstance(initial_equity, (int, float)):
            pnl_total = round(equity - initial_equity, 2)

        return {
            "broker": self.config.broker_mode,
            "balance": balance,
            "orders": history.get("orders", []),
            "managed_positions": history.get("managed_positions", {}),
            "performance": history.get("performance", {}),
            "alerts": history.get("alerts", []),
            "pnl_total": pnl_total,
        }

    def execute(self, requests: list[ExecuteSignalRequest]) -> dict:
        signals = [self._to_signal(item) for item in requests]
        orders = self.broker.execute(signals)
        return {
            "broker": self.config.broker_mode,
            "submitted": len(orders),
            "orders": [asdict(order) for order in orders],
        }

    def _to_signal(self, request: ExecuteSignalRequest) -> Signal:
        return Signal(
            symbol=request.symbol.strip().upper(),
            score=request.score,
            action=request.action,
            confidence=request.confidence,
            expected_return_per_100=request.expected_return_per_100,
            article_count=request.article_count,
            factor_scores=request.factor_scores,
            reasons=request.reasons,
            factor_notes=request.factor_notes,
        )
