"""Does the prior season contain a sample of the role the player now occupies?

The projection anchors on a player's own PER-GAME rate from last season. That is the
best estimator available -- measured, see `model/player_volume` -- but it carries a
silent assumption: that last season's role resembles this season's. When it does not,
the anchor is a confident number describing a job the player no longer has.

MEASURED, on 215 receiving pairs from 2024 into 2025, bucketing by the player's prior
snap share over the median snap share of the depth slot he occupies in the OUTCOME
season:

    prior_snap / role_norm      n     RMSE     bias
    < 0.60  (role grew)        10    1.304   -0.250
    0.60-0.80                  18    1.471   +0.034
    0.80-1.25  (matched)      122    1.309   +0.213
    1.25-1.60                  46    1.217   +0.293
    > 1.60  (role shrank)      19    1.490   +1.053

A player whose role SHRANK is over-projected by **a full target per game** -- five times
the bias of a matched role, and the worst RMSE in the table. That case is refused on
measured evidence.

The role-GREW case is refused on weaker evidence: n=10, and the RMSE is not actually
worse. It is refused on SAMPLING grounds rather than predictive ones. Malik Willis took
42% of Green Bay's snaps across four games in 2025 and is Miami's starting quarterback
in 2026; the QB1 snap norm is 0.922 with a quartile range of 0.857-0.967. His prior
season contains no observation of a starter's workload, so a per-game rate drawn from it
is not an estimate of anything -- it is a backup's number wearing a starter's label. That
is a data-availability statement, and this project's answer to missing data is an empty
state naming the reason, not a confident guess.

Refusing costs coverage. It is the cheaper error: the alternative shipped Willis at 109.4
passing yards against a public consensus of 175-211, as the largest edge on the board.
"""
from __future__ import annotations

import duckdb

#: Median offensive snap share by (position, depth rank), measured on 2025 for players
#: with at least six games. Quartiles are in the module history; the medians are what
#: the ratio is taken against.
#:
#:     QB1 0.922   RB1 0.534   RB2 0.183   TE1 0.601
#:     TE2 0.363   WR1 0.776   WR2 0.572   WR3 0.390
ROLE_SNAP_NORM: dict[tuple[str, int], float] = {
    ("QB", 1): 0.922,
    ("RB", 1): 0.534, ("RB", 2): 0.183,
    ("TE", 1): 0.601, ("TE", 2): 0.363,
    ("WR", 1): 0.776, ("WR", 2): 0.572, ("WR", 3): 0.390,
}

#: Outside this band the prior season is not a sample of the current role.
#: The upper bound carries the measured bias (+1.05 targets/game); the lower bound is
#: a sampling judgement, deliberately loose so that ordinary variation survives it.
MIN_RATIO = 0.60
MAX_RATIO = 1.60


def prior_snap_share(snap_counts_path: str, players_path: str) -> dict[str, float]:
    """gsis_id -> mean offensive snap share last season.

    Reuses the pfr->gsis join in `splits.build_availability` (99.7% coverage) rather
    than repeating it, and requires enough games that the mean means something.
    """
    try:
        rows = duckdb.connect().execute(f"""
            with idmap as (
                select distinct pfr_id, gsis_id from read_parquet('{players_path}')
                where pfr_id is not null and gsis_id is not null
            )
            select m.gsis_id, avg(s.offense_pct)
            from read_parquet('{snap_counts_path}') s
            join idmap m on m.pfr_id = s.pfr_player_id
            where s.game_type = 'REG' and s.offense_pct is not null
            group by 1 having count(*) >= 4
        """).fetchall()
    except Exception:
        return {}
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def role_ratio(
    prior_snap: float | None, position: str | None, depth_rank: int | None
) -> float | None:
    """Prior snap share over the norm for the current role, or None if unknowable.

    None means "no opinion" and must never be treated as a failure: an unmapped slot
    (WR4, a fullback) or a player with no prior snaps is exactly the case where this
    check has nothing to say, and refusing on silence would delete the board.
    """
    if prior_snap is None or not position or depth_rank is None:
        return None
    norm = ROLE_SNAP_NORM.get((position.upper(), int(depth_rank)))
    if not norm:
        return None
    return prior_snap / norm


def is_unsampled(ratio: float | None) -> bool:
    """True when last season cannot speak to this season's role."""
    if ratio is None:
        return False
    return ratio < MIN_RATIO or ratio > MAX_RATIO


def describe(ratio: float, position: str, depth_rank: int, prior_snap: float) -> str:
    """One line for the skip log, stating the direction rather than just the number."""
    norm = ROLE_SNAP_NORM.get((position.upper(), int(depth_rank)), 0.0)
    grew = ratio < MIN_RATIO
    return (
        f"{position}{depth_rank} expects ~{norm:.0%} of snaps; he took {prior_snap:.0%} "
        f"last season ({'a much smaller' if grew else 'a much larger'} role), so his "
        f"per-game rate is not a sample of this one"
    )
