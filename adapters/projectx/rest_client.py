"""
REST client for the ProjectX Gateway API.

All endpoints use POST with JSON bodies and Bearer token auth.
Reference: https://api.topstepx.com/swagger/v1/swagger.json

Bar unit values: 1=Second, 2=Minute, 3=Hour, 4=Day, 5=Week, 6=Month
Order type values: 1=Limit, 2=Market, 3=StopLimit, 4=Stop, 5=TrailingStop, 6=JoinBid, 7=JoinAsk
Order side values: 0=Bid (Buy), 1=Ask (Sell)
"""

import httpx
from loguru import logger

from .auth import AuthSession


class RestClient:
    def __init__(self, auth: AuthSession) -> None:
        self._auth = auth
        self._client = httpx.AsyncClient(base_url=auth.config.api_url)

    # --- Accounts ---

    async def search_accounts(self, only_active: bool = True) -> list[dict]:
        resp = await self._post("/api/Account/search", {"onlyActiveAccounts": only_active})
        return resp.get("accounts", [])

    # --- Contracts ---

    async def search_contracts(self, text: str, live: bool = True) -> list[dict]:
        resp = await self._post("/api/Contract/search", {"searchText": text, "live": live})
        return resp.get("contracts", [])

    async def get_contract(self, contract_id: str) -> dict:
        resp = await self._post("/api/Contract/searchById", {"contractId": contract_id})
        return resp.get("contract", {})

    async def list_available_contracts(self, live: bool = True) -> list[dict]:
        resp = await self._post("/api/Contract/available", {"live": live})
        return resp.get("contracts", [])

    # --- Historical Bars ---

    async def get_bars(
        self,
        contract_id: str,
        start_time: str,
        end_time: str,
        unit: int = 2,
        unit_number: int = 1,
        limit: int = 500,
    ) -> list[dict]:
        """
        Fetch OHLCV bars. Timestamps in ISO 8601 format.
        Returns list of dicts with keys: t, o, h, l, c, v
        """
        resp = await self._post(
            "/api/History/retrieveBars",
            {
                "contractId": contract_id,
                "startTime": start_time,
                "endTime": end_time,
                "unit": unit,
                "unitNumber": unit_number,
                "limit": limit,
            },
        )
        return resp.get("bars", [])

    # --- Orders ---

    async def place_order(
        self,
        account_id: int,
        contract_id: str,
        order_type: int,
        side: int,
        size: int,
        limit_price: float | None = None,
        stop_price: float | None = None,
        custom_tag: str | None = None,
    ) -> dict:
        body: dict = {
            "accountId": account_id,
            "contractId": contract_id,
            "type": order_type,
            "side": side,
            "size": size,
        }
        if limit_price is not None:
            body["limitPrice"] = limit_price
        if stop_price is not None:
            body["stopPrice"] = stop_price
        if custom_tag is not None:
            body["customTag"] = custom_tag
        return await self._post("/api/Order/place", body)

    async def cancel_order(self, account_id: int, order_id: int) -> dict:
        return await self._post("/api/Order/cancel", {"accountId": account_id, "orderId": order_id})

    async def modify_order(
        self,
        account_id: int,
        order_id: int,
        size: int | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> dict:
        body: dict = {"accountId": account_id, "orderId": order_id}
        if size is not None:
            body["size"] = size
        if limit_price is not None:
            body["limitPrice"] = limit_price
        if stop_price is not None:
            body["stopPrice"] = stop_price
        return await self._post("/api/Order/modify", body)

    async def get_open_orders(self, account_id: int) -> list[dict]:
        resp = await self._post("/api/Order/searchOpen", {"accountId": account_id})
        return resp.get("orders", [])

    async def search_orders(
        self, account_id: int, start_timestamp: str, end_timestamp: str
    ) -> list[dict]:
        resp = await self._post(
            "/api/Order/search",
            {"accountId": account_id, "startTimestamp": start_timestamp, "endTimestamp": end_timestamp},
        )
        return resp.get("orders", [])

    # --- Positions ---

    async def get_open_positions(self, account_id: int) -> list[dict]:
        resp = await self._post("/api/Position/searchOpen", {"accountId": account_id})
        return resp.get("positions", [])

    async def close_position(self, account_id: int, contract_id: str) -> dict:
        return await self._post(
            "/api/Position/closeContract",
            {"accountId": account_id, "contractId": contract_id},
        )

    async def partial_close_position(
        self, account_id: int, contract_id: str, size: int
    ) -> dict:
        return await self._post(
            "/api/Position/partialCloseContract",
            {"accountId": account_id, "contractId": contract_id, "size": size},
        )

    # --- Trades ---

    async def search_trades(
        self, account_id: int, start_timestamp: str, end_timestamp: str
    ) -> list[dict]:
        resp = await self._post(
            "/api/Trade/search",
            {"accountId": account_id, "startTimestamp": start_timestamp, "endTimestamp": end_timestamp},
        )
        return resp.get("trades", [])

    # --- Health ---

    async def ping(self) -> bool:
        resp = await self._client.get("/api/Status/ping")
        return resp.text.strip('"') == "pong"

    # --- Internal ---

    async def _post(self, path: str, body: dict) -> dict:
        resp = await self._client.post(
            path,
            json=body,
            headers={"Authorization": f"Bearer {self._auth.token}"},
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
