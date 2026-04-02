"""Approver Agent: monitors and manages pending order approvals in Acciones."""
import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent
from app.config import settings, PROJECT_REGISTRY
from app.connectors.acciones import AccionesConnector
from app.database import async_session
from app.models.metric_snapshot import MetricSnapshot
from app.models.project import Project
from app.notifications.telegram import TelegramNotifier

logger = structlog.get_logger()


class ApproverAgent(BaseAgent):
    name = "approver"
    cadence_seconds = 30
    publish_channel = "orq:approvals"

    def __init__(self):
        super().__init__()
        self._connector: AccionesConnector | None = None
        self._notifier: TelegramNotifier | None = None

    def _get_connector(self) -> AccionesConnector | None:
        if self._connector is None:
            cfg = next((c for c in PROJECT_REGISTRY if c.slug == "acciones"), None)
            if cfg:
                api_key = getattr(settings, cfg.api_key_env, "") if cfg.api_key_env else None
                self._connector = AccionesConnector(base_url=cfg.base_url, api_key=api_key or None)
        return self._connector

    def _get_notifier(self) -> TelegramNotifier:
        if self._notifier is None:
            self._notifier = TelegramNotifier()
        return self._notifier

    async def run_cycle(self):
        # Only process if acciones project is ACTIVE
        async with async_session() as session:
            result = await session.execute(
                select(Project).where(Project.slug == "acciones", Project.status == "ACTIVE")
            )
            project = result.scalar_one_or_none()

        if not project:
            return

        connector = self._get_connector()
        if not connector:
            return

        # Fetch pending approvals
        resp, _ = await connector._safe_get("/api/v1/orders/pending-approval")
        if not resp or resp.status_code != 200:
            return

        pending_orders = resp.json()
        if not pending_orders:
            return

        logger.info("Pending order approvals", count=len(pending_orders))

        # Get latest metrics for context
        async with async_session() as session:
            snap_q = (
                select(MetricSnapshot)
                .where(MetricSnapshot.project_id == project.id)
                .order_by(MetricSnapshot.captured_at.desc())
                .limit(1)
            )
            latest_snap = (await session.execute(snap_q)).scalar_one_or_none()

        total_capital = float(latest_snap.total_capital) if latest_snap and latest_snap.total_capital else 0
        current_drawdown = float(latest_snap.drawdown_pct) if latest_snap and latest_snap.drawdown_pct else 0

        for order in pending_orders:
            order_id = order.get("id")
            if not order_id:
                continue

            decision = self._evaluate_order(order, total_capital, current_drawdown)

            if decision == "approve" and settings.acciones_auto_approve_enabled:
                result = await connector.execute_action("approve_order", {"order_id": order_id})
                logger.info("Auto-approved order", order_id=order_id, success=result.success)
                await self.publish("order_approved", {
                    "order_id": order_id,
                    "auto": True,
                    "symbol": order.get("symbol"),
                })

            elif decision == "reject" and settings.acciones_auto_approve_enabled:
                reason = self._rejection_reason(order, total_capital, current_drawdown)
                result = await connector.execute_action(
                    "reject_order", {"order_id": order_id, "reason": reason},
                )
                logger.warning("Auto-rejected order", order_id=order_id, reason=reason)
                await self.publish("order_rejected", {
                    "order_id": order_id,
                    "reason": reason,
                    "symbol": order.get("symbol"),
                })

            elif decision == "escalate":
                symbol = order.get("symbol", "?")
                side = order.get("side", "?")
                size_usd = order.get("estimated_cost") or order.get("quantity", 0)
                await self._get_notifier().send_alert(
                    "INFO", "Acciones",
                    f"Order pending approval: {side} {symbol} ~${size_usd:.2f} — review at dashboard",
                )
                await self.publish("order_escalated", {
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": side,
                })

            else:
                # auto_approve disabled — just log what we would do
                logger.info(
                    "Approver observation",
                    order_id=order_id,
                    would_do=decision,
                    symbol=order.get("symbol"),
                    auto_approve_enabled=settings.acciones_auto_approve_enabled,
                )

    def _evaluate_order(self, order: dict, total_capital: float, drawdown_pct: float) -> str:
        """
        Evaluate a pending order against rules.

        Returns: "approve", "reject", or "escalate"
        """
        estimated_cost = order.get("estimated_cost") or order.get("quantity", 0)
        confidence = order.get("signal_confidence") or order.get("confidence", 0)

        # Hard reject: drawdown already critical
        if drawdown_pct > 12:
            return "reject"

        # Hard reject: order too large relative to capital
        if total_capital > 0:
            order_pct = (estimated_cost / total_capital) * 100
            if order_pct > settings.acciones_max_order_size_pct:
                return "reject"

        # Hard reject: order exceeds max auto-approve USD
        if estimated_cost > settings.acciones_auto_approve_max_usd:
            return "escalate"

        # Low confidence → escalate to human
        if confidence < 0.6:
            return "escalate"

        # Passes all checks → approve
        return "approve"

    def _rejection_reason(self, order: dict, total_capital: float, drawdown_pct: float) -> str:
        """Build a human-readable rejection reason."""
        reasons = []
        estimated_cost = order.get("estimated_cost") or order.get("quantity", 0)

        if drawdown_pct > 12:
            reasons.append(f"drawdown at {drawdown_pct:.1f}% (>12%)")

        if total_capital > 0:
            order_pct = (estimated_cost / total_capital) * 100
            if order_pct > settings.acciones_max_order_size_pct:
                reasons.append(f"order size {order_pct:.1f}% of capital (max {settings.acciones_max_order_size_pct}%)")

        return f"Orchestrator auto-reject: {'; '.join(reasons)}" if reasons else "Orchestrator auto-reject"
