"""
Paper Trading Placer — simulates order execution without touching the broker.

Fills all orders instantly at the requested price.
Used when settings.trading_mode == "PAPER".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from loguru import logger

try:
    from app.trading.executor import OrderResult
except ImportError:
    from backend.app.trading.executor import OrderResult


class PaperPlacer:
    """
    Simulates order placement for paper trading.

    All orders fill immediately at the requested price (or a configurable
    slippage offset).  No network calls are made.
    """

    def __init__(self, slippage_pct: float = 0.0):
        """
        Args:
            slippage_pct: Simulated slippage as a percentage (e.g. 0.01 = 1%).
                          Positive slippage worsens fills: buys fill higher, sells fill lower.
        """
        self.slippage_pct = slippage_pct
        self.orders: list[dict] = []  # audit log
        logger.info(f"PaperPlacer initialized (slippage={slippage_pct:.2%})")

    async def place_entry(
        self,
        symbol: str,
        token: str,
        exchange: str,
        direction: str,
        quantity: int,
        order_type: str,
        price: float,
        trigger_price: float,
        product_type: str,
    ) -> OrderResult:
        order_id = f"PAPER-{uuid.uuid4().hex[:8]}"
        fill_price = self._apply_slippage(price or trigger_price, direction)

        record = {
            "order_id": order_id,
            "side": "ENTRY",
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
            "order_type": order_type,
            "requested_price": price,
            "fill_price": fill_price,
            "timestamp": datetime.now(),
        }
        self.orders.append(record)
        logger.info(f"[PAPER] ENTRY {direction} {symbol} x{quantity} @ {fill_price:.2f}")

        return OrderResult(
            order_id=order_id,
            status="FILLED",
            filled_price=fill_price,
            filled_quantity=quantity,
            message="Paper fill",
            timestamp=datetime.now(),
        )

    async def place_exit(
        self,
        symbol: str,
        token: str,
        exchange: str,
        direction: str,
        quantity: int,
        order_type: str,
        price: float,
        product_type: str,
    ) -> OrderResult:
        order_id = f"PAPER-{uuid.uuid4().hex[:8]}"
        fill_price = self._apply_slippage(price, direction)

        record = {
            "order_id": order_id,
            "side": "EXIT",
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
            "order_type": order_type,
            "requested_price": price,
            "fill_price": fill_price,
            "timestamp": datetime.now(),
        }
        self.orders.append(record)
        logger.info(f"[PAPER] EXIT {direction} {symbol} x{quantity} @ {fill_price:.2f}")

        return OrderResult(
            order_id=order_id,
            status="FILLED",
            filled_price=fill_price,
            filled_quantity=quantity,
            message="Paper fill",
            timestamp=datetime.now(),
        )

    async def cancel(self, order_id: str) -> bool:
        logger.info(f"[PAPER] CANCEL {order_id}")
        return True

    def _apply_slippage(self, price: float, direction: str) -> float:
        if price <= 0 or self.slippage_pct == 0:
            return price
        # Buy fills higher, Sell fills lower
        if direction == "BUY":
            return round(price * (1 + self.slippage_pct), 4)
        else:
            return round(price * (1 - self.slippage_pct), 4)

    def get_order_log(self, limit: int = 50) -> list[dict]:
        return self.orders[-limit:]
