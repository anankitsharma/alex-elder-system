"""Order placement, modification, and cancellation via Angel One SmartAPI."""

from loguru import logger

from app.broker.angel_client import angel


def place_order(
    symbol: str,
    token: str,
    exchange: str,
    direction: str,  # BUY or SELL
    order_type: str,  # MARKET, LIMIT, SL, SL-M
    quantity: int,
    price: float = 0,
    trigger_price: float = 0,
    product_type: str = "DELIVERY",  # DELIVERY, INTRADAY, MARGIN
    variety: str = "NORMAL",  # NORMAL, AMO, STOPLOSS
    duration: str = "DAY",  # DAY, IOC
) -> dict:
    """Place an order on Angel One.

    Returns:
        dict with 'status', 'orderid', 'message' keys
    """
    params = {
        "variety": variety,
        "tradingsymbol": symbol,
        "symboltoken": token,
        "transactiontype": direction,
        "exchange": exchange,
        "ordertype": order_type,
        "producttype": product_type,
        "duration": duration,
        "quantity": str(quantity),
    }

    if order_type == "LIMIT":
        params["price"] = str(price)
    elif order_type in ("SL", "STOPLOSS_LIMIT"):
        params["price"] = str(price)
        params["triggerprice"] = str(trigger_price)
    elif order_type in ("SL-M", "STOPLOSS_MARKET"):
        params["triggerprice"] = str(trigger_price)

    logger.info("Placing order: {} {} {} x{} @ {} on {}",
                direction, symbol, order_type, quantity, price or "MKT", exchange)

    try:
        result = angel.trading.placeOrder(params)
        if result:
            logger.info("Order placed: {}", result)
        return result or {}
    except Exception as e:
        logger.error("Order placement failed: {}", e)
        return {"status": False, "message": str(e)}


def modify_order(
    order_id: str,
    variety: str = "NORMAL",
    quantity: int | None = None,
    price: float | None = None,
    trigger_price: float | None = None,
    order_type: str | None = None,
) -> dict:
    """Modify an existing order."""
    params = {"variety": variety, "orderid": order_id}
    if quantity is not None:
        params["quantity"] = str(quantity)
    if price is not None:
        params["price"] = str(price)
    if trigger_price is not None:
        params["triggerprice"] = str(trigger_price)
    if order_type is not None:
        params["ordertype"] = order_type

    logger.info("Modifying order {}: {}", order_id, params)
    try:
        return angel.trading.modifyOrder(params) or {}
    except Exception as e:
        logger.error("Order modification failed: {}", e)
        return {"status": False, "message": str(e)}


def cancel_order(order_id: str, variety: str = "NORMAL") -> dict:
    """Cancel an existing order."""
    logger.info("Cancelling order {}", order_id)
    try:
        return angel.trading.cancelOrder(order_id, variety) or {}
    except Exception as e:
        logger.error("Order cancellation failed: {}", e)
        return {"status": False, "message": str(e)}


def place_gtt_order(
    symbol: str,
    token: str,
    exchange: str,
    direction: str,
    trigger_price: float,
    quantity: int,
    price: float = 0,
    product_type: str = "DELIVERY",
) -> dict:
    """Place a GTT (Good Till Triggered) order — used for automated stop losses."""
    params = {
        "tradingsymbol": symbol,
        "symboltoken": token,
        "exchange": exchange,
        "transactiontype": direction,
        "producttype": product_type,
        "price": str(price),
        "qty": str(quantity),
        "triggerprice": str(trigger_price),
        "disclosedqty": "0",
    }

    logger.info("Placing GTT order: {} {} trigger@{} x{}", direction, symbol, trigger_price, quantity)
    try:
        result = angel.trading.gttCreateRule(params)
        if result:
            logger.info("GTT order placed: {}", result)
        return result or {}
    except Exception as e:
        logger.error("GTT order failed: {}", e)
        return {"status": False, "message": str(e)}
