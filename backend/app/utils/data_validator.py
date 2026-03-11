"""
Data Validation Framework

Adapted from reference: modules/elder_data_validator.py
Provides OHLCV validation, anomaly detection, gap identification, and quality scoring.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger


class ValidationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class ValidationResult:
    check_name: str
    severity: ValidationSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    affected_records: int = 0
    quality_impact: float = 0.0  # 0–1


@dataclass
class DataQualityReport:
    symbol: str
    timeframe: str
    total_records: int
    quality_score: float  # 0–1
    completeness_score: float
    consistency_score: float
    validation_results: List[ValidationResult] = field(default_factory=list)
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_acceptable(self) -> bool:
        return self.quality_score >= 0.8


# Timeframe → expected pandas frequency
_TF_FREQ = {
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D", "1w": "1W",
}


class DataValidator:
    """
    Validates OHLCV data quality.

    Usage:
        validator = DataValidator()
        report = validator.validate(df, "NIFTY", "15m")
        if not report.is_acceptable:
            logger.warning(f"Data quality low: {report.quality_score:.0%}")
    """

    def __init__(
        self,
        min_quality: float = 0.8,
        max_gap_hours: float = 24.0,
        max_price_change_pct: float = 20.0,
        min_volume: int = 1,
    ):
        self.min_quality = min_quality
        self.max_gap_hours = max_gap_hours
        self.max_price_change_pct = max_price_change_pct
        self.min_volume = min_volume

    def validate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> DataQualityReport:
        """Run all validations and return a quality report."""
        results: List[ValidationResult] = []
        gaps: List[Dict[str, Any]] = []
        anomalies: List[Dict[str, Any]] = []

        # Structure
        results.extend(self._check_structure(df))

        if df.empty:
            return DataQualityReport(
                symbol=symbol, timeframe=timeframe, total_records=0,
                quality_score=0.0, completeness_score=0.0, consistency_score=0.0,
                validation_results=results,
            )

        # Completeness (gaps, duplicates)
        comp_results, found_gaps = self._check_completeness(df, timeframe)
        results.extend(comp_results)
        gaps.extend(found_gaps)

        # Consistency (OHLC relationships, price sanity)
        cons_results, found_anomalies = self._check_consistency(df)
        results.extend(cons_results)
        anomalies.extend(found_anomalies)

        # Quality scores
        quality = self._quality_score(results)
        completeness = self._completeness_score(df, gaps)
        consistency = self._consistency_score(results)

        report = DataQualityReport(
            symbol=symbol, timeframe=timeframe, total_records=len(df),
            quality_score=quality, completeness_score=completeness,
            consistency_score=consistency, validation_results=results,
            gaps=gaps, anomalies=anomalies,
        )
        logger.debug(f"Validation {symbol} {timeframe}: quality={quality:.0%} records={len(df)}")
        return report

    # ------------------------------------------------------------------
    # Structure checks
    # ------------------------------------------------------------------

    def _check_structure(self, df: pd.DataFrame) -> List[ValidationResult]:
        results = []
        if df.empty:
            results.append(ValidationResult(
                "empty_data", ValidationSeverity.CRITICAL,
                "DataFrame is empty", quality_impact=1.0,
            ))
            return results

        required = ["datetime", "open", "high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            results.append(ValidationResult(
                "missing_columns", ValidationSeverity.ERROR,
                f"Missing columns: {missing}", {"missing": missing},
                quality_impact=0.5,
            ))

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                nulls = int(df[col].isna().sum())
                if nulls:
                    results.append(ValidationResult(
                        f"nulls_{col}", ValidationSeverity.ERROR,
                        f"{nulls} null values in {col}",
                        {"column": col, "count": nulls},
                        affected_records=nulls, quality_impact=0.2,
                    ))

        return results

    # ------------------------------------------------------------------
    # Completeness checks (gaps, duplicates)
    # ------------------------------------------------------------------

    def _check_completeness(
        self, df: pd.DataFrame, timeframe: str
    ) -> Tuple[List[ValidationResult], List[Dict[str, Any]]]:
        results = []
        gaps = []

        if "datetime" not in df.columns:
            return results, gaps

        dt = pd.to_datetime(df["datetime"])

        # Duplicate timestamps
        dupes = int(dt.duplicated().sum())
        if dupes:
            results.append(ValidationResult(
                "duplicate_timestamps", ValidationSeverity.WARNING,
                f"{dupes} duplicate timestamps",
                {"count": dupes}, affected_records=dupes, quality_impact=0.1,
            ))

        # Gap detection
        freq = _TF_FREQ.get(timeframe)
        if freq and len(dt) > 1:
            expected_delta = pd.Timedelta(freq)
            diffs = dt.diff().dropna()
            max_gap = timedelta(hours=self.max_gap_hours)

            for i, d in enumerate(diffs):
                if d > expected_delta * 3 and d < max_gap:
                    gap_info = {
                        "start": str(dt.iloc[i]),
                        "end": str(dt.iloc[i + 1]),
                        "duration_hours": d.total_seconds() / 3600,
                    }
                    gaps.append(gap_info)

            if gaps:
                results.append(ValidationResult(
                    "data_gaps", ValidationSeverity.WARNING,
                    f"{len(gaps)} data gaps detected",
                    {"count": len(gaps)}, quality_impact=0.15,
                ))

        return results, gaps

    # ------------------------------------------------------------------
    # Consistency checks (OHLC logic, price spikes, volume)
    # ------------------------------------------------------------------

    def _check_consistency(
        self, df: pd.DataFrame
    ) -> Tuple[List[ValidationResult], List[Dict[str, Any]]]:
        results = []
        anomalies = []

        cols = {"open", "high", "low", "close"}
        if not cols.issubset(df.columns):
            return results, anomalies

        # High >= Low
        bad_hl = int((df["high"] < df["low"]).sum())
        if bad_hl:
            results.append(ValidationResult(
                "high_lt_low", ValidationSeverity.ERROR,
                f"{bad_hl} bars where high < low",
                {"count": bad_hl}, affected_records=bad_hl, quality_impact=0.3,
            ))

        # High >= Open/Close, Low <= Open/Close
        bad_ho = int((df["high"] < df["open"]).sum())
        bad_hc = int((df["high"] < df["close"]).sum())
        bad_lo = int((df["low"] > df["open"]).sum())
        bad_lc = int((df["low"] > df["close"]).sum())
        ohlc_violations = bad_ho + bad_hc + bad_lo + bad_lc
        if ohlc_violations:
            results.append(ValidationResult(
                "ohlc_violations", ValidationSeverity.WARNING,
                f"{ohlc_violations} OHLC relationship violations",
                {"high<open": bad_ho, "high<close": bad_hc,
                 "low>open": bad_lo, "low>close": bad_lc},
                affected_records=ohlc_violations, quality_impact=0.2,
            ))

        # Extreme price changes
        pct_changes = df["close"].pct_change().abs() * 100
        spikes = pct_changes > self.max_price_change_pct
        spike_count = int(spikes.sum())
        if spike_count:
            for idx in df.index[spikes]:
                anomalies.append({
                    "type": "price_spike",
                    "index": int(idx),
                    "change_pct": float(pct_changes.iloc[idx]),
                })
            results.append(ValidationResult(
                "price_spikes", ValidationSeverity.WARNING,
                f"{spike_count} extreme price changes (>{self.max_price_change_pct}%)",
                {"count": spike_count}, affected_records=spike_count,
                quality_impact=0.15,
            ))

        # Zero/negative volume
        if "volume" in df.columns:
            zero_vol = int((df["volume"] < self.min_volume).sum())
            if zero_vol:
                results.append(ValidationResult(
                    "low_volume", ValidationSeverity.WARNING,
                    f"{zero_vol} bars with volume < {self.min_volume}",
                    {"count": zero_vol}, affected_records=zero_vol,
                    quality_impact=0.05,
                ))

        return results, anomalies

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _quality_score(results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        penalty = sum(r.quality_impact for r in results)
        return max(0.0, min(1.0, 1.0 - penalty))

    @staticmethod
    def _completeness_score(df: pd.DataFrame, gaps: List[Dict]) -> float:
        if df.empty:
            return 0.0
        penalty = min(len(gaps) * 0.05, 0.5)
        return max(0.0, 1.0 - penalty)

    @staticmethod
    def _consistency_score(results: List[ValidationResult]) -> float:
        errors = sum(1 for r in results if r.severity in (ValidationSeverity.ERROR, ValidationSeverity.CRITICAL))
        if errors == 0:
            return 1.0
        return max(0.0, 1.0 - errors * 0.15)
