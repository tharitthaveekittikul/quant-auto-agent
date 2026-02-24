"""
High-level ProjectX client that combines REST, MarketHub, and UserHub.

Usage:
    # From environment variables (PROJECTX_ENV, PROJECTX_USERNAME, PROJECTX_API_KEY)
    client = await ProjectXClient.from_env()

    # Or explicitly
    client = ProjectXClient(env=Environment.DEMO)
    await client.login(username="...", api_key="...")

    # Fetch account info
    accounts = await client.rest.search_accounts()
    account_id = accounts[0]["id"]

    # Stream real-time quotes
    await client.connect_market(["CON.F.US.MES.M25"])

    # Stream user events (orders, positions, trades)
    await client.connect_user(account_id, on_order=my_order_handler)

    # Graceful shutdown
    await client.disconnect()
"""

import asyncio
import os
from collections.abc import Callable

from loguru import logger

from .auth import AuthSession
from .config import ENVIRONMENT_CONFIGS, Environment
from .market_hub import MarketHub
from .rest_client import RestClient
from .user_hub import UserHub


class ProjectXClient:
    """Unified async client for the ProjectX Gateway API."""

    def __init__(self, env: Environment = Environment.DEMO) -> None:
        config = ENVIRONMENT_CONFIGS[env]
        self._auth = AuthSession(config)
        self.rest = RestClient(self._auth)
        self.market = MarketHub(self._auth)
        self.user: UserHub | None = None
        self._refresh_task: asyncio.Task | None = None

    # --- Auth ---

    async def login(self, username: str, api_key: str) -> "ProjectXClient":
        """Authenticate and start background token refresh."""
        await self._auth.login(username, api_key)
        # Keep token alive in the background
        self._refresh_task = asyncio.create_task(self._auth.start_token_refresh())
        return self

    @classmethod
    async def from_env(cls) -> "ProjectXClient":
        """
        Create and authenticate a client using environment variables:
          PROJECTX_ENV      - "demo" or "topstep" (default: "demo")
          PROJECTX_USERNAME - account username
          PROJECTX_API_KEY  - API key
        """
        env_str = os.getenv("PROJECTX_ENV", "demo").lower()
        env = Environment.TOPSTEP if env_str == "topstep" else Environment.DEMO

        username = os.environ["PROJECTX_USERNAME"]
        api_key = os.environ["PROJECTX_API_KEY"]

        client = cls(env)
        await client.login(username, api_key)
        logger.info(f"ProjectXClient ready (env={env.value})")
        return client

    # --- Real-time ---

    async def connect_market(
        self,
        contract_ids: list[str],
        *,
        on_quote: Callable | None = None,
        on_trade: Callable | None = None,
        subscribe_trades: bool = False,
    ) -> None:
        """Connect to MarketHub and subscribe to quotes for the given contracts."""
        self.market = MarketHub(self._auth, on_quote=on_quote, on_trade=on_trade)
        await self.market.connect()
        for cid in contract_ids:
            await self.market.subscribe_quotes(cid)
            if subscribe_trades:
                await self.market.subscribe_trades(cid)

    async def connect_user(
        self,
        account_id: int,
        *,
        on_account: Callable | None = None,
        on_order: Callable | None = None,
        on_position: Callable | None = None,
        on_trade: Callable | None = None,
    ) -> None:
        """Connect to UserHub and subscribe to all events for the account."""
        self.user = UserHub(
            self._auth,
            on_account=on_account,
            on_order=on_order,
            on_position=on_position,
            on_trade=on_trade,
        )
        await self.user.connect()
        await self.user.subscribe(account_id)

    # --- Shutdown ---

    async def disconnect(self) -> None:
        """Gracefully disconnect all hubs and revoke the server token."""
        if self._refresh_task:
            self._refresh_task.cancel()

        await self.market.disconnect()

        if self.user:
            await self.user.disconnect()

        await self.rest.close()
        await self._auth.logout()
