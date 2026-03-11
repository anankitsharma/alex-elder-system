"""
Triple Screen Trading System — Elder's Core Strategy

The Triple Screen system uses three "screens" (timeframes) to filter trades:

Screen 1 (Trend): Weekly chart → identify the tide using MACD-H slope
  - MACD-H rising = bullish tide → only look for buys
  - MACD-H falling = bearish tide → only look for sells

Screen 2 (Oscillator): Daily chart → find entry against the tide
  - In bullish tide: buy when Force Index (2-day) dips below zero
  - In bearish tide: sell when Force Index (2-day) rises above zero
  - Elder-Ray confirms: Bear Power negative but rising (buy), Bull Power positive but falling (sell)

Screen 3 (Precision): Intraday → place the actual order
  - Use trailing buy-stop (above yesterday's high) or sell-stop (below yesterday's low)
  - Tighten stop using SafeZone values

Trade Grading (from Elder's "Come Into My Trading Room"):
  - A trade: both impulse green + value zone entry (top 30% of channel)
  - B trade: impulse green but no value zone
  - C trade: no impulse confirmation but other signals align
"""

import pandas as pd
from typing import Dict, Any, Optional, List
from loguru import logger

try:
    from app.strategy.cross_timeframe_validator import validate_full_analysis
except ImportError:
    from backend.app.strategy.cross_timeframe_validator import validate_full_analysis


