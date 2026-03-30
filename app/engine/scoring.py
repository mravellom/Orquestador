"""Portfolio scoring system: 0-100 composite score per project."""


def calculate_portfolio_score(
    is_healthy: bool,
    roi_pct: float | None,
    roi_trend: float | None,
    win_rate_pct: float | None,
    drawdown_pct: float | None,
    revenue_usd: float | None,
    items_processed: int | None,
    false_positive_rate: float | None,
    focus_hours_weekly: float | None = None,
) -> float:
    """
    Composite score: health(15%) + financial(35%) + momentum(25%) + efficiency(15%) + risk(10%)
    Returns 0-100.
    """
    # Health (15%)
    health_score = 100.0 if is_healthy else 0.0

    # Financial (35%)
    financial_score = 50.0  # baseline
    if roi_pct is not None:
        if roi_pct > 20:
            financial_score = 100.0
        elif roi_pct > 0:
            financial_score = 50 + (roi_pct / 20) * 50
        elif roi_pct > -20:
            financial_score = 50 + (roi_pct / 20) * 50
        else:
            financial_score = 0.0

    if revenue_usd is not None and revenue_usd > 0:
        financial_score = min(100, financial_score + 10)

    # Momentum (25%)
    momentum_score = 50.0
    if roi_trend is not None:
        if roi_trend > 0:
            momentum_score = min(100, 50 + roi_trend * 100)
        else:
            momentum_score = max(0, 50 + roi_trend * 100)

    # Efficiency (15%)
    efficiency_score = 50.0
    if win_rate_pct is not None:
        efficiency_score = min(100, win_rate_pct)
    if false_positive_rate is not None:
        efficiency_score = max(0, 100 - false_positive_rate * 2)
    if items_processed is not None and items_processed > 0:
        efficiency_score = min(100, efficiency_score + 10)

    # Risk (10%)
    risk_score = 80.0
    if drawdown_pct is not None:
        if drawdown_pct > 20:
            risk_score = 0.0
        elif drawdown_pct > 10:
            risk_score = 50 - (drawdown_pct - 10) * 5
        else:
            risk_score = 100 - drawdown_pct * 2

    # Composite
    score = (
        health_score * 0.15
        + financial_score * 0.35
        + momentum_score * 0.25
        + efficiency_score * 0.15
        + risk_score * 0.10
    )

    # Focus cost penalty: each hour/week of your time costs score points
    if focus_hours_weekly is not None and focus_hours_weekly > 0:
        # More than 5h/week on a single MVP is expensive
        focus_penalty = max(0, (focus_hours_weekly - 2) * 3)  # 3 points per hour above 2h
        score -= focus_penalty

    return round(max(0, min(100, score)), 1)


def evaluate_signal_with_hysteresis(
    current_score: float,
    score_history: list[float],
    current_signal: str,
) -> str:
    """
    Apply hysteresis to prevent oscillating decisions.

    Zones:
    - SCALE: score > 75 for 2+ consecutive cycles
    - KILL:  score < 25 for 3+ consecutive cycles
    - HOLD:  between 30-70
    - DEAD ZONE: 25-30 and 70-75 (no change, keep previous signal)

    Args:
        current_score: latest portfolio score (0-100)
        score_history: last N scores (newest last), at least 3 entries
        current_signal: the current signal for this project ("HOLD", "SCALE", "KILL")

    Returns:
        New signal: "SCALE", "HOLD", or "KILL"
    """
    if len(score_history) < 2:
        # Not enough history, use simple thresholds
        if current_score > 75:
            return "SCALE"
        elif current_score < 25:
            return "KILL"
        return "HOLD"

    # Check SCALE: > 75 for last 2 cycles
    if len(score_history) >= 2 and all(s > 75 for s in score_history[-2:]):
        return "SCALE"

    # Check KILL: < 25 for last 3 cycles
    if len(score_history) >= 3 and all(s < 25 for s in score_history[-3:]):
        return "KILL"

    # Clear HOLD zone
    if 30 <= current_score <= 70:
        return "HOLD"

    # Dead zones (25-30, 70-75): maintain previous signal
    if 25 <= current_score <= 30 or 70 <= current_score <= 75:
        return current_signal

    # Fallback
    return "HOLD"
