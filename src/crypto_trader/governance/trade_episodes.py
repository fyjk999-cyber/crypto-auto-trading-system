"""Trade Episode pipeline: CLOSED TRADE -> AITradeEpisode (learning input).

P2 interrupt repair. Every fact comes from canonical database records
(orders, fills, ledger). No synthetic prices, no forced trades, no second
truth source. Idempotent by construction: a stable episode key derived from
the cycle's own fill ids makes replays/backfills single-insert.

A completed trade cycle requires:
- one or more entry fills (position flat -> non-zero)
- one or more reduce-only exit fills (position back to exactly zero)
Partial closes leave the cycle OPEN and are never persisted as completed.
Legacy quarantined fills (EVIDENCE_QUARANTINE) never enter an episode.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

D = Decimal

ENTRY_REASON_DEFAULT = "UNKNOWN"


def _sha(data: str) -> str:
    return hashlib.sha1(data.encode("utf-8")).hexdigest()[:24]


@dataclass
class Cycle:
    symbol: str
    market_type: str
    entry_fills: list[dict] = field(default_factory=list)
    exit_fills: list[dict] = field(default_factory=list)
    open_qty: Decimal = D("0")
    direction: str = "LONG"

    def complete(self) -> bool:
        return bool(self.entry_fills) and bool(self.exit_fills) and self.open_qty == 0


def _quarantined_fill_ids_sync(conn) -> set[str]:
    cur = conn.execute(
        "SELECT target FROM audit_events WHERE action = 'EVIDENCE_QUARANTINE'"
    )
    out: set[str] = set()
    for r in cur.fetchall():
        target = str(r[0] or "")
        if target.startswith("fill_"):
            out.add(target)
    return out


def _parse_ts(value) -> datetime | None:
    """Parse sqlite timestamps: datetime objects, ISO-T, 'YYYY-MM-DD HH:MM:SS'."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text_val = str(value).strip()
    if not text_val:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text_val, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text_val)
    except ValueError:
        return None


def _signed(fill: dict) -> Decimal:
    return fill["quantity"] if fill["side"] == "BUY" else -fill["quantity"]


def _is_reduce(fill: dict, open_qty: Decimal) -> bool:
    return open_qty != 0 and (
        (open_qty > 0 and fill["side"] == "SELL")
        or (open_qty < 0 and fill["side"] == "BUY")
    )


def build_cycles(symbol: str, fills: list[dict]) -> list[Cycle]:
    """Replay canonical fills into flat-to-flat trade cycles."""
    cycles: list[Cycle] = []
    current: Cycle | None = None
    for f in fills:
        if current is None or current.open_qty == 0:
            # Only a non-reduce fill may open a cycle; a reduce-only fill
            # with no tracked entry belongs to an unknown legacy state.
            if current is not None and current.complete():
                cycles.append(current)
            current = None
            if _is_reduce(f, D("0")) or f["reduce_only"]:
                continue
            current = Cycle(
                symbol=symbol,
                market_type=f["market_type"],
                direction="LONG" if f["side"] == "BUY" else "SHORT",
            )
            current.entry_fills.append(f)
            current.open_qty = _signed(f)
            continue
        if _is_reduce(f, current.open_qty) or f["reduce_only"]:
            current.exit_fills.append(f)
        else:
            current.entry_fills.append(f)
        # signed quantity replay: SELL is negative (reduces LONG / opens
        # SHORT), BUY is positive (reduces SHORT / opens LONG)
        current.open_qty += _signed(f)
    if current is not None and current.complete():
        cycles.append(current)
    return cycles


def _weighted_avg(fills: list[dict]) -> Decimal:
    total_qty = sum((f["quantity"] for f in fills), D("0"))
    if total_qty == 0:
        return D("0")
    notional = sum((f["price"] * f["quantity"] for f in fills), D("0"))
    return notional / total_qty


def _ledger_realized_by_order(conn) -> dict[str, tuple[str, str]]:
    """order_id -> (realized_pnl, fee) from canonical FUTURES_REALIZED_PNL."""
    out: dict[str, tuple[str, str]] = {}
    cur = conn.execute(
        "SELECT order_id, metadata_json FROM ledger_transactions "
        "WHERE entry_type = 'FUTURES_REALIZED_PNL' AND order_id IS NOT NULL"
    )
    for order_id, meta_json in cur.fetchall():
        try:
            meta = json.loads(meta_json) if isinstance(meta_json, str) else (meta_json or {})
        except (TypeError, ValueError):
            meta = {}
        if meta.get("realized_pnl") is not None:
            out[str(order_id)] = (str(meta.get("realized_pnl")), str(meta.get("fee") or 0))
    return out


