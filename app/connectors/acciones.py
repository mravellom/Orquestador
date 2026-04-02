"""Connector for Acciones Crypto + Stocks Trading MVP."""
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

        # Reconciliation check
        reconciliation_ok = None
        recon_resp, _ = await self._safe_get("/api/v1/system/reconciliation-status")
        if recon_resp and recon_resp.status_code == 200:
            recon_data = recon_resp.json()
            issues = recon_data.get("issues", [])
            reconciliation_ok = len(issues) == 0
            data["reconciliation"] = recon_data

        return HealthResult(
            is_healthy=data.get("status") == "healthy",
            http_status=resp.status_code,
            response_ms=elapsed,
            database_ok=checks.get("database", {}).get("status") == "healthy",
            redis_ok=checks.get("redis", {}).get("status") == "healthy",
            reconciliation_ok=reconciliation_ok,
            details=data,
        )

    async def collect_metrics(self) -> MetricResult:
        result = MetricResult(metric_type="financial")
        raw = {}

        # Portfolio (aggregate)
        resp, _ = await self._safe_get("/api/v1/portfolio/?mode=PAPER")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.total_capital = data.get("total_capital")
            result.available_capital = data.get("available_capital")
            result.pnl_usd = data.get("pnl") or data.get("daily_pnl")
            raw["portfolio"] = data

        # Portfolio breakdown (crypto vs stocks)
        resp, _ = await self._safe_get("/api/v1/portfolio/breakdown")
        if resp and resp.status_code == 200:
            breakdown = resp.json()
            raw["portfolio_breakdown"] = breakdown
            # Extract per-asset-class data
            for entry in breakdown if isinstance(breakdown, list) else [breakdown]:
                ac = entry.get("asset_class", "").upper()
                if ac == "CRYPTO":
                    result.crypto_pnl_usd = entry.get("pnl") or entry.get("daily_pnl")
                    result.crypto_capital = entry.get("total_capital")
                elif ac in ("STOCKS", "STOCK"):
                    result.stocks_pnl_usd = entry.get("pnl") or entry.get("daily_pnl")
                    result.stocks_capital = entry.get("total_capital")

        # Reconciliation status (also in health, but needed in raw_data for estratega)
        resp, _ = await self._safe_get("/api/v1/system/reconciliation-status")
        if resp and resp.status_code == 200:
            raw["reconciliation"] = resp.json()

        # Analytics summary
        resp, _ = await self._safe_get("/api/v1/analytics/summary")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.win_rate_pct = data.get("win_rate")
            result.sharpe_ratio = data.get("sharpe_ratio")
            raw["analytics"] = data

        # Risk status
        resp, _ = await self._safe_get("/api/v1/risk/status")
        if resp and resp.status_code == 200:
            data = resp.json()
            result.drawdown_pct = data.get("drawdown_pct")
            raw["risk"] = data

        # Strategies list
        resp, _ = await self._safe_get("/api/v1/strategies/")
        if resp and resp.status_code == 200:
            raw["strategies"] = resp.json()

        # Per-strategy analytics
        resp, _ = await self._safe_get("/api/v1/analytics/per-strategy")
        if resp and resp.status_code == 200:
            raw["per_strategy_analytics"] = resp.json()

        # PnL series (30 days)
        resp, _ = await self._safe_get("/api/v1/analytics/pnl?days=30")
        if resp and resp.status_code == 200:
            raw["pnl_series"] = resp.json()

        # Drawdown series (30 days)
        resp, _ = await self._safe_get("/api/v1/analytics/drawdown?days=30")
        if resp and resp.status_code == 200:
            raw["drawdown_series"] = resp.json()

        # Paper vs Live comparison
        resp, _ = await self._safe_get("/api/v1/analytics/paper-vs-live")
        if resp and resp.status_code == 200:
            raw["paper_vs_live"] = resp.json()

        # ML shadow performance
        resp, _ = await self._safe_get("/api/v1/analytics/ml-shadow")
        if resp and resp.status_code == 200:
            raw["ml_shadow"] = resp.json()

        # Win rate by strategy
        resp, _ = await self._safe_get("/api/v1/trades/win-rate")
        if resp and resp.status_code == 200:
            raw["win_rate_by_strategy"] = resp.json()

        # Open positions (for stock market hours check)
        resp, _ = await self._safe_get("/api/v1/positions/open")
        if resp and resp.status_code == 200:
            positions = resp.json()
            raw["open_positions"] = positions

        # Pending order approvals
        resp, _ = await self._safe_get("/api/v1/orders/pending-approval")
        if resp and resp.status_code == 200:
            raw["pending_approvals"] = resp.json()

        result.raw_data = raw
        return result

    async def execute_action(self, action: str, params: dict | None = None) -> ActionResult:
        params = params or {}
        try:
            if action == "halt":
                resp, _ = await self._safe_post(
                    "/api/v1/system/halt",
                    json=params if params else {"reason": "Orchestrator halt"},
                )
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(success=resp.status_code == 200, message=resp.text)

            elif action == "resume":
                resp, _ = await self._safe_post("/api/v1/system/resume")
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(success=resp.status_code == 200, message=resp.text)

            elif action == "check_positions":
                resp, _ = await self._safe_get("/api/v1/risk/status")
                if resp and resp.status_code == 200:
                    data = resp.json()
                    open_positions = data.get("open_positions", 0)
                    return ActionResult(
                        success=True,
                        message=f"{open_positions} open positions",
                        details={"open_positions": open_positions},
                    )
                return ActionResult(success=False, message="Could not check positions")

            elif action == "list_positions":
                resp, _ = await self._safe_get("/api/v1/positions/open")
                if resp and resp.status_code == 200:
                    positions = resp.json()
                    return ActionResult(
                        success=True,
                        message=f"{len(positions)} open positions",
                        details={"positions": positions},
                    )
                return ActionResult(success=False, message="Could not list positions")

            elif action == "close_position":
                position_id = params.get("position_id")
                if not position_id:
                    return ActionResult(success=False, message="position_id required")
                reason = params.get("reason", "Orchestrator close")
                resp, _ = await self._safe_post(
                    f"/api/v1/positions/{position_id}/close",
                    json={"reason": reason},
                )
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(
                    success=resp.status_code == 200,
                    message=resp.text,
                    details={"position_id": position_id},
                )

            elif action == "update_risk_config":
                risk_params = params.get("config", params)
                resp, _ = await self._safe_put("/api/v1/risk/config", json=risk_params)
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(
                    success=resp.status_code == 200,
                    message=resp.text,
                    details={"config_sent": risk_params},
                )

            elif action == "list_strategies":
                resp, _ = await self._safe_get("/api/v1/strategies/")
                if resp and resp.status_code == 200:
                    strategies = resp.json()
                    return ActionResult(
                        success=True,
                        message=f"{len(strategies)} strategies",
                        details={"strategies": strategies},
                    )
                return ActionResult(success=False, message="Could not list strategies")

            elif action == "activate_strategy":
                strategy_id = params.get("strategy_id")
                if not strategy_id:
                    return ActionResult(success=False, message="strategy_id required")
                resp, _ = await self._safe_post(f"/api/v1/strategies/{strategy_id}/activate")
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(
                    success=resp.status_code == 200,
                    message=resp.text,
                    details={"strategy_id": strategy_id},
                )

            elif action == "deactivate_strategy":
                strategy_id = params.get("strategy_id")
                if not strategy_id:
                    return ActionResult(success=False, message="strategy_id required")
                resp, _ = await self._safe_post(f"/api/v1/strategies/{strategy_id}/deactivate")
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(
                    success=resp.status_code == 200,
                    message=resp.text,
                    details={"strategy_id": strategy_id},
                )

            elif action == "approve_order":
                order_id = params.get("order_id")
                if not order_id:
                    return ActionResult(success=False, message="order_id required")
                resp, _ = await self._safe_post(f"/api/v1/orders/{order_id}/approve")
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(
                    success=resp.status_code == 200,
                    message=resp.text,
                    details={"order_id": order_id},
                )

            elif action == "reject_order":
                order_id = params.get("order_id")
                if not order_id:
                    return ActionResult(success=False, message="order_id required")
                reason = params.get("reason", "Rejected by orchestrator")
                resp, _ = await self._safe_post(
                    f"/api/v1/orders/{order_id}/reject",
                    json={"reason": reason},
                )
                if resp is None:
                    return ActionResult(success=False, message="Request failed")
                return ActionResult(
                    success=resp.status_code == 200,
                    message=resp.text,
                    details={"order_id": order_id},
                )

        except Exception as e:
            return ActionResult(success=False, message=str(e))

        return ActionResult(success=False, message=f"Unknown action: {action}")
