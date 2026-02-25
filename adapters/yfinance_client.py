"""
YFinance paper trading client for forex and commodity symbols.

Uses Yahoo Finance via yfinance for free market data (no API key needed).
Maintains a simulated paper portfolio in memory.

Symbol mapping (friendly → Yahoo Finance ticker):
  XAUUSD → GC=F   (Gold futures continuous contract)
  XAGUSD → SI=F   (Silver futures continuous contract)
  AUDUSD → AUDUSD=X
  EURUSD → EURUSD=X
  GBPJPY → GBPJPY=X

Notes:
  - No streaming — all data is fetched via REST on each cycle.
  - Portfolio state is in-memory; resets on process restart.
  - Execution is simulated (paper): no real orders are placed.
  - Quantities for metals are in troy ounces; forex in base-currency units.
"""

import asyncio
from datetime import datetime, timezone

from loguru import logger


SYMBOL_MAP: dict[str, str] = {
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "AUDUSD": "AUDUSD=X",
    "EURUSD": "EURUSD=X",
    "GBPJPY": "GBPJPY=X",
}

# Approximate typical spread as fraction of price (used for bid/ask simulation)
SPREAD_FRACTION: dict[str, float] = {
    "XAUUSD": 0.0002,   # ~$0.60 on $3000
    "XAGUSD": 0.0003,
    "AUDUSD": 0.00015,
    "EURUSD": 0.00010,
    "GBPJPY": 0.00020,
}


