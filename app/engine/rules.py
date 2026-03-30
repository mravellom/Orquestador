"""Decision engine rules. Each rule evaluates project metrics and proposes decisions."""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ProjectMetrics:
    """Aggregated metrics for rule evaluation."""
    slug: str
    business_model: str
    handles_real_money: bool
    # Health
    is_healthy: bool = True
    unhealthy_hours: float = 0
    # Financial
    roi_pct: float | None = None
    roi_trend: float | None = None  # slope of ROI over eval window
    pnl_usd: float | None = None
    drawdown_pct: float | None = None
    win_rate_pct: float | None = None
    win_rate_delta_7d: float | None = None  # change in win rate over 7 days
    sharpe_ratio: float | None = None
    # Operational
    revenue_usd: float | None = None
    active_users: int | None = None
    items_processed: int | None = None
    false_positive_rate: float | None = None
    # Budget
    monthly_spend: float = 0
    monthly_budget: float = 0
    # Compliance
    compliance_risk: str | None = None  # "LOW", "MEDIUM", "HIGH"
    # Circuit breaker (Acciones)
    circuit_breaker_active: bool = False
    # Stagnation
    metric_unchanged_hours: float = 0
    eval_window_hours: int = 720


@dataclass
class RuleResult:
    fired: bool
    decision_type: str = ""  # SCALE, PIVOT, KILL, PAUSE
    confidence: float = 0
    reason: str = ""
    requires_human: bool = False


@dataclass
class Rule:
    id: str
    name: str
    applies_to: list[str]  # project slugs or ["*"]
    evaluate: Callable[[ProjectMetrics], RuleResult]
    cooldown_hours: int = 24


# --- Universal Rules ---

def eval_health_dead(m: ProjectMetrics) -> RuleResult:
    if m.unhealthy_hours >= 24:
        return RuleResult(
            fired=True, decision_type="KILL", confidence=90,
            reason=f"Unhealthy for {m.unhealthy_hours:.0f}h (>24h threshold)",
        )
    return RuleResult(fired=False)


def eval_budget_exceeded(m: ProjectMetrics) -> RuleResult:
    if m.monthly_budget > 0 and m.monthly_spend > m.monthly_budget * 1.5:
        return RuleResult(
            fired=True, decision_type="PAUSE", confidence=95,
            reason=f"Monthly spend ${m.monthly_spend:.0f} exceeds 150% of budget ${m.monthly_budget:.0f}",
        )
    return RuleResult(fired=False)


def eval_stagnant(m: ProjectMetrics) -> RuleResult:
    threshold = m.eval_window_hours * 2
    if m.metric_unchanged_hours >= threshold:
        return RuleResult(
            fired=True, decision_type="PIVOT", confidence=60,
            reason=f"No metric changes for {m.metric_unchanged_hours:.0f}h (threshold: {threshold}h)",
        )
    return RuleResult(fired=False)


# --- Financial Rules ---

def eval_roi_negative_30d(m: ProjectMetrics) -> RuleResult:
    if m.roi_pct is not None and m.roi_pct < -20:
        return RuleResult(
            fired=True, decision_type="KILL", confidence=80,
            reason=f"ROI {m.roi_pct:.1f}% < -20% over evaluation window",
            requires_human=m.handles_real_money,
        )
    return RuleResult(fired=False)


def eval_roi_positive_growing(m: ProjectMetrics) -> RuleResult:
    if m.roi_pct is not None and m.roi_pct > 0 and m.roi_trend is not None and m.roi_trend > 0:
        confidence = min(95, 60 + m.roi_pct)
        return RuleResult(
            fired=True, decision_type="SCALE", confidence=confidence,
            reason=f"ROI {m.roi_pct:.1f}% positive with upward trend ({m.roi_trend:.2f}/day)",
        )
    return RuleResult(fired=False)


def eval_drawdown_critical(m: ProjectMetrics) -> RuleResult:
    if m.drawdown_pct is not None and m.drawdown_pct > 15:
        return RuleResult(
            fired=True, decision_type="PAUSE", confidence=85,
            reason=f"Drawdown {m.drawdown_pct:.1f}% exceeds 15% threshold",
        )
    return RuleResult(fired=False)


def eval_winrate_declining(m: ProjectMetrics) -> RuleResult:
    if m.win_rate_delta_7d is not None and m.win_rate_delta_7d < -10:
        return RuleResult(
            fired=True, decision_type="PAUSE", confidence=65,
            reason=f"Win rate dropped {m.win_rate_delta_7d:.1f}pp in 7 days",
        )
    return RuleResult(fired=False)


# --- Acciones-Specific ---

