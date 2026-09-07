"""Closing line value from the market archive (Sections 8, and D1).

CLV is the single most predictive metric of long-run edge, and -- crucially -- it is
computable WITHOUT historical Kalshi data. Kalshi does not retain settled prop markets
across seasons, so a conventional historical backtest is impossible (DECISIONS.md D1).
Measuring forward against our own archive is what replaces it.

For a YES position entered at price E with closing price C, both in dollars:

    clv_cents = (C - E) * 100

Positive CLV means the market moved toward the position after entry: the bet was
better than the closing line. For a NO position the sign flips, because a NO holder
profits when the yes price falls.

CLV is measured on price movement alone and does not depend on the outcome. That is
the point: it is a far lower-variance signal of edge than win rate, and it is readable
after a few dozen contracts rather than a few hundred settlements.

THE CLOSING LINE IS KICKOFF, not market close. Kalshi's `close_time` is a settlement
deadline two days after the game and these markets stay open through it, so the last
price before close has already seen most of the result. Measuring there would have made
CLV a slow restatement of settlement and forfeited the independence above.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import duckdb

CENTS = Decimal("100")


@dataclass(frozen=True)
class PricePoint:
    market_ticker: str
    ts: datetime
    mins_to_close: int
    yes_bid: Decimal | None
    yes_ask: Decimal | None

    @property
    def mid(self) -> Decimal | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2


def _con(archive_glob: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        f"create or replace view snaps as select * from read_parquet('{archive_glob}')"
    )
    return con


def price_at(
    archive_glob: str, market_ticker: str, mins_before_close: int
) -> PricePoint | None:
    """The archived snapshot closest to T-minus-`mins_before_close`.

    Only snapshots at or before that point are eligible -- picking the nearest in
    absolute terms would happily return a LATER snapshot and leak price information
    from after the reconstruction time.
    """
    con = _con(archive_glob)
    r = con.execute(
        """
        select market_ticker, ts, mins_to_close, yes_bid, yes_ask
        from snaps
        where market_ticker = ? and mins_to_close >= ?
        order by mins_to_close asc
        limit 1
        """,
        [market_ticker, mins_before_close],
    ).fetchone()
    return PricePoint(*r) if r else None


def closing_price(
    archive_glob: str, market_ticker: str, kickoff=None
) -> PricePoint | None:
    """The last archived snapshot before KICKOFF -- the closing line.

    `kickoff` is required for a meaningful answer and optional only so that callers
    with no schedule can still see the last observed price. Without it this falls back
    to the last snapshot before Kalshi's `close_time`, which is a settlement deadline
    two days after the game: these markets carry `can_close_early` and stay open
    THROUGH the game, so that price has already watched the outcome happen. CLV
    measured against it stops being independent of the result, which is the single
    property that makes it readable after dozens of contracts instead of hundreds.
    """
    con = _con(archive_glob)
    if kickoff is not None:
        r = con.execute(
            """
            select market_ticker, ts, mins_to_close, yes_bid, yes_ask
            from snaps
            where market_ticker = ? and ts <= ?
            order by ts desc
            limit 1
            """,
            [market_ticker, kickoff],
        ).fetchone()
    else:
        r = con.execute(
            """
            select market_ticker, ts, mins_to_close, yes_bid, yes_ask
            from snaps
            where market_ticker = ? and mins_to_close >= 0
            order by mins_to_close asc
            limit 1
            """,
            [market_ticker],
        ).fetchone()
    return PricePoint(*r) if r else None


def compute_clv_cents(
    entry_price: Decimal | float | str,
    close_price: Decimal | float | str,
    side: str,
) -> Decimal:
    """CLV in cents for a position taken at `entry_price`.

    Sign convention: positive means the market moved in the position's favour.
    """
    e, c = Decimal(str(entry_price)), Decimal(str(close_price))
    if side not in ("yes", "no"):
        raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
    move = (c - e) * CENTS
    return move if side == "yes" else -move


def settle_pnl_cents(
    entry_price: Decimal | float | str,
    side: str,
    result: str,
    fee_cents: Decimal | float | str,
) -> Decimal:
    """Realised P&L per contract in cents, net of the entry fee.

    A contract settles at $1 or $0. A YES wins when result is 'yes'.
    """
    e = Decimal(str(entry_price))
    fee = Decimal(str(fee_cents))
    if side not in ("yes", "no"):
        raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
    if result not in ("yes", "no"):
        raise ValueError(f"result must be 'yes' or 'no', got {result!r}")

    cost = e * CENTS if side == "yes" else (Decimal(1) - e) * CENTS
    won = (side == result)
    payout = CENTS if won else Decimal(0)
    return payout - cost - fee
