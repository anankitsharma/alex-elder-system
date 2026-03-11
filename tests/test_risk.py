"""
Tests for risk management: PositionSizer (2% Rule) and CircuitBreaker (6% Rule).
"""

import pytest
from backend.app.risk.position_sizer import PositionSizer
from backend.app.risk.circuit_breaker import CircuitBreaker


# ===========================================================================
# PositionSizer (2% Rule) Tests
# ===========================================================================

class TestPositionSizer:
    def _make(self, equity=1_000_000, risk_pct=2.0):
        return PositionSizer({
            "account_equity": equity,
            "max_risk_per_trade_pct": risk_pct,
        })

    def test_basic_position_size(self):
        ps = self._make(equity=1_000_000)
        result = ps.calculate_position_size(
            entry_price=100.0,
            stop_price=95.0,
        )
        # Risk: 2% of 10L = 20,000. Risk per share = 5. Shares = 4000
        assert result["is_valid"] is True
        assert result["shares"] == 4000
        assert result["risk_per_share"] == 5.0
        assert result["risk_amount"] == 20000.0

    def test_lot_size_rounding(self):
        ps = self._make(equity=1_000_000)
        result = ps.calculate_position_size(
            entry_price=100.0,
            stop_price=95.0,
            lot_size=1250,
        )
        # 4000 shares / 1250 lot = 3 lots = 3750 shares
        assert result["is_valid"] is True
        assert result["lots"] == 3
        assert result["shares"] == 3750

    def test_sell_direction(self):
        ps = self._make(equity=1_000_000)
        result = ps.calculate_position_size(
            entry_price=95.0,
            stop_price=100.0,
        )
        # Risk per share = 5, same as buy
        assert result["is_valid"] is True
        assert result["shares"] == 4000
        assert result["risk_per_share"] == 5.0

    def test_1_percent_risk(self):
        ps = self._make(equity=1_000_000, risk_pct=1.0)
        result = ps.calculate_position_size(
            entry_price=100.0,
            stop_price=95.0,
        )
        # 1% of 10L = 10,000. 10,000 / 5 = 2000
        assert result["shares"] == 2000

    def test_override_equity(self):
        ps = self._make(equity=500_000)
        result = ps.calculate_position_size(
            entry_price=100.0,
            stop_price=95.0,
            account_equity=1_000_000,
        )
        assert result["shares"] == 4000  # Uses override, not instance

    def test_override_risk_pct(self):
        ps = self._make(equity=1_000_000, risk_pct=2.0)
        result = ps.calculate_position_size(
            entry_price=100.0,
            stop_price=95.0,
            max_risk_pct=1.0,
        )
        assert result["shares"] == 2000

    def test_zero_equity_error(self):
        ps = self._make(equity=0)
        result = ps.calculate_position_size(entry_price=100, stop_price=95)
        assert result["is_valid"] is False

    def test_equal_entry_stop_error(self):
        ps = self._make(equity=1_000_000)
        result = ps.calculate_position_size(entry_price=100, stop_price=100)
        assert result["is_valid"] is False

    def test_negative_entry_error(self):
        ps = self._make(equity=1_000_000)
        result = ps.calculate_position_size(entry_price=-100, stop_price=95)
        assert result["is_valid"] is False

    def test_tight_stop_small_lot(self):
        """Very tight stop with large lot → may get 0 lots."""
        ps = self._make(equity=100_000, risk_pct=2.0)
        result = ps.calculate_position_size(
            entry_price=1000.0,
            stop_price=999.0,
            lot_size=5000,  # Huge lot, risk per share = 1, max shares = 2000
        )
        # 2000 / 5000 = 0 lots
        assert result["shares"] == 0
        assert result["is_valid"] is False

    def test_actual_risk_within_limit(self):
        ps = self._make(equity=1_000_000, risk_pct=2.0)
        result = ps.calculate_position_size(
            entry_price=100.0,
            stop_price=95.0,
        )
        assert result["actual_risk_pct"] <= 2.0

    def test_position_value(self):
        ps = self._make(equity=1_000_000)
        result = ps.calculate_position_size(entry_price=100.0, stop_price=95.0)
        assert result["position_value"] == result["shares"] * 100.0

    def test_validate_trade_risk_within_limit(self):
        ps = self._make(equity=1_000_000, risk_pct=2.0)
        result = ps.validate_trade_risk(risk_amount=15000)
        assert result["is_allowed"] is True
        assert result["actual_risk_pct"] == 1.5

    def test_validate_trade_risk_exceeds_limit(self):
        ps = self._make(equity=1_000_000, risk_pct=2.0)
        result = ps.validate_trade_risk(risk_amount=25000)
        assert result["is_allowed"] is False
        assert result["actual_risk_pct"] == 2.5

    def test_validate_trade_risk_exact_limit(self):
        ps = self._make(equity=1_000_000, risk_pct=2.0)
        result = ps.validate_trade_risk(risk_amount=20000)
        assert result["is_allowed"] is True

    def test_validate_no_equity(self):
        ps = self._make(equity=0)
        result = ps.validate_trade_risk(risk_amount=1000)
        assert result["is_allowed"] is False


