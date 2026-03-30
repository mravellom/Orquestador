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

    return round(max(0, min(100, score)), 1)
