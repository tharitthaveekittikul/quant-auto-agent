"""
Real-time market data stream via Alpaca WebSocket (alpaca-py StockDataStream).

Stream URLs:
  IEX  (free, 30 symbol limit): wss://stream.data.alpaca.markets/v2/iex
  SIP  (paid, unlimited):        wss://stream.data.alpaca.markets/v2/sip
  Test (always on):              wss://stream.data.alpaca.markets/v2/test  (symbol: FAKEPACA)

Connection flow (raw protocol):
  1. Server sends: [{"T": "success", "msg": "connected"}]
  2. Client sends: {"action": "auth", "key": "...", "secret": "..."}
  3. Server sends: [{"T": "success", "msg": "authenticated"}]
  4. Client sends: {"action": "subscribe", "quotes": ["AAPL"], "trades": ["AAPL"]}

Quote fields: S(symbol), bp(bid), ap(ask), bs(bid size), as(ask size), t(timestamp)
Trade fields: S(symbol), p(price), s(size), t(timestamp)
"""

import asyncio
import threading
from collections.abc import Callable

from alpaca.data.live import StockDataStream
from loguru import logger

from shared.database import send_to_questdb

from .config import AlpacaConfig


class MarketStream:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        config: AlpacaConfig,
        on_quote: Callable[[str, dict], None] | None = None,
        on_trade: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._config = config
        self._on_quote_cb = on_quote
        self._on_trade_cb = on_trade
        self._main_loop: asyncio.AbstractEventLoop | None = None

        self._stream = StockDataStream(
            api_key,
            secret_key,
            feed=config.data_feed,
        )

    async def connect(self, symbols: list[str]) -> None:
        """Subscribe to quotes (and trades) for the given symbols and start streaming."""
        self._main_loop = asyncio.get_running_loop()

        self._stream.subscribe_quotes(self._quote_handler, *symbols)
        self._stream.subscribe_trades(self._trade_handler, *symbols)

        # StockDataStream.run() blocks (starts its own asyncio event loop internally)
        thread = threading.Thread(target=self._stream.run, daemon=True)
        thread.start()
        logger.info(
            f"[{self._config.name}] MarketStream starting for {symbols} "
            f"(feed={self._config.data_feed})"
        )

    async def subscribe(self, symbols: list[str]) -> None:
        """Dynamically add more symbols after initial connection."""
        self._stream.subscribe_quotes(self._quote_handler, *symbols)
        self._stream.subscribe_trades(self._trade_handler, *symbols)
        logger.info(f"[{self._config.name}] MarketStream added symbols: {symbols}")

    async def disconnect(self) -> None:
        try:
            await self._stream.close()
        except Exception as e:
            logger.warning(f"[MarketStream] Close error (safe to ignore): {e}")
        logger.info(f"[{self._config.name}] MarketStream disconnected")

    # --- Alpaca stream handlers (run inside alpaca's internal event loop / thread) ---

    async def _quote_handler(self, data) -> None:
        """
        data fields: symbol, bid_price, ask_price, bid_size, ask_size, timestamp
        """
        symbol: str = data.symbol
        bid: float = float(data.bid_price or 0.0)
        ask: float = float(data.ask_price or 0.0)

        # Persist to QuestDB immediately (sync call, safe from any thread)
        send_to_questdb(symbol=symbol, bid=bid, ask=ask, last=0.0, volume=0.0)

        if self._on_quote_cb and self._main_loop:
            payload = {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "bid_size": float(data.bid_size or 0),
                "ask_size": float(data.ask_size or 0),
                "timestamp": str(data.timestamp),
            }
            asyncio.run_coroutine_threadsafe(
                self._dispatch(self._on_quote_cb, symbol, payload),
                self._main_loop,
            )

    async def _trade_handler(self, data) -> None:
        """
        data fields: symbol, price, size, timestamp
        """
        symbol: str = data.symbol
        price: float = float(data.price or 0.0)
        size: float = float(data.size or 0.0)

        # Persist last price + volume to QuestDB
        send_to_questdb(symbol=symbol, bid=0.0, ask=0.0, last=price, volume=size)

        if self._on_trade_cb and self._main_loop:
            payload = {
                "symbol": symbol,
                "price": price,
                "size": size,
                "timestamp": str(data.timestamp),
            }
            asyncio.run_coroutine_threadsafe(
                self._dispatch(self._on_trade_cb, symbol, payload),
                self._main_loop,
            )

    @staticmethod
    async def _dispatch(cb: Callable, *args) -> None:
        if asyncio.iscoroutinefunction(cb):
            await cb(*args)
        else:
            cb(*args)
