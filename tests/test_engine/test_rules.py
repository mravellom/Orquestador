"""Tests for all 13+ decision engine rules."""
import pytest
from app.engine.rules import (
    ProjectMetrics,
    eval_health_dead,
    eval_budget_exceeded,
    eval_stagnant,
    eval_roi_negative_30d,
    eval_roi_positive_growing,
    eval_drawdown_critical,
    eval_winrate_declining,
    eval_circuit_breaker,
    eval_daily_loss,
    eval_libro_revenue,
    eval_libro_compliance,
    eval_casas_fp_high,
    eval_casas_no_users,
    eval_change_penalty,
)


# --- Health Dead ---

class TestHealthDead:
    def test_fires_at_24h(self, base_metrics):
        base_metrics.unhealthy_hours = 24
        result = eval_health_dead(base_metrics)
        assert result.fired is True
        assert result.decision_type == "KILL"
        assert result.confidence == 90

    def test_no_fire_at_23h(self, base_metrics):
        base_metrics.unhealthy_hours = 23
        result = eval_health_dead(base_metrics)
        assert result.fired is False

    def test_fires_above_24h(self, base_metrics):
        base_metrics.unhealthy_hours = 48
        result = eval_health_dead(base_metrics)
        assert result.fired is True


# --- Budget Exceeded ---

