"""Trading execution — executor, paper placer, live placer."""

from .executor import TradeExecutor, TradePosition, TradeState, ExitReason, OrderResult
from .paper import PaperPlacer

# LivePlacer depends on broker/angel_client which needs runtime config.
# Import it explicitly where needed: from backend.app.trading.live import LivePlacer

__all__ = [
    "TradeExecutor",
    "TradePosition",
    "TradeState",
    "ExitReason",
    "OrderResult",
    "PaperPlacer",
]
