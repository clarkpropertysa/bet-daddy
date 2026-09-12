"""Games a player barely appeared in, which a per-game rate must not count as games.

Joe Burrow's 2025: week 1 a full start, week 2 THIRTY PERCENT of the snaps and then ten
weeks out injured, then six healthy starts. Averaged flat, that reads 34.5 attempts and
226 yards a game. His six healthy starts averaged 39.2 and 270. The projection took the
flat number, so the board offered "Burrow under 225 passing yards" at a 21c edge against
a market pricing him at 27% -- and the market was pricing a healthy quarterback while the
model was pricing one who got hurt in week 2 and could not tell the difference.

The distortion runs both ways and is worst where it matters most: a truncated game drags
the MEAN down and inflates the SPREAD, and both errors push toward the under. Measured on
the Week 2 board, 51 of 142 players with snap data carried at least one such game.

WHAT COUNTS AS TRUNCATED IS RELATIVE TO THE PLAYER, not to a fixed share. A WR3 playing
38% of snaps is doing his job; a starting quarterback playing 30% left injured. So the
test is against the player's OWN median snap share, and a game below half of it is not a
sample of his role.

Efficiency is left alone. Yards per completion is a per-PLAY rate and a short appearance
does not bias it -- only the per-GAME counts are affected -- so the bootstrap still draws
on every play the player ran.
"""
from __future__ import annotations

import duckdb

#: A game below this fraction of the player's own median snap share is not his role.
TRUNCATED_FACTOR = 0.5

#: QUARTERBACKS ONLY, AND THE BACKTEST IS WHY. Applied to everyone, this filter made
#: the model worse: Brier 0.1470 against 0.1466 over the 2025 replay, with receiving
#: the loser (receptions 0.1486 -> 0.1495, rec_yds 0.1424 -> 0.1429, and the mean bias
#: on receptions widening from -0.081 to -0.104). Applied to passing it was a clear
#: gain -- pass_yds 0.1775 -> 0.1758 and its width 0.972 -> 1.002, which is as close to
#: correct as any market in the model gets.
#:
#: The split is mechanical, not fitted. A quarterback is all-or-nothing: he takes every
#: snap or he left, so a game at 30% of his median IS an injury exit. A receiver's share
#: swings with role and game script, so his low games are mostly real low-usage games --
#: a blowout, a heavy-run plan, a rotation. Dropping those keeps only the games that
#: went well, which is selecting on the outcome, and the replay priced it exactly that
#: way: every receiving projection rose and every receiving number got worse.
TRUNCATION_POSITIONS = frozenset({"QB"})


def applies_to(position: str | None) -> bool:
    """Whether a truncated-game filter is honest for this position. See above."""
    return (position or "").upper() in TRUNCATION_POSITIONS

#: Below this many games there is no reliable median to compare against, so nothing is
#: excluded: with three games and one bad one the median is itself the outlier.
MIN_GAMES_FOR_MEDIAN = 4


def truncated_games(
    snaps_path: str,
    players_path: str,
    player_id: str,
    through_week: int | None = None,
    factor: float = TRUNCATED_FACTOR,
    min_games: int = MIN_GAMES_FOR_MEDIAN,
) -> set[str]:
    """Game ids where this player played far below his own usual share of snaps.

    `through_week` bounds BOTH the median and the games it judges, so a backtest for
    week N never sees a snap count from week N or later.
    """
    wk = f"and s.week < {int(through_week)}" if through_week is not None else ""
    try:
        rows = duckdb.connect().execute(
            f"""
            with idmap as (
                select distinct pfr_id, gsis_id from read_parquet('{players_path}')
                where pfr_id is not null and gsis_id is not null
            ),
            mine as (
                select s.game_id, s.offense_pct as pct
                from read_parquet('{snaps_path}') s
                join idmap m on m.pfr_id = s.pfr_player_id
                where m.gsis_id = ? and s.game_type = 'REG'
                  and coalesce(s.offense_snaps, 0) > 0 and s.offense_pct is not null
                  {wk}
            ),
            med as (select median(pct) as mp, count(*) as n from mine)
            select mine.game_id
            from mine, med
            where med.n >= {int(min_games)} and mine.pct < {float(factor)} * med.mp
            """,
            [player_id],
        ).fetchall()
    except duckdb.IOException:
        # No snap file for this season -- the caller keeps every game, which is the
        # behaviour that existed before this filter.
        return set()
    return {r[0] for r in rows}
