"""
risk/position_manager.py — Position sizing and one-at-a-time enforcement.

Two responsibilities:
  1. Ensure only ONE position is open at any time (enforced by checking Alpaca).
  2. Calculate how many shares to buy given a dollar limit.

Why limit to $2,000 per trade?
  TQQQ and SQQQ are 3x leveraged — they move 3x the underlying index.
  A $2,000 max exposure means the most you can lose on a single trade
  (hitting the -10% stop loss) is $200.

How share sizing works:
  shares = floor(max_position_usd / current_price)

  Example: TQQQ at $45.50, max $2,000
    floor(2000 / 45.50) = floor(43.95) = 43 shares
    Actual exposure: 43 * $45.50 = $1,956.50

  We use floor() (round down) to never exceed the dollar limit.
"""

import logging
import math

from config import Config

logger = logging.getLogger(__name__)


def calculate_shares(price: float, buying_power: float, cfg: Config) -> int:
    """
    Calculate how many shares to buy, respecting both the position size limit
    and available buying power.

    Args:
        price:          Current ask price of the ticker
        buying_power:   Available cash in the Alpaca account
        cfg:            Config with max_position_usd

    Returns:
        Number of whole shares to buy (0 if not enough buying power for even 1 share)
    """
    if price <= 0:
        logger.warning("Invalid price %.2f — cannot size position", price)
        return 0

    # Never spend more than the configured max OR what we actually have
    max_spend = min(cfg.max_position_usd, buying_power)

    # math.floor ensures we always round DOWN to whole shares (no fractional shares)
    shares = math.floor(max_spend / price)

    if shares <= 0:
        logger.warning(
            "Cannot open position: buying_power=%.2f < price=%.2f", buying_power, price
        )

    logger.info(
        "Position size: %d shares of $%.2f = $%.2f (max $%.2f, power $%.2f)",
        shares, price, shares * price, cfg.max_position_usd, buying_power,
    )
    return shares
