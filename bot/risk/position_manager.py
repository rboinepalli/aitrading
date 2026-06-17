"""
risk/position_manager.py — Position sizing.

v2: accepts both a per-trade max AND a per-strategy budget cap.
The actual spend is the minimum of: max_per_trade, strategy_budget, buying_power.
"""

import logging
import math

logger = logging.getLogger(__name__)


def calculate_shares(
    price: float,
    buying_power: float,
    max_per_trade: float,
    strategy_budget: float,
) -> int:
    """
    Calculate whole shares to buy, capped by three limits:
      1. max_per_trade_usd (e.g. $2,000 per individual trade)
      2. strategy_budget   (e.g. $10,000 total for this strategy)
      3. available buying power in the Alpaca account

    Returns 0 if price <= 0 or any limit prevents buying even 1 share.
    """
    if price <= 0:
        logger.warning("Invalid price %.2f — cannot size position", price)
        return 0

    max_spend = min(max_per_trade, strategy_budget, buying_power)
    shares = math.floor(max_spend / price)

    if shares <= 0:
        logger.warning(
            "Cannot open position: max_spend=%.2f < price=%.2f", max_spend, price
        )

    logger.info(
        "Position size: %d shares @ $%.2f = $%.2f (cap: trade=$%.0f budget=$%.0f power=$%.0f)",
        shares, price, shares * price, max_per_trade, strategy_budget, buying_power,
    )
    return shares