def _exit_reason_for(
    exit_fills: list[dict],
    ai_exit_intents: dict[str, str],
    entry_ts,
    time_stop_seconds: float | None,
) -> str:
    """Classify exit authority. TIME_STOP must never be labelled AI_EXIT."""
    for f in exit_fills:
        reason = str((f["payload"] or {}).get("exit_reason") or "")
        if reason:
            return reason
    for f in exit_fills:
        hit = ai_exit_intents.get(f["order_id"])
        if hit:
            return hit
    # Legacy fallback (pre-pipeline exits): bridge reduce-only exits whose
    # holding duration reached the configured time-stop window are TIME_STOP;
    # anything else stays honest UNKNOWN.
    strategies = {f["strategy_id"] for f in exit_fills}
    if strategies == {"ai_brain"} and time_stop_seconds and entry_ts is not None:
        entry_dt = _parse_ts(entry_ts)
        exit_dt = _parse_ts(exit_fills[-1]["timestamp"])
        if entry_dt is not None and exit_dt is not None:
            held = (exit_dt - entry_dt).total_seconds()
            if held >= time_stop_seconds * 0.95:
                return "TIME_STOP"
        return "UNKNOWN"
    return ENTRY_REASON_DEFAULT


def cycle_episode(cycle: Cycle, ledger_realized: dict[str, tuple[str, str]]) -> dict | None:
    entry_ids = [f["fill_id"] for f in cycle.entry_fills]
    exit_ids = [f["fill_id"] for f in cycle.exit_fills]
    key = _sha(f"{cycle.symbol}|{cycle.market_type}|{','.join(entry_ids)}|{','.join(exit_ids)}")
    entry_avg = _weighted_avg(cycle.entry_fills)
    exit_avg = _weighted_avg(cycle.exit_fills)
    entry_qty = sum((f["quantity"] for f in cycle.entry_fills), D("0"))
    exit_qty = sum((f["quantity"] for f in cycle.exit_fills), D("0"))
    closed_qty = min(entry_qty, exit_qty)
    fees = sum((f["fee"] for f in cycle.entry_fills + cycle.exit_fills), D("0"))
    fee_currency = (cycle.exit_fills + cycle.entry_fills)[0]["fee_currency"] or "USDT"
    gross: Decimal | None = None
    # Perp realized PnL is canonical from the FuturesLedger (gross of fees).
    for f in cycle.exit_fills:
        hit = ledger_realized.get(f["order_id"])
        if hit:
            gross = D(hit[0])
            break
    if gross is None:
        if cycle.direction == "LONG":
            gross = (exit_avg - entry_avg) * closed_qty
        else:
            gross = (entry_avg - exit_avg) * closed_qty
    net = gross - fees
    result = "WIN" if net > 0 else ("LOSS" if net < 0 else "BREAKEVEN")
    entry_ts = cycle.entry_fills[0]["timestamp"]
    exit_ts = cycle.exit_fills[-1]["timestamp"]
    entry_dt = _parse_ts(entry_ts)
    exit_dt = _parse_ts(exit_ts)
    if entry_dt is not None and exit_dt is not None:
        holding = max(0.0, (exit_dt - entry_dt).total_seconds())
    else:
        holding = 0.0
    entry_decision = (cycle.entry_fills[0]["payload"] or {}).get("decision_id")
    entry_signal = (cycle.entry_fills[0]["payload"] or {}).get("signal_id")
    return {
        "episode_id": f"eps-{key}",
        "symbol": cycle.symbol,
        "market_type": cycle.market_type,
        "direction": cycle.direction,
        "entry_price": entry_avg,
        "exit_price": exit_avg,
        "position_size": closed_qty,
        "entry_qty": entry_qty,
        "exit_qty": exit_qty,
        "holding_time_seconds": holding,
        "gross_pnl": gross,
        "fees": fees,
        "fee_currency": fee_currency,
        "net_pnl": net,
        "result": result,
        "entry_timestamp": entry_ts,
        "exit_timestamp": exit_ts,
        "entry_order_ids": sorted({f["order_id"] for f in cycle.entry_fills}),
        "exit_order_ids": sorted({f["order_id"] for f in cycle.exit_fills}),
        "entry_fill_ids": entry_ids,
        "exit_fill_ids": exit_ids,
        "entry_decision_id": entry_decision,
        "entry_signal_id": entry_signal,
        "strategy_id": cycle.entry_fills[0]["strategy_id"],
        "cycle": cycle,
    }


