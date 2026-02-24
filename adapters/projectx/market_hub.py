"""
SignalR Market Hub client for ProjectX Gateway API.

Provides real-time market data via SignalR WebSocket connection.

Server events:
  GatewayQuote  - quote update (bestBid, bestAsk, lastPrice, volume, ...)
  GatewayTrade  - trade print (price, volume, type)
  GatewayDepth  - depth-of-market update

Server methods to invoke:
  SubscribeContractQuotes(contractId)
  SubscribeContractTrades(contractId)
  SubscribeContractMarketDepth(contractId)
"""

import asyncio
from collections.abc import Callable

from loguru import logger
from signalrcore.hub_connection_builder import HubConnectionBuilder

from shared.database import send_to_questdb

from .auth import AuthSession


class MarketHub:
    def __init__(
        self,
        auth: AuthSession,
        on_quote: Callable[[str, dict], None] | None = None,
        on_trade: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._auth = auth
        self._on_quote_cb = on_quote
        self._on_trade_cb = on_trade
        self._hub = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected = False

    async def connect(self) -> None:
        """Build and start the SignalR connection. Must be called after login."""
        self._loop = asyncio.get_running_loop()
        self._hub = self._build_hub()

        self._hub.on_open(self._on_open)
        self._hub.on_close(lambda err: logger.warning(f"[MarketHub] Closed: {err}"))
        self._hub.on_error(lambda data: logger.error(f"[MarketHub] Error: {data.error}"))

        self._hub.on("GatewayQuote", self._on_quote)
        self._hub.on("GatewayTrade", self._on_trade)
        self._hub.on("GatewayDepth", self._on_depth)

        # start() spawns a background thread; it returns quickly
        self._hub.start()
        logger.info(f"[{self._auth.config.name}] MarketHub connecting...")

    async def subscribe_quotes(self, contract_id: str) -> None:
        self._hub.send("SubscribeContractQuotes", [contract_id])
        logger.info(f"[MarketHub] Subscribed to quotes for {contract_id!r}")

    async def subscribe_trades(self, contract_id: str) -> None:
        self._hub.send("SubscribeContractTrades", [contract_id])
        logger.info(f"[MarketHub] Subscribed to trades for {contract_id!r}")

    async def subscribe_depth(self, contract_id: str) -> None:
        self._hub.send("SubscribeContractMarketDepth", [contract_id])
        logger.info(f"[MarketHub] Subscribed to depth for {contract_id!r}")

    async def disconnect(self) -> None:
        if self._hub:
            self._hub.stop()
            self._connected = False
            logger.info("[MarketHub] Disconnected")

    # --- SignalR callbacks (run in SignalR thread) ---

    def _on_open(self) -> None:
        self._connected = True
        logger.success(f"[{self._auth.config.name}] MarketHub connected")

    def _on_quote(self, args: list) -> None:
        """
        args[0] = contractId (str)
        args[1] = quote dict {symbol, lastPrice, bestBid, bestAsk, volume, ...}
        """
        contract_id: str = args[0] if args else ""
        data: dict = args[1] if len(args) > 1 else {}

        # Persist to QuestDB immediately (synchronous, safe to call from thread)
        send_to_questdb(
            symbol=data.get("symbol", contract_id),
            bid=data.get("bestBid", 0.0),
            ask=data.get("bestAsk", 0.0),
            last=data.get("lastPrice", 0.0),
            volume=data.get("volume", 0.0),
        )

        if self._on_quote_cb and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._dispatch_async(self._on_quote_cb, contract_id, data),
                self._loop,
            )

    def _on_trade(self, args: list) -> None:
        """
        args[0] = contractId (str)
        args[1] = trade dict {symbolId, price, timestamp, type, volume}
        """
        contract_id: str = args[0] if args else ""
        data: dict = args[1] if len(args) > 1 else {}
        logger.debug(f"[MarketHub] Trade {contract_id}: price={data.get('price')} vol={data.get('volume')}")

        if self._on_trade_cb and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._dispatch_async(self._on_trade_cb, contract_id, data),
                self._loop,
            )

    def _on_depth(self, args: list) -> None:
        # DOM updates — implement as needed
        pass

    # --- Helpers ---

    def _build_hub(self):
        return (
            HubConnectionBuilder()
            .with_url(
                self._auth.config.market_hub_url,
                options={
                    "access_token_factory": lambda: self._auth.token,
                    "skip_negotiation": True,
                },
            )
            .with_automatic_reconnect(
                {
                    "type": "raw",
                    "keep_alive_interval": 10,
                    "reconnect_interval": 5,
                    "max_attempts": 999,
                }
            )
            .build()
        )

    @staticmethod
    async def _dispatch_async(cb: Callable, *args) -> None:
        if asyncio.iscoroutinefunction(cb):
            await cb(*args)
        else:
            cb(*args)
