"""
SignalR User Hub client for ProjectX Gateway API.

Provides real-time account/order/position/trade updates.

Server events:
  GatewayUserAccount  - account update (id, name, balance, canTrade, simulated)
  GatewayUserOrder    - order update  (id, accountId, contractId, status, type, side, size, ...)
  GatewayUserPosition - position update (id, accountId, contractId, type, size, averagePrice, action)
  GatewayUserTrade    - trade fill    (id, accountId, contractId, price, profitAndLoss, fees, side, size)

Server methods to invoke:
  SubscribeAccounts()
  SubscribeOrders(accountId)
  SubscribePositions(accountId)
  SubscribeTrades(accountId)

action field on position/trade: 0=create, 1=update, 2=delete
OrderStatus: 0=None,1=Open,2=Filled,3=Cancelled,4=Expired,5=Rejected,6=Pending
OrderType:   1=Limit,2=Market,3=StopLimit,4=Stop,5=TrailingStop,6=JoinBid,7=JoinAsk
OrderSide:   0=Bid(Buy), 1=Ask(Sell)
PositionType: 1=Long, 2=Short
"""

import asyncio
from collections.abc import Callable

from loguru import logger
from signalrcore.hub_connection_builder import HubConnectionBuilder

from .auth import AuthSession

OnAccountCallback = Callable[[dict], None]
OnOrderCallback = Callable[[dict], None]
OnPositionCallback = Callable[[dict], None]
OnTradeCallback = Callable[[dict], None]


class UserHub:
    def __init__(
        self,
        auth: AuthSession,
        on_account: OnAccountCallback | None = None,
        on_order: OnOrderCallback | None = None,
        on_position: OnPositionCallback | None = None,
        on_trade: OnTradeCallback | None = None,
    ) -> None:
        self._auth = auth
        self._on_account_cb = on_account
        self._on_order_cb = on_order
        self._on_position_cb = on_position
        self._on_trade_cb = on_trade
        self._hub = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        """Build and start the SignalR connection. Must be called after login."""
        self._loop = asyncio.get_running_loop()
        self._hub = self._build_hub()

        self._hub.on_open(lambda: logger.success(f"[{self._auth.config.name}] UserHub connected"))
        self._hub.on_close(lambda err: logger.warning(f"[UserHub] Closed: {err}"))
        self._hub.on_error(lambda data: logger.error(f"[UserHub] Error: {data.error}"))

        self._hub.on("GatewayUserAccount", self._on_account)
        self._hub.on("GatewayUserOrder", self._on_order)
        self._hub.on("GatewayUserPosition", self._on_position)
        self._hub.on("GatewayUserTrade", self._on_trade)

        self._hub.start()
        logger.info(f"[{self._auth.config.name}] UserHub connecting...")

    async def subscribe(self, account_id: int) -> None:
        """Subscribe to all user events for the given account."""
        self._hub.send("SubscribeAccounts", [])
        self._hub.send("SubscribeOrders", [account_id])
        self._hub.send("SubscribePositions", [account_id])
        self._hub.send("SubscribeTrades", [account_id])
        logger.info(f"[UserHub] Subscribed to all events for account {account_id}")

    async def disconnect(self) -> None:
        if self._hub:
            self._hub.stop()
            logger.info("[UserHub] Disconnected")

    # --- SignalR callbacks (run in SignalR thread) ---

    def _on_account(self, args: list) -> None:
        data: dict = args[0] if args else {}
        logger.debug(f"[UserHub] Account update: id={data.get('id')} balance={data.get('balance')}")
        self._fire(self._on_account_cb, data)

    def _on_order(self, args: list) -> None:
        data: dict = args[0] if args else {}
        logger.info(
            f"[UserHub] Order update: id={data.get('id')} status={data.get('status')} "
            f"side={data.get('side')} size={data.get('size')}"
        )
        self._fire(self._on_order_cb, data)

    def _on_position(self, args: list) -> None:
        data: dict = args[0] if args else {}
        logger.info(
            f"[UserHub] Position update: contractId={data.get('contractId')} "
            f"type={data.get('type')} size={data.get('size')} avg={data.get('averagePrice')}"
        )
        self._fire(self._on_position_cb, data)

    def _on_trade(self, args: list) -> None:
        data: dict = args[0] if args else {}
        logger.info(
            f"[UserHub] Trade fill: contractId={data.get('contractId')} "
            f"price={data.get('price')} pnl={data.get('profitAndLoss')}"
        )
        self._fire(self._on_trade_cb, data)

    # --- Helpers ---

    def _fire(self, cb: Callable | None, data: dict) -> None:
        if cb is None or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._call(cb, data), self._loop)

    def _build_hub(self):
        return (
            HubConnectionBuilder()
            .with_url(
                self._auth.config.user_hub_url,
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
    async def _call(cb: Callable, data: dict) -> None:
        if asyncio.iscoroutinefunction(cb):
            await cb(data)
        else:
            cb(data)
