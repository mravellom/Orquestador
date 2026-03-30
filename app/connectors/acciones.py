"""Connector for Acciones Crypto Trading MVP."""
import httpx
import structlog

from app.connectors.base import BaseConnector, HealthResult, MetricResult, ActionResult

logger = structlog.get_logger()


class AccionesConnector(BaseConnector):

    async def check_health(self) -> HealthResult:
        resp, elapsed = await self._safe_get("/api/v1/system/health")
        if resp is None:
            return HealthResult(is_healthy=False, response_ms=elapsed, error_message="Unreachable")

        if resp.status_code != 200:
            return HealthResult(
                is_healthy=False, http_status=resp.status_code,
                response_ms=elapsed, error_message=f"HTTP {resp.status_code}",
            )

        data = resp.json()
        checks = data.get("checks", {})
        return HealthResult(
            is_healthy=data.get("status") == "healthy",
            http_status=resp.status_code,
            response_ms=elapsed,
            database_ok=checks.get("database", {}).get("status") == "healthy",
            redis_ok=checks.get("redis", {}).get("status") == "healthy",
            details=data,
        )

    async def collect_metrics(self) -> MetricResult:
        result = MetricResult(metric_type="financial")
        raw = {}

        # Portfolio
        resp, _ = await self._safe_get("/api/v1/portfolio/?mode=PAPER")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.total_capital = data.get("total_capital")
            result.available_capital = data.get("available_capital")
            result.pnl_usd = data.get("pnl") or data.get("daily_pnl")
            raw["portfolio"] = data

        # Analytics summary
        resp, _ = await self._safe_get("/api/v1/analytics/summary")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.win_rate_pct = data.get("win_rate")
            result.sharpe_ratio = data.get("sharpe_ratio")
            raw["analytics"] = data

        # Risk
        resp, _ = await self._safe_get("/api/v1/risk/status")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.drawdown_pct = data.get("drawdown_pct")
            raw["risk"] = data

        result.raw_data = raw
        return result

    async def execute_action(self, action: str, params: dict | None = None) -> ActionResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if action == "halt":
                    resp = await client.post(
                        f"{self.base_url}/api/v1/system/halt",
                        json=params or {"reason": "Orchestrator halt"},
                        headers=self._headers(),
                    )
                    return ActionResult(success=resp.status_code == 200, message=resp.text)
                elif action == "resume":
                    resp = await client.post(
                        f"{self.base_url}/api/v1/system/resume",
                        headers=self._headers(),
                    )
                    return ActionResult(success=resp.status_code == 200, message=resp.text)
                elif action == "check_positions":
                    resp = await client.get(
                        f"{self.base_url}/api/v1/risk/status",
                        headers=self._headers(),
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        open_positions = data.get("open_positions", 0)
                        return ActionResult(
                            success=True,
                            message=f"{open_positions} open positions",
                            details={"open_positions": open_positions},
                        )
                    return ActionResult(success=False, message=resp.text)
        except Exception as e:
            return ActionResult(success=False, message=str(e))

        return ActionResult(success=False, message=f"Unknown action: {action}")