def eval_circuit_breaker(m: ProjectMetrics) -> RuleResult:
    if m.circuit_breaker_active:
        return RuleResult(
            fired=True, decision_type="PAUSE", confidence=95,
            reason="Circuit breaker activated - trading halted by risk system",
        )
    return RuleResult(fired=False)


def eval_daily_loss(m: ProjectMetrics) -> RuleResult:
    if m.pnl_usd is not None and m.pnl_usd < 0:
        # Check if loss exceeds 5% of capital
        if m.roi_pct is not None and m.roi_pct < -5:
            return RuleResult(
                fired=True, decision_type="PAUSE", confidence=80,
                reason=f"Daily PnL {m.roi_pct:.1f}% exceeds -5% threshold",
            )
    return RuleResult(fired=False)


# --- Libro-Specific ---

def eval_libro_revenue(m: ProjectMetrics) -> RuleResult:
    if m.revenue_usd is not None and m.items_processed and m.items_processed > 0:
        rev_per_book = m.revenue_usd / m.items_processed
        if rev_per_book > 5:
            return RuleResult(
                fired=True, decision_type="SCALE", confidence=75,
                reason=f"Revenue ${rev_per_book:.2f}/book exceeds $5 threshold",
            )
    return RuleResult(fired=False)


def eval_libro_compliance(m: ProjectMetrics) -> RuleResult:
    if m.compliance_risk == "HIGH":
        return RuleResult(
            fired=True, decision_type="PAUSE", confidence=90,
            reason="KDP 5.4.8 compliance risk is HIGH - pause publishing",
        )
    return RuleResult(fired=False)


# --- Casas-Specific ---

def eval_casas_fp_high(m: ProjectMetrics) -> RuleResult:
    if m.false_positive_rate is not None and m.false_positive_rate > 40:
        return RuleResult(
            fired=True, decision_type="PIVOT", confidence=70,
            reason=f"False positive rate {m.false_positive_rate:.0f}% > 40% - retune scoring",
        )
    return RuleResult(fired=False)


def eval_casas_no_users(m: ProjectMetrics) -> RuleResult:
    if m.active_users is not None and m.active_users == 0 and m.unhealthy_hours == 0:
        return RuleResult(
            fired=True, decision_type="KILL", confidence=70,
            reason="Zero active Telegram users for extended period",
        )
    return RuleResult(fired=False)


# --- Rule Registry ---

ALL_RULES: list[Rule] = [
    # Universal
    Rule(id="UNIV_HEALTH_DEAD", name="Project dead (unhealthy >24h)", applies_to=["*"], evaluate=eval_health_dead, cooldown_hours=168),
    Rule(id="UNIV_BUDGET_EXCEEDED", name="Budget exceeded >150%", applies_to=["*"], evaluate=eval_budget_exceeded, cooldown_hours=24),
    Rule(id="UNIV_STAGNANT", name="Metrics stagnant", applies_to=["*"], evaluate=eval_stagnant, cooldown_hours=336),
    # Financial
    Rule(id="FIN_ROI_NEGATIVE", name="ROI < -20%", applies_to=["acciones", "compraventa"], evaluate=eval_roi_negative_30d, cooldown_hours=168),
    Rule(id="FIN_ROI_GROWING", name="ROI positive and growing", applies_to=["acciones", "compraventa"], evaluate=eval_roi_positive_growing, cooldown_hours=72),
    Rule(id="FIN_DRAWDOWN", name="Drawdown > 15%", applies_to=["acciones", "compraventa"], evaluate=eval_drawdown_critical, cooldown_hours=24),
    Rule(id="FIN_WINRATE_DROP", name="Win rate declining", applies_to=["acciones", "compraventa"], evaluate=eval_winrate_declining, cooldown_hours=48),
    # Acciones
    Rule(id="ACC_CIRCUIT_BREAKER", name="Circuit breaker active", applies_to=["acciones"], evaluate=eval_circuit_breaker, cooldown_hours=1),
    Rule(id="ACC_DAILY_LOSS", name="Daily loss > 5%", applies_to=["acciones"], evaluate=eval_daily_loss, cooldown_hours=24),
    # Libro
    Rule(id="LIB_REVENUE", name="Revenue per book > $5", applies_to=["libro"], evaluate=eval_libro_revenue, cooldown_hours=720),
    Rule(id="LIB_COMPLIANCE", name="KDP compliance HIGH", applies_to=["libro"], evaluate=eval_libro_compliance, cooldown_hours=24),
    # Casas
    Rule(id="CAS_FP_HIGH", name="False positive > 40%", applies_to=["casas"], evaluate=eval_casas_fp_high, cooldown_hours=48),
    Rule(id="CAS_NO_USERS", name="Zero active users", applies_to=["casas"], evaluate=eval_casas_no_users, cooldown_hours=336),
]
