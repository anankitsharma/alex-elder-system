"""
Error Recovery System

Adapted from reference: modules/elder_error_recovery.py
Retry with exponential backoff, error classification, recovery strategies.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar
from loguru import logger

T = TypeVar("T")


class RecoveryStrategy(str, Enum):
    RETRY = "retry"
    FALLBACK = "fallback"
    PARTIAL = "partial"
    SKIP = "skip"


class ErrorType(str, Enum):
    NETWORK = "network"
    API = "api"
    DATA = "data"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    TIMEOUT = "timeout"


@dataclass
class RecoveryAttempt:
    attempt: int
    strategy: RecoveryStrategy
    error_type: ErrorType
    error_message: str
    success: bool
    duration_seconds: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class RecoveryResult:
    success: bool
    strategy_used: RecoveryStrategy
    total_attempts: int
    duration_seconds: float
    attempts: List[RecoveryAttempt] = field(default_factory=list)
    data: Any = None
    final_error: Optional[str] = None


# Default error → strategy mapping
_DEFAULT_STRATEGY_MAP: Dict[ErrorType, List[RecoveryStrategy]] = {
    ErrorType.NETWORK: [RecoveryStrategy.RETRY, RecoveryStrategy.FALLBACK],
    ErrorType.API: [RecoveryStrategy.RETRY, RecoveryStrategy.FALLBACK],
    ErrorType.DATA: [RecoveryStrategy.PARTIAL, RecoveryStrategy.SKIP],
    ErrorType.VALIDATION: [RecoveryStrategy.PARTIAL, RecoveryStrategy.SKIP],
    ErrorType.RATE_LIMIT: [RecoveryStrategy.RETRY],
    ErrorType.AUTH: [RecoveryStrategy.SKIP],
    ErrorType.TIMEOUT: [RecoveryStrategy.RETRY, RecoveryStrategy.FALLBACK],
}


class ErrorRecovery:
    """
    Error recovery with retry, exponential backoff, and strategy selection.

    Usage:
        recovery = ErrorRecovery(max_retries=3)

        # Sync retry
        result = recovery.retry_sync(fetch_data, symbol="NIFTY", timeframe="15m")

        # Async retry
        result = await recovery.retry_async(async_fetch, symbol="NIFTY")

        # Classify + recover
        result = recovery.recover(error, retry_fn=fetch_data)
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        exponential_backoff: bool = True,
        strategy_map: Optional[Dict[ErrorType, List[RecoveryStrategy]]] = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_backoff = exponential_backoff
        self.strategy_map = strategy_map or _DEFAULT_STRATEGY_MAP
        self.recovery_log: List[RecoveryAttempt] = []

    # ------------------------------------------------------------------
    # Sync retry
    # ------------------------------------------------------------------

    def retry_sync(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Retry a synchronous function with backoff. Raises on exhaustion."""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                delay = self._delay(attempt)
                logger.warning(f"Retry {attempt}/{self.max_retries} failed: {e} — waiting {delay:.1f}s")
                self._log_attempt(attempt, RecoveryStrategy.RETRY, e, False, delay)
                if attempt < self.max_retries:
                    time.sleep(delay)

        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Async retry
    # ------------------------------------------------------------------

    async def retry_async(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Retry an async function with backoff. Raises on exhaustion."""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                delay = self._delay(attempt)
                logger.warning(f"Async retry {attempt}/{self.max_retries} failed: {e} — waiting {delay:.1f}s")
                self._log_attempt(attempt, RecoveryStrategy.RETRY, e, False, delay)
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Full recovery flow (classify → strategy → execute)
    # ------------------------------------------------------------------

    def recover(
        self,
        error: Exception,
        retry_fn: Optional[Callable] = None,
        fallback_fn: Optional[Callable] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecoveryResult:
        """
        Attempt recovery based on error classification.

        Tries each strategy in order for the classified error type.
        """
        error_type = self.classify_error(error)
        strategies = self.strategy_map.get(error_type, [RecoveryStrategy.SKIP])
        attempts: List[RecoveryAttempt] = []
        start = time.time()

        for strategy in strategies:
            for attempt_num in range(1, self.max_retries + 1):
                t0 = time.time()
                try:
                    if strategy == RecoveryStrategy.RETRY and retry_fn:
                        data = retry_fn(**(context or {}))
                        dur = time.time() - t0
                        att = RecoveryAttempt(attempt_num, strategy, error_type, "", True, dur)
                        attempts.append(att)
                        return RecoveryResult(
                            True, strategy, len(attempts), time.time() - start,
                            attempts, data=data,
                        )

                    elif strategy == RecoveryStrategy.FALLBACK and fallback_fn:
                        data = fallback_fn(**(context or {}))
                        dur = time.time() - t0
                        att = RecoveryAttempt(attempt_num, strategy, error_type, "", True, dur)
                        attempts.append(att)
                        return RecoveryResult(
                            True, strategy, len(attempts), time.time() - start,
                            attempts, data=data,
                        )

                    elif strategy == RecoveryStrategy.SKIP:
                        dur = time.time() - t0
                        att = RecoveryAttempt(attempt_num, strategy, error_type, "skipped", True, dur)
                        attempts.append(att)
                        return RecoveryResult(
                            False, strategy, len(attempts), time.time() - start,
                            attempts, final_error="Skipped",
                        )

                except Exception as e2:
                    dur = time.time() - t0
                    att = RecoveryAttempt(attempt_num, strategy, error_type, str(e2), False, dur)
                    attempts.append(att)
                    if attempt_num < self.max_retries:
                        time.sleep(self._delay(attempt_num))

        return RecoveryResult(
            False, strategies[-1] if strategies else RecoveryStrategy.SKIP,
            len(attempts), time.time() - start, attempts,
            final_error=str(error),
        )

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify_error(error: Exception) -> ErrorType:
        """Classify an exception into an ErrorType."""
        msg = str(error).lower()
        etype = type(error).__name__.lower()

        if any(k in msg for k in ("timeout", "timed out")):
            return ErrorType.TIMEOUT
        if any(k in msg for k in ("rate limit", "429", "too many")):
            return ErrorType.RATE_LIMIT
        if any(k in msg for k in ("auth", "401", "403", "token", "login")):
            return ErrorType.AUTH
        if any(k in msg for k in ("connection", "network", "dns", "socket")):
            return ErrorType.NETWORK
        if any(k in etype for k in ("connection", "timeout", "socket")):
            return ErrorType.NETWORK
        if any(k in msg for k in ("api", "500", "502", "503")):
            return ErrorType.API
        if any(k in msg for k in ("validation", "invalid", "schema")):
            return ErrorType.VALIDATION
        return ErrorType.DATA

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _delay(self, attempt: int) -> float:
        if self.exponential_backoff:
            return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        return self.base_delay

    def _log_attempt(
        self, attempt: int, strategy: RecoveryStrategy, error: Exception,
        success: bool, duration: float,
    ):
        error_type = self.classify_error(error)
        att = RecoveryAttempt(attempt, strategy, error_type, str(error), success, duration)
        self.recovery_log.append(att)

    def get_recovery_log(self, limit: int = 50) -> List[RecoveryAttempt]:
        return self.recovery_log[-limit:]
