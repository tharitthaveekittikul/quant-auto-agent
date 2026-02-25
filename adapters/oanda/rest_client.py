"""
REST client for OANDA v20 API.

Auth: Bearer token (Personal Access Token) — no login/refresh flow.
Units convention: positive = buy, negative = sell (e.g. "100" or "-100").
All price/units fields in request bodies are strings per OANDA spec.

Key endpoints:
  GET  /v3/accounts
  GET  /v3/accounts/{id}
  GET  /v3/accounts/{id}/openPositions
  GET  /v3/instruments/{inst}/candles
  POST /v3/accounts/{id}/orders
  PUT  /v3/accounts/{id}/orders/{id}/cancel
  GET  /v3/accounts/{id}/pendingOrders
  PUT  /v3/accounts/{id}/positions/{inst}/close
"""

from __future__ import annotations

import httpx
from loguru import logger

from .config import OandaConfig


class RestClient:
    def __init__(self, api_key: str, config: OandaConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.rest_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # --- Accounts ---

    async def get_accounts(self) -> list[dict]:
        resp = await self._client.get("/v3/accounts")
        resp.raise_for_status()
        return resp.json().get("accounts", [])

    async def get_account(self, account_id: str) -> dict:
        resp = await self._client.get(f"/v3/accounts/{account_id}")
        resp.raise_for_status()
        return resp.json().get("account", {})

    # --- Positions ---

    async def get_open_positions(self, account_id: str) -> list[dict]:
        resp = await self._client.get(f"/v3/accounts/{account_id}/openPositions")
        resp.raise_for_status()
        return resp.json().get("positions", [])

    async def close_position(self, account_id: str, instrument: str) -> dict:
        resp = await self._client.put(
            f"/v3/accounts/{account_id}/positions/{instrument}/close",
            json={"longUnits": "ALL", "shortUnits": "ALL"},
        )
        resp.raise_for_status()
        return resp.json()

    # --- Candles ---

    async def get_candles(
        self,
        instrument: str,
        granularity: str = "M5",
        count: int = 100,
    ) -> list[dict]:
        """
        Returns candle dicts with keys: time, mid.{o,h,l,c}, volume.
        granularity examples: M1, M5, M15, H1, H4, D
        """
        resp = await self._client.get(
            f"/v3/instruments/{instrument}/candles",
            params={"granularity": granularity, "count": count, "price": "M"},
        )
        resp.raise_for_status()
        return resp.json().get("candles", [])

    # --- Orders ---

    async def place_market_order(
        self,
        account_id: str,
        instrument: str,
        units: str,
    ) -> dict:
        """
        Place a market order.
        units: positive string = buy, negative string = sell (e.g. "100" or "-100")
        """
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": units,
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        resp = await self._client.post(f"/v3/accounts/{account_id}/orders", json=body)
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            f"[{self._config.name}] Market order placed: {units} {instrument}"
        )
        return data

    async def place_limit_order(
        self,
        account_id: str,
        instrument: str,
        units: str,
        price: str,
    ) -> dict:
        """
        Place a limit order.
        units: positive = buy, negative = sell.
        price: limit price as string.
        """
        body = {
            "order": {
                "type": "LIMIT",
                "instrument": instrument,
                "units": units,
                "price": price,
                "timeInForce": "GTC",
                "positionFill": "DEFAULT",
            }
        }
        resp = await self._client.post(f"/v3/accounts/{account_id}/orders", json=body)
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            f"[{self._config.name}] Limit order placed: {units} {instrument} @ {price}"
        )
        return data

    async def cancel_order(self, account_id: str, order_id: str) -> dict:
        resp = await self._client.put(
            f"/v3/accounts/{account_id}/orders/{order_id}/cancel"
        )
        resp.raise_for_status()
        logger.info(f"[{self._config.name}] Order {order_id} cancelled")
        return resp.json()

    async def get_orders(self, account_id: str) -> list[dict]:
        resp = await self._client.get(f"/v3/accounts/{account_id}/pendingOrders")
        resp.raise_for_status()
        return resp.json().get("orders", [])

    # --- Portfolio helper ---

    async def get_portfolio(self, account_id: str) -> dict:
        """
        Fetch account details and return a normalized portfolio dict compatible
        with market_reader's expected shape.
        """
        account = await self.get_account(account_id)
        positions = await self.get_open_positions(account_id)

        balance = float(account.get("balance", 0) or 0)
        nav = float(account.get("NAV", balance) or balance)
        unrealized_pl = float(account.get("unrealizedPL", 0) or 0)
        pl = float(account.get("pl", 0) or 0)

        # OANDA does not expose a "last equity" baseline for daily P&L directly;
        # approximate with unrealizedPL relative to NAV.
        daily_pnl = unrealized_pl
        daily_pnl_pct = daily_pnl / nav if nav else 0.0
        drawdown_pct = max(0.0, -daily_pnl_pct)

        return {
            "cash": balance,
            "equity": nav,
            "buying_power": float(account.get("marginAvailable", nav) or nav),
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "drawdown_pct": drawdown_pct,
            "positions": [
                {
                    "symbol": p.get("instrument"),
                    "qty": float(p.get("long", {}).get("units", 0) or 0)
                    + float(p.get("short", {}).get("units", 0) or 0),
                    "market_value": float(p.get("long", {}).get("unrealizedPL", 0) or 0)
                    + float(p.get("short", {}).get("unrealizedPL", 0) or 0),
                    "unrealized_pl": float(p.get("unrealizedPL", 0) or 0),
                }
                for p in positions
            ],
        }
