"""Connector for CompraVenta Arbitrage MVP."""
import structlog

from app.connectors.base import BaseConnector, HealthResult, MetricResult

logger = structlog.get_logger()


class CompraVentaConnector(BaseConnector):

    async def check_health(self) -> HealthResult:
        resp, elapsed = await self._safe_get("/health")
        if resp is None:
            return HealthResult(is_healthy=False, response_ms=elapsed, error_message="Unreachable")

        if resp.status_code != 200:
            return HealthResult(
                is_healthy=False, http_status=resp.status_code,
                response_ms=elapsed, error_message=f"HTTP {resp.status_code}",
            )

        # Also check pipeline health for deeper insight
        pipe_resp, _ = await self._safe_get("/health/pipeline")
        pipe_data = pipe_resp.json() if pipe_resp and pipe_resp.status_code == 200 else {}

        data = resp.json()
        return HealthResult(
            is_healthy=data.get("status") == "ok",
            http_status=resp.status_code,
            response_ms=elapsed,
            database_ok=pipe_data.get("database", {}).get("status") == "ok",
            redis_ok=pipe_data.get("redis", {}).get("status") == "ok",
            details={**data, "pipeline": pipe_data},
        )

    async def collect_metrics(self) -> MetricResult:
        result = MetricResult(metric_type="financial")
        raw = {}

        # Opportunities stats
        resp, _ = await self._safe_get("/api/v1/opportunities/stats")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.roi_pct = data.get("avg_roi")
            result.items_processed = data.get("total_opportunities")
            raw["opportunities"] = data

        # Capital metrics
        resp, _ = await self._safe_get("/capital/metrics")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.total_capital = data.get("total_capital")
            result.available_capital = data.get("available_capital")
            result.win_rate_pct = data.get("win_rate")
            result.drawdown_pct = data.get("drawdown_pct")
            raw["capital"] = data

        # Trade accuracy
        resp, _ = await self._safe_get("/api/v1/trades/accuracy?window=7d")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.pnl_usd = data.get("avg_actual_profit")
            raw["accuracy"] = data

        result.raw_data = raw
        return result