class YFinanceClient:
    """
    Paper-trading client backed by Yahoo Finance data.

    Exposes the same interface used by market_reader and execution nodes:
      get_bars(), get_account(), get_all_positions(), buy(), sell(), disconnect()
    """

    def __init__(self, starting_capital: float = 100_000.0) -> None:
        self._starting_capital = starting_capital
        self._cash = starting_capital
        self._positions: dict[str, dict] = {}  # symbol → {qty, avg_price}
        self._peak_equity = starting_capital
        # Expose self as .rest so execution.py can call broker_client.rest.* if needed
        self.rest = self

    # ------------------------------------------------------------------
    # Symbol helpers
    # ------------------------------------------------------------------

    @staticmethod
    def yf_symbol(symbol: str) -> str:
        return SYMBOL_MAP.get(symbol.upper(), symbol)

    @staticmethod
    def _spread(symbol: str) -> float:
        return SPREAD_FRACTION.get(symbol.upper(), 0.0002)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_bars(
        self,
        symbol: str,
        interval: str = "5m",
        lookback_days: int = 5,
    ) -> list[dict]:
        """
        Fetch OHLCV bars from Yahoo Finance.
        Returns bars sorted oldest → newest with keys: t, o, h, l, c, v, bid, ask.
        """
        yf_sym = self.yf_symbol(symbol)
        spread_frac = self._spread(symbol)

        def _fetch() -> list[dict]:
            import yfinance as yf

            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period=f"{lookback_days}d", interval=interval)
            if hist.empty:
                return []
            bars: list[dict] = []
            for ts, row in hist.iterrows():
                close = float(row["Close"])
                half_spread = close * spread_frac / 2
                bars.append(
                    {
                        "t": ts.isoformat(),
                        "o": float(row["Open"]),
                        "h": float(row["High"]),
                        "l": float(row["Low"]),
                        "c": close,
                        "v": float(row.get("Volume", 0) or 0),
                        "bid": close - half_spread,
                        "ask": close + half_spread,
                    }
                )
            return bars

        bars = await asyncio.to_thread(_fetch)
        logger.debug(f"[YFinance] {symbol} ({yf_sym}): {len(bars)} bars ({interval}, {lookback_days}d)")
        return bars

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_account(self) -> dict:
        """Return simulated paper account state."""
        equity = self._cash

        for sym, pos in list(self._positions.items()):
            if pos["qty"] <= 0:
                continue
            bars = await self.get_bars(sym, interval="1m", lookback_days=1)
            if bars:
                equity += pos["qty"] * bars[-1]["c"]

        self._peak_equity = max(self._peak_equity, equity)

        daily_pnl = equity - self._starting_capital
        daily_pnl_pct = daily_pnl / self._starting_capital if self._starting_capital else 0.0
        drawdown_pct = (
            (self._peak_equity - equity) / self._peak_equity
            if self._peak_equity > 0
            else 0.0
        )

        return {
            "cash": self._cash,
            "equity": equity,
            "buying_power": self._cash,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "drawdown_pct": max(0.0, drawdown_pct),
            "last_equity": self._starting_capital,
        }

    def get_all_positions(self) -> list[dict]:
        return [
            {
                "symbol": sym,
                "qty": pos["qty"],
                "market_value": 0.0,
                "unrealized_pl": 0.0,
            }
            for sym, pos in self._positions.items()
            if pos["qty"] > 0.0001
        ]

    # ------------------------------------------------------------------
    # Order execution (paper)
    # ------------------------------------------------------------------

    async def buy(self, symbol: str, qty: float, order_type: str = "market", **kwargs) -> dict:
        bars = await self.get_bars(symbol, interval="1m", lookback_days=1)
        if not bars:
            raise RuntimeError(f"[YFinance] No price data available for {symbol}")

        price = bars[-1]["ask"]
        cost = price * qty

        if cost > self._cash:
            qty = (self._cash * 0.99) / price
            cost = price * qty

        if qty <= 0:
            raise RuntimeError(f"[YFinance] Insufficient cash (${self._cash:.2f}) to buy {symbol}")

        self._cash -= cost
        if symbol in self._positions:
            old = self._positions[symbol]
            total_qty = old["qty"] + qty
            avg_price = (old["avg_price"] * old["qty"] + price * qty) / total_qty
            self._positions[symbol] = {"qty": total_qty, "avg_price": avg_price}
        else:
            self._positions[symbol] = {"qty": qty, "avg_price": price}

        logger.success(
            f"[YFinance Paper] BUY {qty:.4f} {symbol} @ {price:.4f} | cost=${cost:.2f} | cash=${self._cash:.2f}"
        )
        return {
            "id": f"paper-buy-{symbol}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            "status": "filled",
            "filled_avg_price": price,
            "filled_qty": qty,
            "symbol": symbol,
            "side": "buy",
        }

    async def sell(self, symbol: str, qty: float, order_type: str = "market", **kwargs) -> dict:
        current_qty = self._positions.get(symbol, {}).get("qty", 0.0)
        if current_qty < 0.0001:
            raise RuntimeError(f"[YFinance] No {symbol} position to sell")

        # Capture cost basis BEFORE modifying positions
        avg_cost = self._positions[symbol].get("avg_price", 0.0)

        bars = await self.get_bars(symbol, interval="1m", lookback_days=1)
        if not bars:
            raise RuntimeError(f"[YFinance] No price data available for {symbol}")

        price = bars[-1]["bid"]
        qty = min(qty, current_qty)
        proceeds = price * qty
        pnl = (price - avg_cost) * qty

        self._cash += proceeds
        remaining = current_qty - qty
        if remaining < 0.0001:
            self._positions.pop(symbol, None)
        else:
            self._positions[symbol]["qty"] = remaining

        logger.success(
            f"[YFinance Paper] SELL {qty:.4f} {symbol} @ {price:.4f} | "
            f"cost={avg_cost:.4f} | pnl=${pnl:+.2f} | cash=${self._cash:.2f}"
        )
        return {
            "id": f"paper-sell-{symbol}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            "status": "filled",
            "filled_avg_price": price,
            "filled_qty": qty,
            "avg_cost": avg_cost,   # cost basis for P&L calculation
            "pnl": pnl,
            "symbol": symbol,
            "side": "sell",
        }

    # ------------------------------------------------------------------
    # No-op stream methods (interface compatibility)
    # ------------------------------------------------------------------

    async def connect_market(self, symbols: list[str], **kwargs) -> None:
        logger.info(f"[YFinance] REST-based data — no stream needed for {symbols}")

    async def connect_user(self, **kwargs) -> None:
        pass

    async def disconnect(self) -> None:
        logger.info(f"[YFinance] Paper session closed | final cash=${self._cash:.2f} | positions={list(self._positions.keys())}")
