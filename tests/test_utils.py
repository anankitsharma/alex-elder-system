"""
Tests for Data Validator and Error Recovery utilities.
"""

import pytest
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from backend.app.utils.data_validator import (
    DataValidator, DataQualityReport, ValidationSeverity, ValidationResult,
)
from backend.app.utils.error_recovery import (
    ErrorRecovery, RecoveryStrategy, ErrorType, RecoveryResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100, freq: str = "15min", start: str = "2024-01-01") -> pd.DataFrame:
    """Generate a clean OHLCV DataFrame."""
    dates = pd.date_range(start, periods=n, freq=freq)
    rng = np.random.default_rng(42)
    close = 100 + rng.standard_normal(n).cumsum()
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    opn = close + rng.uniform(-1, 1, n)
    # Ensure OHLC consistency
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.integers(100, 10000, n)
    return pd.DataFrame({
        "datetime": dates,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ===========================================================================
# DataValidator
# ===========================================================================

class TestDataValidatorStructure:

    def test_empty_dataframe(self):
        v = DataValidator()
        report = v.validate(pd.DataFrame(), "TEST", "15m")
        assert report.quality_score == 0.0
        assert report.total_records == 0
        assert not report.is_acceptable

    def test_missing_columns(self):
        v = DataValidator()
        df = pd.DataFrame({"datetime": [1, 2], "close": [10, 20]})
        report = v.validate(df, "TEST", "15m")
        missing = [r for r in report.validation_results if r.check_name == "missing_columns"]
        assert len(missing) == 1
        assert "open" in missing[0].details["missing"]

    def test_null_values_detected(self):
        v = DataValidator()
        df = _make_ohlcv(20)
        df.loc[3, "close"] = np.nan
        df.loc[5, "open"] = np.nan
        report = v.validate(df, "TEST", "15m")
        null_checks = [r for r in report.validation_results if r.check_name.startswith("nulls_")]
        assert len(null_checks) >= 1

    def test_clean_data_high_quality(self):
        v = DataValidator()
        df = _make_ohlcv(200)
        report = v.validate(df, "NIFTY", "15m")
        assert report.quality_score >= 0.8
        assert report.is_acceptable


class TestDataValidatorCompleteness:

    def test_duplicate_timestamps(self):
        v = DataValidator()
        df = _make_ohlcv(20)
        df.loc[5, "datetime"] = df.loc[4, "datetime"]  # duplicate
        report = v.validate(df, "TEST", "15m")
        dupes = [r for r in report.validation_results if r.check_name == "duplicate_timestamps"]
        assert len(dupes) == 1
        assert dupes[0].details["count"] == 1

    def test_gap_detection(self):
        v = DataValidator()
        df = _make_ohlcv(50, freq="15min")
        # Inject a gap: remove rows 20-30
        df = pd.concat([df.iloc[:20], df.iloc[30:]]).reset_index(drop=True)
        report = v.validate(df, "TEST", "15m")
        assert len(report.gaps) >= 1

    def test_no_gaps_in_clean_data(self):
        v = DataValidator()
        df = _make_ohlcv(50, freq="15min")
        report = v.validate(df, "TEST", "15m")
        assert len(report.gaps) == 0


class TestDataValidatorConsistency:

    def test_high_lt_low(self):
        v = DataValidator()
        df = _make_ohlcv(20)
        # Force high < low on row 5
        df.loc[5, "high"] = df.loc[5, "low"] - 1
        report = v.validate(df, "TEST", "15m")
        hl = [r for r in report.validation_results if r.check_name == "high_lt_low"]
        assert len(hl) == 1

    def test_ohlc_violations(self):
        v = DataValidator()
        df = _make_ohlcv(20)
        # Force high < open
        df.loc[3, "high"] = df.loc[3, "open"] - 5
        report = v.validate(df, "TEST", "15m")
        violations = [r for r in report.validation_results if r.check_name == "ohlc_violations"]
        assert len(violations) >= 1

    def test_price_spikes(self):
        v = DataValidator(max_price_change_pct=5.0)
        df = _make_ohlcv(30)
        # Inject a 50% spike
        df.loc[15, "close"] = df.loc[14, "close"] * 1.5
        report = v.validate(df, "TEST", "15m")
        spikes = [r for r in report.validation_results if r.check_name == "price_spikes"]
        assert len(spikes) >= 1
        assert len(report.anomalies) >= 1

    def test_zero_volume(self):
        v = DataValidator()
        df = _make_ohlcv(20)
        df.loc[4, "volume"] = 0
        df.loc[8, "volume"] = 0
        report = v.validate(df, "TEST", "15m")
        vol = [r for r in report.validation_results if r.check_name == "low_volume"]
        assert len(vol) == 1
        assert vol[0].details["count"] == 2


class TestDataQualityReport:

    def test_acceptable_threshold(self):
        r = DataQualityReport("A", "15m", 100, 0.85, 0.9, 0.9)
        assert r.is_acceptable is True

    def test_unacceptable_threshold(self):
        r = DataQualityReport("A", "15m", 100, 0.6, 0.5, 0.5)
        assert r.is_acceptable is False

    def test_quality_scoring(self):
        v = DataValidator()
        df = _make_ohlcv(200)
        report = v.validate(df, "TEST", "15m")
        assert 0.0 <= report.quality_score <= 1.0
        assert 0.0 <= report.completeness_score <= 1.0
        assert 0.0 <= report.consistency_score <= 1.0


# ===========================================================================
# ErrorRecovery — Classification
# ===========================================================================

class TestErrorClassification:

    def test_timeout_classification(self):
        assert ErrorRecovery.classify_error(Exception("Connection timed out")) == ErrorType.TIMEOUT

    def test_rate_limit_classification(self):
        assert ErrorRecovery.classify_error(Exception("429 Too Many Requests")) == ErrorType.RATE_LIMIT

    def test_auth_classification(self):
        assert ErrorRecovery.classify_error(Exception("401 Unauthorized")) == ErrorType.AUTH

    def test_network_classification(self):
        assert ErrorRecovery.classify_error(Exception("DNS resolution failed")) == ErrorType.NETWORK

    def test_network_by_exception_type(self):
        assert ErrorRecovery.classify_error(ConnectionError("reset")) == ErrorType.NETWORK

    def test_api_classification(self):
        assert ErrorRecovery.classify_error(Exception("500 Internal Server Error")) == ErrorType.API

    def test_validation_classification(self):
        assert ErrorRecovery.classify_error(Exception("Validation failed: invalid schema")) == ErrorType.VALIDATION

    def test_fallback_to_data(self):
        assert ErrorRecovery.classify_error(Exception("something weird")) == ErrorType.DATA


# ===========================================================================
# ErrorRecovery — Sync Retry
# ===========================================================================

class TestSyncRetry:

    def test_success_first_try(self):
        r = ErrorRecovery(max_retries=3, base_delay=0.01)
        result = r.retry_sync(lambda: 42)
        assert result == 42

    def test_success_after_failures(self):
        call_count = {"n": 0}
        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise Exception("transient")
            return "ok"

        r = ErrorRecovery(max_retries=3, base_delay=0.01)
        result = r.retry_sync(flaky)
        assert result == "ok"
        assert call_count["n"] == 3

    def test_exhaustion_raises(self):
        r = ErrorRecovery(max_retries=2, base_delay=0.01)
        with pytest.raises(Exception, match="always fail"):
            r.retry_sync(lambda: (_ for _ in ()).throw(Exception("always fail")))

    def test_recovery_log_populated(self):
        call_count = {"n": 0}
        def fail_then_ok():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise Exception("once")
            return True

        r = ErrorRecovery(max_retries=3, base_delay=0.01)
        r.retry_sync(fail_then_ok)
        log = r.get_recovery_log()
        assert len(log) == 1
        assert log[0].success is False


# ===========================================================================
# ErrorRecovery — Async Retry
# ===========================================================================

class TestAsyncRetry:

    @pytest.mark.asyncio
    async def test_async_success(self):
        r = ErrorRecovery(max_retries=3, base_delay=0.01)

        async def ok():
            return "async_ok"

        result = await r.retry_async(ok)
        assert result == "async_ok"

    @pytest.mark.asyncio
    async def test_async_retry_then_success(self):
        call_count = {"n": 0}

        async def flaky():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise Exception("async transient")
            return "recovered"

        r = ErrorRecovery(max_retries=3, base_delay=0.01)
        result = await r.retry_async(flaky)
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_async_exhaustion(self):
        r = ErrorRecovery(max_retries=2, base_delay=0.01)

        async def always_fail():
            raise Exception("permanent")

        with pytest.raises(Exception, match="permanent"):
            await r.retry_async(always_fail)


# ===========================================================================
# ErrorRecovery — Full Recovery Flow
# ===========================================================================

class TestRecoverFlow:

    def test_retry_recovery(self):
        r = ErrorRecovery(max_retries=2, base_delay=0.01)
        result = r.recover(
            Exception("connection reset"),
            retry_fn=lambda: "retried",
        )
        assert result.success is True
        assert result.strategy_used == RecoveryStrategy.RETRY

    def test_fallback_recovery(self):
        call_count = {"n": 0}
        def bad_retry():
            raise Exception("still broken")

        r = ErrorRecovery(max_retries=1, base_delay=0.01)
        result = r.recover(
            Exception("connection reset"),
            retry_fn=bad_retry,
            fallback_fn=lambda: "fallback_data",
        )
        assert result.success is True
        assert result.strategy_used == RecoveryStrategy.FALLBACK

    def test_skip_for_auth_errors(self):
        r = ErrorRecovery(max_retries=2, base_delay=0.01)
        result = r.recover(Exception("401 auth failed"))
        assert result.success is False
        assert result.strategy_used == RecoveryStrategy.SKIP

    def test_recovery_result_has_attempts(self):
        r = ErrorRecovery(max_retries=2, base_delay=0.01)
        result = r.recover(
            Exception("connection error"),
            retry_fn=lambda: "ok",
        )
        assert result.total_attempts >= 1
        assert result.duration_seconds >= 0


# ===========================================================================
# ErrorRecovery — Backoff
# ===========================================================================

class TestBackoff:

    def test_exponential_backoff(self):
        r = ErrorRecovery(base_delay=1.0, max_delay=60.0, exponential_backoff=True)
        assert r._delay(1) == 1.0
        assert r._delay(2) == 2.0
        assert r._delay(3) == 4.0
        assert r._delay(4) == 8.0

    def test_max_delay_cap(self):
        r = ErrorRecovery(base_delay=10.0, max_delay=30.0, exponential_backoff=True)
        assert r._delay(5) == 30.0  # 10 * 16 = 160, capped at 30

    def test_linear_backoff(self):
        r = ErrorRecovery(base_delay=2.0, exponential_backoff=False)
        assert r._delay(1) == 2.0
        assert r._delay(5) == 2.0
