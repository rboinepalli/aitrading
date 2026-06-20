"""
signals/entry.py — Time window gating for entries.

v3 responsibility: determine WHICH time window we're in and return
the minimum conviction score required. The actual scoring happens
in strategies/strategy_a.py, strategy_b.py, and strategy_c.py.

Time windows (ET):
  9:30–11:30am  PRIMARY     → min score 5/8 — strongest signals, most volume
  11:30am–1:30pm DEAD ZONE  → NO ENTRIES — markets are choppy mid-day
  1:30pm–3:30pm POWER HOUR  → min score 6/8 — second window, stricter bar
  After 3:30pm  NO ENTRY    → too close to hard close at 3:45pm

Note: DEAD ZONE still runs exit checks on open positions (changed in v3).
      Only NEW entries are blocked; stops and TPs are always monitored.

Why avoid 11:30am–1:30pm?
  Intraday volume and directional momentum are weakest mid-day.
  Narrowed from 11am–2pm (v2) to 11:30am–1:30pm (v3) to capture
  the 11:00–11:30am and 1:30–2:00pm windows which often have good setups.
"""

import logging
from datetime import datetime, time
from enum import Enum

import pytz

ET = pytz.timezone("America/New_York")
logger = logging.getLogger(__name__)


class TimeWindow(str, Enum):
    """
    Which time window is active right now.
    TypeScript analogy: `type TimeWindow = 'PRIMARY' | 'DEAD_ZONE' | 'POWER_HOUR' | 'CLOSED'`
    """
    PRIMARY = "PRIMARY"         # 9:30–11:00am, min score 5
    DEAD_ZONE = "DEAD_ZONE"     # 11am–2pm, no entries
    POWER_HOUR = "POWER_HOUR"   # 2pm–3:30pm, min score 6
    CLOSED = "CLOSED"           # before open or after 3:30pm


def get_time_window(cfg) -> tuple[TimeWindow, int]:
    """
    Return the current time window and the minimum conviction score required.

    Returns:
        (TimeWindow, min_score)
        min_score is 0 for DEAD_ZONE and CLOSED — signals not to enter.
    """
    now = datetime.now(ET).time()

    entry_start = _t(cfg.entry_window_start)    # 09:30
    entry_end = _t(cfg.entry_window_end)         # 11:00
    dead_end = _t(cfg.dead_zone_end)             # 14:00
    power_cutoff = _t(cfg.power_hour_entry_cutoff)  # 15:30

    if now < entry_start:
        return TimeWindow.CLOSED, 0

    if entry_start <= now < entry_end:
        return TimeWindow.PRIMARY, 5   # or cfg.strategy_a.primary_min_score

    if entry_end <= now < dead_end:
        return TimeWindow.DEAD_ZONE, 0

    if dead_end <= now < power_cutoff:
        return TimeWindow.POWER_HOUR, 6  # stricter

    # After 3:30pm — no new entries (exits still run)
    return TimeWindow.CLOSED, 0


def _t(hhmm: str) -> time:
    """Parse "HH:MM" string into a time object."""
    h, m = hhmm.split(":")
    return time(int(h), int(m))
