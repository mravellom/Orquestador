"""Connector for GeneradorDeIdeasMuertas MVP."""
import structlog

from app.connectors.base import BaseConnector, HealthResult, MetricResult

logger = structlog.get_logger()


class IdeasConnector(BaseConnector):

    async def check_health(self) -> HealthResult:
        resp, elapsed = await self._safe_get("/")
        if resp is None:
            return HealthResult(is_healthy=False, response_ms=elapsed, error_message="Unreachable")

        if resp.status_code != 200:
            return HealthResult(
                is_healthy=False, http_status=resp.status_code,
                response_ms=elapsed, error_message=f"HTTP {resp.status_code}",
            )

        data = resp.json()
        return HealthResult(
            is_healthy=data.get("status") == "running",
            http_status=resp.status_code,
            response_ms=elapsed,
            details=data,
        )

    async def collect_metrics(self) -> MetricResult:
        result = MetricResult(metric_type="operational")
        raw = {}

        # Ideas count
        resp, _ = await self._safe_get("/api/ideas/")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.items_processed = len(data) if isinstance(data, list) else 0
            raw["ideas_count"] = result.items_processed

        # Top ideas
        resp, _ = await self._safe_get("/api/ideas/top?limit=10")
        if resp and resp.status_code == 200:
            raw["top_ideas"] = resp.json()

        result.raw_data = raw
        return result
