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
    total_capital: float | None = None
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
    circuit_breaker_active_previous: bool = False
    # Reconciliation
    reconciliation_issues: int = 0
    # Portfolio score (set by estratega before rule evaluation)
    portfolio_score: float | None = None
    # Asset class breakdown (Acciones)
    crypto_pnl_usd: float | None = None
    stocks_pnl_usd: float | None = None
    crypto_capital: float | None = None
    stocks_capital: float | None = None
    stocks_positions_open: int = 0
    is_stock_market_open: bool = True
    # Strategy performance
    strategy_performance: list = field(default_factory=list)  # list of dicts with strategy-level metrics
    active_strategy_count: int = 0
    # ML shadow
    ml_shadow_win_rate: float | None = None
    live_win_rate: float | None = None
    # Paper vs live
    paper_pnl: float | None = None
    live_pnl: float | None = None
    # Stagnation
    metric_unchanged_hours: float = 0
    eval_window_hours: int = 720
    # Change penalty
    last_decision_type: str | None = None  # last decision for this project
    hours_since_last_decision: float = 999  # hours since last decision was executed


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


def eval_reconciliation(m: ProjectMetrics) -> RuleResult:
    """Pause if Acciones has state inconsistencies between DB and exchange."""
    if m.reconciliation_issues > 0:
        return RuleResult(
            fired=True, decision_type="PAUSE", confidence=90,
            reason=f"Reconciliation found {m.reconciliation_issues} inconsistencies — data integrity risk",
        )
    return RuleResult(fired=False)


def eval_risk_tighten(m: ProjectMetrics) -> RuleResult:
    """Tighten risk parameters when portfolio score drops below 40."""
    if m.portfolio_score is not None and m.portfolio_score < 40:
        confidence = min(90, 60 + (40 - m.portfolio_score))
        return RuleResult(
            fired=True, decision_type="ADJUST_RISK", confidence=confidence,
            reason=f"Portfolio score {m.portfolio_score:.1f} < 40 — tightening risk parameters",
            requires_human=False,
        )
    return RuleResult(fired=False)


def eval_cb_reset(m: ProjectMetrics) -> RuleResult:
    """Propose RESUME when circuit breaker was active but conditions recovered."""
    if (
        m.circuit_breaker_active_previous
        and not m.circuit_breaker_active
        and m.drawdown_pct is not None
        and m.drawdown_pct < 10
        and m.win_rate_pct is not None
        and m.win_rate_pct >= 40
    ):
        return RuleResult(
            fired=True, decision_type="RESUME", confidence=70,
            reason=f"Circuit breaker recovered: drawdown {m.drawdown_pct:.1f}% < 10%, win rate {m.win_rate_pct:.1f}% stable",
            requires_human=True,
        )
    return RuleResult(fired=False)


# --- Acciones Stocks Rules ---

def eval_stocks_market_hours(m: ProjectMetrics) -> RuleResult:
    """Alert when stock positions are open outside market hours."""
    if not m.is_stock_market_open and m.stocks_positions_open > 0:
        return RuleResult(
            fired=True, decision_type="PAUSE", confidence=85,
            reason=f"{m.stocks_positions_open} stock positions open outside market hours (9:30-16:00 ET)",
        )
    return RuleResult(fired=False)


def eval_stocks_concentration(m: ProjectMetrics) -> RuleResult:
    """Tighten risk if stocks exceed 70% of total capital."""
    if m.stocks_capital and m.total_capital and m.total_capital > 0:
        stocks_pct = (m.stocks_capital / m.total_capital) * 100
        if stocks_pct > 70:
            return RuleResult(
                fired=True, decision_type="ADJUST_RISK", confidence=75,
                reason=f"Stocks concentration {stocks_pct:.0f}% exceeds 70% of total capital",
                requires_human=False,
            )
    return RuleResult(fired=False)


