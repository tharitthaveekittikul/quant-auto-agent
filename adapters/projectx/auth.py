import asyncio

import httpx
from loguru import logger

from .config import EnvironmentConfig


class AuthSession:
    """
    Manages authentication with the ProjectX API.

    Token is valid for 24 hours. Call validate() periodically (e.g. every 23h)
    to refresh it without re-authenticating.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        self._config = config
        self._token: str | None = None
        self._client = httpx.AsyncClient(base_url=config.api_url)

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def config(self) -> EnvironmentConfig:
        return self._config

    async def login(self, username: str, api_key: str) -> str:
        """Authenticate with API key and store the JWT token."""
        resp = await self._client.post(
            "/api/Auth/loginKey",
            json={"userName": username, "apiKey": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["token"]
        logger.success(f"[{self._config.name}] Authenticated as {username!r}")
        return self._token

    async def validate(self) -> str:
        """Refresh/extend the current session token. Call every ~23 hours."""
        resp = await self._client.post(
            "/api/Auth/validate",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        # Server may return a new token or keep the same one
        self._token = data.get("newToken") or self._token
        logger.debug(f"[{self._config.name}] Session token validated")
        return self._token

    async def logout(self) -> None:
        if self._token:
            try:
                await self._client.post(
                    "/api/Auth/logout",
                    headers=self._auth_headers(),
                )
            except Exception as e:
                logger.warning(f"Logout request failed: {e}")
            self._token = None
        await self._client.aclose()
        logger.info(f"[{self._config.name}] Logged out")

    async def start_token_refresh(self, interval_hours: float = 23.0) -> None:
        """Background task that keeps the token alive. Run with asyncio.create_task()."""
        while True:
            await asyncio.sleep(interval_hours * 3600)
            try:
                await self.validate()
            except Exception as e:
                logger.error(f"Token refresh failed: {e}")

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}
