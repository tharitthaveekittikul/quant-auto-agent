"""
High-level OANDA client combining REST, MarketStream, and TradeStream.

Usage:
    # From environment variables
    client = await OandaClient.from_env()

    # Fetch account info
    account = await client.rest.get_account(client.account_id)

    # Stream real-time prices → auto-saved to QuestDB
    await client.connect_market(["XAU_USD", "EUR_USD"])

    # Stream order/fill events
    await client.connect_user(on_order=my_order_handler)

    # Place orders (positive units = buy, negative = sell)
    await client.buy("XAU_USD", qty=1)
    await client.sell("EUR_USD", qty=10000)

    # Graceful shutdown
    await client.disconnect()

Environment variables:
    OANDA_ENV        - "practice" or "live" (default: "practice")
    OANDA_API_KEY    - Personal Access Token from OANDA
    OANDA_ACCOUNT_ID - optional; auto-fetched from /v3/accounts if absent
"""

from __future__ import annotations

import os
from collections.abc import Callable

from loguru import logger

from .config import OANDA_CONFIGS, Environment
from .market_stream import MarketStream
from .rest_client import RestClient
from .trade_stream import TradeStream


class OandaClient:
    """Unified async client for OANDA v20 (practice or live)."""

    def __init__(self, env: Environment = Environment.PRACTICE) -> None:
        self._env = env
        self._config = OANDA_CONFIGS[env]
        self._api_key: str = ""
        self.account_id: str = ""
        self.rest: RestClient | None = None
        self.market: MarketStream | None = None
        self.user: TradeStream | None = None

    async def login(self, api_key: str, account_id: str = "") -> "OandaClient":
        """Initialise the REST client and resolve account_id."""
        self._api_key = api_key
        self.rest = RestClient(api_key, self._config)

        if account_id:
            self.account_id = account_id
        else:
            accounts = await self.rest.get_accounts()
            if not accounts:
                raise RuntimeError("No OANDA accounts found for this API key")
            self.account_id = accounts[0]["id"]
            logger.info(
                f"[{self._config.name}] Auto-selected account_id={self.account_id}"
            )

        logger.success(f"[{self._config.name}] Client ready (account={self.account_id})")
        return self

    @classmethod
    async def from_env(cls) -> "OandaClient":
        """
        Create and initialise a client from environment variables:
          OANDA_ENV        - "practice" or "live" (default: "practice")
          OANDA_API_KEY    - Personal Access Token
          OANDA_ACCOUNT_ID - optional; auto-fetched if absent
        """
        env_str = os.getenv("OANDA_ENV", "practice").lower()
        env = Environment.LIVE if env_str == "live" else Environment.PRACTICE

        api_key = os.getenv("OANDA_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OANDA_API_KEY is not set. Add your Personal Access Token to .env")
        account_id = os.getenv("OANDA_ACCOUNT_ID", "").strip()

        client = cls(env)
        await client.login(api_key, account_id)
        logger.info(f"OandaClient ready (env={env.value})")
        return client

    # --- Real-time ---

    async def connect_market(
        self,
        instruments: list[str],
        *,
        on_quote: Callable | None = None,
    ) -> None:
        """Start streaming prices for the given instruments into QuestDB."""
        self.market = MarketStream(self._api_key, self._config, on_quote=on_quote)
        await self.market.connect(self.account_id, instruments)

    async def connect_user(self, *, on_order: Callable | None = None) -> None:
        """Start the transaction stream to receive order fill events."""
        self.user = TradeStream(self._api_key, self._config, on_order=on_order)
        await self.user.connect(self.account_id)

    # --- Convenience order methods ---

    async def buy(self, symbol: str, qty: float, order_type: str = "market", **kwargs) -> dict:
        """Buy `qty` units of `symbol`. Delegates to rest client."""
        units = str(int(qty)) if qty == int(qty) else str(qty)
        if order_type == "market":
            return await self.rest.place_market_order(self.account_id, symbol, units)
        elif order_type == "limit":
            price = str(kwargs["limit_price"])
            return await self.rest.place_limit_order(self.account_id, symbol, units, price)
        raise ValueError(f"Unsupported order_type: {order_type!r}")

    async def sell(self, symbol: str, qty: float, order_type: str = "market", **kwargs) -> dict:
        """Sell `qty` units of `symbol` (units become negative)."""
        units = f"-{int(qty)}" if qty == int(qty) else f"-{qty}"
        if order_type == "market":
            return await self.rest.place_market_order(self.account_id, symbol, units)
        elif order_type == "limit":
            price = str(kwargs["limit_price"])
            return await self.rest.place_limit_order(self.account_id, symbol, units, price)
        raise ValueError(f"Unsupported order_type: {order_type!r}")

    # --- Portfolio snapshot helper (mirrors yfinance/alpaca interface used by main.py) ---

    async def get_account(self) -> dict:
        """Return normalized portfolio dict (for AccountState snapshot in main.py)."""
        return await self.rest.get_portfolio(self.account_id)

    # --- Shutdown ---

    async def disconnect(self) -> None:
        """Gracefully stop all streams and close the HTTP client."""
        if self.market:
            await self.market.disconnect()
        if self.user:
            await self.user.disconnect()
        if self.rest:
            await self.rest.close()
        logger.info(f"[{self._config.name}] Client disconnected")