def eval_crypto_stocks_divergence(m: ProjectMetrics) -> RuleResult:
    """Alert when crypto and stocks PnL diverge significantly."""
    if m.crypto_pnl_usd is not None and m.stocks_pnl_usd is not None:
        if m.total_capital and m.total_capital > 0:
            divergence = abs(m.crypto_pnl_usd - m.stocks_pnl_usd) / m.total_capital * 100
            # One deeply negative while other positive
            if divergence > 5 and (
                (m.crypto_pnl_usd < 0 and m.stocks_pnl_usd > 0)
                or (m.crypto_pnl_usd > 0 and m.stocks_pnl_usd < 0)
            ):
                return RuleResult(
                    fired=True, decision_type="PIVOT", confidence=65,
                    reason=f"Crypto/stocks PnL divergence: crypto ${m.crypto_pnl_usd:.2f}, stocks ${m.stocks_pnl_usd:.2f} ({divergence:.1f}% of capital)",
                )
    return RuleResult(fired=False)


# --- Acciones Strategy Rules ---

def eval_strategy_underperform(m: ProjectMetrics) -> RuleResult:
    """Deactivate strategies with win rate < 30% over 50+ trades."""
    for strat in m.strategy_performance:
        trades = strat.get("trades_count", 0)
        win_rate = strat.get("win_rate_pct", 50)
        is_active = strat.get("is_active", True)
        if is_active and trades >= 50 and win_rate < 30:
            return RuleResult(
                fired=True, decision_type="DEACTIVATE_STRATEGY", confidence=80,
                reason=f"Strategy '{strat.get('name', '?')}' win rate {win_rate:.1f}% < 30% over {trades} trades",
                requires_human=False,
            )
    return RuleResult(fired=False)


def eval_strategy_overperform(m: ProjectMetrics) -> RuleResult:
    """Suggest reactivating a deactivated strategy with good shadow performance."""
    for strat in m.strategy_performance:
        is_active = strat.get("is_active", True)
        win_rate = strat.get("win_rate_pct", 0)
        trades = strat.get("trades_count", 0)
        if not is_active and trades >= 30 and win_rate > 60:
            return RuleResult(
                fired=True, decision_type="ACTIVATE_STRATEGY", confidence=65,
                reason=f"Deactivated strategy '{strat.get('name', '?')}' showing {win_rate:.1f}% win rate over {trades} shadow trades",
                requires_human=True,
            )
    return RuleResult(fired=False)


# --- Acciones ML & Paper Rules ---

def eval_ml_shadow_divergence(m: ProjectMetrics) -> RuleResult:
    """Alert when ML shadow signals significantly outperform live trading."""
    if m.ml_shadow_win_rate is not None and m.live_win_rate is not None:
        divergence_pp = m.ml_shadow_win_rate - m.live_win_rate
        if divergence_pp > 15:
            return RuleResult(
                fired=True, decision_type="PIVOT", confidence=70,
                reason=f"ML shadow win rate {m.ml_shadow_win_rate:.1f}% vs live {m.live_win_rate:.1f}% (+{divergence_pp:.1f}pp) — consider enabling ML",
            )
    return RuleResult(fired=False)


def eval_paper_live_divergence(m: ProjectMetrics) -> RuleResult:
    """Alert when paper trading significantly outperforms live."""
    if m.paper_pnl is not None and m.live_pnl is not None:
        if m.total_capital and m.total_capital > 0:
            paper_roi = (m.paper_pnl / m.total_capital) * 100
            live_roi = (m.live_pnl / m.total_capital) * 100
            if paper_roi - live_roi > 5:
                return RuleResult(
                    fired=True, decision_type="PIVOT", confidence=65,
                    reason=f"Paper ROI {paper_roi:.1f}% vs live ROI {live_roi:.1f}% — execution slippage or fear-based overrides likely",
                )
    return RuleResult(fired=False)


