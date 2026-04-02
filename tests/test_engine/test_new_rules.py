"""Tests for Phase 1-2 rules: reconciliation, risk tighten, CB reset, stocks, strategies, ML, paper."""
import pytest
from app.engine.rules import (
    eval_reconciliation,
    eval_risk_tighten,
    eval_cb_reset,
    eval_stocks_market_hours,
    eval_stocks_concentration,
    eval_crypto_stocks_divergence,
    eval_strategy_underperform,
    eval_strategy_overperform,
    eval_ml_shadow_divergence,
    eval_paper_live_divergence,
)


# --- Reconciliation ---

class TestReconciliation:
    def test_fires_on_issues(self, acciones_metrics):
        acciones_metrics.reconciliation_issues = 3
        result = eval_reconciliation(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"
        assert result.confidence == 90

    def test_no_fire_zero_issues(self, acciones_metrics):
        acciones_metrics.reconciliation_issues = 0
        result = eval_reconciliation(acciones_metrics)
        assert result.fired is False

    def test_fires_on_single_issue(self, acciones_metrics):
        acciones_metrics.reconciliation_issues = 1
        result = eval_reconciliation(acciones_metrics)
        assert result.fired is True


# --- Risk Tighten ---

class TestRiskTighten:
    def test_fires_below_40(self, acciones_metrics):
        acciones_metrics.portfolio_score = 35
        result = eval_risk_tighten(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "ADJUST_RISK"
        assert result.requires_human is False

    def test_no_fire_at_40(self, acciones_metrics):
        acciones_metrics.portfolio_score = 40
        result = eval_risk_tighten(acciones_metrics)
        assert result.fired is False

    def test_no_fire_above_40(self, acciones_metrics):
        acciones_metrics.portfolio_score = 60
        result = eval_risk_tighten(acciones_metrics)
        assert result.fired is False

    def test_no_fire_when_none(self, acciones_metrics):
        acciones_metrics.portfolio_score = None
        result = eval_risk_tighten(acciones_metrics)
        assert result.fired is False

    def test_confidence_scales_with_low_score(self, acciones_metrics):
        acciones_metrics.portfolio_score = 20
        result = eval_risk_tighten(acciones_metrics)
        assert result.fired is True
        assert result.confidence == 80  # 60 + (40 - 20) = 80


# --- Circuit Breaker Reset ---

class TestCBReset:
    def test_fires_on_recovery(self, acciones_metrics):
        acciones_metrics.circuit_breaker_active_previous = True
        acciones_metrics.circuit_breaker_active = False
        acciones_metrics.drawdown_pct = 5
        acciones_metrics.win_rate_pct = 55
        result = eval_cb_reset(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "RESUME"
        assert result.requires_human is True

    def test_no_fire_cb_still_active(self, acciones_metrics):
        acciones_metrics.circuit_breaker_active_previous = True
        acciones_metrics.circuit_breaker_active = True
        acciones_metrics.drawdown_pct = 5
        acciones_metrics.win_rate_pct = 55
        result = eval_cb_reset(acciones_metrics)
        assert result.fired is False

    def test_no_fire_drawdown_too_high(self, acciones_metrics):
        acciones_metrics.circuit_breaker_active_previous = True
        acciones_metrics.circuit_breaker_active = False
        acciones_metrics.drawdown_pct = 12
        acciones_metrics.win_rate_pct = 55
        result = eval_cb_reset(acciones_metrics)
        assert result.fired is False

    def test_no_fire_win_rate_too_low(self, acciones_metrics):
        acciones_metrics.circuit_breaker_active_previous = True
        acciones_metrics.circuit_breaker_active = False
        acciones_metrics.drawdown_pct = 5
        acciones_metrics.win_rate_pct = 30
        result = eval_cb_reset(acciones_metrics)
        assert result.fired is False

    def test_no_fire_cb_was_not_active(self, acciones_metrics):
        acciones_metrics.circuit_breaker_active_previous = False
        acciones_metrics.circuit_breaker_active = False
        acciones_metrics.drawdown_pct = 5
        acciones_metrics.win_rate_pct = 55
        result = eval_cb_reset(acciones_metrics)
        assert result.fired is False


# --- Stocks Market Hours ---

class TestStocksMarketHours:
    def test_fires_outside_hours_with_positions(self, acciones_metrics):
        acciones_metrics.is_stock_market_open = False
        acciones_metrics.stocks_positions_open = 3
        result = eval_stocks_market_hours(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"

    def test_no_fire_during_hours(self, acciones_metrics):
        acciones_metrics.is_stock_market_open = True
        acciones_metrics.stocks_positions_open = 3
        result = eval_stocks_market_hours(acciones_metrics)
        assert result.fired is False

    def test_no_fire_no_positions(self, acciones_metrics):
        acciones_metrics.is_stock_market_open = False
        acciones_metrics.stocks_positions_open = 0
        result = eval_stocks_market_hours(acciones_metrics)
        assert result.fired is False


# --- Stocks Concentration ---

class TestStocksConcentration:
    def test_fires_above_70_pct(self, acciones_metrics):
        acciones_metrics.stocks_capital = 8000
        acciones_metrics.total_capital = 10000
        result = eval_stocks_concentration(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "ADJUST_RISK"

    def test_no_fire_at_70_pct(self, acciones_metrics):
        acciones_metrics.stocks_capital = 7000
        acciones_metrics.total_capital = 10000
        result = eval_stocks_concentration(acciones_metrics)
        assert result.fired is False

    def test_no_fire_no_stocks(self, acciones_metrics):
        acciones_metrics.stocks_capital = None
        acciones_metrics.total_capital = 10000
        result = eval_stocks_concentration(acciones_metrics)
        assert result.fired is False


# --- Crypto Stocks Divergence ---

class TestCryptoStocksDivergence:
    def test_fires_on_divergence(self, acciones_metrics):
        acciones_metrics.crypto_pnl_usd = -600
        acciones_metrics.stocks_pnl_usd = 200
        acciones_metrics.total_capital = 10000
        result = eval_crypto_stocks_divergence(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "PIVOT"

    def test_no_fire_same_direction(self, acciones_metrics):
        acciones_metrics.crypto_pnl_usd = 200
        acciones_metrics.stocks_pnl_usd = 300
        acciones_metrics.total_capital = 10000
        result = eval_crypto_stocks_divergence(acciones_metrics)
        assert result.fired is False

    def test_no_fire_small_divergence(self, acciones_metrics):
        acciones_metrics.crypto_pnl_usd = -100
        acciones_metrics.stocks_pnl_usd = 100
        acciones_metrics.total_capital = 10000
        result = eval_crypto_stocks_divergence(acciones_metrics)
        assert result.fired is False

    def test_no_fire_missing_data(self, acciones_metrics):
        acciones_metrics.crypto_pnl_usd = None
        acciones_metrics.stocks_pnl_usd = 200
        result = eval_crypto_stocks_divergence(acciones_metrics)
        assert result.fired is False


# --- Strategy Underperform ---

class TestStrategyUnderperform:
    def test_fires_low_winrate_enough_trades(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "BadStrat", "is_active": True, "win_rate_pct": 25, "trades_count": 60},
        ]
        result = eval_strategy_underperform(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "DEACTIVATE_STRATEGY"

    def test_no_fire_good_winrate(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "GoodStrat", "is_active": True, "win_rate_pct": 55, "trades_count": 100},
        ]
        result = eval_strategy_underperform(acciones_metrics)
        assert result.fired is False

    def test_no_fire_not_enough_trades(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "NewStrat", "is_active": True, "win_rate_pct": 20, "trades_count": 10},
        ]
        result = eval_strategy_underperform(acciones_metrics)
        assert result.fired is False

    def test_no_fire_inactive_strategy(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "OldStrat", "is_active": False, "win_rate_pct": 20, "trades_count": 100},
        ]
        result = eval_strategy_underperform(acciones_metrics)
        assert result.fired is False

    def test_fires_on_worst_strategy(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "Good", "is_active": True, "win_rate_pct": 60, "trades_count": 100},
            {"name": "Bad", "is_active": True, "win_rate_pct": 20, "trades_count": 80},
        ]
        result = eval_strategy_underperform(acciones_metrics)
        assert result.fired is True
        assert "Bad" in result.reason


# --- Strategy Overperform ---

class TestStrategyOverperform:
    def test_fires_deactivated_good_performance(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "OldGold", "is_active": False, "win_rate_pct": 70, "trades_count": 50},
        ]
        result = eval_strategy_overperform(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "ACTIVATE_STRATEGY"
        assert result.requires_human is True

    def test_no_fire_active_strategy(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "Active", "is_active": True, "win_rate_pct": 70, "trades_count": 50},
        ]
        result = eval_strategy_overperform(acciones_metrics)
        assert result.fired is False

    def test_no_fire_low_winrate(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "Meh", "is_active": False, "win_rate_pct": 45, "trades_count": 50},
        ]
        result = eval_strategy_overperform(acciones_metrics)
        assert result.fired is False

    def test_no_fire_not_enough_trades(self, acciones_metrics):
        acciones_metrics.strategy_performance = [
            {"name": "New", "is_active": False, "win_rate_pct": 80, "trades_count": 10},
        ]
        result = eval_strategy_overperform(acciones_metrics)
        assert result.fired is False


