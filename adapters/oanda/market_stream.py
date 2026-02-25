"""
Real-time market data stream via OANDA chunked HTTP pricing stream.

Stream endpoint:
  GET /v3/accounts/{id}/pricing/stream?instruments=EUR_USD,XAU_USD

Each newline-delimited JSON chunk is one of:
  {"type": "PRICE", "instrument": "XAU_USD", "bids": [...], "asks": [...], ...}
  {"type": "HEARTBEAT", "time": "..."}

No WebSocket/SignalR — httpx handles chunked HTTP natively with async streaming.
Runs as a background asyncio.Task (no threading needed).
Auto-reconnects on connection drop with exponential backoff (max 60s).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
from loguru import logger

from shared.database import send_to_questdb

from .config import OandaConfig

_MAX_BACKOFF = 60.0


class MarketStream:
    def __init__(
        self,
        api_key: str,
        config: OandaConfig,
        on_quote: Callable | None = None,
    ) -> None:
        self._api_key = api_key
        self._config = config
        self._on_quote_cb = on_quote
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def connect(self, account_id: str, instruments: list[str]) -> None:
        """Start streaming prices for the given instruments in a background task."""
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._stream_loop(account_id, instruments),
            name=f"oanda-market-stream-{account_id}",
        )
        logger.info(
            f"[{self._config.name}] MarketStream starting for {instruments}"
        )

    async def disconnect(self) -> None:
        """Signal the streaming task to stop and await its completion."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info(f"[{self._config.name}] MarketStream disconnected")

    # --- Internal streaming loop ---

    async def _stream_loop(self, account_id: str, instruments: list[str]) -> None:
        backoff = 1.0
        instruments_param = ",".join(instruments)
        url = (
            f"{self._config.stream_url}/v3/accounts/{account_id}"
            f"/pricing/stream?instruments={instruments_param}"
        )
        headers = {"Authorization": f"Bearer {self._api_key}"}

        while not self._stop_event.is_set():
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", url, headers=headers) as resp:
                        resp.raise_for_status()
                        backoff = 1.0  # reset on successful connection
                        logger.info(
                            f"[{self._config.name}] Pricing stream connected"
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
                    f"[{self._config.name}] MarketStream connection lost: {exc} "
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
            logger.debug(f"[{self._config.name}] Heartbeat: {msg.get('time')}")
            return

        if msg_type != "PRICE":
            return

        instrument: str = msg.get("instrument", "")
        bids = msg.get("bids", [])
        asks = msg.get("asks", [])

        if not bids or not asks:
            return

        bid = float(bids[0].get("price", 0))
        ask = float(asks[0].get("price", 0))
        mid = (bid + ask) / 2.0

        # Persist to QuestDB
        send_to_questdb(symbol=instrument, bid=bid, ask=ask, last=mid, volume=0.0)

        if self._on_quote_cb:
            payload = {"symbol": instrument, "bid": bid, "ask": ask, "mid": mid}
            await _dispatch(self._on_quote_cb, payload)


async def _dispatch(cb: Callable, *args) -> None:
    if asyncio.iscoroutinefunction(cb):
        await cb(*args)
    else:
        cb(*args)
