"""Connector for Libro KDP Publishing MVP."""
import structlog

from app.connectors.base import BaseConnector, HealthResult, MetricResult

logger = structlog.get_logger()


class LibroConnector(BaseConnector):

    async def check_health(self) -> HealthResult:
        resp, elapsed = await self._safe_get("/api/metrics")
        if resp is None:
            return HealthResult(is_healthy=False, response_ms=elapsed, error_message="Unreachable")

        return HealthResult(
            is_healthy=resp.status_code == 200,
            http_status=resp.status_code,
            response_ms=elapsed,
            details=resp.json() if resp.status_code == 200 else {},
        )

    async def collect_metrics(self) -> MetricResult:
        result = MetricResult(metric_type="financial")
        raw = {}

        # Core metrics
        resp, _ = await self._safe_get("/api/metrics")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.revenue_usd = data.get("total_revenue")
            result.items_processed = data.get("total_published")
            raw["metrics"] = data

        # Analytics
        resp, _ = await self._safe_get("/api/analytics")
        if resp and resp.status_code == 200:
            raw["analytics"] = resp.json()

        # Compliance risk
        resp, _ = await self._safe_get("/api/risk")
        if resp and resp.status_code == 200:
            raw["risk"] = resp.json()

        result.raw_data = raw
        return result
