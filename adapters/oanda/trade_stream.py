"""
Real-time transaction stream via OANDA chunked HTTP transactions stream.

Stream endpoint:
  GET /v3/accounts/{id}/transactions/stream

Each newline-delimited JSON chunk is one of:
  {"type": "TRANSACTION", "transaction": {...}}   — actual transaction
  {"type": "HEARTBEAT", "lastTransactionID": "...", "time": "..."}

Relevant transaction types handled:
  ORDER_FILL, MARKET_ORDER, LIMIT_ORDER, ORDER_CANCEL

Fires on_order callback with a normalized dict payload.
Runs as a background asyncio.Task with exponential backoff reconnect.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
from loguru import logger

from .config import OandaConfig

_WATCHED_TYPES = frozenset(
    {"ORDER_FILL", "MARKET_ORDER", "LIMIT_ORDER", "ORDER_CANCEL"}
)
_MAX_BACKOFF = 60.0


class TradeStream:
    def __init__(
        self,
        api_key: str,
        config: OandaConfig,
        on_order: Callable | None = None,
    ) -> None:
        self._api_key = api_key
        self._config = config
        self._on_order_cb = on_order
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def connect(self, account_id: str) -> None:
        """Start the transaction stream in a background task."""
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._stream_loop(account_id),
            name=f"oanda-trade-stream-{account_id}",
        )
        logger.info(f"[{self._config.name}] TradeStream starting")

    async def disconnect(self) -> None:
        """Signal the streaming task to stop."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info(f"[{self._config.name}] TradeStream disconnected")

    # --- Internal streaming loop ---

    async def _stream_loop(self, account_id: str) -> None:
        backoff = 1.0
        url = (
            f"{self._config.stream_url}/v3/accounts/{account_id}/transactions/stream"
        )
        headers = {"Authorization": f"Bearer {self._api_key}"}

        while not self._stop_event.is_set():
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", url, headers=headers) as resp:
                        resp.raise_for_status()
                        backoff = 1.0
                        logger.info(
                            f"[{self._config.name}] Transaction stream connected"
                        )
                        async for line in resp.aiter_lines():
                            if self._stop_event.is_set():
                                return
                            if not line:
                                continue
                            await self._handle_message(line)

            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self._stop_event.is_set():
                    return
                logger.warning(
                    f"[{self._config.name}] TradeStream connection lost: {exc} "
                    f"— reconnecting in {backoff}s"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    async def _handle_message(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        if msg_type == "HEARTBEAT":
            logger.debug(
                f"[{self._config.name}] TradeStream heartbeat: "
                f"lastTransactionID={msg.get('lastTransactionID')}"
            )
            return

        if msg_type != "TRANSACTION":
            return

        txn = msg.get("transaction", {})
        txn_type = txn.get("type", "")

        if txn_type not in _WATCHED_TYPES:
            return

        payload = {
            "type": txn_type,
            "id": txn.get("id"),
            "account_id": txn.get("accountID"),
            "instrument": txn.get("instrument"),
            "units": txn.get("units"),
            "price": txn.get("price"),
            "time": txn.get("time"),
            "order_id": txn.get("orderID"),
            "reason": txn.get("reason"),
        }

        # Extra fill details
        if txn_type == "ORDER_FILL":
            payload["fill_price"] = txn.get("price")
            payload["realized_pl"] = txn.get("pl")
            payload["financing"] = txn.get("financing")

        logger.info(
            f"[{self._config.name}] Transaction: {txn_type} "
            f"instrument={payload.get('instrument')} units={payload.get('units')}"
        )

        if self._on_order_cb:
            await _dispatch(self._on_order_cb, payload)


async def _dispatch(cb: Callable, *args) -> None:
    if asyncio.iscoroutinefunction(cb):
        await cb(*args)
    else:
        cb(*args)
