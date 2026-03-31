"""Connector for Libro KDP Publishing MVP."""
import httpx
import structlog

from app.connectors.base import BaseConnector, HealthResult, MetricResult, ActionResult

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

    async def execute_action(self, action: str, params: dict | None = None) -> ActionResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if action == "pause_publishing":
                    resp = await client.post(
                        f"{self.base_url}/api/pipeline/pause",
                        json=params or {"reason": "Orchestrator pause"},
                        headers=self._headers(),
                    )
                    return ActionResult(success=resp.status_code == 200, message=resp.text)
                elif action == "resume_publishing":
                    resp = await client.post(
                        f"{self.base_url}/api/pipeline/resume",
                        headers=self._headers(),
                    )
                    return ActionResult(success=resp.status_code == 200, message=resp.text)
                elif action == "check_compliance":
                    resp = await client.get(
                        f"{self.base_url}/api/risk",
                        headers=self._headers(),
                    )
                    if resp.status_code == 200:
                        return ActionResult(success=True, message="OK", details=resp.json())
                    return ActionResult(success=False, message=resp.text)
        except Exception as e:
            return ActionResult(success=False, message=str(e))
        return ActionResult(success=False, message=f"Unknown action: {action}")
