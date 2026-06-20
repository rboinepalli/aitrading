"""
risk/position_manager.py — Position sizing with conviction scaling.

v3 adds conviction-scaled sizing:
  5/8 score = 80% of max_per_trade  (lower conviction → smaller bet)
  6/8 score = 100% of max_per_trade (baseline)
  7/8 score = 115% of max_per_trade (strong signal → bigger bet)
  8/8 score = 130% of max_per_trade (maximum conviction → maximum bet)

Why scale by conviction?
  Flat-betting every trade wastes edge. A 8/8 signal (all indicators agree)
  is empirically stronger than a 5/8 signal. Sizing up on high conviction
  and down on low conviction increases expected value per dollar risked.

  TypeScript analogy: this is like a confidence-weighted multiplier on
  an ML model's output — you bet more when the model is more certain.
"""

import logging
import math

logger = logging.getLogger(__name__)

# Multiplier applied to max_per_trade based on conviction score
# Score below 5 should never reach this function (entry gating filters it)
_CONVICTION_SCALE: dict[int, float] = {
    5: 0.80,
    6: 1.00,
    7: 1.15,
    8: 1.30,
}


def calculate_shares(
    price: float,
    buying_power: float,
    max_per_trade: float,
    strategy_budget: float,
    conviction_score: int = 6,
) -> int:
    """
    Calculate whole shares to buy, capped by three limits and scaled by conviction.

    Sizing logic:
      1. Scale max_per_trade by conviction (5/8=80%, 6=100%, 7=115%, 8=130%)
      2. Cap at strategy_budget (total capital allocated to this strategy)
      3. Cap at available buying_power in the Alpaca account
      4. floor() — always whole shares, never fractional

    Returns 0 if price <= 0 or any limit prevents buying even 1 share.
    """
    if price <= 0:
        logger.warning("Invalid price %.2f — cannot size position", price)
        return 0

    # Scale max_per_trade by conviction; clamp score to [5, 8] range
    scale = _CONVICTION_SCALE.get(min(max(conviction_score, 5), 8), 1.0)
    scaled_max = max_per_trade * scale

    max_spend = min(scaled_max, strategy_budget, buying_power)
    shares = math.floor(max_spend / price)

    if shares <= 0:
        logger.warning(
            "Cannot open position: max_spend=%.2f < price=%.2f", max_spend, price
        )

    logger.info(
        "Position size: %d shares @ $%.2f = $%.2f "
        "(conviction=%d/8 scale=%.0f%% cap: trade=$%.0f budget=$%.0f power=$%.0f)",
        shares, price, shares * price,
        conviction_score, scale * 100,
        scaled_max, strategy_budget, buying_power,
    )
    return shares
