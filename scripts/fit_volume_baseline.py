"""Does share x shrunk team volume beat the player's own rate? Measure, do not assume.

The projection builds a receiving baseline as `target_share x team_targets`. Both halves
come from the prior season, and the team half is shrunk toward the league mean
(`PLAYS_SHRINKAGE = 0.14`, `PASS_RATE_SHRINKAGE = 0.39`) while the player half is not.

That asymmetry is worth measuring rather than reasoning about, because of an identity
that makes most of the argument moot:

    share_Y x team_targets_Y == player_targets_per_game_Y     (exactly)

So an UNSHRUNK decomposition is just the player's own observed rate wearing a costume.
The decomposition can only earn its keep through the shrinkage -- and shrinking one
component while leaving the other alone is not obviously the right way to do it. It
pulls a player on a low-volume offence up and one on a high-volume offence down, which
is precisely the pattern that put seven Jaxon Smith-Njigba rungs on the board.

Run:  uv run python scripts/fit_volume_baseline.py
"""
from __future__ import annotations

import glob
import re
import statistics as st

import duckdb

from pipeline.model.team_volume import (
    LEAGUE_PASS_RATE,
    LEAGUE_PLAYS_PER_GAME,
    LEAGUE_TARGET_RATIO,
    PASS_RATE_SHRINKAGE,
    PLAYS_SHRINKAGE,
    TARGET_RATIO_SHRINKAGE,
)

MIN_GAMES = 8          # a rate off fewer games is mostly noise
MIN_TARGETS_PG = 2.0   # below this the market has no line anyway
MIN_CELL = 25          # below this a position gets no pool of its own
PLAYERS = "data/raw/nflverse/players.parquet"


def _season_rows(path: str, season: int) -> list[dict]:
    """Per (player, team) season rates, plus that team's own volume."""
    con = duckdb.connect()
    return con.execute(f"""
        with p as (
            select * from read_parquet('{path}')
            where season_type = 'REG' and posteam is not null
              and play_type in ('pass','run')
              and coalesce(two_point_attempt,0) = 0
              and coalesce(qb_kneel,0) = 0
              and coalesce(special,0) = 0
        ),
        team as (
            select posteam team,
                   count(distinct game_id) tg,
                   count(*)::double / count(distinct game_id) plays_pg,
                   avg(case when play_type='pass' then 1.0 else 0.0 end) pass_rate,
                   sum(case when play_type='pass' and receiver_player_id is not null
                            then 1.0 else 0 end)
                     / nullif(sum(case when play_type='pass' then 1.0 else 0 end),0)
                                                                        tratio,
                   sum(case when play_type='pass' and receiver_player_id is not null
                            then 1.0 else 0 end)                        team_targets
            from p group by 1
        ),
        pl as (
            select receiver_player_id pid, posteam team,
                   count(distinct game_id) g,
                   count(*)::double                                      targets
            from p
            where play_type='pass' and receiver_player_id is not null
            group by 1,2
        )
        select pl.pid, pl.team, pl.g, pl.targets,
               t.tg, t.team_targets, t.plays_pg, t.pass_rate, t.tratio,
               ros.position
        from pl join team t on t.team = pl.team
        left join read_parquet('{PLAYERS}') ros on ros.gsis_id = pl.pid
        where pl.g >= {MIN_GAMES}
    """).df().to_dict("records")


def _rush_rows(path: str) -> list[dict]:
    """Per (player, team) season rushing, KNEEL-INCLUSIVE.

    Must match what `features_for_projection.load_player_inputs` measures, or the
    pool fitted here is a pool the anchor never sees. Kneels are official rushing
    attempts and the projection now counts them, so they are counted here too.
    """
    return duckdb.connect().execute(f"""
        with p as (
            select * from read_parquet('{path}')
            where season_type = 'REG' and posteam is not null
              and coalesce(two_point_attempt,0) = 0
              and rusher_player_id is not null
        ),
        agg as (
            select rusher_player_id pid, posteam team,
                   count(distinct game_id) g, count(*)::double carries
            from p group by 1,2 having count(distinct game_id) >= {MIN_GAMES}
        )
        select a.pid, a.team, a.g, a.carries, ros.position
        from agg a
        left join read_parquet('{PLAYERS}') ros on ros.gsis_id = a.pid
    """).df().to_dict("records")


def _fit_pools(obs: list[tuple[str, float, float]], label: str) -> None:
    """Per-position pool mean and the shrinkage that minimises held-out error."""
    groups: dict[str, list[tuple[float, float]]] = {}
    for pos, own, actual in obs:
        groups.setdefault(pos or "?", []).append((own, actual))
    for pos, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(g) < MIN_CELL:
            print(f"{label:9} {pos:4} {len(g):5}   -- below the {MIN_CELL}-pair floor, "
                  f"left unshrunk")
            continue
        pool = st.mean(a for _, a in g)
        k, rmse = min(
            ((k, _err([(pool + (o - pool) * k, a) for o, a in g])[0])
             for k in [i / 100 for i in range(40, 106, 2)]), key=lambda x: x[1])
        raw = _err([(o, a) for o, a in g])[0]
        print(f"{label:9} {pos:4} {len(g):5} {pool:7.2f} {k:6.2f} {rmse:8.3f} {raw:9.3f}")


