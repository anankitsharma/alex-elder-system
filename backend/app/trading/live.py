"""
Live Trading Placer — sends orders to Angel One via broker/orders.py.

Used when settings.trading_mode == "LIVE".
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from loguru import logger

from backend.app.broker.orders import place_order, cancel_order
from backend.app.trading.executor import OrderResult


class LivePlacer:
    """
    Places real orders on Angel One SmartAPI.

    Order results are returned with status PENDING — the executor should
    wait for WebSocket fill confirmation via confirm_entry_fill / confirm_exit_fill.
    """

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
        result = await asyncio.to_thread(
            place_order,
            symbol=symbol,
            token=token,
            exchange=exchange,
            direction=direction,
            order_type=order_type,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            product_type=product_type,
        )

        order_id = str(result.get("orderid", result.get("data", {}).get("orderid", "")))
        status = "PENDING" if order_id else "REJECTED"
        message = result.get("message", str(result))

        logger.info(f"[LIVE] ENTRY {direction} {symbol} x{quantity} → {status} id={order_id}")

        return OrderResult(
            order_id=order_id,
            status=status,
            filled_price=None,  # fill comes via WebSocket
            filled_quantity=None,
            message=message,
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
        result = await asyncio.to_thread(
            place_order,
            symbol=symbol,
            token=token,
            exchange=exchange,
            direction=direction,
            order_type=order_type,
            quantity=quantity,
            price=price,
            product_type=product_type,
        )

        order_id = str(result.get("orderid", result.get("data", {}).get("orderid", "")))
        status = "PENDING" if order_id else "REJECTED"
        message = result.get("message", str(result))

        logger.info(f"[LIVE] EXIT {direction} {symbol} x{quantity} → {status} id={order_id}")

        return OrderResult(
            order_id=order_id,
            status=status,
            filled_price=None,
            filled_quantity=None,
            message=message,
            timestamp=datetime.now(),
        )

    async def cancel(self, order_id: str) -> bool:
        result = await asyncio.to_thread(cancel_order, order_id)
        success = bool(result.get("status", False))
        logger.info(f"[LIVE] CANCEL {order_id} → {'OK' if success else 'FAILED'}")
        return success
