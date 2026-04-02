"""Tests for Phase 2 scoring enrichment: reconciliation, diversification, strategy, approvals."""
from app.engine.scoring import calculate_portfolio_score


BASELINE_ARGS = dict(
    is_healthy=True, roi_pct=None, roi_trend=None,
    win_rate_pct=None, drawdown_pct=None, revenue_usd=None,
    items_processed=None, false_positive_rate=None,
)


class TestReconciliationPenalty:
    def test_reconciliation_ok_no_change(self):
        score = calculate_portfolio_score(**BASELINE_ARGS, reconciliation_ok=True)
        baseline = calculate_portfolio_score(**BASELINE_ARGS)
        assert score == baseline

    def test_reconciliation_bad_loses_30(self):
        ok = calculate_portfolio_score(**BASELINE_ARGS, reconciliation_ok=True)
        bad = calculate_portfolio_score(**BASELINE_ARGS, reconciliation_ok=False)
        assert ok - bad == 30.0


class TestAssetClassDiversification:
    def test_single_asset_no_bonus(self):
        score = calculate_portfolio_score(**BASELINE_ARGS, asset_class_count=1)
        baseline = calculate_portfolio_score(**BASELINE_ARGS)
        assert score == baseline

    def test_two_assets_adds_5(self):
        one = calculate_portfolio_score(**BASELINE_ARGS, asset_class_count=1)
        two = calculate_portfolio_score(**BASELINE_ARGS, asset_class_count=2)
        assert two - one == 5.0


class TestStrategyDiversity:
    def test_single_strategy_no_bonus(self):
        score = calculate_portfolio_score(**BASELINE_ARGS, strategy_diversity=1)
        baseline = calculate_portfolio_score(**BASELINE_ARGS)
        assert score == baseline

    def test_two_strategies_adds_2(self):
        one = calculate_portfolio_score(**BASELINE_ARGS, strategy_diversity=1)
        two = calculate_portfolio_score(**BASELINE_ARGS, strategy_diversity=2)
        assert two - one == 2.0

    def test_four_strategies_capped_at_5(self):
        one = calculate_portfolio_score(**BASELINE_ARGS, strategy_diversity=1)
        four = calculate_portfolio_score(**BASELINE_ARGS, strategy_diversity=4)
        assert four - one == 5.0

    def test_none_no_effect(self):
        score = calculate_portfolio_score(**BASELINE_ARGS, strategy_diversity=None)
        baseline = calculate_portfolio_score(**BASELINE_ARGS)
        assert score == baseline


class TestPendingApprovalsPenalty:
    def test_five_or_less_no_penalty(self):
        score = calculate_portfolio_score(**BASELINE_ARGS, pending_approvals_count=5)
        baseline = calculate_portfolio_score(**BASELINE_ARGS)
        assert score == baseline

    def test_above_five_loses_10(self):
        ok = calculate_portfolio_score(**BASELINE_ARGS, pending_approvals_count=0)
        backlog = calculate_portfolio_score(**BASELINE_ARGS, pending_approvals_count=6)
        assert ok - backlog == 10.0


class TestCombinedEnrichment:
    def test_all_bonuses_stack(self):
        baseline = calculate_portfolio_score(**BASELINE_ARGS)
        enriched = calculate_portfolio_score(
            **BASELINE_ARGS,
            reconciliation_ok=True,
            asset_class_count=2,
            strategy_diversity=3,
        )
        # +5 (assets) + +4 (2 extra strategies * 2) = +9
        assert enriched - baseline == 9.0

    def test_penalties_stack(self):
        baseline = calculate_portfolio_score(**BASELINE_ARGS)
        penalized = calculate_portfolio_score(
            **BASELINE_ARGS,
            reconciliation_ok=False,
            pending_approvals_count=10,
        )
        # -30 (reconciliation) + -10 (approvals) = -40
        assert baseline - penalized == 40.0

    def test_still_clamped_0_100(self):
        score = calculate_portfolio_score(
            is_healthy=False, roi_pct=-100, roi_trend=-10,
            win_rate_pct=0, drawdown_pct=50, revenue_usd=0,
            items_processed=0, false_positive_rate=100,
            reconciliation_ok=False, pending_approvals_count=20,
        )
        assert score == 0

        score = calculate_portfolio_score(
            is_healthy=True, roi_pct=100, roi_trend=10,
            win_rate_pct=100, drawdown_pct=0, revenue_usd=10000,
            items_processed=1000, false_positive_rate=0,
            asset_class_count=3, strategy_diversity=5,
        )
        assert score == 100