def ensure_columns(conn) -> list[str]:
    """Idempotent minimal schema extension for learning lineage."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_trade_episodes)").fetchall()}
    added: list[str] = []
    for name, ddl in (
        (
            "market_type",
            "ALTER TABLE ai_trade_episodes ADD COLUMN market_type "
            "VARCHAR(16) NOT NULL DEFAULT 'SPOT'",
        ),
        (
            "direction",
            "ALTER TABLE ai_trade_episodes ADD COLUMN direction "
            "VARCHAR(8) NOT NULL DEFAULT 'LONG'",
        ),
        ("exit_reason", "ALTER TABLE ai_trade_episodes ADD COLUMN exit_reason VARCHAR(32)"),
        ("lineage_json", "ALTER TABLE ai_trade_episodes ADD COLUMN lineage_json JSON"),
        ("gross_pnl", "ALTER TABLE ai_trade_episodes ADD COLUMN gross_pnl DECIMAL(30,12)"),
        ("fees", "ALTER TABLE ai_trade_episodes ADD COLUMN fees DECIMAL(30,12)"),
        ("net_pnl", "ALTER TABLE ai_trade_episodes ADD COLUMN net_pnl DECIMAL(30,12)"),
    ):
        if name not in have:
            conn.execute(ddl)
            added.append(name)
    return added


def persist_episode_sync(conn, episode: dict, exit_reason: str, lineage: dict) -> str:
    """Insert one episode row. Returns 'inserted' or 'exists' (idempotent)."""
    row = conn.execute(
        "SELECT 1 FROM ai_trade_episodes WHERE episode_id = ?",
        (episode["episode_id"],),
    ).fetchone()
    if row:
        # deterministic derived fields: re-derive from canonical facts
        conn.execute(
            "UPDATE ai_trade_episodes SET entry_price=?, exit_price=?, "
            "position_size=?, holding_time_seconds=?, pnl=?, gross_pnl=?, "
            "fees=?, net_pnl=?, result=?, market_type=?, direction=?, "
            "exit_reason=?, lineage_json=? WHERE episode_id=?",
            (
                str(episode["entry_price"]),
                str(episode["exit_price"]),
                str(episode["position_size"]),
                float(episode["holding_time_seconds"]),
                str(episode["net_pnl"]),
                str(episode["gross_pnl"]),
                str(episode["fees"]),
                str(episode["net_pnl"]),
                episode["result"],
                episode["market_type"],
                episode["direction"],
                exit_reason,
                json.dumps(lineage, default=str),
                episode["episode_id"],
            ),
        )
        return "updated"
    conn.execute(
        "INSERT INTO ai_trade_episodes (episode_id, symbol, market_regime, "
        "strategy_selected, llm_reasoning, entry_price, exit_price, "
        "position_size, leverage, holding_time_seconds, pnl, mfe, mae, "
        "result, review_status, created_at, market_type, direction, "
        "exit_reason, gross_pnl, fees, net_pnl, lineage_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            episode["episode_id"],
            episode["symbol"],
            str(lineage.get("entry_regime") or "UNKNOWN"),
            episode["strategy_id"],
            "",
            str(episode["entry_price"]),
            str(episode["exit_price"]),
            str(episode["position_size"]),
            "0",
            float(episode["holding_time_seconds"]),
            str(episode["net_pnl"]),
            "0",
            "0",
            episode["result"],
            "PENDING",
            datetime.utcnow().isoformat(),
            episode["market_type"],
            episode["direction"],
            exit_reason,
            str(episode["gross_pnl"]),
            str(episode["fees"]),
            str(episode["net_pnl"]),
            json.dumps(lineage, default=str),
        ),
    )
    return "inserted"


def _ai_exit_intents_sync(conn) -> dict[str, str]:
    """exit order_id -> exit_reason from durable AI_EXIT_INTENT audit rows."""
    out: dict[str, str] = {}
    cur = conn.execute(
        "SELECT order_id, after_json FROM audit_events WHERE action = 'AI_EXIT_INTENT' "
        "AND order_id IS NOT NULL"
    )
    for order_id, after_json in cur.fetchall():
        try:
            after = json.loads(after_json) if isinstance(after_json, str) else (after_json or {})
        except (TypeError, ValueError):
            after = {}
        reason = str(after.get("exit_reason") or "")
        if reason:
            out[str(order_id)] = reason
    return out


def record_all_cycles_sync(db_path: str, symbols: list[str] | None = None) -> dict:
    """Deterministic, idempotent backfill of all completed cycles."""
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        added_cols = ensure_columns(conn)
        quarantined = _quarantined_fill_ids_sync(conn)
        ledger_realized = _ledger_realized_by_order(conn)
        ai_exit_intents = _ai_exit_intents_sync(conn)
        if symbols is None:
            symbols = [
                r[0] for r in conn.execute("SELECT DISTINCT symbol FROM fills").fetchall()
            ]
        inserted = 0
        existed = 0
        details: list[dict] = []
        for symbol in symbols:
            cur = conn.execute(
                "SELECT f.fill_id, f.order_id, f.side, f.price, f.quantity, f.timestamp, "
                "f.fee, f.fee_currency, f.payload_json, o.reduce_only, o.strategy_id, "
                "o.client_order_id FROM fills f LEFT JOIN orders o "
                "ON f.order_id = o.internal_order_id WHERE f.symbol = ? "
                "ORDER BY f.timestamp ASC, f.id ASC",
                (symbol,),
            )
            fills: list[dict] = []
            for r in cur.fetchall():
                if r[0] in quarantined:
                    continue
                try:
                    payload = json.loads(r[8]) if r[8] else {}
                except (TypeError, ValueError):
                    payload = {}
                fills.append(
                    {
                        "fill_id": r[0],
                        "order_id": r[1],
                        "side": r[2],
                        "price": D(str(r[3])),
                        "quantity": D(str(r[4])),
                        "timestamp": r[5],
                        "fee": D(str(r[6] or 0)),
                        "fee_currency": r[7] or "USDT",
                        "market_type": str((payload or {}).get("market_type") or "SPOT"),
                        "reduce_only": bool(r[9]),
                        "strategy_id": r[10] or "unknown",
                        "client_order_id": r[11] or "",
                        "payload": payload or {},
                    }
                )
            for cycle in build_cycles(symbol, fills):
                ep = cycle_episode(cycle, ledger_realized)
                if ep is None:
                    continue
                exit_reason = _exit_reason_for(
                    cycle.exit_fills,
                    ai_exit_intents,
                    cycle.entry_fills[0]["timestamp"],
                    time_stop_seconds=14400.0,
                )
                lineage = {
                    "entry_order_ids": ep["entry_order_ids"],
                    "exit_order_ids": ep["exit_order_ids"],
                    "entry_fill_ids": ep["entry_fill_ids"],
                    "exit_fill_ids": ep["exit_fill_ids"],
                    "entry_decision_id": ep["entry_decision_id"],
                    "entry_signal_id": ep["entry_signal_id"],
                    "exit_reason": exit_reason,
                    "entry_timestamp": str(ep["entry_timestamp"]),
                    "exit_timestamp": str(ep["exit_timestamp"]),
                    "entry_qty": str(ep["entry_qty"]),
                    "exit_qty": str(ep["exit_qty"]),
                    "fee_currency": ep["fee_currency"],
                    "mae": "NOT_AVAILABLE",
                    "mfe": "NOT_AVAILABLE",
                }
                status = persist_episode_sync(conn, ep, exit_reason, lineage)
                if status == "inserted":
                    inserted += 1
                    details.append(
                        {
                            "episode_id": ep["episode_id"],
                            "symbol": ep["symbol"],
                            "market_type": ep["market_type"],
                            "result": ep["result"],
                            "net_pnl": str(ep["net_pnl"]),
                            "exit_reason": exit_reason,
                        }
                    )
                else:
                    existed += 1
        conn.commit()
        return {
            "inserted": inserted,
            "existed": existed,
            "columns_added": added_cols,
            "episodes": details,
        }
    finally:
        conn.close()


def record_cycle_for_fill_sync(
    db_path: str,
    fill_id: str,
    symbol: str,
    time_stop_seconds: float | None,
) -> dict:
    """Runtime hook: if this fill just completed a cycle, persist it once."""
    result = record_all_cycles_sync(db_path, symbols=[symbol])
    # Only the newest cycle can have been completed by this fill; if the
    # episode already existed (restart/replay) the unique key keeps it single.
    return result
