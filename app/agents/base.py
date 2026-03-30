"""Base agent with async loop, Redis pub/sub, and graceful shutdown."""
import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime

import redis.asyncio as aioredis
import structlog

from app.config import settings

logger = structlog.get_logger()


class BaseAgent(ABC):
    name: str = "base"
    cadence_seconds: int = 60
    publish_channel: str = ""

    def __init__(self):
        self.running = False
        self._redis: aioredis.Redis | None = None
        self._cycle_count = 0
        self._last_cycle: datetime | None = None
        self._consecutive_errors = 0
        self._status = "initialized"

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def publish(self, event_type: str, data: dict):
        """Publish an event to this agent's channel."""
        if not self.publish_channel:
            return
        redis = await self._get_redis()
        message = json.dumps({
            "agent": self.name,
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        })
        await redis.publish(self.publish_channel, message)

    async def start(self):
        """Main loop: run cycles at the configured cadence."""
        self.running = True
        self._status = "running"
        logger.info(f"Agent {self.name} started", cadence=self.cadence_seconds)

        while self.running:
            try:
                await self.run_cycle()
                self._cycle_count += 1
                self._last_cycle = datetime.utcnow()
                self._consecutive_errors = 0
                self._status = "running"
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                self._status = "degraded" if self._consecutive_errors >= 5 else "running"
                backoff = min(self.cadence_seconds * 2, 300) if self._consecutive_errors >= 5 else self.cadence_seconds
                logger.error(
                    f"Agent {self.name} cycle failed",
                    error=str(e),
                    consecutive_errors=self._consecutive_errors,
                )
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(self.cadence_seconds)

    async def stop(self):
        """Signal the agent to stop."""
        self.running = False
        self._status = "stopped"
        if self._redis:
            await self._redis.close()
        logger.info(f"Agent {self.name} stopped")

    @abstractmethod
    async def run_cycle(self):
        """Execute one cycle of the agent's work."""
        ...

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "status": self._status,
            "cycle_count": self._cycle_count,
            "last_cycle": self._last_cycle.isoformat() if self._last_cycle else None,
            "consecutive_errors": self._consecutive_errors,
            "cadence_seconds": self.cadence_seconds,
        }
