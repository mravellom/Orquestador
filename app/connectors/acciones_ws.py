"""WebSocket client for real-time Acciones events.

Subscribes to Acciones WS channels (risk, system, positions, portfolio)
and republishes events to Redis so agents react faster than polling cadence.

This is a supplement to HTTP polling, not a replacement. Polling remains
the source of truth for MetricSnapshot persistence.
"""
import asyncio
import json

import redis.asyncio as aioredis
import structlog

from app.config import settings

logger = structlog.get_logger()

# Redis channels where agents listen
REDIS_CHANNEL_MAP = {
    "risk": "orq:ws:risk",
    "system": "orq:ws:system",
    "positions": "orq:ws:positions",
    "portfolio": "orq:ws:portfolio",
}

# Acciones WS channels to subscribe to
SUBSCRIBE_CHANNELS = ["risk", "system", "positions", "portfolio"]


class AccionesWebSocketManager:
    """Manages a persistent WebSocket connection to Acciones."""

    def __init__(
        self,
        ws_url: str | None = None,
        api_key: str | None = None,
        redis_url: str | None = None,
    ):
        self.ws_url = ws_url or settings.acciones_ws_url
        self.api_key = api_key or settings.acciones_api_key
        self.redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None
        self._running = False
        self._reconnect_delay = 1  # seconds, with exponential backoff
        self._max_reconnect_delay = 60
        self._consecutive_failures = 0

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    async def start(self):
        """Start the WebSocket connection loop. Does not block startup on failure."""
        if not settings.acciones_ws_enabled:
            logger.info("Acciones WebSocket disabled (acciones_ws_enabled=False)")
            return

        self._running = True
        logger.info("Acciones WebSocket manager starting", url=self.ws_url)

        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_failures += 1
                delay = min(
                    self._reconnect_delay * (2 ** min(self._consecutive_failures, 6)),
                    self._max_reconnect_delay,
                )
                logger.warning(
                    "WebSocket connection failed, reconnecting",
                    error=str(e),
                    retry_in=delay,
                    consecutive_failures=self._consecutive_failures,
                )
                await asyncio.sleep(delay)

    async def stop(self):
        """Signal the manager to stop."""
        self._running = False
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("Acciones WebSocket manager stopped")

    async def _connect_and_listen(self):
        """Establish WS connection, subscribe, and process messages."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed — WS manager disabled")
            self._running = False
            return

        # Build URL with token auth if available
        url = self.ws_url
        if self.api_key:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}token={self.api_key}"

        async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
            logger.info("WebSocket connected", url=self.ws_url)
            self._consecutive_failures = 0

            # Subscribe to channels
            subscribe_msg = json.dumps({
                "action": "subscribe",
                "channels": SUBSCRIBE_CHANNELS,
            })
            await ws.send(subscribe_msg)
            logger.info("Subscribed to channels", channels=SUBSCRIBE_CHANNELS)

            # Message loop
            async for raw_message in ws:
                if not self._running:
                    break
                await self._handle_message(raw_message)

    async def _handle_message(self, raw_message: str):
        """Parse and republish a WS message to Redis."""
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from WebSocket", raw=raw_message[:200])
            return

        channel = data.get("channel") or data.get("type", "unknown")
        redis_channel = REDIS_CHANNEL_MAP.get(channel)

        if not redis_channel:
            return

        # Republish to Redis for agents
        redis = await self._get_redis()
        enriched = {
            "source": "websocket",
            "channel": channel,
            "data": data.get("data", data),
        }
        await redis.publish(redis_channel, json.dumps(enriched))

        # Fast-path alerts for critical events
        if channel == "risk":
            await self._handle_risk_event(data.get("data", data))
        elif channel == "system":
            await self._handle_system_event(data.get("data", data))

    async def _handle_risk_event(self, data: dict):
        """Fast-path: publish circuit breaker activation to health channel."""
        cb_active = data.get("circuit_breaker_active")
        if cb_active is True:
            redis = await self._get_redis()
            alert = json.dumps({
                "source": "websocket",
                "event": "circuit_breaker_activated",
                "data": data,
            })
            await redis.publish("orq:health", alert)
            logger.warning("Circuit breaker detected via WebSocket")

    async def _handle_system_event(self, data: dict):
        """Fast-path: publish system halt/reconciliation issues to health channel."""
        status = data.get("status")
        if status in ("HALTED", "SHUTTING_DOWN"):
            redis = await self._get_redis()
            alert = json.dumps({
                "source": "websocket",
                "event": "system_status_change",
                "status": status,
                "data": data,
            })
            await redis.publish("orq:health", alert)
            logger.warning("System status change via WebSocket", status=status)

    def get_status(self) -> dict:
        return {
            "name": "acciones_ws",
            "running": self._running,
            "enabled": settings.acciones_ws_enabled,
            "url": self.ws_url,
            "consecutive_failures": self._consecutive_failures,
        }