def eval_change_penalty(m: ProjectMetrics) -> RuleResult:
    """Suppress decisions if one was recently executed (cost of change)."""
    # If a decision was executed less than 48h ago, don't fire new ones
    # This is checked by the estratega before evaluating other rules
    return RuleResult(fired=False)  # Sentinel - handled in estratega logic


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
    Rule(id="UNIV_BUDGET_EXCEEDED", name="Budget exceeded >150%", applies_to=["acciones", "compraventa", "libro", "casas"], evaluate=eval_budget_exceeded, cooldown_hours=24),
    Rule(id="UNIV_STAGNANT", name="Metrics stagnant", applies_to=["acciones", "compraventa", "libro", "casas"], evaluate=eval_stagnant, cooldown_hours=336),
    # Financial
    Rule(id="FIN_ROI_NEGATIVE", name="ROI < -20%", applies_to=["acciones", "compraventa"], evaluate=eval_roi_negative_30d, cooldown_hours=168),
    Rule(id="FIN_ROI_GROWING", name="ROI positive and growing", applies_to=["acciones", "compraventa"], evaluate=eval_roi_positive_growing, cooldown_hours=72),
    Rule(id="FIN_DRAWDOWN", name="Drawdown > 15%", applies_to=["acciones", "compraventa"], evaluate=eval_drawdown_critical, cooldown_hours=24),
    Rule(id="FIN_WINRATE_DROP", name="Win rate declining", applies_to=["acciones", "compraventa"], evaluate=eval_winrate_declining, cooldown_hours=48),
    # Acciones
    Rule(id="ACC_CIRCUIT_BREAKER", name="Circuit breaker active", applies_to=["acciones"], evaluate=eval_circuit_breaker, cooldown_hours=1),
    Rule(id="ACC_DAILY_LOSS", name="Daily loss > 5%", applies_to=["acciones"], evaluate=eval_daily_loss, cooldown_hours=24),
    Rule(id="ACC_RECONCILIATION", name="Reconciliation inconsistencies", applies_to=["acciones"], evaluate=eval_reconciliation, cooldown_hours=1),
    Rule(id="ACC_RISK_TIGHTEN", name="Tighten risk on low score", applies_to=["acciones"], evaluate=eval_risk_tighten, cooldown_hours=6),
    Rule(id="ACC_CB_RESET", name="Circuit breaker recovery", applies_to=["acciones"], evaluate=eval_cb_reset, cooldown_hours=24),
    # Acciones Stocks
    Rule(id="ACC_STOCKS_MARKET_HOURS", name="Stocks open outside market hours", applies_to=["acciones"], evaluate=eval_stocks_market_hours, cooldown_hours=1),
    Rule(id="ACC_STOCKS_CONCENTRATION", name="Stocks > 70% of capital", applies_to=["acciones"], evaluate=eval_stocks_concentration, cooldown_hours=12),
    Rule(id="ACC_CRYPTO_STOCKS_DIVERGENCE", name="Crypto/stocks PnL divergence", applies_to=["acciones"], evaluate=eval_crypto_stocks_divergence, cooldown_hours=48),
    # Acciones Strategies
    Rule(id="ACC_STRATEGY_UNDERPERFORM", name="Strategy underperforming", applies_to=["acciones"], evaluate=eval_strategy_underperform, cooldown_hours=72),
    Rule(id="ACC_STRATEGY_OVERPERFORM", name="Deactivated strategy overperforming", applies_to=["acciones"], evaluate=eval_strategy_overperform, cooldown_hours=72),
    # Acciones ML & Paper
    Rule(id="ACC_ML_SHADOW_DIVERGENCE", name="ML shadow outperforms live", applies_to=["acciones"], evaluate=eval_ml_shadow_divergence, cooldown_hours=168),
    Rule(id="ACC_PAPER_LIVE_DIVERGENCE", name="Paper outperforms live", applies_to=["acciones"], evaluate=eval_paper_live_divergence, cooldown_hours=168),
    # Libro
    Rule(id="LIB_REVENUE", name="Revenue per book > $5", applies_to=["libro"], evaluate=eval_libro_revenue, cooldown_hours=720),
    Rule(id="LIB_COMPLIANCE", name="KDP compliance HIGH", applies_to=["libro"], evaluate=eval_libro_compliance, cooldown_hours=24),
    # Casas
    Rule(id="CAS_FP_HIGH", name="False positive > 40%", applies_to=["casas"], evaluate=eval_casas_fp_high, cooldown_hours=48),
    Rule(id="CAS_NO_USERS", name="Zero active users", applies_to=["casas"], evaluate=eval_casas_no_users, cooldown_hours=336),
    # Change penalty
    Rule(id="UNIV_CHANGE_PENALTY", name="Recent decision cooldown", applies_to=["*"], evaluate=eval_change_penalty, cooldown_hours=48),
]
