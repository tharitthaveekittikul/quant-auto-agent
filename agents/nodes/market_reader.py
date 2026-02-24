"""
market_reader node — fetches OHLCV bars from QuestDB, computes indicators,
and retrieves portfolio state from the broker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.constants import MIN_BARS_REQUIRED, OHLCV_LOOKBACK_HOURS, OHLCV_SAMPLE_INTERVAL
from utils.indicators import compute_all

if TYPE_CHECKING:
    import asyncpg


# ---------------------------------------------------------------------------
# QuestDB query
# ---------------------------------------------------------------------------

_OHLCV_QUERY = """
SELECT
    timestamp,
    first(last)  AS o,
    max(last)    AS h,
    min(last)    AS l,
    last(last)   AS c,
    sum(volume)  AS v,
    last(bid)    AS bid,
    last(ask)    AS ask
FROM market_data
WHERE symbol = $1
  AND last > 0
  AND timestamp >= dateadd('h', -{lookback}, now())
SAMPLE BY {interval} ALIGN TO CALENDAR
ORDER BY timestamp ASC
LIMIT 100
""".strip()


async def _fetch_bars_questdb(db_pool: "asyncpg.Pool", symbol: str) -> list[dict]:
    query = _OHLCV_QUERY.format(
        lookback=OHLCV_LOOKBACK_HOURS,
        interval=OHLCV_SAMPLE_INTERVAL,
    )
    try:
        rows = await db_pool.fetch(query, symbol)
        bars = []
        for row in rows:
            bars.append(
                {
                    "t": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
                    "o": float(row["o"] or 0),
                    "h": float(row["h"] or 0),
                    "l": float(row["l"] or 0),
                    "c": float(row["c"] or 0),
                    "v": float(row["v"] or 0),
                    "bid": float(row["bid"] or 0),
                    "ask": float(row["ask"] or 0),
                }
            )
        logger.debug(f"[market_reader] QuestDB returned {len(bars)} bars for {symbol}")
        return bars
    except Exception as exc:
        logger.warning(f"[market_reader] QuestDB fetch failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Broker fallback — REST historical bars
# ---------------------------------------------------------------------------

async def _fetch_bars_alpaca(broker_client: Any, symbol: str) -> list[dict]:
    """Use alpaca-py StockHistoricalDataClient to get minute bars as fallback."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        import asyncio
        from datetime import timedelta

        client = StockHistoricalDataClient(
            broker_client._api_key, broker_client._secret_key
        )
        start = datetime.now(timezone.utc) - timedelta(hours=OHLCV_LOOKBACK_HOURS)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            limit=200,
        )
        resp = await asyncio.to_thread(client.get_stock_bars, req)
        raw_bars = resp[symbol] if symbol in resp else []
        bars = [
            {
                "t": b.timestamp.isoformat(),
                "o": float(b.open),
                "h": float(b.high),
                "l": float(b.low),
                "c": float(b.close),
                "v": float(b.volume),
                "bid": float(b.close),
                "ask": float(b.close),
            }
            for b in raw_bars
        ]
        logger.info(f"[market_reader] Alpaca REST fallback: {len(bars)} bars for {symbol}")
        return bars
    except Exception as exc:
        logger.error(f"[market_reader] Alpaca REST fallback failed: {exc}")
        return []


