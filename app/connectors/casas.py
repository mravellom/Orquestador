"""Connector for Casas InmoAlert Chile MVP."""
import structlog

from app.connectors.base import BaseConnector, HealthResult, MetricResult

logger = structlog.get_logger()


class CasasConnector(BaseConnector):

    async def check_health(self) -> HealthResult:
        resp, elapsed = await self._safe_get("/api/v1/admin/health")
        if resp is None:
            return HealthResult(is_healthy=False, response_ms=elapsed, error_message="Unreachable")

        if resp.status_code != 200:
            return HealthResult(
                is_healthy=False, http_status=resp.status_code,
                response_ms=elapsed, error_message=f"HTTP {resp.status_code}",
            )

        data = resp.json()
        return HealthResult(
            is_healthy=data.get("status") == "ok",
            http_status=resp.status_code,
            response_ms=elapsed,
            database_ok=data.get("database") == "connected",
            details=data,
        )

    async def collect_metrics(self) -> MetricResult:
        result = MetricResult(metric_type="operational")
        raw = {}

        # Admin metrics
        resp, _ = await self._safe_get("/api/v1/admin/metrics")
        if resp and resp.status_code == 200:
            raw["metrics"] = resp.json()

        # Feedback stats
        resp, _ = await self._safe_get("/api/v1/admin/feedback/stats")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.false_positive_rate = data.get("false_positive_rate")
            result.active_users = data.get("total_feedback")
            raw["feedback"] = data

        # Opportunities
        resp, _ = await self._safe_get("/api/v1/opportunities?min_score=70&limit=1")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.items_processed = data.get("total", 0)
            raw["opportunities"] = {"total": result.items_processed}

        result.raw_data = raw
        return result