def _shrunk_team_targets(r: dict) -> float:
    """What build_team_volume would produce for this team, prior-season only."""
    plays = LEAGUE_PLAYS_PER_GAME + (r["plays_pg"] - LEAGUE_PLAYS_PER_GAME) * PLAYS_SHRINKAGE
    rate = LEAGUE_PASS_RATE + (r["pass_rate"] - LEAGUE_PASS_RATE) * PASS_RATE_SHRINKAGE
    tratio = LEAGUE_TARGET_RATIO + (r["tratio"] - LEAGUE_TARGET_RATIO) * TARGET_RATIO_SHRINKAGE
    return plays * rate * tratio


def _err(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    rmse = (sum((p - a) ** 2 for p, a in pairs) / len(pairs)) ** 0.5
    mae = sum(abs(p - a) for p, a in pairs) / len(pairs)
    return rmse, mae


def main() -> None:
    paths = {int(re.search(r"(\d{4})", p).group(1)): p
             for p in sorted(glob.glob("data/raw/nflverse/pbp_*.parquet"))}
    seasons = sorted(paths)
    by_season = {y: _season_rows(paths[y], y) for y in seasons}

    # (prior row, actual next-season targets/game), same player, same team
    obs: list[tuple[dict, float]] = []
    for a, b in zip(seasons, seasons[1:]):
        nxt = {(r["pid"], r["team"]): r for r in by_season[b]}
        for r in by_season[a]:
            if r["targets"] / r["g"] < MIN_TARGETS_PG:
                continue
            n = nxt.get((r["pid"], r["team"]))
            if n:
                obs.append((r, n["targets"] / n["g"]))

    if len(obs) < 50:
        print(f"only {len(obs)} player-season pairs -- not enough to decide anything")
        return

    pool = st.mean(a for _, a in obs)

    cands: dict[str, list[tuple[float, float]]] = {}
    for r, actual in obs:
        share = (r["targets"] / r["team_targets"]) if r["team_targets"] else 0.0
        own_pg = r["targets"] / r["g"]
        team_pg = r["team_targets"] / r["tg"]
        cands.setdefault("A share x shrunk team volume (current)", []).append(
            (share * _shrunk_team_targets(r), actual))
        cands.setdefault("B share x unshrunk team volume", []).append(
            (share * team_pg, actual))
        cands.setdefault("C player's own rate, shrunk 0.60 to pool", []).append(
            (pool + (own_pg - pool) * 0.60, actual))
        cands.setdefault("D product shrunk 0.60 to pool", []).append(
            (pool + (share * _shrunk_team_targets(r) - pool) * 0.60, actual))

    print(f"n = {len(obs)} player-seasons, {seasons[0]}-{seasons[-1]}, "
          f"pool mean {pool:.2f} targets/game\n")
    print(f"{'baseline':44} {'RMSE':>7} {'MAE':>7} {'bias':>7}")
    for name, pairs in cands.items():
        rmse, mae = _err(pairs)
        bias = st.mean(p - a for p, a in pairs)
        print(f"{name:44} {rmse:7.3f} {mae:7.3f} {bias:+7.3f}")

    # Best single shrinkage applied to the player's own rate, for reference.
    best = min(
        ((k, _err([(pool + (r['targets'] / r['g'] - pool) * k, a) for r, a in obs])[0])
         for k in [i / 20 for i in range(21)]),
        key=lambda x: x[1])
    print(f"\nbest POOLED shrinkage on the player's own rate: k = {best[0]:.2f} "
          f"(RMSE {best[1]:.3f})")
    print("k = 1.00 would mean no shrinkage; k = 0 would mean everyone is league average.")

    # --- and now the part that actually ships -------------------------------
    #
    # A single pool across positions is not good enough to use. Pooling every rusher
    # gives a mean near 9 carries a game, which is a running back's number; shrinking
    # a QUARTERBACK toward it doubles his rushing projection. Fit per position.
    print("\nPER-POSITION POOLS -- these are the constants in player_volume.py.")
    print("A position below the cell floor is deliberately left unshrunk.\n")
    print(f"{'metric':9} {'pos':4} {'n':>5} {'pool':>7} {'k':>6} {'RMSE':>8} {'unshrunk':>9}")
    _fit_pools(
        [(str(r.get("position") or "?"), r["targets"] / r["g"], a) for r, a in obs],
        "targets",
    )

    # Rushing, on the same footing. KNEEL-INCLUSIVE, matching what the projection now
    # measures -- a pool fitted on a different definition is a pool the anchor never
    # sees, and for quarterbacks the two definitions differ by about 0.7 carries a game.
    rush = {y: _rush_rows(paths[y]) for y in seasons}
    robs: list[tuple[str, float, float]] = []
    for a, b in zip(seasons, seasons[1:]):
        nxt = {(r["pid"], r["team"]): r for r in rush[b]}
        for r in rush[a]:
            if r["carries"] / r["g"] < MIN_TARGETS_PG:
                continue
            n = nxt.get((r["pid"], r["team"]))
            if n:
                robs.append((str(r.get("position") or "?"),
                             r["carries"] / r["g"], n["carries"] / n["g"]))
    _fit_pools(robs, "carries")


if __name__ == "__main__":
    main()
