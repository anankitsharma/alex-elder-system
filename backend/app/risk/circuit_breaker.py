"""
Portfolio Circuit Breaker — Elder's 6% Rule

The 6% Rule: Stop trading for the rest of the month if total open risk
plus closed losses exceed 6% of account equity at month start.

Open risk = sum of (entry - stop) × shares for all open positions.
Closed losses = sum of realized losses in current month.

When the 6% threshold is breached:
1. Close all open positions
2. Cancel all pending orders
3. Halt new trading until next month

This is the most important money management rule in Elder's system.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, date
from loguru import logger


class CircuitBreaker:
    """
    Elder's 6% Rule circuit breaker.

    Tracks:
    - Month-start equity
    - Open risk from all positions
    - Realized losses in current month
    - Combined exposure check
    """

    def __init__(self, config: Dict[str, Any]):
        self.max_portfolio_risk_pct = config.get("max_portfolio_risk_pct", 6.0)
        self.month_start_equity = config.get("month_start_equity", 0.0)

        # State
        self.is_halted = False
        self.halt_reason: Optional[str] = None
        self.halt_timestamp: Optional[datetime] = None
        self.current_month: Optional[str] = None  # "YYYY-MM"

        # Tracking
        self.realized_losses: float = 0.0
        self.open_positions: List[Dict[str, Any]] = []

        self._init_month()

    def _init_month(self):
        """Initialize or reset for current month."""
        now_month = date.today().strftime("%Y-%m")
        if self.current_month != now_month:
            self.current_month = now_month
            self.realized_losses = 0.0
            self.is_halted = False
            self.halt_reason = None
            self.halt_timestamp = None
            logger.info(f"Circuit breaker: new month {now_month}")

    def set_month_start_equity(self, equity: float):
        """Set month-start equity (call at start of each month)."""
        self.month_start_equity = equity
        self._init_month()
        logger.info(f"Month-start equity set: {equity:.2f}")

    def record_loss(self, loss_amount: float):
        """Record a realized loss (positive number = loss)."""
        self._init_month()
        if loss_amount > 0:
            self.realized_losses += loss_amount
            logger.debug(f"Recorded loss: {loss_amount:.2f}, total: {self.realized_losses:.2f}")
            self._check_threshold()

    def update_open_positions(self, positions: List[Dict[str, Any]]):
        """
        Update the list of open positions for risk calculation.

        Each position dict should have:
        - entry_price: float
        - stop_price: float
        - shares: int
        - direction: "BUY" or "SELL"
        """
        self._init_month()
        self.open_positions = positions
        self._check_threshold()

    def check_can_trade(self) -> Dict[str, Any]:
        """
        Check if new trades are allowed under the 6% rule.

        Returns:
            Dict with is_allowed, current exposure details
        """
        self._init_month()

        if self.month_start_equity <= 0:
            return {
                "is_allowed": not self.is_halted,
                "is_halted": self.is_halted,
                "halt_reason": self.halt_reason,
                "month_start_equity": 0,
                "realized_losses": 0,
                "open_risk": 0,
                "total_exposure": 0,
                "max_allowed": 0,
                "exposure_pct": 0,
                "max_portfolio_risk_pct": self.max_portfolio_risk_pct,
                "remaining_budget": 0,
                "current_month": self.current_month,
                "open_positions_count": len(self.open_positions),
            }

        open_risk = self._calculate_open_risk()
        total_exposure = self.realized_losses + open_risk
        max_allowed = self.month_start_equity * (self.max_portfolio_risk_pct / 100.0)
        exposure_pct = (total_exposure / self.month_start_equity) * 100.0

        is_allowed = not self.is_halted and total_exposure < max_allowed

        return {
            "is_allowed": is_allowed,
            "is_halted": self.is_halted,
            "halt_reason": self.halt_reason,
            "month_start_equity": self.month_start_equity,
            "realized_losses": round(self.realized_losses, 2),
            "open_risk": round(open_risk, 2),
            "total_exposure": round(total_exposure, 2),
            "max_allowed": round(max_allowed, 2),
            "exposure_pct": round(exposure_pct, 4),
            "max_portfolio_risk_pct": self.max_portfolio_risk_pct,
            "remaining_budget": round(max_allowed - total_exposure, 2),
            "current_month": self.current_month,
            "open_positions_count": len(self.open_positions),
        }

    def check_new_trade_risk(
        self, additional_risk: float
    ) -> Dict[str, Any]:
        """
        Check if adding a new trade would breach the 6% limit.

        Args:
            additional_risk: Risk amount of the proposed new trade
        """
        status = self.check_can_trade()

        if not status["is_allowed"]:
            return {
                "is_allowed": False,
                "reason": status.get("halt_reason", "Circuit breaker active"),
                **status,
            }

        new_total = status["total_exposure"] + additional_risk
        max_allowed = status["max_allowed"]

        would_breach = new_total > max_allowed

        return {
            "is_allowed": not would_breach,
            "reason": "Would breach 6% limit" if would_breach else "Within limits",
            "current_exposure": status["total_exposure"],
            "additional_risk": round(additional_risk, 2),
            "projected_exposure": round(new_total, 2),
            "max_allowed": max_allowed,
            "projected_pct": round((new_total / self.month_start_equity) * 100.0, 4) if self.month_start_equity > 0 else 0,
        }

    def force_halt(self, reason: str = "Manual halt"):
        """Manually halt trading."""
        self.is_halted = True
        self.halt_reason = reason
        self.halt_timestamp = datetime.now()
        logger.warning(f"Circuit breaker HALTED: {reason}")

    def reset_halt(self):
        """Manually reset halt (use with caution)."""
        self.is_halted = False
        self.halt_reason = None
        self.halt_timestamp = None
        logger.info("Circuit breaker halt reset")

    def get_status(self) -> Dict[str, Any]:
        """Get full circuit breaker status."""
        return self.check_can_trade()

    def sync_from_db(self, month_trades: list):
        """Restore circuit breaker state from DB trade records.

        Args:
            month_trades: List of Trade model instances for the current month.
        """
        self._init_month()
        total_losses = 0.0
        for trade in month_trades:
            pnl = getattr(trade, "pnl", 0.0) or 0.0
            if pnl < 0:
                total_losses += abs(pnl)
        self.realized_losses = total_losses
        self._check_threshold()
        logger.info(
            "Circuit breaker synced from DB: {} trades, losses={:.2f}",
            len(month_trades), total_losses,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _calculate_open_risk(self) -> float:
        """Sum of risk across all open positions."""
        total = 0.0
        for pos in self.open_positions:
            entry = pos.get("entry_price", 0)
            stop = pos.get("stop_price", 0)
            shares = pos.get("shares", 0)
            direction = pos.get("direction", "BUY")

            if direction == "BUY":
                risk = (entry - stop) * shares
            else:
                risk = (stop - entry) * shares

            if risk > 0:
                total += risk

        return total

    def _check_threshold(self):
        """Check if 6% threshold is breached and halt if so."""
        if self.month_start_equity <= 0:
            return

        open_risk = self._calculate_open_risk()
        total = self.realized_losses + open_risk
        max_allowed = self.month_start_equity * (self.max_portfolio_risk_pct / 100.0)

        if total >= max_allowed and not self.is_halted:
            self.is_halted = True
            pct = (total / self.month_start_equity) * 100.0
            self.halt_reason = (
                f"6% Rule breached: {pct:.2f}% exposure "
                f"(losses: {self.realized_losses:.2f}, open risk: {open_risk:.2f})"
            )
            self.halt_timestamp = datetime.now()
            logger.critical(
                "CIRCUIT BREAKER TRIGGERED: {} | Equity: {} | Exposure: {:.2f}%",
                self.halt_reason, self.month_start_equity, pct,
            )
