"""
Real-time account/order update stream via Alpaca TradingStream.

Stream URLs:
  Paper: wss://paper-api.alpaca.markets/stream
  Live:  wss://api.alpaca.markets/stream

Subscription: "trade_updates" channel

Order event types: new, fill, partial_fill, canceled, expired, replaced,
                   done_for_day, rejected, pending_new, pending_cancel, etc.

Fill events include: timestamp, price, qty, position_qty
"""

import asyncio
import threading
from collections.abc import Callable

from alpaca.trading.stream import TradingStream
from loguru import logger

from .config import AlpacaConfig

OnOrderCallback = Callable[[dict], None]
OnPositionCallback = Callable[[dict], None]


class TradeStream:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        config: AlpacaConfig,
        on_order: OnOrderCallback | None = None,
    ) -> None:
        self._config = config
        self._on_order_cb = on_order
        self._main_loop: asyncio.AbstractEventLoop | None = None

        self._stream = TradingStream(api_key, secret_key, paper=config.paper)
        self._stream.subscribe_trade_updates(self._order_handler)

    async def connect(self) -> None:
        """Start the trade update stream in a background thread."""
        self._main_loop = asyncio.get_running_loop()

        thread = threading.Thread(target=self._stream.run, daemon=True)
        thread.start()
        logger.info(f"[{self._config.name}] TradeStream connected (trade_updates)")

    async def disconnect(self) -> None:
        try:
            await self._stream.close()
        except Exception as e:
            logger.warning(f"[TradeStream] Close error (safe to ignore): {e}")
        logger.info(f"[{self._config.name}] TradeStream disconnected")

    # --- Handler (runs inside alpaca's internal event loop / thread) ---

    async def _order_handler(self, data) -> None:
        """
        data.event: "fill", "partial_fill", "new", "canceled", etc.
        data.order: Order object with all order fields
        """
        event: str = data.event
        order = data.order

        order_dict = order.model_dump() if hasattr(order, "model_dump") else {}
        payload = {
            "event": event,
            "order": order_dict,
        }

        # Attach fill details when available
        if event in ("fill", "partial_fill"):
            payload["filled_at"] = str(getattr(data, "timestamp", ""))
            payload["filled_price"] = float(getattr(data, "price", 0.0) or 0.0)
            payload["filled_qty"] = float(getattr(data, "qty", 0.0) or 0.0)
            payload["position_qty"] = float(getattr(data, "position_qty", 0.0) or 0.0)

        logger.info(
            f"[{self._config.name}] Order event: {event} "
            f"symbol={order_dict.get('symbol')} status={order_dict.get('status')}"
        )

        if self._on_order_cb and self._main_loop:
            asyncio.run_coroutine_threadsafe(
                self._dispatch(self._on_order_cb, payload),
                self._main_loop,
            )

    @staticmethod
    async def _dispatch(cb: Callable, data: dict) -> None:
        if asyncio.iscoroutinefunction(cb):
            await cb(data)
        else:
            cb(data)
