"""
Multi-Asset Screener

Scans a list of symbols through the Elder indicator stack and returns
ranked results filtered by impulse color, force index, signal strength, etc.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from loguru import logger

from backend.app.indicators.ema import EMAEnhanced
from backend.app.indicators.macd import MACDEnhanced
from backend.app.indicators.force_index import ForceIndexEnhanced
from backend.app.indicators.impulse import ElderImpulseEnhanced
from backend.app.indicators.safezone import SafeZoneV2


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScreenFilter:
    """Criteria for filtering scan results."""
    impulse_colors: Optional[List[str]] = None   # e.g. ["green"], ["red","green"]
    min_score: float = 0.0                        # 0–100
    direction: Optional[str] = None               # "LONG" or "SHORT"
    fi_above_zero: Optional[bool] = None          # Force Index > 0
    min_volume: Optional[int] = None              # Minimum average volume


@dataclass
class ScreenResult:
    """Result for a single scanned symbol."""
    symbol: str
    timeframe: str
    impulse_signal: str                           # bullish / bearish / neutral
    impulse_color: str                            # green / red / blue
    score: float                                  # 0–100
    direction: Optional[str] = None               # LONG / SHORT / None
    fi_value: Optional[float] = None
    fi_trend: Optional[str] = None                # RISING / FALLING / SIDEWAYS
    ema_value: Optional[float] = None
    ema_slope: Optional[str] = None               # UP / DOWN / SIDEWAYS
    safezone_long: Optional[float] = None
    safezone_short: Optional[float] = None
    last_close: Optional[float] = None
    avg_volume: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_bullish(self) -> bool:
        return self.impulse_signal == "bullish"

    @property
    def is_bearish(self) -> bool:
        return self.impulse_signal == "bearish"


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------

class AssetScreener:
    """
    Scans multiple symbols through the Elder indicator stack.

    Usage:
        screener = AssetScreener()
        results = screener.scan({"NIFTY": df_nifty, "BANKNIFTY": df_bank}, "15m")
        bullish = screener.filter_results(results, ScreenFilter(impulse_colors=["green"]))
    """

    def __init__(
        self,
        ema_period: int = 13,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        fi_length: int = 13,
        sz_lookback: int = 22,
        sz_coefficient: float = 2.0,
    ):
        self.ema_period = ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.fi_length = fi_length
        self.sz_lookback = sz_lookback
        self.sz_coefficient = sz_coefficient
        logger.info("AssetScreener initialized")

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan(
        self,
        data: Dict[str, pd.DataFrame],
        timeframe: str,
    ) -> List[ScreenResult]:
        """
        Scan all symbols and return ScreenResult list.

        Args:
            data: {symbol: ohlcv_dataframe}
            timeframe: e.g. "15m", "1h"

        Returns:
            List of ScreenResult, sorted by score descending.
        """
        results: List[ScreenResult] = []

        for symbol, df in data.items():
            try:
                result = self._scan_single(symbol, df, timeframe)
                if result is not None:
                    results.append(result)
            except Exception as e:
                logger.warning(f"Scan failed for {symbol}: {e}")

        results.sort(key=lambda r: r.score, reverse=True)
        logger.info(f"Scanned {len(data)} symbols, {len(results)} results")
        return results

    def _scan_single(self, symbol: str, df: pd.DataFrame, timeframe: str) -> Optional[ScreenResult]:
        """Run indicators on a single symbol and produce a ScreenResult."""
        if df.empty or len(df) < 30:
            return None

        # --- Impulse (combines EMA + MACD) ---
        impulse = ElderImpulseEnhanced(symbol, timeframe, {
            "ema_length": self.ema_period,
            "macd_fast_length": self.macd_fast,
            "macd_slow_length": self.macd_slow,
            "macd_signal_length": self.macd_signal,
        })
        impulse_df = impulse.calculate(df)
        impulse_signal = impulse.get_impulse_signal() or "neutral"
        impulse_color = impulse.get_impulse_color() or "blue"

        # --- Force Index ---
        fi_value = None
        fi_trend = None
        has_volume = "volume" in df.columns and df["volume"].sum() > 0
        if has_volume:
            try:
                fi = ForceIndexEnhanced(symbol, timeframe, {"length": self.fi_length})
                fi.calculate(df)
                fi_value = fi.get_efi_value()
                fi_trend = fi.get_efi_trend()
            except Exception:
                pass

        # --- EMA ---
        ema = EMAEnhanced(symbol, timeframe, {"period": self.ema_period})
        ema.calculate(df)
        ema_value = ema.get_ema_value()
        ema_slope = ema.get_trend_direction()

        # --- SafeZone ---
        sz_long = None
        sz_short = None
        if len(df) >= self.sz_lookback + 10:
            try:
                sz = SafeZoneV2(symbol, timeframe, {
                    "lookback_length": self.sz_lookback,
                    "coefficient": self.sz_coefficient,
                })
                sz.calculate(df)
                sz_long = sz.get_long_stop()
                sz_short = sz.get_short_stop()
            except Exception:
                pass

        # --- Score ---
        score = self._calculate_score(
            impulse_signal, impulse_color, fi_value, fi_trend, ema_slope,
        )

        # --- Direction ---
        direction = None
        if impulse_signal == "bullish":
            direction = "LONG"
        elif impulse_signal == "bearish":
            direction = "SHORT"

        last_close = float(df["close"].iloc[-1]) if "close" in df.columns else None
        avg_volume = float(df["volume"].mean()) if has_volume else None

        return ScreenResult(
            symbol=symbol,
            timeframe=timeframe,
            impulse_signal=impulse_signal,
            impulse_color=impulse_color,
            score=score,
            direction=direction,
            fi_value=fi_value,
            fi_trend=fi_trend,
            ema_value=ema_value,
            ema_slope=ema_slope,
            safezone_long=sz_long,
            safezone_short=sz_short,
            last_close=last_close,
            avg_volume=avg_volume,
        )

    # ------------------------------------------------------------------
    # Scoring  (0–100)
    # ------------------------------------------------------------------

    def _calculate_score(
        self,
        impulse_signal: str,
        impulse_color: str,
        fi_value: Optional[float],
        fi_trend: Optional[str],
        ema_slope: Optional[str],
    ) -> float:
        """
        Score a symbol 0–100 based on alignment of Elder indicators.

        Breakdown:
          Impulse color (green/red) :  40
          Force Index alignment     :  25
          EMA slope alignment       :  20
          Neutral penalty           : -15
        """
        score = 0.0

        # Impulse color
        if impulse_signal in ("bullish", "bearish"):
            score += 40
        else:
            score -= 15  # neutral penalty

        # Force Index alignment
        if fi_value is not None:
            if impulse_signal == "bullish" and fi_value > 0:
                score += 25
            elif impulse_signal == "bearish" and fi_value < 0:
                score += 25
            elif fi_trend in ("RISING",) and impulse_signal == "bullish":
                score += 10
            elif fi_trend in ("FALLING",) and impulse_signal == "bearish":
                score += 10

        # EMA slope alignment
        if ema_slope:
            if impulse_signal == "bullish" and ema_slope == "UP":
                score += 20
            elif impulse_signal == "bearish" and ema_slope == "DOWN":
                score += 20
            elif ema_slope == "SIDEWAYS":
                score += 5

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    @staticmethod
    def filter_results(
        results: List[ScreenResult],
        filt: ScreenFilter,
    ) -> List[ScreenResult]:
        """Apply a ScreenFilter to narrow down results."""
        filtered = results

        if filt.impulse_colors:
            colors = {c.lower() for c in filt.impulse_colors}
            filtered = [r for r in filtered if r.impulse_color in colors]

        if filt.min_score > 0:
            filtered = [r for r in filtered if r.score >= filt.min_score]

        if filt.direction:
            d = filt.direction.upper()
            filtered = [r for r in filtered if r.direction == d]

        if filt.fi_above_zero is True:
            filtered = [r for r in filtered if r.fi_value is not None and r.fi_value > 0]
        elif filt.fi_above_zero is False:
            filtered = [r for r in filtered if r.fi_value is not None and r.fi_value < 0]

        if filt.min_volume is not None:
            filtered = [r for r in filtered if r.avg_volume is not None and r.avg_volume >= filt.min_volume]

        return filtered

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    @staticmethod
    def top_n(results: List[ScreenResult], n: int = 10) -> List[ScreenResult]:
        """Return top N results by score."""
        return sorted(results, key=lambda r: r.score, reverse=True)[:n]
