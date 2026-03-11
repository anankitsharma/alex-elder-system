"""
Tests for the Trade Executor and Paper/Live placers.
"""

import pytest
import asyncio
from backend.app.trading.executor import (
    TradeExecutor, TradePosition, TradeState, ExitReason, OrderResult,
)
from backend.app.trading.paper import PaperPlacer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def paper_placer():
    return PaperPlacer(slippage_pct=0.0)


@pytest.fixture
def executor(paper_placer):
    events = []
    def on_notify(event, data):
        events.append((event, data))
    ex = TradeExecutor(paper_placer, on_notify=on_notify)
    ex._events = events  # stash for test assertions
    return ex


# ---------------------------------------------------------------------------
# PaperPlacer
# ---------------------------------------------------------------------------

class TestPaperPlacer:

    @pytest.mark.asyncio
    async def test_entry_fills_immediately(self, paper_placer):
        result = await paper_placer.place_entry(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="BUY", quantity=75, order_type="MARKET",
            price=22500, trigger_price=0, product_type="CARRYFORWARD",
        )
        assert result.status == "FILLED"
        assert result.filled_price == 22500
        assert result.filled_quantity == 75
        assert result.order_id.startswith("PAPER-")

    @pytest.mark.asyncio
    async def test_exit_fills_immediately(self, paper_placer):
        result = await paper_placer.place_exit(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="SELL", quantity=75, order_type="MARKET",
            price=22600, product_type="CARRYFORWARD",
        )
        assert result.status == "FILLED"
        assert result.filled_price == 22600

    @pytest.mark.asyncio
    async def test_slippage_buy(self):
        placer = PaperPlacer(slippage_pct=0.01)  # 1%
        result = await placer.place_entry(
            symbol="TEST", token="1", exchange="NSE",
            direction="BUY", quantity=10, order_type="MARKET",
            price=100.0, trigger_price=0, product_type="DELIVERY",
        )
        assert result.filled_price == pytest.approx(101.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_slippage_sell(self):
        placer = PaperPlacer(slippage_pct=0.01)
        result = await placer.place_exit(
            symbol="TEST", token="1", exchange="NSE",
            direction="SELL", quantity=10, order_type="MARKET",
            price=100.0, product_type="DELIVERY",
        )
        assert result.filled_price == pytest.approx(99.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_cancel(self, paper_placer):
        assert await paper_placer.cancel("PAPER-abc123") is True

    @pytest.mark.asyncio
    async def test_order_log(self, paper_placer):
        await paper_placer.place_entry(
            symbol="A", token="1", exchange="NSE", direction="BUY",
            quantity=1, order_type="MARKET", price=10, trigger_price=0,
            product_type="DELIVERY",
        )
        log = paper_placer.get_order_log()
        assert len(log) == 1
        assert log[0]["symbol"] == "A"


# ---------------------------------------------------------------------------
# TradeExecutor — Entry
# ---------------------------------------------------------------------------

class TestExecutorEntry:

    @pytest.mark.asyncio
    async def test_basic_entry(self, executor):
        pos = await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22500,
        )
        assert pos is not None
        assert pos.state == TradeState.OPEN
        assert pos.direction == "LONG"
        assert pos.entry_price == 22500
        assert pos.quantity == 75
        assert pos.entry_order_id.startswith("PAPER-")

    @pytest.mark.asyncio
    async def test_duplicate_entry_skipped(self, executor):
        await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22500,
        )
        pos2 = await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22600,
        )
        # Should return existing position, not create new
        assert pos2.entry_price == 22500

    @pytest.mark.asyncio
    async def test_entry_notification(self, executor):
        await executor.enter(
            symbol="TEST", token="1", exchange="NSE",
            direction="SHORT", quantity=10, entry_price=100,
        )
        assert any(e[0] == "entry" for e in executor._events)


# ---------------------------------------------------------------------------
# TradeExecutor — Stoploss
# ---------------------------------------------------------------------------

class TestExecutorStoploss:

    @pytest.mark.asyncio
    async def test_update_stop_long(self, executor):
        pos = await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22500,
            stop_price=22400,
        )
        assert pos.stop_price == 22400

        executor.update_stop("NIFTY", 22450)
        assert executor.positions["NIFTY"].stop_price == 22450
        assert executor.positions["NIFTY"].state == TradeState.TRAILING

    @pytest.mark.asyncio
    async def test_stop_only_trails_up_for_long(self, executor):
        await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22500,
            stop_price=22400,
        )
        executor.update_stop("NIFTY", 22350)  # lower → ignored
        assert executor.positions["NIFTY"].stop_price == 22400

    @pytest.mark.asyncio
    async def test_check_stop_breach(self, executor):
        await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22500,
            stop_price=22400,
        )
        assert executor.check_stop("NIFTY", 22450) is False
        assert executor.check_stop("NIFTY", 22400) is True
        assert executor.check_stop("NIFTY", 22350) is True

    @pytest.mark.asyncio
    async def test_check_stop_short(self, executor):
        await executor.enter(
            symbol="TEST", token="1", exchange="NSE",
            direction="SHORT", quantity=10, entry_price=100,
            stop_price=105,
        )
        assert executor.check_stop("TEST", 104) is False
        assert executor.check_stop("TEST", 106) is True


