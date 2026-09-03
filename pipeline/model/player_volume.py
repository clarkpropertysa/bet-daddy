"""Player opportunity as share x team volume.

This is what `features/usage.py` and `features/splits.py` were built for and what they
were missing: a team-volume number to be a share OF.

    player_targets = team_pass_attempts x target_share

Splitting them means the projection responds to either changing.

  * the team throws more or less (game script, a new coordinator) -> team volume moves
  * a teammate is out -> the SHARE moves, via the with/without split

THE LEVEL IS ANCHORED ON THE PLAYER'S OWN RATE; the split supplies only the MOVE.

That is a correction, and it was measured. There is an identity hiding in the formula
above -- `share x team_volume == the player's own per-game rate`, exactly, when neither
half is shrunk. So the decomposition can only beat the raw count through the shrinkage
it applies to the team half. Tested on 411 player-seasons, 2022-25, predicting the next
season's targets per game:

    share x shrunk team volume        RMSE 1.541      <- what this module did
    share x unshrunk team volume      RMSE 1.523
    own rate, shrunk to pool          RMSE 1.328      <- best
    own rate x shrunk team ratio      RMSE 1.351

The shrinkage does not merely fail to help, it hurts: prior-season team volume carries
r^2 = 0.021 for plays, so pulling a team toward the league mean while leaving the
player's share alone moves the product away from the one number that does predict --
what the player himself did. It inflates players on low-volume offences and deflates
them on high-volume ones, which is how one Seattle receiver came to hold seven of the
top ten rows on the board.

So the level is `OWN_RATE_SHRINKAGE`-shrunk own rate, and team volume enters only as a
RATIO of adjusted to unadjusted -- game script, wind, and teammate absence, which are
genuinely new information about this game. With no adjustment the ratio is 1.0 and the
projection is the measured-best estimator.

The share is shrunk toward the player's season share by sample size, and the
with/without adjustment is applied ONLY when the split clears its own significance and
sample gates. Section 5.2 is emphatic that most with/without splits are noise; this
consumes the flags `features/splits.py` already computes rather than re-deciding.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pyarrow as pa

# A share estimated on very few games is mostly noise; below this it is blended
# toward the positional prior implied by the player's own raw rate.
MIN_GAMES_FOR_SHARE = 4

# Cap on how far a with/without split may move a share. The splits themselves carry
# wide confidence intervals, and an uncapped delta on a 4-game sample would dominate
# every other input.
MAX_SPLIT_SWING = 0.10

#: (pool mean, shrinkage) per (metric, POSITION), in that metric's own per-game units.
#: Both are MEASURED on consecutive-season pairs for players who held a real role
#: (>= 2 per game) in both; see `scripts/fit_volume_baseline.py`.
#:
#:     targets   WR  n=204  pool 5.79  k 0.78   RMSE 1.474  (unshrunk 1.552)
#:               TE  n=113  pool 4.28  k 0.82   RMSE 1.235  (unshrunk 1.285)
#:               RB  n= 90  pool 3.29  k 0.60   RMSE 0.941  (unshrunk 1.049)
#:     carries   RB  n=124  pool 10.84 k 0.68   RMSE 3.559  (unshrunk 3.904)
#:               QB  n= 52  pool 4.37  k 0.76   RMSE 0.991  (unshrunk 1.134)
#:
#: The carries pools are fitted KNEEL-INCLUSIVE, matching what
#: `features_for_projection` now measures. Fitting them on one definition while the
#: anchor is fed the other is a pool the projection never sees -- for quarterbacks the
#: two differ by about 0.7 carries a game, which is most of what the shrinkage does at
#: that volume.
#:
#: POSITION IS NOT OPTIONAL HERE. A single pooled mean across positions was tried
#: first and is actively harmful: the carries pool is 9.01 when every rusher is thrown
#: together, which is a running back's number, and shrinking a QUARTERBACK toward it
#: pulled Sam Darnold from his own 8.7 rushing yards a game to 17.5 -- straight to the
#: top of the board on an edge that was pure artefact. Shrinking toward the wrong pool
#: is worse than not shrinking at all.
OWN_RATE_PRIOR: dict[tuple[str, str], tuple[float, float]] = {
    ("target_share", "WR"): (5.79, 0.78),
    ("target_share", "TE"): (4.28, 0.82),
    ("target_share", "RB"): (3.29, 0.60),
    ("carry_share", "RB"): (10.84, 0.68),
    ("carry_share", "QB"): (4.37, 0.76),
}


def _anchor(own_per_game: float, metric: str, position: str | None) -> float:
    """The player's own rate, regressed toward the pool of players in his own role.

    An unmeasured (metric, position) pair returns the rate UNSHRUNK. Every remaining
    combination is genuinely rare -- a receiving fullback, a wide receiver taking
    handoffs -- and there were too few of them to fit a pool honestly. Leaving those
    alone costs a little accuracy; inventing a pool for them costs correctness.
    """
    prior = OWN_RATE_PRIOR.get((metric, (position or "").upper()))
    if prior is None:
        return own_per_game
    pool, k = prior
    return pool + (own_per_game - pool) * k


@dataclass
class PlayerVolume:
    player_id: str
    market_share: float
    team_volume: float
    projected: float
    games: int
    split_delta: float | None = None
    split_teammate: str | None = None
    notes: str | None = None


def player_share(
    usage: pa.Table, player_id: str, metric: str = "target_share",
) -> tuple[float | None, int]:
    """Season share and the games it rests on."""
    con = duckdb.connect()
    con.register("u", usage)
    r = con.execute(
        f"select avg({metric}), count(*) from u where player_id = ? and {metric} is not null",
        [player_id],
    ).fetchone()
    return (float(r[0]), int(r[1])) if r and r[0] is not None else (None, 0)


def split_adjustment(
    splits: pa.Table, player_id: str, absent_teammates: list[str],
) -> tuple[float, str | None]:
    """Share delta from teammates who are OUT, using only trustworthy splits.

    Consumes `significant` and `suppressed` from features/splits.py rather than
    re-deriving them: a split that failed its own sample gate must not be applied
    here just because a teammate happens to be absent.
    """
    if not absent_teammates:
        return 0.0, None
    con = duckdb.connect()
    con.register("s", splits)
    placeholders = ", ".join("?" for _ in absent_teammates)
    rows = con.execute(f"""
        select teammate_id, delta, n_without, confound_regulars_out
        from s
        where player_id = ?
          and teammate_id in ({placeholders})
          and significant and not suppressed and delta is not null
        order by abs(delta) desc
    """, [player_id, *absent_teammates]).fetchall()
    if not rows:
        return 0.0, None
    # Take the single largest trustworthy split rather than summing: overlapping
    # absences double-count, which is the confounding features/splits.py measures.
    mate, delta, _n, _conf = rows[0]
    return max(-MAX_SPLIT_SWING, min(MAX_SPLIT_SWING, float(delta))), mate


def project_player_volume(
    usage: pa.Table,
    splits: pa.Table | None,
    player_id: str,
    team_volume: float,
    absent_teammates: list[str] | None = None,
    metric: str = "target_share",
    fallback_per_game: float | None = None,
    game_script_ratio: float = 1.0,
    position: str | None = None,
) -> PlayerVolume | None:
    """Projected opportunity for one player in one game.

    `fallback_per_game` is the player's own historical rate and is now the ANCHOR, not
    a fallback -- see the module docstring for the measurement that made it so. It is
    still the sole estimate when the share is too thin to carry a split.

    `game_script_ratio` is this game's team volume over the team's unadjusted volume:
    spread, wind, and the current-season blend. 1.0 means nothing game-specific is
    known, and the projection reduces to the shrunk own rate.
    """
    share, games = player_share(usage, player_id, metric)

    if fallback_per_game is None:
        # Nothing to anchor on. A share alone cannot produce a level.
        return None

    anchored = _anchor(fallback_per_game, metric, position)

    if share is None or games < MIN_GAMES_FOR_SHARE:
        # Not enough games to trust a share, so no with/without split can apply. The
        # game-script ratio still does -- it is a property of the team, not the share.
        return PlayerVolume(
            player_id=player_id, market_share=share or 0.0,
            team_volume=team_volume, projected=anchored * game_script_ratio,
            games=games,
            notes=f"share rests on {games} games; used his own per-game rate instead",
        )

    delta, mate = (split_adjustment(splits, player_id, absent_teammates or [])
                   if splits is not None else (0.0, None))
    adjusted = max(0.0, min(1.0, share + delta))
    # The split enters as a RATIO for the same reason team volume does: `anchored`
    # already contains this player's own share, so multiplying by the share again
    # would apply it twice. Only the CHANGE in share is new information.
    split_ratio = (adjusted / share) if share > 0 else 1.0
    return PlayerVolume(
        player_id=player_id, market_share=adjusted, team_volume=team_volume,
        projected=anchored * game_script_ratio * split_ratio, games=games,
        split_delta=delta or None, split_teammate=mate,
    )
