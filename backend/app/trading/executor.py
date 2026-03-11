"""
Trade Executor — Unified entry/exit engine with state machine.

Adapted from reference: modules/live_orders/live_trade_executor.py
Changes:
  - Decoupled from database — state kept in-memory, persisted via callbacks
  - Supports PAPER and LIVE modes via strategy pattern
  - No Telegram dependency (notifications via pluggable callback)
  - Uses our broker/orders.py for live execution
  - Clean async interface throughout

Trade states:
  IDLE → PENDING_ENTRY → OPEN → (TRAILING) → PENDING_EXIT → CLOSED
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol
from loguru import logger


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TradeState(str, Enum):
    IDLE = "IDLE"
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN = "OPEN"
    TRAILING = "TRAILING"
    PENDING_EXIT = "PENDING_EXIT"
    CLOSED = "CLOSED"


class ExitReason(str, Enum):
    STOPLOSS = "STOPLOSS"
    FLIP = "FLIP"
    TARGET = "TARGET"
    EOD = "EOD"
    MANUAL = "MANUAL"
    SIGNAL = "SIGNAL"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class OrderResult:
    order_id: str
    status: str  # PENDING, FILLED, REJECTED, CANCELLED
    filled_price: Optional[float] = None
    filled_quantity: Optional[int] = None
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TradePosition:
    symbol: str
    direction: str  # LONG or SHORT
    quantity: int
    entry_price: Optional[float] = None
    entry_order_id: Optional[str] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    exit_price: Optional[float] = None
    exit_order_id: Optional[str] = None
    exit_reason: Optional[ExitReason] = None
    state: TradeState = TradeState.IDLE
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self.state in (TradeState.OPEN, TradeState.TRAILING)

    @property
    def is_closed(self) -> bool:
        return self.state == TradeState.CLOSED


# ---------------------------------------------------------------------------
# Order placer protocol (strategy pattern for PAPER vs LIVE)
# ---------------------------------------------------------------------------

class OrderPlacer(Protocol):
    """Interface for placing orders — implemented by LivePlacer / PaperPlacer."""

    async def place_entry(
        self, symbol: str, token: str, exchange: str,
        direction: str, quantity: int,
        order_type: str, price: float, trigger_price: float,
        product_type: str,
    ) -> OrderResult: ...

    async def place_exit(
        self, symbol: str, token: str, exchange: str,
        direction: str, quantity: int,
        order_type: str, price: float,
        product_type: str,
    ) -> OrderResult: ...

    async def cancel(self, order_id: str) -> bool: ...


# ---------------------------------------------------------------------------
# Trade Executor
# ---------------------------------------------------------------------------

NotifyCallback = Callable[[str, Dict[str, Any]], Any]


class TradeExecutor:
    """
    Manages trade lifecycle: entry → stoploss/trailing → exit.

    Usage:
        placer = PaperPlacer()  # or LivePlacer(...)
        executor = TradeExecutor(placer)

        pos = await executor.enter(symbol="NIFTY", token="26000", exchange="NFO",
                                   direction="LONG", quantity=75,
                                   entry_price=22500, stop_price=22400)
        # ... later ...
        await executor.exit_position(pos, ExitReason.STOPLOSS, current_price=22390)
    """

    def __init__(
        self,
        placer: OrderPlacer,
        on_notify: Optional[NotifyCallback] = None,
    ):
        self.placer = placer
        self.on_notify = on_notify or self._default_notify
        self.positions: Dict[str, TradePosition] = {}  # symbol → active position
        self.closed_trades: List[TradePosition] = []
        logger.info("TradeExecutor initialized")

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    async def enter(
        self,
        symbol: str,
        token: str,
        exchange: str,
        direction: str,
        quantity: int,
        entry_price: float = 0,
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        order_type: str = "MARKET",
        trigger_price: float = 0,
        product_type: str = "CARRYFORWARD",
    ) -> Optional[TradePosition]:
        """Place an entry order and create a position."""

        # Guard: already in a position for this symbol
        if symbol in self.positions and self.positions[symbol].is_open:
            logger.warning(f"Already in position for {symbol}, skipping entry")
            return self.positions[symbol]

        pos = TradePosition(
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            stop_price=stop_price,
            target_price=target_price,
            state=TradeState.PENDING_ENTRY,
        )

        result = await self.placer.place_entry(
            symbol=symbol, token=token, exchange=exchange,
            direction="BUY" if direction == "LONG" else "SELL",
            quantity=quantity, order_type=order_type,
            price=entry_price, trigger_price=trigger_price,
            product_type=product_type,
        )

        pos.entry_order_id = result.order_id

        if result.status in ("FILLED", "COMPLETE"):
            pos.entry_price = result.filled_price or entry_price
            pos.entry_time = result.timestamp
            pos.state = TradeState.OPEN
            logger.info(f"ENTRY FILLED {symbol} {direction} x{quantity} @ {pos.entry_price}")
        elif result.status == "PENDING":
            pos.state = TradeState.PENDING_ENTRY
            logger.info(f"ENTRY PENDING {symbol} {direction} order_id={result.order_id}")
        else:
            logger.error(f"ENTRY FAILED {symbol}: {result.message}")
            pos.state = TradeState.CLOSED
            self._notify("entry_failed", {"symbol": symbol, "reason": result.message})
            return None

        self.positions[symbol] = pos
        self._notify("entry", {
            "symbol": symbol, "direction": direction,
            "price": pos.entry_price, "order_id": result.order_id,
        })
        return pos

    # ------------------------------------------------------------------
    # Confirm entry fill (for async fills via websocket)
    # ------------------------------------------------------------------

    def confirm_entry_fill(self, symbol: str, filled_price: float, filled_qty: Optional[int] = None):
        """Call when entry order fill is confirmed (e.g. from WebSocket)."""
        pos = self.positions.get(symbol)
        if pos is None or pos.state != TradeState.PENDING_ENTRY:
            return
        pos.entry_price = filled_price
        if filled_qty:
            pos.quantity = filled_qty
        pos.entry_time = datetime.now()
        pos.state = TradeState.OPEN
        logger.info(f"Entry confirmed {symbol} @ {filled_price}")

    # ------------------------------------------------------------------
    # Update stoploss (trailing)
    # ------------------------------------------------------------------

    def update_stop(self, symbol: str, new_stop: float):
        """Update stoploss level for an open position."""
        pos = self.positions.get(symbol)
        if pos is None or not pos.is_open:
            return

        if pos.direction == "LONG" and new_stop > (pos.stop_price or 0):
            pos.stop_price = new_stop
            pos.state = TradeState.TRAILING
            logger.debug(f"Trailing SL up for {symbol}: {new_stop:.4f}")
        elif pos.direction == "SHORT" and (pos.stop_price is None or new_stop < pos.stop_price):
            pos.stop_price = new_stop
            pos.state = TradeState.TRAILING
            logger.debug(f"Trailing SL down for {symbol}: {new_stop:.4f}")

    # ------------------------------------------------------------------
    # Check stoploss
    # ------------------------------------------------------------------

    def check_stop(self, symbol: str, current_price: float) -> bool:
        """Return True if stoploss is breached and exit should be triggered."""
        pos = self.positions.get(symbol)
        if pos is None or not pos.is_open or pos.stop_price is None:
            return False

        if pos.direction == "LONG" and current_price <= pos.stop_price:
            return True
        if pos.direction == "SHORT" and current_price >= pos.stop_price:
            return True
        return False

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    async def exit_position(
        self,
        symbol: str,
        reason: ExitReason,
        current_price: float = 0,
        order_type: str = "MARKET",
        token: str = "",
        exchange: str = "",
        product_type: str = "CARRYFORWARD",
    ) -> Optional[TradePosition]:
        """Exit an open position."""
        pos = self.positions.get(symbol)
        if pos is None or not pos.is_open:
            logger.warning(f"No open position for {symbol} to exit")
            return None

        pos.state = TradeState.PENDING_EXIT
        exit_direction = "SELL" if pos.direction == "LONG" else "BUY"

        result = await self.placer.place_exit(
            symbol=symbol, token=token, exchange=exchange,
            direction=exit_direction, quantity=pos.quantity,
            order_type=order_type, price=current_price,
            product_type=product_type,
        )

        pos.exit_order_id = result.order_id
        pos.exit_reason = reason

        if result.status in ("FILLED", "COMPLETE"):
            pos.exit_price = result.filled_price or current_price
            pos.exit_time = result.timestamp
            pos.state = TradeState.CLOSED
            pos.pnl = self._calc_pnl(pos)
            logger.info(f"EXIT {reason.value} {symbol} @ {pos.exit_price} PnL={pos.pnl}")
        elif result.status == "PENDING":
            logger.info(f"EXIT PENDING {symbol} order_id={result.order_id}")
        else:
            logger.error(f"EXIT FAILED {symbol}: {result.message}")
            pos.state = TradeState.OPEN  # revert to open
            return pos

        if pos.is_closed:
            self.closed_trades.append(pos)
            del self.positions[symbol]

        self._notify("exit", {
            "symbol": symbol, "reason": reason.value,
            "price": pos.exit_price, "pnl": pos.pnl,
        })
        return pos

    # ------------------------------------------------------------------
    # Confirm exit fill
    # ------------------------------------------------------------------

    def confirm_exit_fill(self, symbol: str, filled_price: float):
        pos = self.positions.get(symbol)
        if pos is None or pos.state != TradeState.PENDING_EXIT:
            return
        pos.exit_price = filled_price
        pos.exit_time = datetime.now()
        pos.state = TradeState.CLOSED
        pos.pnl = self._calc_pnl(pos)
        self.closed_trades.append(pos)
        del self.positions[symbol]
        logger.info(f"Exit confirmed {symbol} @ {filled_price} PnL={pos.pnl}")

    # ------------------------------------------------------------------
    # Flip (reverse direction)
    # ------------------------------------------------------------------

    async def flip_position(
        self,
        symbol: str,
        new_direction: str,
        current_price: float,
        token: str = "",
        exchange: str = "",
        quantity: Optional[int] = None,
        product_type: str = "CARRYFORWARD",
    ) -> Optional[TradePosition]:
        """Exit current position and enter in opposite direction."""
        pos = self.positions.get(symbol)
        if pos and pos.is_open:
            await self.exit_position(symbol, ExitReason.FLIP, current_price,
                                     token=token, exchange=exchange,
                                     product_type=product_type)

        qty = quantity or (pos.quantity if pos else 1)
        return await self.enter(
            symbol=symbol, token=token, exchange=exchange,
            direction=new_direction, quantity=qty,
            entry_price=current_price, product_type=product_type,
        )

    # ------------------------------------------------------------------
    # EOD exit all
    # ------------------------------------------------------------------

    async def eod_exit_all(
        self,
        token_map: Optional[Dict[str, tuple]] = None,
        current_prices: Optional[Dict[str, float]] = None,
    ):
        """Exit all open positions — called at end-of-day cutoff."""
        symbols = list(self.positions.keys())
        for sym in symbols:
            pos = self.positions[sym]
            if not pos.is_open:
                continue
            price = (current_prices or {}).get(sym, 0)
            token, exchange = (token_map or {}).get(sym, ("", ""))
            await self.exit_position(
                sym, ExitReason.EOD, current_price=price,
                token=token, exchange=exchange,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_pnl(pos: TradePosition) -> Optional[float]:
        if pos.entry_price is None or pos.exit_price is None:
            return None
        if pos.direction == "LONG":
            return round((pos.exit_price - pos.entry_price) * pos.quantity, 2)
        else:
            return round((pos.entry_price - pos.exit_price) * pos.quantity, 2)

    def _notify(self, event: str, data: Dict[str, Any]):
        try:
            self.on_notify(event, data)
        except Exception as e:
            logger.warning(f"Notification callback error: {e}")

    @staticmethod
    def _default_notify(event: str, data: Dict[str, Any]):
        logger.info(f"Trade event: {event} — {data}")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_open_positions(self) -> Dict[str, TradePosition]:
        return {s: p for s, p in self.positions.items() if p.is_open}

    def get_closed_trades(self, limit: int = 50) -> List[TradePosition]:
        return self.closed_trades[-limit:]

    def get_position(self, symbol: str) -> Optional[TradePosition]:
        return self.positions.get(symbol)