class TestBudgetExceeded:
    def test_fires_at_151_pct(self, base_metrics):
        base_metrics.monthly_budget = 100
        base_metrics.monthly_spend = 151
        result = eval_budget_exceeded(base_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"
        assert result.confidence == 95

    def test_no_fire_at_150_pct(self, base_metrics):
        base_metrics.monthly_budget = 100
        base_metrics.monthly_spend = 150
        result = eval_budget_exceeded(base_metrics)
        assert result.fired is False

    def test_no_fire_zero_budget(self, base_metrics):
        base_metrics.monthly_budget = 0
        base_metrics.monthly_spend = 1000
        result = eval_budget_exceeded(base_metrics)
        assert result.fired is False


# --- Stagnant ---

class TestStagnant:
    def test_fires_at_2x_window(self, base_metrics):
        base_metrics.eval_window_hours = 720
        base_metrics.metric_unchanged_hours = 1440
        result = eval_stagnant(base_metrics)
        assert result.fired is True
        assert result.decision_type == "PIVOT"

    def test_no_fire_below_threshold(self, base_metrics):
        base_metrics.eval_window_hours = 720
        base_metrics.metric_unchanged_hours = 1439
        result = eval_stagnant(base_metrics)
        assert result.fired is False


# --- ROI Negative ---

class TestRoiNegative:
    def test_fires_below_minus20(self, base_metrics):
        base_metrics.roi_pct = -21
        result = eval_roi_negative_30d(base_metrics)
        assert result.fired is True
        assert result.decision_type == "KILL"
        assert result.confidence == 80

    def test_no_fire_at_minus20(self, base_metrics):
        base_metrics.roi_pct = -20
        result = eval_roi_negative_30d(base_metrics)
        assert result.fired is False

    def test_no_fire_when_none(self, base_metrics):
        base_metrics.roi_pct = None
        result = eval_roi_negative_30d(base_metrics)
        assert result.fired is False

    def test_requires_human_real_money(self, acciones_metrics):
        acciones_metrics.roi_pct = -25
        result = eval_roi_negative_30d(acciones_metrics)
        assert result.fired is True
        assert result.requires_human is True

    def test_no_human_paper(self, base_metrics):
        base_metrics.roi_pct = -25
        base_metrics.handles_real_money = False
        result = eval_roi_negative_30d(base_metrics)
        assert result.fired is True
        assert result.requires_human is False


# --- ROI Positive Growing ---

class TestRoiPositiveGrowing:
    def test_fires_both_positive(self, base_metrics):
        base_metrics.roi_pct = 10
        base_metrics.roi_trend = 0.5
        result = eval_roi_positive_growing(base_metrics)
        assert result.fired is True
        assert result.decision_type == "SCALE"

    def test_no_fire_trend_zero(self, base_metrics):
        base_metrics.roi_pct = 10
        base_metrics.roi_trend = 0
        result = eval_roi_positive_growing(base_metrics)
        assert result.fired is False

    def test_no_fire_roi_zero(self, base_metrics):
        base_metrics.roi_pct = 0
        base_metrics.roi_trend = 0.5
        result = eval_roi_positive_growing(base_metrics)
        assert result.fired is False

    def test_confidence_capped_at_95(self, base_metrics):
        base_metrics.roi_pct = 50
        base_metrics.roi_trend = 1
        result = eval_roi_positive_growing(base_metrics)
        assert result.fired is True
        assert result.confidence == 95


# --- Drawdown Critical ---

class TestDrawdownCritical:
    def test_fires_above_15(self, base_metrics):
        base_metrics.drawdown_pct = 15.1
        result = eval_drawdown_critical(base_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"

    def test_no_fire_at_15(self, base_metrics):
        base_metrics.drawdown_pct = 15
        result = eval_drawdown_critical(base_metrics)
        assert result.fired is False


# --- Win Rate Declining ---

class TestWinrateDeclining:
    def test_fires_below_minus10(self, base_metrics):
        base_metrics.win_rate_delta_7d = -11
        result = eval_winrate_declining(base_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"

    def test_no_fire_at_minus10(self, base_metrics):
        base_metrics.win_rate_delta_7d = -10
        result = eval_winrate_declining(base_metrics)
        assert result.fired is False


# --- Circuit Breaker ---

class TestCircuitBreaker:
    def test_fires_when_active(self, base_metrics):
        base_metrics.circuit_breaker_active = True
        result = eval_circuit_breaker(base_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"

    def test_no_fire_when_inactive(self, base_metrics):
        base_metrics.circuit_breaker_active = False
        result = eval_circuit_breaker(base_metrics)
        assert result.fired is False


# --- Daily Loss ---

class TestDailyLoss:
    def test_fires_negative_pnl_and_roi(self, base_metrics):
        base_metrics.pnl_usd = -100
        base_metrics.roi_pct = -6
        result = eval_daily_loss(base_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"

    def test_no_fire_pnl_neg_roi_ok(self, base_metrics):
        base_metrics.pnl_usd = -100
        base_metrics.roi_pct = -4
        result = eval_daily_loss(base_metrics)
        assert result.fired is False


# --- Libro Revenue ---

class TestLibroRevenue:
    def test_fires_above_5_per_book(self, libro_metrics):
        libro_metrics.revenue_usd = 60
        libro_metrics.items_processed = 10
        result = eval_libro_revenue(libro_metrics)
        assert result.fired is True
        assert result.decision_type == "SCALE"

    def test_no_fire_zero_items(self, libro_metrics):
        libro_metrics.revenue_usd = 60
        libro_metrics.items_processed = 0
        result = eval_libro_revenue(libro_metrics)
        assert result.fired is False

    def test_no_fire_at_5_per_book(self, libro_metrics):
        libro_metrics.revenue_usd = 50
        libro_metrics.items_processed = 10
        result = eval_libro_revenue(libro_metrics)
        assert result.fired is False


# --- Libro Compliance ---

class TestLibroCompliance:
    def test_fires_high(self, libro_metrics):
        libro_metrics.compliance_risk = "HIGH"
        result = eval_libro_compliance(libro_metrics)
        assert result.fired is True
        assert result.decision_type == "PAUSE"

    def test_no_fire_medium(self, libro_metrics):
        libro_metrics.compliance_risk = "MEDIUM"
        result = eval_libro_compliance(libro_metrics)
        assert result.fired is False


# --- Casas FP ---

class TestCasasFP:
    def test_fires_above_40(self, casas_metrics):
        casas_metrics.false_positive_rate = 41
        result = eval_casas_fp_high(casas_metrics)
        assert result.fired is True
        assert result.decision_type == "PIVOT"

    def test_no_fire_at_40(self, casas_metrics):
        casas_metrics.false_positive_rate = 40
        result = eval_casas_fp_high(casas_metrics)
        assert result.fired is False


# --- Casas No Users ---

class TestCasasNoUsers:
    def test_fires_zero_healthy(self, casas_metrics):
        casas_metrics.active_users = 0
        casas_metrics.unhealthy_hours = 0
        result = eval_casas_no_users(casas_metrics)
        assert result.fired is True
        assert result.decision_type == "KILL"

    def test_no_fire_zero_unhealthy(self, casas_metrics):
        casas_metrics.active_users = 0
        casas_metrics.unhealthy_hours = 1
        result = eval_casas_no_users(casas_metrics)
        assert result.fired is False

    def test_no_fire_has_users(self, casas_metrics):
        casas_metrics.active_users = 5
        casas_metrics.unhealthy_hours = 0
        result = eval_casas_no_users(casas_metrics)
        assert result.fired is False


# --- Change Penalty (sentinel) ---

class TestChangePenalty:
    def test_never_fires(self, base_metrics):
        result = eval_change_penalty(base_metrics)
        assert result.fired is False