async def _fetch_bars_projectx(broker_client: Any, symbol: str) -> list[dict]:
    """Use ProjectX REST get_bars as fallback."""
    try:
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=OHLCV_LOOKBACK_HOURS)).isoformat()
        end = now.isoformat()
        raw = await broker_client.rest.get_bars(
            contract_id=symbol,
            start_time=start,
            end_time=end,
            unit=2,
            unit_number=5,
            limit=200,
        )
        bars = [
            {
                "t": b.get("t", ""),
                "o": float(b.get("o", 0)),
                "h": float(b.get("h", 0)),
                "l": float(b.get("l", 0)),
                "c": float(b.get("c", 0)),
                "v": float(b.get("v", 0)),
                "bid": float(b.get("c", 0)),
                "ask": float(b.get("c", 0)),
            }
            for b in raw
        ]
        logger.info(f"[market_reader] ProjectX REST fallback: {len(bars)} bars for {symbol}")
        return bars
    except Exception as exc:
        logger.error(f"[market_reader] ProjectX REST fallback failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Portfolio normalisation
# ---------------------------------------------------------------------------

async def _fetch_portfolio_alpaca(broker_client: Any) -> dict:
    account = await broker_client.rest.get_account()
    positions = await broker_client.rest.get_all_positions()

    equity = float(account.get("equity", 0) or 0)
    last_equity = float(account.get("last_equity", equity) or equity)
    daily_pnl = equity - last_equity
    daily_pnl_pct = daily_pnl / last_equity if last_equity else 0.0
    drawdown_pct = max(0.0, -daily_pnl_pct)

    return {
        "cash": float(account.get("cash", 0) or 0),
        "equity": equity,
        "buying_power": float(account.get("buying_power", 0) or 0),
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
        "drawdown_pct": drawdown_pct,
        "positions": [
            {
                "symbol": p.get("symbol"),
                "qty": float(p.get("qty", 0) or 0),
                "market_value": float(p.get("market_value", 0) or 0),
                "unrealized_pl": float(p.get("unrealized_pl", 0) or 0),
            }
            for p in positions
        ],
    }


async def _fetch_portfolio_projectx(broker_client: Any, account_id: int) -> dict:
    accounts = await broker_client.rest.search_accounts()
    acc = next((a for a in accounts if a.get("id") == account_id), accounts[0] if accounts else {})
    positions = await broker_client.rest.get_open_positions(account_id)

    equity = float(acc.get("balance", 0) or 0)
    daily_pnl = float(acc.get("dailyPnl", 0) or 0)
    daily_pnl_pct = daily_pnl / equity if equity else 0.0
    drawdown_pct = max(0.0, -daily_pnl_pct)

    return {
        "cash": equity,
        "equity": equity,
        "buying_power": equity,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
        "drawdown_pct": drawdown_pct,
        "positions": [
            {
                "symbol": p.get("contractId"),
                "qty": float(p.get("size", 0) or 0),
                "market_value": 0.0,
                "unrealized_pl": float(p.get("unrealizedPnl", 0) or 0),
            }
            for p in positions
        ],
    }


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------

async def market_reader(state: dict, *, db_pool: "asyncpg.Pool", broker_client: Any) -> dict:
    """LangGraph node: fetches OHLCV bars + indicators + portfolio."""
    symbol: str = state["symbol"]
    broker: str = state["broker"]
    account_id = state.get("account_id")

    logger.info(f"[market_reader] Fetching data for {symbol} via {broker}")

    # 1. Fetch bars (QuestDB first, REST fallback)
    bars = await _fetch_bars_questdb(db_pool, symbol)
    if len(bars) < MIN_BARS_REQUIRED:
        logger.info(f"[market_reader] Insufficient QuestDB bars ({len(bars)}), using REST fallback")
        if broker == "alpaca":
            bars = await _fetch_bars_alpaca(broker_client, symbol)
        else:
            bars = await _fetch_bars_projectx(broker_client, symbol)

    if not bars:
        logger.warning(f"[market_reader] No bars available for {symbol}")
        return {
            "market_data": [],
            "signals": {},
            "portfolio": {},
            "error": f"No market data for {symbol}",
        }

    # 2. Compute indicators
    signals = compute_all(bars)
    logger.debug(f"[market_reader] Signals computed: price={signals.get('current_price')}")

    # 3. Fetch portfolio
    try:
        if broker == "alpaca":
            portfolio = await _fetch_portfolio_alpaca(broker_client)
        else:
            portfolio = await _fetch_portfolio_projectx(broker_client, account_id)
        logger.debug(f"[market_reader] Portfolio equity={portfolio['equity']:.2f}")
    except Exception as exc:
        logger.error(f"[market_reader] Portfolio fetch failed: {exc}")
        portfolio = {
            "cash": 0.0, "equity": 0.0, "buying_power": 0.0,
            "daily_pnl": 0.0, "daily_pnl_pct": 0.0, "drawdown_pct": 0.0,
            "positions": [],
        }

    return {"market_data": bars, "signals": signals, "portfolio": portfolio}
