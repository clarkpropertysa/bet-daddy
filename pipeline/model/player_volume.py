"""Player opportunity as share x team volume.

This is what `features/usage.py` and `features/splits.py` were built for and what they
were missing: a team-volume number to be a share OF.

    player_targets = team_pass_attempts x target_share

Why this beats projecting the raw historical count, which is what the model did
before: a raw count silently assumes both the team's volume and the player's role stay
put. Splitting them means the projection responds to either changing.

  * the team throws more or less (game script, a new coordinator) -> team volume moves
  * a teammate is out -> the SHARE moves, via the with/without split

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
) -> PlayerVolume | None:
    """Projected opportunity for one player in one game."""
    share, games = player_share(usage, player_id, metric)

    if share is None or games < MIN_GAMES_FOR_SHARE:
        # Not enough games to trust a share. Fall back to the raw historical rate
        # rather than inventing one -- an unreliable share multiplied by team volume
        # is worse than the count it replaced.
        if fallback_per_game is None:
            return None
        return PlayerVolume(
            player_id=player_id, market_share=share or 0.0,
            team_volume=team_volume, projected=fallback_per_game, games=games,
            notes=f"share rests on {games} games; used the raw per-game rate instead",
        )

    delta, mate = (split_adjustment(splits, player_id, absent_teammates or [])
                   if splits is not None else (0.0, None))
    adjusted = max(0.0, min(1.0, share + delta))
    return PlayerVolume(
        player_id=player_id, market_share=adjusted, team_volume=team_volume,
        projected=team_volume * adjusted, games=games,
        split_delta=delta or None, split_teammate=mate,
    )
