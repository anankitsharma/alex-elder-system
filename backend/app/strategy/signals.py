"""
Signal Manager — Cross-Timeframe Signal Generation

Adapted from reference: modules/signal_generation/signal_manager.py
Changes:
  - Timeframe hierarchy is configurable (was hardcoded ['4h','1h','15m','5m','1m'])
  - Uses our indicator classes directly instead of generic attribute access
  - loguru logging
  - Typed signal output matching our Signal ORM model fields
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from loguru import logger


# Default timeframe hierarchy from longest to shortest.
# Higher timeframes appear first; confirmation looks "upward" from current.
DEFAULT_TIMEFRAME_HIERARCHY: List[str] = ["1w", "1d", "4h", "1h", "15m", "5m", "1m"]


class SignalManager:
    """
    Manages signal generation and coordination across timeframes.

    Usage:
        sm = SignalManager(timeframes=["4h", "1h", "15m", "5m"])
        signal = sm.generate_signals(symbol, "15m", indicators, all_tf_indicators)
    """

    def __init__(self, timeframes: Optional[List[str]] = None):
        self.timeframes = timeframes or DEFAULT_TIMEFRAME_HIERARCHY
        logger.info(f"SignalManager initialized — timeframes: {self.timeframes}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        symbol: str,
        timeframe: str,
        indicators: Any,
        all_timeframe_indicators: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a trading signal from indicators with cross-timeframe confirmation.

        Args:
            symbol: Trading symbol (e.g. "NATURALGAS")
            timeframe: Current timeframe being evaluated
            indicators: Indicator bundle for *timeframe*
              Expected attributes: impulse_signal (str), impulse_color (str),
              fi_value (float), ema_value (float),
              safezone_long (float), safezone_short (float)
            all_timeframe_indicators: {tf: indicator_bundle} for all timeframes

        Returns:
            Signal dict or None if no confirmed signal.
        """
        try:
            confirmation = self._check_cross_timeframe_confirmation(
                symbol, timeframe, indicators, all_timeframe_indicators
            )

            if not confirmation["confirmed"]:
                return None

            signal = self._generate_signal_from_indicators(indicators, confirmation)

            if signal:
                signal.update({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": datetime.now(),
                    "cross_timeframe_confirmation": True,
                })

            return signal

        except Exception as e:
            logger.error(f"Error generating signals for {symbol} {timeframe}: {e}")
            return None

    # ------------------------------------------------------------------
    # Cross-timeframe confirmation
    # ------------------------------------------------------------------

    def _check_cross_timeframe_confirmation(
        self,
        symbol: str,
        timeframe: str,
        indicators: Any,
        all_timeframe_indicators: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check higher timeframes for directional agreement."""
        try:
            current_signal = self._extract_direction(indicators)
            if not current_signal or current_signal == "HOLD":
                return {"confirmed": False, "reason": "no_current_signal"}

            # Find position of current timeframe in hierarchy
            try:
                current_index = self.timeframes.index(timeframe)
            except ValueError:
                return {"confirmed": False, "reason": f"timeframe {timeframe} not in hierarchy"}

            confirmations = 0
            total_checked = 0

            # Only look at *higher* timeframes (earlier in the list)
            for tf in self.timeframes[:current_index]:
                tf_indicators = all_timeframe_indicators.get(tf)
                if tf_indicators is None:
                    continue

                tf_signal = self._extract_direction(tf_indicators)
                if tf_signal == current_signal:
                    confirmations += 1
                total_checked += 1

            confirmed = confirmations > 0 and total_checked > 0

            return {
                "confirmed": confirmed,
                "confirmations": confirmations,
                "total_checked": total_checked,
                "reason": (
                    f"{confirmations}/{total_checked} confirmations"
                    if total_checked > 0
                    else "no_higher_timeframes"
                ),
            }

        except Exception as e:
            logger.error(f"Error checking cross-timeframe confirmation: {e}")
            return {"confirmed": False, "reason": "confirmation_error"}

    # ------------------------------------------------------------------
    # Signal construction
    # ------------------------------------------------------------------

    def _generate_signal_from_indicators(
        self, indicators: Any, confirmation: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Build a signal dict from indicator state + confirmation."""
        try:
            direction = self._extract_direction(indicators)
            if not direction or direction == "HOLD":
                return None

            strength = self._calculate_signal_strength(indicators, confirmation)

            return {
                "direction": direction,
                "score": int(round(strength * 100)),
                "impulse_color": getattr(indicators, "impulse_color", None),
                "fi_value": getattr(indicators, "fi_value", None),
                "ema_value": getattr(indicators, "ema_value", None),
                "safezone_long": getattr(indicators, "safezone_long", None),
                "safezone_short": getattr(indicators, "safezone_short", None),
                "confirmation_details": confirmation,
            }

        except Exception as e:
            logger.error(f"Error generating signal from indicators: {e}")
            return None

    # ------------------------------------------------------------------
    # Strength scoring  (0.0 – 1.0)
    # ------------------------------------------------------------------

    def _calculate_signal_strength(
        self, indicators: Any, confirmation: Dict[str, Any]
    ) -> float:
        """
        Composite signal strength from impulse + force index + confirmations.

        Weights:
          Impulse agreement  : up to 0.30
          Force Index (13)   : up to 0.20
          Force Index (2)    : up to 0.20
          TF confirmations   : up to 0.30
        """
        try:
            strength = 0.0

            # Impulse color agreement
            impulse = getattr(indicators, "impulse_color", None)
            if impulse and impulse.upper() in ("GREEN", "RED"):
                strength += 0.30

            # Force Index contribution
            fi_13 = getattr(indicators, "fi_13", 0) or 0
            fi_2 = getattr(indicators, "fi_2", 0) or 0
            strength += min(abs(fi_13) * 0.1, 0.20)
            strength += min(abs(fi_2) * 0.1, 0.20)

            # Cross-timeframe confirmations
            if confirmation.get("confirmed"):
                strength += min(confirmation["confirmations"] * 0.10, 0.30)

            return min(strength, 1.0)

        except Exception as e:
            logger.error(f"Error calculating signal strength: {e}")
            return 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_direction(indicators: Any) -> Optional[str]:
        """Pull a direction string from an indicator bundle."""
        # Try multiple common attribute names
        for attr in ("impulse_signal", "triple_screen_signal", "direction", "signal"):
            val = getattr(indicators, attr, None)
            if val and val != "HOLD":
                # Normalise to LONG / SHORT
                val_upper = val.upper()
                if val_upper in ("BUY", "BULLISH", "LONG"):
                    return "LONG"
                elif val_upper in ("SELL", "BEARISH", "SHORT"):
                    return "SHORT"
                return val_upper
        return None