class TripleScreenAnalysis:
    """
    Complete Triple Screen analysis for a symbol.

    Produces a structured analysis of all three screens
    with a final recommendation and trade grade.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.timeframe_ratio = self.config.get("timeframe_ratio", 5)

    def analyze(
        self,
        screen1_data: Dict[str, Any],
        screen2_data: Dict[str, Any],
        screen3_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run full Triple Screen analysis.

        Args:
            screen1_data: Higher timeframe indicators
                Expected keys: macd_histogram_slope, impulse_signal, ema_trend
            screen2_data: Medium timeframe indicators
                Expected keys: force_index_2, elder_ray_bear, elder_ray_bull,
                               elder_ray_bear_trend, impulse_signal, value_zone_position
            screen3_data: Lower timeframe for precision entry (optional)
                Expected keys: safezone_long, safezone_short, last_high, last_low

        Returns:
            Complete analysis dict with recommendation and grade
        """
        s1 = self._screen1_trend(screen1_data)
        s2 = self._screen2_oscillator(screen2_data, s1["tide"])
        s3 = self._screen3_entry(screen3_data, s1["tide"]) if screen3_data else {"entry_type": "MARKET"}

        # Cross-timeframe validation
        validation = validate_full_analysis(s1, s2, s3)

        # Final decision
        recommendation = self._make_recommendation(s1, s2, s3)

        # Override recommendation if validation blocks the trade
        if not validation.is_valid and recommendation.get("action") not in ("WAIT", None):
            recommendation = {
                "action": "WAIT",
                "reason": "; ".join(validation.blocks),
                "confidence": 0,
            }

        grade = self._grade_trade(s1, s2, screen2_data)

        return {
            "screen1": s1,
            "screen2": s2,
            "screen3": s3,
            "recommendation": recommendation,
            "grade": grade,
            "validation": validation.to_dict(),
        }

    # ------------------------------------------------------------------
    # Screen 1: Trend (the tide)
    # ------------------------------------------------------------------

    def _screen1_trend(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Screen 1 identifies the tide using weekly MACD-H slope.

        Returns tide: BULLISH, BEARISH, or NEUTRAL
        """
        macd_slope = data.get("macd_histogram_slope", 0)
        impulse = data.get("impulse_signal", "neutral")
        ema_trend = data.get("ema_trend", "UNKNOWN")

        if macd_slope > 0:
            tide = "BULLISH"
        elif macd_slope < 0:
            tide = "BEARISH"
        else:
            tide = "NEUTRAL"

        # Impulse confirmation strengthens the tide
        impulse_confirms = (
            (tide == "BULLISH" and impulse == "bullish") or
            (tide == "BEARISH" and impulse == "bearish")
        )

        return {
            "tide": tide,
            "macd_histogram_slope": macd_slope,
            "impulse_signal": impulse,
            "impulse_confirms": impulse_confirms,
            "ema_trend": ema_trend,
        }

    # ------------------------------------------------------------------
    # Screen 2: Oscillator (the wave)
    # ------------------------------------------------------------------

    def _screen2_oscillator(
        self, data: Dict[str, Any], tide: str
    ) -> Dict[str, Any]:
        """
        Screen 2 finds entries against the tide using oscillators.

        Bullish tide → buy when FI(2) < 0 and Bear Power negative but rising
        Bearish tide → sell when FI(2) > 0 and Bull Power positive but falling
        """
        fi2 = data.get("force_index_2", 0)
        bear_power = data.get("elder_ray_bear", 0)
        bull_power = data.get("elder_ray_bull", 0)
        bear_trend = data.get("elder_ray_bear_trend", "UNKNOWN")
        bull_trend = data.get("elder_ray_bull_trend", "UNKNOWN")
        impulse = data.get("impulse_signal", "neutral")

        signal = "NONE"
        reasons = []

        if tide == "BULLISH":
            # Look for buying opportunity
            fi2_ready = fi2 < 0
            bear_ready = bear_power < 0 and bear_trend == "RISING"

            if fi2_ready:
                reasons.append("FI(2) below zero — buyers pulling back")
            if bear_ready:
                reasons.append("Bear Power negative but rising — bears losing grip")
            if impulse == "bullish":
                reasons.append("Impulse green — momentum confirms")

            if fi2_ready or bear_ready:
                signal = "BUY"

        elif tide == "BEARISH":
            # Look for selling opportunity
            fi2_ready = fi2 > 0
            bull_ready = bull_power > 0 and bull_trend == "FALLING"

            if fi2_ready:
                reasons.append("FI(2) above zero — sellers pulling back")
            if bull_ready:
                reasons.append("Bull Power positive but falling — bulls losing grip")
            if impulse == "bearish":
                reasons.append("Impulse red — momentum confirms")

            if fi2_ready or bull_ready:
                signal = "SELL"

        return {
            "signal": signal,
            "force_index_2": fi2,
            "elder_ray_bear": bear_power,
            "elder_ray_bull": bull_power,
            "bear_trend": bear_trend,
            "bull_trend": bull_trend,
            "impulse_signal": impulse,
            "reasons": reasons,
        }

    # ------------------------------------------------------------------
    # Screen 3: Precision entry
    # ------------------------------------------------------------------

    def _screen3_entry(
        self, data: Dict[str, Any], tide: str
    ) -> Dict[str, Any]:
        """
        Screen 3 determines exact entry using trailing stops.

        Bullish: trailing buy-stop above yesterday's high
        Bearish: trailing sell-stop below yesterday's low
        """
        last_high = data.get("last_high", 0)
        last_low = data.get("last_low", 0)
        sz_long = data.get("safezone_long", 0)
        sz_short = data.get("safezone_short", 0)

        if tide == "BULLISH":
            entry_price = last_high  # Buy-stop above yesterday's high
            stop_price = sz_long if sz_long > 0 else last_low
            entry_type = "BUY_STOP"
        elif tide == "BEARISH":
            entry_price = last_low  # Sell-stop below yesterday's low
            stop_price = sz_short if sz_short > 0 else last_high
            entry_type = "SELL_STOP"
        else:
            return {"entry_type": "NONE", "entry_price": 0, "stop_price": 0}

        return {
            "entry_type": entry_type,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "safezone_long": sz_long,
            "safezone_short": sz_short,
        }

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _make_recommendation(
        self, s1: Dict, s2: Dict, s3: Dict
    ) -> Dict[str, Any]:
        """Combine all three screens into a final recommendation."""
        tide = s1["tide"]
        wave_signal = s2["signal"]

        if tide == "NEUTRAL":
            return {
                "action": "WAIT",
                "reason": "No clear trend on Screen 1",
                "confidence": 0,
            }

        if wave_signal == "NONE":
            return {
                "action": "WAIT",
                "reason": f"Tide is {tide} but Screen 2 oscillator not ready",
                "confidence": 0,
            }

        # Alignment check
        aligned = (
            (tide == "BULLISH" and wave_signal == "BUY") or
            (tide == "BEARISH" and wave_signal == "SELL")
        )

        if not aligned:
            return {
                "action": "WAIT",
                "reason": f"Screen 1 ({tide}) conflicts with Screen 2 ({wave_signal})",
                "confidence": 0,
            }

        # Calculate confidence
        confidence = 50  # Base

        if s1["impulse_confirms"]:
            confidence += 20

        confidence += len(s2["reasons"]) * 10  # Each reason adds 10
        confidence = min(confidence, 100)

        return {
            "action": wave_signal,
            "reason": "; ".join(s2["reasons"]) if s2["reasons"] else "Screens aligned",
            "confidence": confidence,
            "entry_type": s3.get("entry_type"),
            "entry_price": s3.get("entry_price"),
            "stop_price": s3.get("stop_price"),
        }

    # ------------------------------------------------------------------
    # Trade grading
    # ------------------------------------------------------------------

    def _grade_trade(
        self, s1: Dict, s2: Dict, raw_screen2: Dict[str, Any]
    ) -> str:
        """
        Grade the trade A/B/C/D per Elder's methodology.

        A: Impulse confirms + value zone entry
        B: Impulse confirms, no value zone
        C: No impulse but other signals align
        D: Weak or conflicting signals
        """
        impulse_confirms = s1.get("impulse_confirms", False)
        wave_impulse = s2.get("impulse_signal", "neutral")
        value_zone_pos = raw_screen2.get("value_zone_position", None)

        # Check if price is in value zone
        in_value_zone = value_zone_pos is not None and value_zone_pos == 0  # 0 = in zone

        wave_impulse_ok = wave_impulse in ("bullish", "bearish")

        if impulse_confirms and wave_impulse_ok and in_value_zone:
            return "A"
        elif impulse_confirms and wave_impulse_ok:
            return "B"
        elif s2["signal"] != "NONE":
            return "C"
        else:
            return "D"