# --- ML Shadow Divergence ---

class TestMLShadowDivergence:
    def test_fires_above_15pp(self, acciones_metrics):
        acciones_metrics.ml_shadow_win_rate = 70
        acciones_metrics.live_win_rate = 50
        result = eval_ml_shadow_divergence(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "PIVOT"

    def test_no_fire_at_15pp(self, acciones_metrics):
        acciones_metrics.ml_shadow_win_rate = 65
        acciones_metrics.live_win_rate = 50
        result = eval_ml_shadow_divergence(acciones_metrics)
        assert result.fired is False

    def test_no_fire_ml_worse(self, acciones_metrics):
        acciones_metrics.ml_shadow_win_rate = 40
        acciones_metrics.live_win_rate = 55
        result = eval_ml_shadow_divergence(acciones_metrics)
        assert result.fired is False

    def test_no_fire_missing_data(self, acciones_metrics):
        acciones_metrics.ml_shadow_win_rate = None
        acciones_metrics.live_win_rate = 50
        result = eval_ml_shadow_divergence(acciones_metrics)
        assert result.fired is False


# --- Paper Live Divergence ---

class TestPaperLiveDivergence:
    def test_fires_paper_much_better(self, acciones_metrics):
        acciones_metrics.paper_pnl = 1000
        acciones_metrics.live_pnl = 200
        acciones_metrics.total_capital = 10000
        result = eval_paper_live_divergence(acciones_metrics)
        assert result.fired is True
        assert result.decision_type == "PIVOT"

    def test_no_fire_similar_performance(self, acciones_metrics):
        acciones_metrics.paper_pnl = 500
        acciones_metrics.live_pnl = 400
        acciones_metrics.total_capital = 10000
        result = eval_paper_live_divergence(acciones_metrics)
        assert result.fired is False

    def test_no_fire_live_better(self, acciones_metrics):
        acciones_metrics.paper_pnl = 200
        acciones_metrics.live_pnl = 800
        acciones_metrics.total_capital = 10000
        result = eval_paper_live_divergence(acciones_metrics)
        assert result.fired is False

    def test_no_fire_missing_data(self, acciones_metrics):
        acciones_metrics.paper_pnl = None
        acciones_metrics.live_pnl = 200
        acciones_metrics.total_capital = 10000
        result = eval_paper_live_divergence(acciones_metrics)
        assert result.fired is False

    def test_no_fire_zero_capital(self, acciones_metrics):
        acciones_metrics.paper_pnl = 1000
        acciones_metrics.live_pnl = 200
        acciones_metrics.total_capital = 0
        result = eval_paper_live_divergence(acciones_metrics)
        assert result.fired is False
