"""Per-project threshold configurations."""

PROJECT_THRESHOLDS = {
    "acciones": {
        "kill_roi_threshold": -20,
        "scale_roi_threshold": 5,
        "max_drawdown": 15,
        "max_daily_loss_pct": 5,
        "eval_window_hours": 168,
        "max_reconciliation_issues": 0,
        "cb_reset_drawdown_threshold": 10,
        "risk_tighten_score": 40,
        "risk_restore_score": 60,
        # Phase 2: stocks + strategies
        "stocks_max_concentration_pct": 70,
        "strategy_underperform_winrate": 30,
        "strategy_underperform_min_trades": 50,
        "ml_shadow_divergence_pp": 15,
        "paper_live_divergence_pct": 5,
    },
    "compraventa": {
        "kill_roi_threshold": -20,
        "scale_roi_threshold": 10,
        "max_drawdown": 15,
        "min_opportunities_per_day": 1,
        "eval_window_hours": 336,
    },
    "libro": {
        "min_revenue_per_book": 5.0,
        "max_kill_rate": 0.6,
        "compliance_risk_threshold": "HIGH",
        "eval_window_hours": 2160,
    },
    "ideas": {
        "min_ideas_per_week": 10,
        "min_top_score": 70,
        "eval_window_hours": 720,
        "is_research_lab": True,  # No financial rules, no KILL
        "max_focus_hours_weekly": 3,  # R&D should be low-maintenance
    },
    "casas": {
        "max_false_positive_rate": 40,
        "min_active_users": 1,
        "min_opportunities_per_day": 1,
        "eval_window_hours": 336,
    },
}