# ---------------------------------------------------------------------------
# TradeExecutor — Exit
# ---------------------------------------------------------------------------

class TestExecutorExit:

    @pytest.mark.asyncio
    async def test_stoploss_exit(self, executor):
        await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22500,
        )
        pos = await executor.exit_position("NIFTY", ExitReason.STOPLOSS, current_price=22400)
        assert pos is not None
        assert pos.state == TradeState.CLOSED
        assert pos.exit_reason == ExitReason.STOPLOSS
        assert pos.pnl == (22400 - 22500) * 75

    @pytest.mark.asyncio
    async def test_target_exit(self, executor):
        await executor.enter(
            symbol="TEST", token="1", exchange="NSE",
            direction="SHORT", quantity=10, entry_price=100,
        )
        pos = await executor.exit_position("TEST", ExitReason.TARGET, current_price=90)
        assert pos.pnl == (100 - 90) * 10

    @pytest.mark.asyncio
    async def test_exit_no_position(self, executor):
        pos = await executor.exit_position("MISSING", ExitReason.MANUAL, current_price=0)
        assert pos is None

    @pytest.mark.asyncio
    async def test_closed_trade_history(self, executor):
        await executor.enter(
            symbol="A", token="1", exchange="NSE",
            direction="LONG", quantity=1, entry_price=100,
        )
        await executor.exit_position("A", ExitReason.MANUAL, current_price=110)
        closed = executor.get_closed_trades()
        assert len(closed) == 1
        assert closed[0].symbol == "A"

    @pytest.mark.asyncio
    async def test_exit_notification(self, executor):
        await executor.enter(
            symbol="A", token="1", exchange="NSE",
            direction="LONG", quantity=1, entry_price=100,
        )
        await executor.exit_position("A", ExitReason.SIGNAL, current_price=105)
        assert any(e[0] == "exit" for e in executor._events)


# ---------------------------------------------------------------------------
# TradeExecutor — Flip
# ---------------------------------------------------------------------------

class TestExecutorFlip:

    @pytest.mark.asyncio
    async def test_flip_long_to_short(self, executor):
        await executor.enter(
            symbol="NIFTY", token="26000", exchange="NFO",
            direction="LONG", quantity=75, entry_price=22500,
        )
        pos = await executor.flip_position(
            "NIFTY", "SHORT", current_price=22600,
            token="26000", exchange="NFO",
        )
        assert pos is not None
        assert pos.direction == "SHORT"
        assert pos.state == TradeState.OPEN

        # Old position should be in closed trades
        assert len(executor.get_closed_trades()) == 1
        assert executor.get_closed_trades()[0].exit_reason == ExitReason.FLIP


# ---------------------------------------------------------------------------
# TradeExecutor — EOD
# ---------------------------------------------------------------------------

class TestExecutorEOD:

    @pytest.mark.asyncio
    async def test_eod_exit_all(self, executor):
        await executor.enter(
            symbol="A", token="1", exchange="NSE",
            direction="LONG", quantity=1, entry_price=100,
        )
        await executor.enter(
            symbol="B", token="2", exchange="NSE",
            direction="SHORT", quantity=1, entry_price=200,
        )
        assert len(executor.get_open_positions()) == 2

        await executor.eod_exit_all(
            current_prices={"A": 105, "B": 190},
            token_map={"A": ("1", "NSE"), "B": ("2", "NSE")},
        )
        assert len(executor.get_open_positions()) == 0
        assert len(executor.get_closed_trades()) == 2
        for trade in executor.get_closed_trades():
            assert trade.exit_reason == ExitReason.EOD


# ---------------------------------------------------------------------------
# TradeExecutor — Confirm fills
# ---------------------------------------------------------------------------

class TestExecutorConfirm:

    @pytest.mark.asyncio
    async def test_confirm_entry_fill(self, executor):
        # Simulate pending by using a placer that returns PENDING
        # For paper placer it fills immediately, so we manually set state
        pos = await executor.enter(
            symbol="X", token="1", exchange="NSE",
            direction="LONG", quantity=10, entry_price=50,
        )
        # Force to pending state for test
        pos.state = TradeState.PENDING_ENTRY
        pos.entry_price = None
        executor.positions["X"] = pos

        executor.confirm_entry_fill("X", 50.5)
        assert executor.positions["X"].state == TradeState.OPEN
        assert executor.positions["X"].entry_price == 50.5


# ---------------------------------------------------------------------------
# TradePosition dataclass
# ---------------------------------------------------------------------------

class TestTradePosition:

    def test_is_open(self):
        p = TradePosition(symbol="A", direction="LONG", quantity=1, state=TradeState.OPEN)
        assert p.is_open is True
        assert p.is_closed is False

    def test_is_closed(self):
        p = TradePosition(symbol="A", direction="LONG", quantity=1, state=TradeState.CLOSED)
        assert p.is_open is False
        assert p.is_closed is True

    def test_trailing_is_open(self):
        p = TradePosition(symbol="A", direction="LONG", quantity=1, state=TradeState.TRAILING)
        assert p.is_open is True