# ===========================================================================
# CircuitBreaker (6% Rule) Tests
# ===========================================================================

class TestCircuitBreaker:
    def _make(self, equity=1_000_000, risk_pct=6.0):
        cb = CircuitBreaker({"max_portfolio_risk_pct": risk_pct})
        cb.set_month_start_equity(equity)
        return cb

    def test_initial_state(self):
        cb = self._make()
        status = cb.check_can_trade()
        assert status["is_allowed"] is True
        assert status["is_halted"] is False
        assert status["exposure_pct"] == 0.0

    def test_record_loss_within_limit(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(30_000)  # 3% — under 6%
        status = cb.check_can_trade()
        assert status["is_allowed"] is True
        assert status["realized_losses"] == 30_000

    def test_record_loss_exceeds_limit(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(60_000)  # 6% — triggers halt
        status = cb.check_can_trade()
        assert status["is_allowed"] is False
        assert status["is_halted"] is True
        assert "6% Rule" in status.get("halt_reason", "")

    def test_cumulative_losses(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(20_000)  # 2%
        cb.record_loss(20_000)  # 4%
        assert cb.check_can_trade()["is_allowed"] is True
        cb.record_loss(20_000)  # 6% — halt
        assert cb.check_can_trade()["is_allowed"] is False

    def test_open_positions_risk(self):
        cb = self._make(equity=1_000_000)
        cb.update_open_positions([
            {"entry_price": 100, "stop_price": 95, "shares": 4000, "direction": "BUY"},
            # Risk = 5 * 4000 = 20,000 (2%)
        ])
        status = cb.check_can_trade()
        assert status["is_allowed"] is True
        assert status["open_risk"] == 20_000

    def test_combined_loss_and_open_risk(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(30_000)  # 3%
        cb.update_open_positions([
            {"entry_price": 100, "stop_price": 95, "shares": 6000, "direction": "BUY"},
            # Risk = 5 * 6000 = 30,000 (3%)
        ])
        # Total: 3% + 3% = 6% → halt
        status = cb.check_can_trade()
        assert status["is_allowed"] is False

    def test_check_new_trade_risk_allowed(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(20_000)  # 2%
        result = cb.check_new_trade_risk(additional_risk=20_000)
        assert result["is_allowed"] is True  # 4% total

    def test_check_new_trade_risk_denied(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(40_000)  # 4%
        result = cb.check_new_trade_risk(additional_risk=25_000)
        assert result["is_allowed"] is False  # 6.5% would breach

    def test_force_halt(self):
        cb = self._make()
        cb.force_halt("Manual intervention")
        assert cb.check_can_trade()["is_allowed"] is False
        assert cb.is_halted is True

    def test_reset_halt(self):
        cb = self._make()
        cb.force_halt("Test")
        cb.reset_halt()
        assert cb.check_can_trade()["is_allowed"] is True

    def test_sell_position_risk(self):
        cb = self._make(equity=1_000_000)
        cb.update_open_positions([
            {"entry_price": 95, "stop_price": 100, "shares": 4000, "direction": "SELL"},
            # Risk = (100 - 95) * 4000 = 20,000
        ])
        status = cb.check_can_trade()
        assert status["open_risk"] == 20_000

    def test_no_equity_set(self):
        cb = CircuitBreaker({"max_portfolio_risk_pct": 6.0})
        # No month_start_equity set
        status = cb.check_can_trade()
        assert status["is_allowed"] is True  # Inactive without equity

    def test_status_details(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(10_000)
        status = cb.get_status()
        assert "realized_losses" in status
        assert "open_risk" in status
        assert "total_exposure" in status
        assert "remaining_budget" in status
        assert "max_portfolio_risk_pct" in status

    def test_remaining_budget(self):
        cb = self._make(equity=1_000_000)
        cb.record_loss(20_000)
        status = cb.check_can_trade()
        # Max: 60,000. Used: 20,000. Remaining: 40,000
        assert status["remaining_budget"] == 40_000

    def test_negative_risk_ignored(self):
        """Negative loss (i.e., a profit) should not count."""
        cb = self._make(equity=1_000_000)
        cb.record_loss(-5000)  # Profit, not loss
        status = cb.check_can_trade()
        assert status["realized_losses"] == 0  # Should not add negative
