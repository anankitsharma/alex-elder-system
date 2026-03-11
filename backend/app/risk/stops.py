"""
SafeZone Stoploss System

Adapted from reference: modules/risk_management/safezone_stoploss.py
Changes:
  - Fixed imports: SafeZone → SafeZoneV2, EMA → EMAEnhanced
  - Decoupled from database — pure calculation, no DB dependency
  - loguru logging
  - Configurable risk-reward target multiplier
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
from datetime import datetime
from loguru import logger

try:
    from app.indicators.safezone import SafeZoneV2
    from app.indicators.ema import EMAEnhanced
except ImportError:
    from backend.app.indicators.safezone import SafeZoneV2
    from backend.app.indicators.ema import EMAEnhanced


class SafeZoneStoploss:
    """
    SafeZone-based stoploss calculation system.

    Provides:
    - Initial SafeZone stoploss from indicator values
    - Trailing stoploss updates (direction-aware)
    - Breakeven logic
    - Breach detection
    - Risk metrics (R:R ratio, target price)
    - History tracking
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = config

        # SafeZone params
        self.safezone_lookback = config.get("safezone_lookback", 22)
        self.safezone_coefficient = config.get("safezone_coefficient", 2.0)

        # EMA params
        self.ema_period = config.get("ema_period", 22)

        # Risk params
        self.rr_target_multiplier = config.get("rr_target_multiplier", 2.0)
        self.min_distance_pct = config.get("min_distance_pct", 0.01)  # 1%
        self.conservative_modifier = config.get("conservative_modifier", 0.05)  # 5%
        self.breakeven_threshold = config.get("breakeven_threshold", 0.02)  # 2%

        # Build indicator instances
        self.safezone = SafeZoneV2(symbol, timeframe, {
            "lookback_length": self.safezone_lookback,
            "coefficient": self.safezone_coefficient,
            "progressive_mode": True,
        })
        self.ema = EMAEnhanced(symbol, timeframe, {
            "period": self.ema_period,
            "ma_type": "None",
        })

        # State
        self.current_stoploss: Optional[Dict[str, Any]] = None
        self.stoploss_history: List[Dict[str, Any]] = []
        self.trend_direction = "NEUTRAL"
        self.last_update_time: Optional[datetime] = None

        logger.info(f"SafeZoneStoploss initialized for {symbol} {timeframe}")

    # ------------------------------------------------------------------
    # Initial stoploss
    # ------------------------------------------------------------------

    def calculate_initial_stoploss(
        self, data: pd.DataFrame, entry_price: float, signal_direction: str
    ) -> Dict[str, Any]:
        """
        Calculate initial SafeZone-based stoploss.

        Args:
            data: OHLCV DataFrame
            entry_price: Fill price
            signal_direction: "BUY" or "SELL"
        """
        try:
            if data.empty:
                return self._empty_result()

            # Calculate indicators
            self.safezone.calculate(data)
            self.ema.calculate(data)

            sz_value = self._get_safezone_value(entry_price, signal_direction)
            ema_value = self.ema.get_latest_value()
            if ema_value is None:
                return self._empty_result()

            trend = self._determine_trend(ema_value, sz_value)

            if signal_direction == "BUY":
                stoploss = self._buy_stoploss(entry_price, sz_value, ema_value, trend)
            elif signal_direction == "SELL":
                stoploss = self._sell_stoploss(entry_price, sz_value, ema_value, trend)
            else:
                return self._empty_result()

            risk_metrics = self._risk_metrics(entry_price, stoploss, signal_direction)

            result = {
                "stoploss_price": stoploss,
                "entry_price": entry_price,
                "signal_direction": signal_direction,
                "trend_direction": trend,
                "safezone_value": sz_value,
                "ema_value": ema_value,
                "risk_metrics": risk_metrics,
                "stoploss_type": "INITIAL",
                "timestamp": datetime.now(),
                "is_valid": True,
            }

            self.current_stoploss = result
            self.trend_direction = trend
            self.last_update_time = datetime.now()

            logger.debug(f"Initial SL: {stoploss:.4f} for {signal_direction} @ {entry_price:.4f}")
            return result

        except Exception as e:
            logger.error(f"Error calculating initial stoploss: {e}")
            return self._error_result(str(e))

    # ------------------------------------------------------------------
    # Trailing update
    # ------------------------------------------------------------------

    def update_stoploss(
        self, data: pd.DataFrame, current_price: float, signal_direction: str
    ) -> Dict[str, Any]:
        """
        Trail the stoploss toward profit; never widen it.

        For BUY: new SL must be >= current SL  (trail up).
        For SELL: new SL must be <= current SL (trail down).
        """
        try:
            if self.current_stoploss is None:
                return self.calculate_initial_stoploss(data, current_price, signal_direction)

            self.safezone.calculate(data)
            self.ema.calculate(data)

            sz_value = self._get_safezone_value(current_price, signal_direction)
            ema_value = self.ema.get_latest_value()
            if ema_value is None:
                return self.current_stoploss

            trend = self._determine_trend(ema_value, sz_value)
            prev_sl = self.current_stoploss["stoploss_price"]
            entry_price = self.current_stoploss["entry_price"]

            if signal_direction == "BUY":
                new_sl = self._buy_stoploss(current_price, sz_value, ema_value, trend)
                if new_sl > prev_sl:
                    updated_sl, sl_type = new_sl, "TRAILING_UP"
                else:
                    updated_sl, sl_type = prev_sl, "MAINTAINED"

            elif signal_direction == "SELL":
                new_sl = self._sell_stoploss(current_price, sz_value, ema_value, trend)
                if new_sl < prev_sl:
                    updated_sl, sl_type = new_sl, "TRAILING_DOWN"
                else:
                    updated_sl, sl_type = prev_sl, "MAINTAINED"
            else:
                return self.current_stoploss

            risk_metrics = self._risk_metrics(entry_price, updated_sl, signal_direction)

            result = {
                "stoploss_price": updated_sl,
                "entry_price": entry_price,
                "signal_direction": signal_direction,
                "trend_direction": trend,
                "safezone_value": sz_value,
                "ema_value": ema_value,
                "risk_metrics": risk_metrics,
                "stoploss_type": sl_type,
                "previous_stoploss": prev_sl,
                "timestamp": datetime.now(),
                "is_valid": True,
            }

            self.current_stoploss = result
            self.trend_direction = trend
            self.last_update_time = datetime.now()
            self.stoploss_history.append(result)

            logger.debug(f"SL update: {updated_sl:.4f} ({sl_type})")
            return result

        except Exception as e:
            logger.error(f"Error updating stoploss: {e}")
            return self.current_stoploss or self._error_result(str(e))

    # ------------------------------------------------------------------
    # Breach detection
    # ------------------------------------------------------------------

    def check_stoploss_breach(self, current_price: float) -> Dict[str, Any]:
        """Check if current price has hit the stoploss."""
        try:
            if self.current_stoploss is None:
                return {
                    "is_breached": False,
                    "breach_type": "NO_STOPLOSS",
                    "current_price": current_price,
                    "stoploss_price": None,
                    "breach_distance": 0.0,
                    "timestamp": datetime.now(),
                }

            sl = self.current_stoploss["stoploss_price"]
            direction = self.current_stoploss["signal_direction"]

            is_breached = False
            breach_distance = 0.0

            if direction == "BUY" and current_price <= sl:
                is_breached = True
                breach_distance = sl - current_price
            elif direction == "SELL" and current_price >= sl:
                is_breached = True
                breach_distance = current_price - sl

            return {
                "is_breached": is_breached,
                "breach_type": "STOPLOSS_HIT" if is_breached else "NO_BREACH",
                "current_price": current_price,
                "stoploss_price": sl,
                "breach_distance": breach_distance,
                "signal_direction": direction,
                "timestamp": datetime.now(),
            }

        except Exception as e:
            logger.error(f"Error checking stoploss breach: {e}")
            return {
                "is_breached": False,
                "breach_type": "ERROR",
                "current_price": current_price,
                "stoploss_price": None,
                "breach_distance": 0.0,
                "error": str(e),
                "timestamp": datetime.now(),
            }

    # ------------------------------------------------------------------
    # Breakeven
    # ------------------------------------------------------------------

    def get_breakeven_stoploss(self, entry_price: float, signal_direction: str) -> float:
        """Breakeven SL — 0.1 % past entry in the favourable direction."""
        if signal_direction == "BUY":
            return entry_price * 1.001
        elif signal_direction == "SELL":
            return entry_price * 0.999
        return entry_price

    def should_move_to_breakeven(
        self, current_price: float, entry_price: float, signal_direction: str
    ) -> bool:
        """True when unrealised profit exceeds breakeven_threshold (default 2 %)."""
        try:
            if signal_direction == "BUY":
                pct = (current_price - entry_price) / entry_price
            elif signal_direction == "SELL":
                pct = (entry_price - current_price) / entry_price
            else:
                return False
            return pct >= self.breakeven_threshold
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_current_stoploss(self) -> Optional[Dict[str, Any]]:
        return self.current_stoploss

    def get_stoploss_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.stoploss_history[-limit:] if self.stoploss_history else []

    def reset(self):
        self.current_stoploss = None
        self.stoploss_history = []
        self.trend_direction = "NEUTRAL"
        self.last_update_time = None
        logger.info("SafeZoneStoploss reset")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_safezone_value(self, price: float, direction: str) -> float:
        """Get SafeZone stop for the given direction, with fallback."""
        if direction == "BUY":
            val = self.safezone.get_long_stop()
        else:
            val = self.safezone.get_short_stop()

        if val is None or val == 0.0 or np.isnan(val):
            # Fallback to percentage-based
            if direction == "BUY":
                val = price * (1 - self.min_distance_pct * 2)
            else:
                val = price * (1 + self.min_distance_pct * 2)
        return val

    def _determine_trend(self, ema_value: float, safezone_value: float) -> str:
        if ema_value > safezone_value:
            return "BULLISH"
        elif ema_value < safezone_value:
            return "BEARISH"
        return "NEUTRAL"

    def _buy_stoploss(
        self, entry: float, sz: float, ema: float, trend: str
    ) -> float:
        try:
            if trend == "BULLISH":
                sl = sz
            elif trend == "BEARISH":
                sl = sz * (1 - self.conservative_modifier)
            else:
                sl = ema

            min_dist = entry * self.min_distance_pct
            if sl > entry - min_dist:
                sl = entry - min_dist
            return sl
        except Exception:
            return entry * (1 - self.min_distance_pct * 2)

    def _sell_stoploss(
        self, entry: float, sz: float, ema: float, trend: str
    ) -> float:
        try:
            if trend == "BEARISH":
                sl = sz
            elif trend == "BULLISH":
                sl = sz * (1 + self.conservative_modifier)
            else:
                sl = ema

            min_dist = entry * self.min_distance_pct
            if sl < entry + min_dist:
                sl = entry + min_dist
            return sl
        except Exception:
            return entry * (1 + self.min_distance_pct * 2)

    def _risk_metrics(
        self, entry: float, sl: float, direction: str
    ) -> Dict[str, Any]:
        try:
            if direction == "BUY":
                risk_amount = entry - sl
            elif direction == "SELL":
                risk_amount = sl - entry
            else:
                risk_amount = 0.0

            risk_pct = (risk_amount / entry) * 100 if entry > 0 else 0.0
            reward = risk_amount * self.rr_target_multiplier

            if direction == "BUY":
                target = entry + reward
            else:
                target = entry - reward

            rr_ratio = reward / risk_amount if risk_amount > 0 else 0.0

            return {
                "risk_amount": round(risk_amount, 4),
                "risk_percentage": round(risk_pct, 2),
                "risk_reward_ratio": round(rr_ratio, 2),
                "target_price": round(target, 4),
                "reward_amount": round(reward, 4),
            }
        except Exception:
            return {
                "risk_amount": 0.0,
                "risk_percentage": 0.0,
                "risk_reward_ratio": 0.0,
                "target_price": entry,
                "reward_amount": 0.0,
            }

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "stoploss_price": None,
            "entry_price": None,
            "signal_direction": None,
            "trend_direction": "NEUTRAL",
            "safezone_value": None,
            "ema_value": None,
            "risk_metrics": {},
            "stoploss_type": "NONE",
            "timestamp": datetime.now(),
            "is_valid": False,
        }

    def _error_result(self, msg: str) -> Dict[str, Any]:
        return {
            "stoploss_price": None,
            "entry_price": None,
            "signal_direction": None,
            "trend_direction": "NEUTRAL",
            "safezone_value": None,
            "ema_value": None,
            "risk_metrics": {},
            "stoploss_type": "ERROR",
            "error": msg,
            "timestamp": datetime.now(),
            "is_valid": False,
        }

    def __str__(self) -> str:
        return f"SafeZoneStoploss({self.symbol}, {self.timeframe})"

    def __repr__(self) -> str:
        return (
            f"SafeZoneStoploss(symbol='{self.symbol}', timeframe='{self.timeframe}', "
            f"safezone_lookback={self.safezone_lookback}, ema_period={self.ema_period}, "
            f"has_stoploss={self.current_stoploss is not None})"
        )
