"""
broker/alpaca_client.py — Thin wrapper around the Alpaca paper trading API.

Why wrap the SDK instead of calling it directly?
  - Centralises error handling and logging in one place.
  - Makes it easy to swap paper → live by just changing the base URL.
  - Easier to mock in unit tests (TypeScript analogy: a service class).

Alpaca lets you trade stocks and ETFs via a REST API.
The alpaca-py SDK handles auth and request formatting for us.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position dataclass — a clean Python struct for what we care about.
# TypeScript analogy: interface OpenPosition { ticker: string; ... }
# ---------------------------------------------------------------------------
@dataclass
class OpenPosition:
    ticker: str
    shares: float
    entry_price: float          # average cost basis
    current_price: float
    market_value: float         # shares * current_price
    unrealized_pnl: float       # in dollars
    unrealized_pnl_pct: float   # as a decimal, e.g. 0.05 = +5%


class AlpacaClient:
    """Manages all communication with the Alpaca brokerage API."""

    def __init__(self, cfg: Config):
        # TradingClient handles auth and knows whether to hit paper or live URLs.
        # paper=True tells it to use paper trading endpoints automatically.
        self._client = TradingClient(
            api_key=cfg.alpaca_api_key,
            secret_key=cfg.alpaca_secret_key,
            paper=(cfg.alpaca_base_url == "https://paper-api.alpaca.markets"),
        )
        logger.info("AlpacaClient connected (paper=%s)", cfg.alpaca_base_url)

    # -----------------------------------------------------------------------
    # Account info
    # -----------------------------------------------------------------------

    def get_buying_power(self) -> float:
        """
        Return available cash / buying power in dollars.

        Alpaca paper accounts expose several monetary fields — we try them
        in order until we find one that's non-zero.
        """
        account = self._client.get_account()

        # Log every monetary field so we can see exactly what Alpaca returns
        def _f(val) -> float:
            try:
                return float(val) if val is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        buying_power              = _f(account.buying_power)
        cash                      = _f(account.cash)
        equity                    = _f(account.equity)
        portfolio_value           = _f(getattr(account, "portfolio_value", None))
        non_marginable_bp         = _f(getattr(account, "non_marginable_buying_power", None))
        regt_bp                   = _f(getattr(account, "regt_buying_power", None))
        daytrading_bp             = _f(getattr(account, "daytrading_buying_power", None))

        logger.info(
            "Account — buying_power=%.2f  cash=%.2f  equity=%.2f  "
            "portfolio_value=%.2f  non_marginable_bp=%.2f  regt_bp=%.2f  daytrading_bp=%.2f",
            buying_power, cash, equity,
            portfolio_value, non_marginable_bp, regt_bp, daytrading_bp,
        )

        # Return the first non-zero value in preference order
        for label, val in [
            ("non_marginable_bp", non_marginable_bp),
            ("cash",              cash),
            ("equity",            equity),
            ("portfolio_value",   portfolio_value),
            ("regt_bp",           regt_bp),
            ("buying_power",      buying_power),
            ("daytrading_bp",     daytrading_bp),
        ]:
            if val > 0:
                logger.info("Using %s = $%.2f as buying power", label, val)
                return val

        logger.error(
            "All Alpaca account fields are 0 — check paper.alpaca.markets "
            "to confirm the account has funds and the API key is correct."
        )
        return 0.0

    def get_daily_pnl(self) -> float:
        """
        Return today's realized P&L in dollars.
        Alpaca tracks this as equity change from yesterday's close.
        """
        account = self._client.get_account()
        # last_equity is yesterday's closing equity
        return float(account.equity) - float(account.last_equity)

    # -----------------------------------------------------------------------
    # Position management
    # -----------------------------------------------------------------------

    def get_open_position(self, ticker: str) -> Optional[OpenPosition]:
        """
        Return the current open position for a ticker, or None if flat.

        Alpaca raises an exception (not None) when there's no position,
        so we catch that and convert it to None — a cleaner interface.
        """
        try:
            pos = self._client.get_open_position(ticker)
            return OpenPosition(
                ticker=pos.symbol,
                shares=float(pos.qty),
                entry_price=float(pos.avg_entry_price),
                current_price=float(pos.current_price),
                market_value=float(pos.market_value),
                unrealized_pnl=float(pos.unrealized_pl),
                unrealized_pnl_pct=float(pos.unrealized_plpc),  # already a decimal
            )
        except Exception:
            # No position open for this ticker
            return None

    def has_any_open_position(self) -> bool:
        """Return True if any position is open (we only allow one at a time)."""
        positions = self._client.get_all_positions()
        return len(positions) > 0

    # -----------------------------------------------------------------------
    # Order execution
    # -----------------------------------------------------------------------

    def buy(self, ticker: str, shares: int) -> str:
        """
        Submit a market buy order. Returns the Alpaca order ID.

        Market orders fill immediately at the current ask price.
        We use DAY time-in-force so the order cancels if not filled by close.
        """
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(request)
        logger.info("BUY order submitted: %s x%d (id=%s)", ticker, shares, order.id)
        return str(order.id)

    def sell_all(self, ticker: str) -> str:
        """
        Close the entire position for a ticker via a market sell order.
        Returns the Alpaca order ID.
        """
        request = MarketOrderRequest(
            symbol=ticker,
            qty=None,           # qty=None with close_position tells Alpaca to sell all shares
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        # Use close_position which handles the full-position close cleanly
        order = self._client.close_position(ticker)
        logger.info("SELL order submitted: %s (id=%s)", ticker, order.id)
        return str(order.id)
