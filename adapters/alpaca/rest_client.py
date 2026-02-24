"""
REST client for Alpaca Trading API.

Wraps alpaca-py's synchronous TradingClient with async helpers using asyncio.to_thread().

Paper base URL: https://paper-api.alpaca.markets
Live base URL:  https://api.alpaca.markets

Order types: market, limit, stop, stop_limit, trailing_stop
Order sides:  buy, sell
TimeInForce:  day, gtc, ioc, fok, opg, cls
"""

import asyncio

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopLimitOrderRequest,
    StopOrderRequest,
)
from loguru import logger

from .config import AlpacaConfig


class RestClient:
    def __init__(self, api_key: str, secret_key: str, config: AlpacaConfig) -> None:
        self._config = config
        self._client = TradingClient(api_key, secret_key, paper=config.paper)

    # --- Account ---

    async def get_account(self) -> dict:
        """Return account info: cash, equity, buying_power, etc."""
        account = await asyncio.to_thread(self._client.get_account)
        return account.model_dump()

    # --- Positions ---

    async def get_all_positions(self) -> list[dict]:
        positions = await asyncio.to_thread(self._client.get_all_positions)
        return [p.model_dump() for p in positions]

    async def close_position(self, symbol: str) -> dict:
        result = await asyncio.to_thread(self._client.close_position, symbol)
        return result.model_dump()

    async def close_all_positions(self, cancel_orders: bool = True) -> list[dict]:
        results = await asyncio.to_thread(
            self._client.close_all_positions, cancel_orders=cancel_orders
        )
        return [r.model_dump() for r in results]

    # --- Orders ---

    async def place_market_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        time_in_force: str = "day",
    ) -> dict:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide(side),
            time_in_force=TimeInForce(time_in_force),
        )
        order = await asyncio.to_thread(self._client.submit_order, req)
        logger.info(f"[{self._config.name}] Market order placed: {side} {qty} {symbol} → id={order.id}")
        return order.model_dump()

    async def place_limit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        limit_price: float,
        time_in_force: str = "day",
    ) -> dict:
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide(side),
            limit_price=limit_price,
            time_in_force=TimeInForce(time_in_force),
        )
        order = await asyncio.to_thread(self._client.submit_order, req)
        logger.info(f"[{self._config.name}] Limit order placed: {side} {qty} {symbol} @ {limit_price}")
        return order.model_dump()

    async def place_stop_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_price: float,
        time_in_force: str = "day",
    ) -> dict:
        req = StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide(side),
            stop_price=stop_price,
            time_in_force=TimeInForce(time_in_force),
        )
        order = await asyncio.to_thread(self._client.submit_order, req)
        return order.model_dump()

    async def place_stop_limit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_price: float,
        limit_price: float,
        time_in_force: str = "day",
    ) -> dict:
        req = StopLimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide(side),
            stop_price=stop_price,
            limit_price=limit_price,
            time_in_force=TimeInForce(time_in_force),
        )
        order = await asyncio.to_thread(self._client.submit_order, req)
        return order.model_dump()

    async def cancel_order(self, order_id: str) -> None:
        await asyncio.to_thread(self._client.cancel_order_by_id, order_id)
        logger.info(f"[{self._config.name}] Order {order_id} cancelled")

    async def cancel_all_orders(self) -> list[dict]:
        results = await asyncio.to_thread(self._client.cancel_orders)
        return [r.model_dump() for r in results]

    async def get_orders(self, status: str = "open") -> list[dict]:
        req = GetOrdersRequest(status=QueryOrderStatus(status))
        orders = await asyncio.to_thread(self._client.get_orders, filter=req)
        return [o.model_dump() for o in orders]

    async def get_order(self, order_id: str) -> dict:
        order = await asyncio.to_thread(self._client.get_order_by_id, order_id)
        return order.model_dump()

    # --- Assets ---

    async def get_asset(self, symbol: str) -> dict:
        asset = await asyncio.to_thread(self._client.get_asset, symbol)
        return asset.model_dump()
