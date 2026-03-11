"""
Position Sizing — Elder's 2% Rule

The 2% Rule: Never risk more than 2% of trading equity on any single trade.

Position size = (Account Equity × Risk%) / (Entry Price - Stop Price)

For futures/options with lot sizes, rounds DOWN to nearest lot.

Example:
  Account: ₹10,00,000 | Risk: 2% = ₹20,000
  Entry: ₹100 | Stop: ₹95 | Risk per share: ₹5
  Position size: 20,000 / 5 = 4,000 shares
  If lot_size = 1,250 → 3 lots (3,750 shares)
"""

from typing import Dict, Any, Optional
from loguru import logger


class PositionSizer:
    """
    Elder's 2% Rule position sizing.

    Calculates maximum position size based on:
    - Account equity
    - Risk percentage per trade (default 2%)
    - Entry price and stop-loss distance
    - Lot size for derivatives
    """

    def __init__(self, config: Dict[str, Any]):
        self.max_risk_pct = config.get("max_risk_per_trade_pct", 2.0)
        self.account_equity = config.get("account_equity", 0.0)
        self.default_lot_size = config.get("default_lot_size", 1)

    def calculate_position_size(
        self,
        entry_price: float,
        stop_price: float,
        account_equity: Optional[float] = None,
        lot_size: int = 1,
        max_risk_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculate position size using the 2% Rule.

        Args:
            entry_price: Planned entry price
            stop_price: Stop-loss price
            account_equity: Current account equity (overrides instance default)
            lot_size: Lot size for derivatives (1 for cash)
            max_risk_pct: Override max risk % (default: instance setting)

        Returns:
            Dict with shares, lots, risk_amount, etc.
        """
        equity = account_equity or self.account_equity
        risk_pct = max_risk_pct or self.max_risk_pct

        if equity <= 0:
            return self._error("Account equity must be positive")

        if entry_price <= 0:
            return self._error("Entry price must be positive")

        if stop_price <= 0:
            return self._error("Stop price must be positive")

        # Risk per share
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share == 0:
            return self._error("Entry and stop price cannot be equal")

        # Maximum risk amount
        max_risk_amount = equity * (risk_pct / 100.0)

        # Raw position size
        raw_shares = max_risk_amount / risk_per_share

        # Lot sizing for derivatives
        if lot_size > 1:
            lots = int(raw_shares // lot_size)
            shares = lots * lot_size
        else:
            lots = 0
            shares = int(raw_shares)

        if shares <= 0:
            return {
                "shares": 0,
                "lots": 0,
                "risk_amount": 0.0,
                "risk_pct": risk_pct,
                "risk_per_share": round(risk_per_share, 4),
                "max_risk_amount": round(max_risk_amount, 2),
                "entry_price": entry_price,
                "stop_price": stop_price,
                "position_value": 0.0,
                "actual_risk_pct": 0.0,
                "is_valid": False,
                "reason": "Position too small for given risk parameters",
            }

        position_value = shares * entry_price
        actual_risk = shares * risk_per_share
        actual_risk_pct = (actual_risk / equity) * 100.0

        return {
            "shares": shares,
            "lots": lots if lot_size > 1 else None,
            "lot_size": lot_size,
            "risk_amount": round(actual_risk, 2),
            "risk_pct": round(actual_risk_pct, 4),
            "risk_per_share": round(risk_per_share, 4),
            "max_risk_amount": round(max_risk_amount, 2),
            "entry_price": entry_price,
            "stop_price": stop_price,
            "position_value": round(position_value, 2),
            "actual_risk_pct": round(actual_risk_pct, 4),
            "account_equity": equity,
            "is_valid": True,
        }

    def validate_trade_risk(
        self,
        risk_amount: float,
        account_equity: Optional[float] = None,
        max_risk_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Validate if a trade's risk is within the 2% limit.

        Returns:
            Dict with is_allowed, actual_risk_pct, limit
        """
        equity = account_equity or self.account_equity
        risk_pct = max_risk_pct or self.max_risk_pct

        if equity <= 0:
            return {"is_allowed": False, "reason": "No equity"}

        actual_pct = (risk_amount / equity) * 100.0
        is_allowed = actual_pct <= risk_pct

        return {
            "is_allowed": is_allowed,
            "actual_risk_pct": round(actual_pct, 4),
            "max_risk_pct": risk_pct,
            "risk_amount": round(risk_amount, 2),
            "remaining_risk_budget": round(equity * (risk_pct / 100.0) - risk_amount, 2),
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {
            "shares": 0,
            "lots": 0,
            "risk_amount": 0.0,
            "is_valid": False,
            "reason": msg,
        }
