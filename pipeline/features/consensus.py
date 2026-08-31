"""Comparing Kalshi's price to the sportsbook consensus.

REFERENCE ONLY. Nothing here may produce a Signal, an edge, or a bet size.

DECISIONS.md D8 deferred paid odds data with an explicit revisit trigger: "Revisit if the
archive shows Kalshi pricing diverging from consensus." That trigger was unmeasurable,
because measuring it appeared to require the very data it was gating. It does not:

- Kalshi lists NFL game markets (`KXNFLGAME`) alongside its player props.
- nflverse ships closing Vegas moneylines, spreads and totals in `schedules.parquet`,
  free, and the Slate already displays them.

Game markets need no player identity, which is what makes this affordable. The paid path
foundered on cross-source name resolution -- a book gives you "Brock Purdy" where the
crosswalk expects `SFBPURDY13` -- and a game market has no player in it at all.

WHY THIS IS NOT AN EDGE CALCULATION. `signal.py` assumes a $1 binary contract: the
unquoted side is `1 - yes_price`, Kelly uses `b = (1 - price) / price`, and `fees.py`
rejects any price outside [0,1] dollars. American odds satisfy none of that. Keeping this
module reference-only is not timidity about the spec; it is the reason none of that
machinery has to change.
"""
from __future__ import annotations

from dataclasses import dataclass


def american_to_prob(odds: int | float) -> float:
    """American odds -> implied probability, vig included.

    -150 -> 0.600, +150 -> 0.400. The result is the book's price, not a belief: the two
    sides of a market sum to more than 1 by exactly the book's margin.
    """
    o = float(odds)
    if o == 0:
        raise ValueError("American odds cannot be 0")
    if o < 0:
        return -o / (-o + 100.0)
    return 100.0 / (o + 100.0)


def devig_pair(p_a: float, p_b: float) -> tuple[float, float]:
    """Normalise a two-sided market so the probabilities sum to 1.

    Multiplicative (proportional) de-vigging: each side is divided by the overround.
    Chosen over Shin or power methods because it makes no assumption about how the
    margin is distributed between favourite and longshot. Those methods exist precisely
    because the margin usually is NOT proportional -- books load more of it onto
    longshots -- so this will be slightly wrong in a known direction on lopsided games.
    That is acceptable for a reference comparison and would not be for a bet.

    Applied to BOTH venues. Kalshi's two team markets are separate binaries whose asks
    also sum above 1, by its own spread. De-vigging the book and comparing it to a raw
    exchange ask would manufacture divergence equal to that spread -- inventing the bias
    the comparison exists to detect.
    """
    total = p_a + p_b
    if total <= 0:
        raise ValueError(f"probabilities must sum above 0, got {total}")
    return p_a / total, p_b / total


@dataclass(frozen=True)
class GameComparison:
    kalshi_prob_home: float
    vegas_prob_home: float
    #: Kalshi minus consensus, in percentage points. Positive = Kalshi rates the home
    #: team higher than the book consensus does.
    diff_pts: float
    kalshi_overround: float
    vegas_overround: float


def compare_game(
    kalshi_home_ask: float,
    kalshi_away_ask: float,
    vegas_home_ml: int | float,
    vegas_away_ml: int | float,
) -> GameComparison:
    """One game's divergence, both sides de-vigged the same way.

    Kalshi asks are decimal dollars in [0,1] and ARE implied probabilities; the Vegas
    inputs are American odds and are converted first.
    """
    for name, ask in (("home", kalshi_home_ask), ("away", kalshi_away_ask)):
        if not (0.0 < ask < 1.0):
            raise ValueError(f"kalshi {name} ask must be in (0,1) dollars, got {ask}")

    k_home, _ = devig_pair(kalshi_home_ask, kalshi_away_ask)
    v_home, _ = devig_pair(
        american_to_prob(vegas_home_ml), american_to_prob(vegas_away_ml)
    )
    return GameComparison(
        kalshi_prob_home=k_home,
        vegas_prob_home=v_home,
        diff_pts=(k_home - v_home) * 100.0,
        kalshi_overround=kalshi_home_ask + kalshi_away_ask,
        vegas_overround=american_to_prob(vegas_home_ml) + american_to_prob(vegas_away_ml),
    )


def summarise(comparisons: list[GameComparison]) -> dict:
    """Aggregate divergence -- the number D8 actually asks for.

    Reports MEAN ABSOLUTE divergence alongside the signed mean. The signed mean is near
    zero whenever Kalshi is noisy but unbiased, which reads as agreement and is the
    opposite of what noise means for a prop trader. Both are needed to tell "Kalshi
    tracks consensus" from "Kalshi is all over the place".
    """
    n = len(comparisons)
    if n == 0:
        return {"n": 0, "mean_diff_pts": None, "mean_abs_diff_pts": None,
                "max_abs_diff_pts": None}
    diffs = [c.diff_pts for c in comparisons]
    return {
        "n": n,
        "mean_diff_pts": sum(diffs) / n,
        "mean_abs_diff_pts": sum(abs(d) for d in diffs) / n,
        "max_abs_diff_pts": max(abs(d) for d in diffs),
    }
