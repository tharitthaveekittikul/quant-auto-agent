import asyncio
import json
import websockets
from loguru import logger
from datetime import datetime
from shared.database import send_to_questdb

class TopstepWebSocketClient:
    def __init__(self, api_key: str, symbol: str):
        self.uri = "wss://api.projectx.topstep.com/v1/realtime"
        self.api_key = api_key
        self.symbol = symbol
        self.is_running = False
    
    async def connect(self):
        """Create connection and manage reconnection"""
        while True:
            try:
                async with websockets.connect(self.uri) as ws:
                    logger.info(f"Connected to TopstepX Websocket for {self.symbol}")
                    self.is_running = True

                    # Authentication & Subscription
                    auth_payload = {
                        "action": "subscribe",
                        "key": self.api_key,
                        "symbol": [self.symbol]
                    }

                    await ws.send(json.dumps(auth_payload))

                    # Loop receive data and heartbeat
                    await asyncio.gather(
                        self._listen_message(ws),
                        self._send_heartbeat(ws)
                    )
            except Exception as e:
                self.is_running = False
                logger.error(f"Connection lost: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

    async def _listen_message(self, ws):
        """Receive price data and send to QuestDB immediately"""
        async for message in ws:
            data = json.loads(message)

            if data.get("type") == "ticker":
                bid = data.get("bid", 0.0)
                ask = data.get("ask", 0.0)
                last = data.get("last", 0.0)
                vol = data.get("vol", 0.0)

                await send_to_questdb(self.symbol, bid, ask, last, vol)
        

    async def _send_heartbeat(self, ws):
        """Send heartbeat to keep connection alive"""
        while self.is_running:
            try:
                await ws.send(json.dumps({"action": "ping"}))
                await asyncio.sleep(20) # every 20 seconds
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
                break