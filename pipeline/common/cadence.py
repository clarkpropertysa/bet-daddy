"""Adaptive snapshot cadence.

Kalshi lists prop markets ~15 days before close. Snapshotting every 15 minutes for
that whole window costs 1,440 snapshots per market to capture a number that only
matters in the final hour -- 3.91 GB/season with orderbooks attached, which exceeds
every free object-storage tier.

Closing line value is measured at T-60m against the settlement price. Density far from
close buys almost nothing; density near close is the entire point. So sample on a
schedule shaped like the value of the data:

    <= 6h to close    every 15 min   (captures T-60m precisely)
    6h - 48h          every 60 min   (pre-slate line movement)
    > 48h             every 6h       (listing drift, injury-news repricing)

Result: ~118 snapshots per market instead of 1,440 (12x fewer, 0.32 GB/season).
"""
from __future__ import annotations

FIFTEEN_MIN = 15
HOUR = 60
SIX_HOURS = 360


def snapshot_interval_mins(mins_to_close: int | None) -> int:
    """Desired sampling interval for a market this far from close."""
    if mins_to_close is None:
        return HOUR
    if mins_to_close <= 6 * 60:
        return FIFTEEN_MIN
    if mins_to_close <= 48 * 60:
        return HOUR
    return SIX_HOURS


def is_due(mins_to_close: int | None, mins_since_last: float | None) -> bool:
    """True if this market should be re-snapshotted now.

    A market never snapshotted (mins_since_last is None) is always due -- first
    observation of a newly listed market is never skipped.
    """
    if mins_since_last is None:
        return True
    # 1-minute tolerance: the job runs every 15 min and must not skip a due market
    # merely because it fired 30 seconds early.
    return mins_since_last >= snapshot_interval_mins(mins_to_close) - 1
