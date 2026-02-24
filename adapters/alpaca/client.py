"""
High-level Alpaca client combining REST, MarketStream, and TradeStream.

Usage:
    # From environment variables (ALPACA_ENV, ALPACA_API_KEY, ALPACA_SECRET_KEY)
    client = await AlpacaClient.from_env()

    # Or explicitly
    client = AlpacaClient(env=Environment.PAPER)
    await client.login(api_key="...", secret_key="...")

    # Fetch account info (paper starts with $100,000 simulated cash)
    account = await client.rest.get_account()

    # Stream real-time quotes → auto-saved to QuestDB
    await client.connect_market(["AAPL", "SPY", "QQQ"])

    # Stream order/fill events
    await client.connect_user(on_order=my_order_handler)

    # Place orders
    await client.rest.place_market_order("SPY", qty=1, side="buy")
    await client.rest.place_limit_order("AAPL", qty=10, side="sell", limit_price=200.0)

    # Graceful shutdown
    await client.disconnect()

Notes:
    - Paper trading is fully isolated from live accounts — separate credentials required.
    - Free IEX feed is limited to 30 symbols at a time over WebSocket.
    - Use Environment.LIVE with "sip" feed for production (requires paid subscription).
    - TradingStream / MarketStream run in background daemon threads.
"""

import os
from collections.abc import Callable

from loguru import logger

from .config import ALPACA_CONFIGS, Environment
from .market_stream import MarketStream
from .rest_client import RestClient
from .trade_stream import TradeStream


class AlpacaClient:
    """Unified async client for Alpaca Markets (paper or live)."""

    def __init__(self, env: Environment = Environment.PAPER) -> None:
        self._env = env
        self._config = ALPACA_CONFIGS[env]
        self._api_key: str = ""
        self._secret_key: str = ""
        self.rest: RestClient | None = None
        self.market: MarketStream | None = None
        self.user: TradeStream | None = None

    async def login(self, api_key: str, secret_key: str) -> "AlpacaClient":
        """Initialize the REST client with credentials."""
        self._api_key = api_key
        self._secret_key = secret_key
        self.rest = RestClient(api_key, secret_key, self._config)
        logger.success(f"[{self._config.name}] Client ready")
        return self

    @classmethod
    async def from_env(cls) -> "AlpacaClient":
        """
        Create and initialize a client using environment variables:
          ALPACA_ENV        - "paper" or "live" (default: "paper")
          ALPACA_API_KEY    - Alpaca API key ID
          ALPACA_SECRET_KEY - Alpaca secret key
        """
        env_str = os.getenv("ALPACA_ENV", "paper").lower()
        env = Environment.LIVE if env_str == "live" else Environment.PAPER

        api_key = os.environ["ALPACA_API_KEY"]
        secret_key = os.environ["ALPACA_SECRET_KEY"]

        client = cls(env)
        await client.login(api_key, secret_key)
        logger.info(f"AlpacaClient ready (env={env.value})")
        return client

    # --- Real-time ---

    async def connect_market(
        self,
        symbols: list[str],
        *,
        on_quote: Callable | None = None,
        on_trade: Callable | None = None,
    ) -> None:
        """
        Start the market data stream and subscribe to quotes + trades for symbols.
        Data is automatically persisted to QuestDB on every tick.
        Free IEX feed: max 30 symbols simultaneously.
        """
        self.market = MarketStream(
            self._api_key,
            self._secret_key,
            self._config,
            on_quote=on_quote,
            on_trade=on_trade,
        )
        await self.market.connect(symbols)

    async def connect_user(self, *, on_order: Callable | None = None) -> None:
        """Start the trade update stream to receive order fill events."""
        self.user = TradeStream(
            self._api_key,
            self._secret_key,
            self._config,
            on_order=on_order,
        )
        await self.user.connect()

    # --- Convenience order methods (delegates to rest) ---

    async def buy(self, symbol: str, qty: float, order_type: str = "market", **kwargs) -> dict:
        if order_type == "market":
            return await self.rest.place_market_order(symbol, qty, "buy", **kwargs)
        elif order_type == "limit":
            return await self.rest.place_limit_order(symbol, qty, "buy", **kwargs)
        raise ValueError(f"Unsupported order_type: {order_type!r}")

    async def sell(self, symbol: str, qty: float, order_type: str = "market", **kwargs) -> dict:
        if order_type == "market":
            return await self.rest.place_market_order(symbol, qty, "sell", **kwargs)
        elif order_type == "limit":
            return await self.rest.place_limit_order(symbol, qty, "sell", **kwargs)
        raise ValueError(f"Unsupported order_type: {order_type!r}")

    # --- Shutdown ---

    async def disconnect(self) -> None:
        """Gracefully stop all streams."""
        if self.market:
            await self.market.disconnect()
        if self.user:
            await self.user.disconnect()
        logger.info(f"[{self._config.name}] Client disconnected")
