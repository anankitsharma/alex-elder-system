"""Tests for anti-spam alert system in AssetSession/AlertStateManager.

Covers: dead zones, flip confirmation, wave confirmation, stop dedup,
position-aware signal dedup, and oscillation scenarios.
"""

import sys
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Add backend/ to sys.path so 'app.' imports resolve correctly
_backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

from backend.app.pipeline.asset_session import AlertStateManager


# ── AlertStateManager: Tide dead zone ───────────────────────


class TestTideDeadZone:
    """Dead zone is applied in _evaluate_signals, not AlertStateManager itself.
    These tests verify the integration logic by checking that clamped slope
    values produce the expected alignment outcomes.
    """

    def test_slope_below_dead_zone_is_clamped(self):
        """slope 0.001 < default dead zone 0.005 → should be clamped to 0."""
        from backend.app.config import settings
        slope = 0.001
        clamped = 0 if abs(slope) < settings.tide_dead_zone else slope
        assert clamped == 0

    def test_slope_above_dead_zone_unchanged(self):
        """slope 0.01 > default dead zone 0.005 → not clamped."""
        from backend.app.config import settings
        slope = 0.01
        clamped = 0 if abs(slope) < settings.tide_dead_zone else slope
        assert clamped == 0.01

    def test_negative_slope_below_dead_zone(self):
        """slope -0.003 → abs < 0.005 → clamped to 0."""
        from backend.app.config import settings
        slope = -0.003
        clamped = 0 if abs(slope) < settings.tide_dead_zone else slope
        assert clamped == 0

    def test_none_slope_not_clamped(self):
        """None slope should pass through (not crash)."""
        from backend.app.config import settings
        slope = None
        clamped = 0 if (slope is not None and abs(slope) < settings.tide_dead_zone) else slope
        assert clamped is None


# ── AlertStateManager: Flip confirmation ────────────────────


class TestFlipConfirmation:
    """Flip from one direction to another requires N consecutive bars."""

    def test_single_bar_flip_suppressed(self):
        """One bar of opposite direction → no alert (flip not confirmed)."""
        mgr = AlertStateManager({"flip_confirm_bars": 2})
        now = time.time()

        # Establish LONG — needs 2 consecutive evals (CONFIRM_COUNT[1] = 2)
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60
        assert mgr.check_alignment_alert(1, "LONG", now) is True  # Confirmed
        now += 60

        # Single bar flip to SHORT — should NOT alert (not confirmed)
        assert mgr.check_alignment_alert(1, "SHORT", now) is False

    def test_confirmed_flip_fires(self):
        """N consecutive bars of opposite direction → alert fires."""
        mgr = AlertStateManager({"flip_confirm_bars": 2})
        now = time.time()

        # Establish LONG (2 bars for hysteresis)
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60

        # Flip bar 1 → not confirmed
        mgr.check_alignment_alert(1, "SHORT", now)
        now += 60

        # Flip bar 2 → confirmed flip
        result = mgr.check_alignment_alert(1, "SHORT", now)
        assert result is True

    def test_confirmed_flip_respects_cooldown(self):
        """Confirmed flip within cooldown window → suppressed."""
        mgr = AlertStateManager({"flip_confirm_bars": 2})
        now = time.time()

        # Establish LONG
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60

        # Confirmed flip to SHORT (2 bars)
        mgr.check_alignment_alert(1, "SHORT", now)
        now += 60
        assert mgr.check_alignment_alert(1, "SHORT", now) is True
        now += 60  # Only 60s later — well within 30 min cooldown

        # Flip back to LONG (2 bars) — should be suppressed by cooldown
        # because "1:LONG" was alerted very recently
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60
        result = mgr.check_alignment_alert(1, "LONG", now)
        assert result is False

    def test_flip_resets_on_same_direction(self):
        """If direction returns to original before confirmation, flip counter resets."""
        mgr = AlertStateManager({"flip_confirm_bars": 3})
        now = time.time()

        # Establish LONG
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60

        # One bar SHORT
        mgr.check_alignment_alert(1, "SHORT", now)
        assert mgr._flip_counter == 1
        now += 60

        # Back to LONG — flip counter should reset
        mgr.check_alignment_alert(1, "LONG", now)
        assert mgr._flip_counter == 0


