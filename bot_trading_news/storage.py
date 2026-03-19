from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path


DEFAULT_ACTIVITY_DB = "bot_activity.db"
DEFAULT_ACTIVITY_JSON = "bot_activity.json"


def append_activity_snapshot_sqlite(
    orders,
    status,
    db_path: str | Path = DEFAULT_ACTIVITY_DB,
    legacy_json_path: str | Path = DEFAULT_ACTIVITY_JSON,
) -> None:
    database = _connect(_resolve_db_path(db_path))
    try:
        _ensure_schema(database)
        _import_legacy_if_needed(database, _resolve_legacy_json_path(legacy_json_path))

        balance_state = _load_balance_state(database)
        current_equity = _to_float(status.equity)
        initial_equity = balance_state.get("initial_equity")
        if initial_equity is None and current_equity is not None:
            initial_equity = current_equity

        updated_at = datetime.now(UTC).isoformat()
        database.execute(
            """
            INSERT INTO balance_state (
                singleton_id, broker, status, currency, equity, initial_equity,
                cash, buying_power, is_paper, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                broker=excluded.broker,
                status=excluded.status,
                currency=excluded.currency,
                equity=excluded.equity,
                initial_equity=excluded.initial_equity,
                cash=excluded.cash,
                buying_power=excluded.buying_power,
                is_paper=excluded.is_paper,
                updated_at=excluded.updated_at
            """,
            (
                status.broker,
                status.status,
                status.currency,
                current_equity,
                initial_equity,
                _to_float(status.cash),
                _to_float(status.buying_power),
                1 if status.is_paper else 0,
                updated_at,
            ),
        )

        for order in orders:
            order_payload = asdict(order)
            database.execute(
                """
                INSERT INTO orders (
                    created_at, symbol, side, notional_usd, score, confidence,
                    reasons_json, broker, status, broker_order_id, detail, pnl_usd, setup_tag, session_tag
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_payload.get("created_at"),
                    order_payload.get("symbol"),
                    order_payload.get("side"),
                    order_payload.get("notional_usd"),
                    order_payload.get("score"),
                    order_payload.get("confidence"),
                    json.dumps(order_payload.get("reasons", [])),
                    order_payload.get("broker"),
                    order_payload.get("status"),
                    order_payload.get("broker_order_id"),
                    order_payload.get("detail"),
                    order_payload.get("pnl_usd"),
                    order_payload.get("setup_tag"),
                    order_payload.get("session_tag"),
                ),
            )

        database.commit()
    finally:
        database.close()


def load_bot_activity_sqlite(
    db_path: str | Path = DEFAULT_ACTIVITY_DB,
    legacy_json_path: str | Path = DEFAULT_ACTIVITY_JSON,
) -> dict:
    database = _connect(_resolve_db_path(db_path))
    try:
        _ensure_schema(database)
        _import_legacy_if_needed(database, _resolve_legacy_json_path(legacy_json_path))

        balance = _load_balance_state(database)
        orders = []
        rows = database.execute(
            """
            SELECT created_at, symbol, side, notional_usd, score, confidence,
                   reasons_json, broker, status, broker_order_id, detail, pnl_usd, setup_tag, session_tag
            FROM orders
            ORDER BY datetime(created_at) DESC
            LIMIT 80
            """
        ).fetchall()
        for row in rows:
            orders.append(
                {
                    "created_at": row["created_at"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "notional_usd": row["notional_usd"],
                    "score": row["score"],
                    "confidence": row["confidence"],
                    "reasons": _safe_json_load(row["reasons_json"], []),
                    "broker": row["broker"],
                    "status": row["status"],
                    "broker_order_id": row["broker_order_id"],
                    "detail": row["detail"],
                    "pnl_usd": row["pnl_usd"],
                    "setup_tag": row["setup_tag"],
                    "session_tag": row["session_tag"],
                }
            )

        return {"balance": balance, "orders": orders}
    finally:
        database.close()


def sync_managed_positions_sqlite(
    managed_positions: dict[str, dict],
    db_path: str | Path = DEFAULT_ACTIVITY_DB,
) -> dict[str, dict]:
    database = _connect(_resolve_db_path(db_path))
    try:
        _ensure_schema(database)
        now = datetime.now(UTC).isoformat()
        existing_rows = database.execute(
            """
            SELECT symbol, opened_at, peak_unrealized_pnl_pct, last_unrealized_pnl_pct
            FROM managed_positions
            """
        ).fetchall()
        existing = {row["symbol"]: row for row in existing_rows}
        active_symbols = set()
        enriched: dict[str, dict] = {}

        for symbol, position in managed_positions.items():
            active_symbols.add(symbol)
            current_pnl_pct = round(float(position.get("unrealized_plpc") or 0.0) * 100, 2)
            previous_peak = existing.get(symbol)["peak_unrealized_pnl_pct"] if symbol in existing else None
            peak_pnl_pct = max(previous_peak or current_pnl_pct, current_pnl_pct)
            database.execute(
                """
                INSERT INTO managed_positions (
                    symbol, opened_at, entry_notional_usd, peak_unrealized_pnl_pct,
                    last_unrealized_pnl_pct, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    opened_at=excluded.opened_at,
                    entry_notional_usd=excluded.entry_notional_usd,
                    peak_unrealized_pnl_pct=excluded.peak_unrealized_pnl_pct,
                    last_unrealized_pnl_pct=excluded.last_unrealized_pnl_pct,
                    updated_at=excluded.updated_at
                """,
                (
                    symbol,
                    position.get("opened_at"),
                    position.get("entry_notional_usd"),
                    peak_pnl_pct,
                    current_pnl_pct,
                    now,
                ),
            )
            enriched[symbol] = {
                **position,
                "peak_unrealized_pnl_pct": peak_pnl_pct,
                "last_unrealized_pnl_pct": current_pnl_pct,
            }

        if active_symbols:
            placeholders = ",".join("?" for _ in active_symbols)
            database.execute(
                f"DELETE FROM managed_positions WHERE symbol NOT IN ({placeholders})",
                tuple(active_symbols),
            )
        else:
            database.execute("DELETE FROM managed_positions")

        database.commit()
        return enriched
    finally:
        database.close()


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema(database: sqlite3.Connection) -> None:
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS balance_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            broker TEXT,
            status TEXT,
            currency TEXT,
            equity REAL,
            initial_equity REAL,
            cash REAL,
            buying_power REAL,
            is_paper INTEGER,
            updated_at TEXT
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            symbol TEXT,
            side TEXT,
            notional_usd REAL,
            score REAL,
            confidence REAL,
            reasons_json TEXT,
            broker TEXT,
            status TEXT,
            broker_order_id TEXT,
            detail TEXT
            ,
            pnl_usd REAL,
            setup_tag TEXT,
            session_tag TEXT
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS managed_positions (
            symbol TEXT PRIMARY KEY,
            opened_at TEXT,
            entry_notional_usd REAL,
            peak_unrealized_pnl_pct REAL,
            last_unrealized_pnl_pct REAL,
            updated_at TEXT
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at TEXT,
            symbol TEXT,
            horizon TEXT,
            action TEXT,
            score REAL,
            confidence REAL,
            expected_return_per_100 REAL,
            setup_tag TEXT,
            session_tag TEXT,
            entry_price REAL,
            exit_price REAL,
            realized_return_pct REAL,
            status TEXT,
            evaluated_at TEXT,
            factor_scores_json TEXT
        )
        """
    )
    columns = {row["name"] for row in database.execute("PRAGMA table_info(orders)").fetchall()}
    if "pnl_usd" not in columns:
        database.execute("ALTER TABLE orders ADD COLUMN pnl_usd REAL")
    if "setup_tag" not in columns:
        database.execute("ALTER TABLE orders ADD COLUMN setup_tag TEXT")
    if "session_tag" not in columns:
        database.execute("ALTER TABLE orders ADD COLUMN session_tag TEXT")


def _import_legacy_if_needed(database: sqlite3.Connection, legacy_json_path: str | Path) -> None:
    has_balance = database.execute("SELECT COUNT(*) AS count FROM balance_state").fetchone()["count"]
    has_orders = database.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
    if has_balance or has_orders:
        return

    legacy_path = Path(legacy_json_path)
    if not legacy_path.exists():
        return

    try:
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    balance = payload.get("balance", {})
    if balance:
        database.execute(
            """
            INSERT OR REPLACE INTO balance_state (
                singleton_id, broker, status, currency, equity, initial_equity,
                cash, buying_power, is_paper, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                balance.get("broker"),
                balance.get("status"),
                balance.get("currency"),
                balance.get("equity"),
                balance.get("initial_equity"),
                balance.get("cash"),
                balance.get("buying_power"),
                1 if balance.get("is_paper") else 0,
                balance.get("updated_at"),
            ),
        )

    for order in payload.get("orders", [])[:80]:
        database.execute(
            """
            INSERT INTO orders (
                created_at, symbol, side, notional_usd, score, confidence,
                reasons_json, broker, status, broker_order_id, detail, pnl_usd, setup_tag, session_tag
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.get("created_at"),
                order.get("symbol"),
                order.get("side"),
                order.get("notional_usd"),
                order.get("score"),
                order.get("confidence"),
                json.dumps(order.get("reasons", [])),
                order.get("broker"),
                order.get("status"),
                order.get("broker_order_id"),
                order.get("detail"),
                order.get("pnl_usd"),
                order.get("setup_tag"),
                order.get("session_tag"),
            ),
        )

    database.commit()


def _load_balance_state(database: sqlite3.Connection) -> dict:
    row = database.execute(
        """
        SELECT broker, status, currency, equity, initial_equity, cash,
               buying_power, is_paper, updated_at
        FROM balance_state
        WHERE singleton_id = 1
        """
    ).fetchone()
    if not row:
        return {}
    return {
        "broker": row["broker"],
        "status": row["status"],
        "currency": row["currency"],
        "equity": row["equity"],
        "initial_equity": row["initial_equity"],
        "cash": row["cash"],
        "buying_power": row["buying_power"],
        "is_paper": bool(row["is_paper"]) if row["is_paper"] is not None else None,
        "updated_at": row["updated_at"],
    }


def _safe_json_load(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return None


def _resolve_db_path(default_path: str | Path) -> str | Path:
    return os.getenv("ACTIVITY_DB_PATH") or default_path


def _resolve_legacy_json_path(default_path: str | Path) -> str | Path:
    return os.getenv("ACTIVITY_JSON_PATH") or default_path


def load_setup_stats_sqlite(db_path: str | Path = DEFAULT_ACTIVITY_DB) -> dict[str, dict]:
    database = _connect(_resolve_db_path(db_path))
    try:
        _ensure_schema(database)
        rows = database.execute(
            """
            SELECT
                setup_tag,
                COUNT(*) AS trades,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) AS winners,
                SUM(COALESCE(pnl_usd, 0)) AS total_pnl,
                AVG(COALESCE(pnl_usd, 0)) AS avg_pnl
            FROM orders
            WHERE side = 'SELL'
              AND status IN ('filled', 'simulated_exit', 'close_submitted')
              AND setup_tag IS NOT NULL
              AND setup_tag != ''
            GROUP BY setup_tag
            """
        ).fetchall()
        return {
            row["setup_tag"]: {
                "trades": int(row["trades"] or 0),
                "winners": int(row["winners"] or 0),
                "win_rate": round(((row["winners"] or 0) / row["trades"]) * 100, 1) if row["trades"] else 0.0,
                "total_pnl": round(float(row["total_pnl"] or 0.0), 2),
                "avg_pnl": round(float(row["avg_pnl"] or 0.0), 2),
            }
            for row in rows
        }
    finally:
        database.close()


def record_predictions_sqlite(
    signals,
    snapshots: dict,
    horizon: str,
    db_path: str | Path = DEFAULT_ACTIVITY_DB,
) -> int:
    database = _connect(_resolve_db_path(db_path))
    try:
        _ensure_schema(database)
        created = 0
        generated_at = datetime.now(UTC).isoformat()
        cutoff = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        for signal in signals:
            snapshot = snapshots.get(signal.symbol)
            close_prices = list(getattr(snapshot, "close_prices", []) or (snapshot or {}).get("close_prices", []))
            if not close_prices:
                continue
            exists = database.execute(
                """
                SELECT 1 FROM predictions
                WHERE generated_at >= ? AND symbol = ? AND horizon = ? AND action = ? AND setup_tag = ?
                LIMIT 1
                """,
                (cutoff, signal.symbol, horizon, signal.action, signal.setup_tag),
            ).fetchone()
            if exists:
                continue
            database.execute(
                """
                INSERT INTO predictions (
                    generated_at, symbol, horizon, action, score, confidence,
                    expected_return_per_100, setup_tag, session_tag, entry_price,
                    status, factor_scores_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generated_at,
                    signal.symbol,
                    horizon,
                    signal.action,
                    signal.score,
                    signal.confidence,
                    signal.expected_return_per_100,
                    signal.setup_tag,
                    signal.session_tag,
                    float(close_prices[-1]),
                    "pending",
                    json.dumps(signal.factor_scores),
                ),
            )
            created += 1
        database.commit()
        return created
    finally:
        database.close()


def evaluate_predictions_sqlite(
    snapshots: dict,
    db_path: str | Path = DEFAULT_ACTIVITY_DB,
) -> dict[str, int]:
    database = _connect(_resolve_db_path(db_path))
    try:
        _ensure_schema(database)
        rows = database.execute(
            """
            SELECT id, generated_at, symbol, horizon, action, entry_price
            FROM predictions
            WHERE status = 'pending'
            ORDER BY datetime(generated_at) ASC
            """
        ).fetchall()
        now = datetime.now(UTC)
        summary = {"evaluated": 0, "winners": 0, "losers": 0}
        for row in rows:
            generated_at = _parse_dt_utc(row["generated_at"])
            if not generated_at or now < generated_at + _prediction_window(str(row["horizon"])):
                continue
            snapshot = snapshots.get(str(row["symbol"]).upper())
            close_prices = list(getattr(snapshot, "close_prices", []) or (snapshot or {}).get("close_prices", []))
            if not close_prices or not row["entry_price"]:
                continue
            exit_price = float(close_prices[-1])
            entry_price = float(row["entry_price"])
            raw_return_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0.0
            realized_return_pct = raw_return_pct if str(row["action"]).upper() == "BUY" else -raw_return_pct
            outcome = "win" if realized_return_pct > 0 else "loss" if realized_return_pct < 0 else "flat"
            database.execute(
                """
                UPDATE predictions
                SET status = ?, exit_price = ?, realized_return_pct = ?, evaluated_at = ?
                WHERE id = ?
                """,
                (outcome, exit_price, round(realized_return_pct, 2), now.isoformat(), row["id"]),
            )
            summary["evaluated"] += 1
            if outcome == "win":
                summary["winners"] += 1
            elif outcome == "loss":
                summary["losers"] += 1
        database.commit()
        return summary
    finally:
        database.close()


def _prediction_window(horizon: str) -> timedelta:
    mapping = {
        "short": timedelta(days=3),
        "medium": timedelta(days=28),
        "long": timedelta(days=180),
    }
    return mapping.get(horizon.lower(), timedelta(days=28))


def _parse_dt_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
