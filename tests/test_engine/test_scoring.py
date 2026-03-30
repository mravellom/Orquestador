"""Tests for portfolio scoring and hysteresis."""
import pytest
from app.engine.scoring import calculate_portfolio_score, evaluate_signal_with_hysteresis


class TestCalculatePortfolioScore:
    def test_all_none_returns_baseline(self):
        score = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        # health=100*0.15 + financial=50*0.35 + momentum=50*0.25 + efficiency=50*0.15 + risk=80*0.10
        # = 15 + 17.5 + 12.5 + 7.5 + 8 = 60.5
        assert score == 60.5

    def test_unhealthy_loses_15_points(self):
        healthy = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        unhealthy = calculate_portfolio_score(
            is_healthy=False, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        assert healthy - unhealthy == 15.0

    def test_roi_20_gives_max_financial(self):
        score = calculate_portfolio_score(
            is_healthy=True, roi_pct=20, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        # financial = 100 * 0.35 = 35 (vs baseline 50*0.35=17.5, diff = 17.5)
        baseline = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        assert score > baseline

    def test_roi_0_gives_mid_financial(self):
        score = calculate_portfolio_score(
            is_healthy=True, roi_pct=0, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        # roi=0: financial_score = 50 + (0/20)*50 = 50 (same as baseline)
        baseline = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        assert score == baseline

    def test_roi_minus20_gives_zero_financial(self):
        score = calculate_portfolio_score(
            is_healthy=True, roi_pct=-20, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        # roi=-20: financial=0. Diff from baseline = -17.5
        baseline = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        assert score < baseline

    def test_revenue_positive_adds_bonus(self):
        without = calculate_portfolio_score(
            is_healthy=True, roi_pct=10, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        with_rev = calculate_portfolio_score(
            is_healthy=True, roi_pct=10, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=100,
            items_processed=None, false_positive_rate=None,
        )
        assert with_rev > without

    def test_drawdown_20_gives_zero_risk(self):
        score = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=20, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        baseline = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        assert score < baseline

    def test_focus_2h_no_penalty(self):
        without = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
            focus_hours_weekly=None,
        )
        with_2h = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
            focus_hours_weekly=2,
        )
        assert without == with_2h

    def test_focus_5h_penalizes_9_points(self):
        without = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
        )
        with_5h = calculate_portfolio_score(
            is_healthy=True, roi_pct=None, roi_trend=None,
            win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
            items_processed=None, false_positive_rate=None,
            focus_hours_weekly=5,
        )
        assert without - with_5h == 9.0

    def test_score_clamped_0_to_100(self):
        # Extreme positive
        high = calculate_portfolio_score(
            is_healthy=True, roi_pct=100, roi_trend=10,
            win_rate_pct=100, drawdown_pct=0, revenue_usd=10000,
            items_processed=1000, false_positive_rate=0,
        )
        assert 0 <= high <= 100

        # Extreme negative
        low = calculate_portfolio_score(
            is_healthy=False, roi_pct=-100, roi_trend=-10,
            win_rate_pct=0, drawdown_pct=50, revenue_usd=0,
            items_processed=0, false_positive_rate=100,
            focus_hours_weekly=20,
        )
        assert 0 <= low <= 100


class TestHysteresis:
    def test_empty_history_high_score_returns_scale(self):
        signal = evaluate_signal_with_hysteresis(80, [], "HOLD")
        assert signal == "SCALE"

    def test_empty_history_low_score_returns_kill(self):
        signal = evaluate_signal_with_hysteresis(20, [], "HOLD")
        assert signal == "KILL"

    def test_empty_history_mid_score_returns_hold(self):
        signal = evaluate_signal_with_hysteresis(50, [], "HOLD")
        assert signal == "HOLD"

    def test_single_element_history_high_score(self):
        signal = evaluate_signal_with_hysteresis(80, [80], "HOLD")
        assert signal == "SCALE"

    def test_scale_requires_two_cycles_above_75(self):
        signal = evaluate_signal_with_hysteresis(82, [80, 82], "HOLD")
        assert signal == "SCALE"

    def test_no_scale_single_spike(self):
        signal = evaluate_signal_with_hysteresis(80, [60, 80], "HOLD")
        assert signal != "SCALE"

    def test_kill_requires_three_cycles_below_25(self):
        signal = evaluate_signal_with_hysteresis(18, [20, 22, 18], "HOLD")
        assert signal == "KILL"

    def test_no_kill_only_two_cycles_low(self):
        signal = evaluate_signal_with_hysteresis(22, [20, 22], "HOLD")
        assert signal != "KILL"

    def test_dead_zone_70_75_keeps_previous(self):
        signal = evaluate_signal_with_hysteresis(72, [65, 72], "HOLD")
        assert signal == "HOLD"

    def test_dead_zone_25_30_keeps_previous(self):
        signal = evaluate_signal_with_hysteresis(27, [35, 27], "HOLD")
        assert signal == "HOLD"

    def test_clear_hold_zone(self):
        signal = evaluate_signal_with_hysteresis(50, [45, 50, 55], "SCALE")
        assert signal == "HOLD"

    def test_boundary_75_is_dead_zone(self):
        signal = evaluate_signal_with_hysteresis(75, [70, 75], "HOLD")
        assert signal == "HOLD"

    def test_boundary_30_is_hold_zone(self):
        signal = evaluate_signal_with_hysteresis(30, [35, 30], "SCALE")
        assert signal == "HOLD"