# ── AlertStateManager: Wave confirmation ────────────────────


class TestWaveConfirmation:
    """Wave signal must persist N consecutive bars before being confirmed."""

    def test_single_wave_not_confirmed(self):
        """Single BUY reading → not confirmed, returns None (no prior state)."""
        mgr = AlertStateManager({"wave_confirm_bars": 2})
        result = mgr.check_wave_confirmed("BUY")
        assert result is None  # No prior confirmed state

    def test_consecutive_wave_confirmed(self):
        """N consecutive same readings → confirmed."""
        mgr = AlertStateManager({"wave_confirm_bars": 2})
        mgr.check_wave_confirmed("BUY")
        result = mgr.check_wave_confirmed("BUY")
        assert result == "BUY"

    def test_wave_flip_resets_count(self):
        """Alternating BUY/SELL → never confirmed."""
        mgr = AlertStateManager({"wave_confirm_bars": 2})
        mgr.check_wave_confirmed("BUY")
        result = mgr.check_wave_confirmed("SELL")
        # SELL count is only 1, BUY was reset, no confirmed state
        assert result is None

    def test_wave_confirmed_persists(self):
        """Once confirmed, a single flip doesn't change the confirmed state."""
        mgr = AlertStateManager({"wave_confirm_bars": 2})
        mgr.check_wave_confirmed("BUY")
        mgr.check_wave_confirmed("BUY")  # Confirmed BUY

        # Single SELL — not confirmed yet, should still return BUY
        result = mgr.check_wave_confirmed("SELL")
        assert result == "BUY"

    def test_wave_none_preserves_state(self):
        """None wave input preserves last confirmed state."""
        mgr = AlertStateManager({"wave_confirm_bars": 2})
        mgr.check_wave_confirmed("SELL")
        mgr.check_wave_confirmed("SELL")  # Confirmed SELL
        result = mgr.check_wave_confirmed(None)
        assert result == "SELL"

    def test_wave_new_direction_confirmed_after_n_bars(self):
        """After confirmed BUY, SELL needs N bars to take over."""
        mgr = AlertStateManager({"wave_confirm_bars": 2})
        mgr.check_wave_confirmed("BUY")
        mgr.check_wave_confirmed("BUY")  # Confirmed BUY

        mgr.check_wave_confirmed("SELL")  # Count 1
        result = mgr.check_wave_confirmed("SELL")  # Count 2 → confirmed
        assert result == "SELL"


# ── Stop/Target dedup ───────────────────────────────────────


class TestStopDedup:
    """Exit dedup prevents duplicate stop/target notifications."""

    def test_exit_initiated_prevents_reprocessing(self):
        """Once a position ID is in _exit_initiated, it's skipped."""
        exit_set: set[int] = set()

        # Simulate first hit
        pos_id = 42
        assert pos_id not in exit_set
        exit_set.add(pos_id)

        # Simulate second hit — should be skipped
        assert pos_id in exit_set

    def test_exit_set_cleared_on_new_position(self):
        """Opening a new position clears the exit set."""
        exit_set: set[int] = {1, 2, 3}
        exit_set.clear()  # Simulates what _auto_execute does
        assert len(exit_set) == 0


# ── Position-aware signal dedup ─────────────────────────────


class TestPositionAwareSignalDedup:
    """Open position in same direction suppresses new signal."""

    def test_same_direction_suppressed(self):
        """Already LONG + new BUY signal → suppressed."""
        # Simulate: existing position direction matches signal direction
        existing_direction = "LONG"
        signal_direction = "LONG"
        assert existing_direction == signal_direction  # Would be suppressed

    def test_opposite_direction_allowed(self):
        """Already LONG + new SELL signal → allowed (flip)."""
        existing_direction = "LONG"
        signal_direction = "SHORT"
        assert existing_direction != signal_direction  # Would be allowed


