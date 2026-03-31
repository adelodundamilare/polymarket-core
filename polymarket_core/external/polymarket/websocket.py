import asyncio
import json
from collections.abc import Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from polymarket_core.logger import get_logger

logger = get_logger(__name__)

class MarketWebSocket:
    URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, reconnect_interval: int = 5) -> None:
        self._reconnect_interval = reconnect_interval
        self._running = False
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscribed_assets: set[str] = set()
        self._callbacks: list[Callable[[dict], Any]] = []

    def on_message(self, callback: Callable[[dict], Any]) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect()
            except Exception as e:
                logger.error(f"WebSocket connection failed: {e}")
                await asyncio.sleep(self._reconnect_interval)

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

    async def subscribe(self, asset_ids: list[str]) -> None:
        self._subscribed_assets.update(asset_ids)
        if self._ws and self._ws.open:
            await self._send_subscription(asset_ids)

    async def _connect(self) -> None:
        logger.info("Connecting to WebSocket...")
        async with websockets.connect(self.URL) as ws:
            self._ws = ws
            logger.info("WebSocket connected")
            
            if self._subscribed_assets:
                await self._send_subscription(list(self._subscribed_assets))

            async for message in ws:
                if not self._running:
                    break
                await self._handle_message(message)

    async def _send_subscription(self, asset_ids: list[str]) -> None:
        payload = {
            "assets_ids": asset_ids,
            "type": "MARKET",
        }
        await self._ws.send(json.dumps(payload))
        logger.info(f"Subscribed to {len(asset_ids)} assets")

    async def _handle_message(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
            
        if not message or not message.strip() or message.strip() == "PONG":
            return

        if not (message.strip().startswith("{") or message.strip().startswith("[")):
            return

        try:
            data = json.loads(message)
            events = data if isinstance(data, list) else [data]
            
            for event in events:
                for callback in self._callbacks:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
        except Exception as e:
            logger.error(f"Failed to process message: {e}")