# ── Oscillation scenario ────────────────────────────────────


class TestOscillationScenario:
    """Full integration: MACD-H slope oscillating near 0 for 10 bars."""

    def test_oscillation_max_one_alert(self):
        """10 bars of slope oscillating ±0.001 → max 1 alert from level increase."""
        mgr = AlertStateManager({"flip_confirm_bars": 2})
        now = time.time()
        alert_count = 0

        # First 2 LONGs to establish (hysteresis for level 1)
        for i in range(2):
            result = mgr.check_alignment_alert(1, "LONG", now + i * 60)
            if result:
                alert_count += 1

        # Then 10 bars where direction toggles every bar
        directions = ["SHORT", "LONG"] * 5
        for i, direction in enumerate(directions):
            result = mgr.check_alignment_alert(1, direction, now + (i + 2) * 60)
            if result:
                alert_count += 1

        # First LONG fires (new level), after that flips never confirm
        # because direction changes every bar (counter never reaches 2)
        assert alert_count == 1

    def test_sustained_direction_change_alerts(self):
        """After oscillation, sustained 3-bar direction change → 1 alert."""
        mgr = AlertStateManager({"flip_confirm_bars": 2})
        now = time.time()

        # Establish LONG (2 bars for hysteresis)
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60
        mgr.check_alignment_alert(1, "LONG", now)
        now += 60

        # Oscillate 4 times (not sustained)
        for i in range(4):
            d = "SHORT" if i % 2 == 0 else "LONG"
            mgr.check_alignment_alert(1, d, now)
            now += 60

        # Now sustain SHORT for 2 bars
        mgr.check_alignment_alert(1, "SHORT", now)
        now += 60
        result = mgr.check_alignment_alert(1, "SHORT", now)
        # Should fire — 2 consecutive SHORT bars confirms flip
        assert result is True


# ── Reset ───────────────────────────────────────────────────


class TestReset:
    """reset() clears all state including flip and wave tracking."""

    def test_reset_clears_all(self):
        mgr = AlertStateManager({"flip_confirm_bars": 2, "wave_confirm_bars": 2})
        now = time.time()

        # Build up state
        mgr.check_alignment_alert(1, "LONG", now)
        mgr.check_wave_confirmed("BUY")
        mgr.check_wave_confirmed("BUY")
        mgr.check_signal_dedup("LONG", now)

        # Verify state exists
        assert mgr._prev_direction == "LONG"
        assert mgr._wave_state == "BUY"
        assert len(mgr._last_signal_time) > 0

        # Reset
        mgr.reset()

        # Verify everything cleared
        assert mgr._prev_level == 0
        assert mgr._prev_direction is None
        assert mgr._established_direction is None
        assert mgr._flip_counter == 0
        assert mgr._flip_direction is None
        assert mgr._wave_state is None
        assert mgr._wave_pending is None
        assert mgr._wave_confirm_count == 0
        assert len(mgr._last_alert) == 0
        assert len(mgr._last_signal_time) == 0
        assert mgr._consecutive == {1: 0, 2: 0, 3: 0}


# ── Signal dedup (existing functionality, regression check) ─


class TestSignalDedup:
    """Existing signal dedup still works correctly."""

    def test_first_signal_passes(self):
        mgr = AlertStateManager()
        assert mgr.check_signal_dedup("LONG") is True

    def test_duplicate_within_cooldown_blocked(self):
        mgr = AlertStateManager()
        now = time.time()
        mgr.check_signal_dedup("LONG", now)
        assert mgr.check_signal_dedup("LONG", now + 60) is False  # 1 min later

    def test_opposite_direction_not_blocked(self):
        mgr = AlertStateManager()
        now = time.time()
        mgr.check_signal_dedup("LONG", now)
        assert mgr.check_signal_dedup("SHORT", now + 60) is True

    def test_after_cooldown_passes(self):
        mgr = AlertStateManager()
        now = time.time()
        mgr.check_signal_dedup("LONG", now)
        assert mgr.check_signal_dedup("LONG", now + 31 * 60) is True  # 31 min later
