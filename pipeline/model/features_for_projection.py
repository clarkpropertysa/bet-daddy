"""Assemble per-player model inputs from the Parquet layer.

Point-in-time by construction: every query takes a `season`/`through_week` bound and
never reads beyond it. A projection for week N may only see weeks < N.

Players with no prior data are SKIPPED with a recorded reason, never defaulted to a
league average. Section 0 rule 3 -- a plausible invented baseline is exactly the kind
of fake number that survives into the UI and destroys the point of the tool.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np

from pipeline.features.rates import shrink, shrink_samples


@dataclass
class PlayerInputs:
    player_id: str
    games: int
    targets_per_game: float
    catch_rate: float
    carries_per_game: float
    yards_per_catch: np.ndarray
    yards_per_carry: np.ndarray
    target_dispersion: float
    carry_dispersion: float
    # passing (QBs)
    attempts_per_game: float = 0.0
    completion_rate: float = 0.0
    yards_per_completion: np.ndarray = None  # type: ignore[assignment]
    attempt_dispersion: float = 1.0
    pass_td_rate: float = 0.0


class InsufficientHistory(Exception):
    """Not enough prior data to project this player honestly."""


MIN_GAMES = 4


def load_player_inputs(
    pbp_path: str,
    player_id: str,
    season_type: str = "REG",
    through_week: int | None = None,
    min_games: int = MIN_GAMES,
) -> PlayerInputs:
    con = duckdb.connect()
    wk = f"and week < {int(through_week)}" if through_week is not None else ""

    # KNEEL-DOWNS ARE OFFICIAL RUSHING ATTEMPTS, and these rates face settlement.
    #
    # A Kalshi rushing-yards market settles on the official statistic, and the NFL
    # scores a kneel as a carry for negative yards. Verified against nflverse weekly
    # stats over 2025: of the players who took at least one knee, 34 season totals
    # match the kneel-INCLUSIVE figure exactly against 7 that match kneel-free --
    # J.J. McCarthy's official 181 yards on 37 carries is precisely his kneel-
    # inclusive total, and his kneel-free total is 191 on 28.
    #
    # Excluding them therefore projected a quarterback ABOVE what the market pays
    # out on, by 0.77 yards a game on average and 1.8 at worst (Stafford), always in
    # the same direction. Only quarterbacks are affected -- no running back, receiver
    # or tight end took a knee all season.
    #
    # Kneels carry no passer_player_id and no receiver_player_id (checked: 0 of 434),
    # so admitting them here cannot touch the passing or receiving inputs. The SHARE
    # denominators in features/usage.py and model/team_volume.py deliberately keep
    # excluding them: those two must agree with each other -- tests/test_volume_units.py
    # pins that -- and they now enter the projection only as a RATIO of adjusted to
    # unadjusted volume, where any consistent convention cancels out.
    row = con.execute(f"""
        with plays as (
            select * from read_parquet('{pbp_path}')
            where season_type = '{season_type}'
              and coalesce(two_point_attempt, 0) = 0
              {wk}
        ),
        rec as (
            select game_id, count(*) t, sum(coalesce(complete_pass,0)) c
            from plays where receiver_player_id = ? group by 1
        ),
        rush as (
            select game_id, count(*) a from plays where rusher_player_id = ? group by 1
        ),
        pass as (
            select game_id, count(*) att,
                   sum(coalesce(complete_pass,0)) comp,
                   sum(coalesce(pass_touchdown,0)) tds
            from plays where passer_player_id = ? group by 1
        )
        select
            (select count(*) from (
                select game_id from rec union
                select game_id from rush union
                select game_id from pass)),
            coalesce((select avg(t) from rec), 0),
            coalesce((select sum(c)::double / nullif(sum(t),0) from rec), 0),
            coalesce((select avg(a) from rush), 0),
            coalesce((select var_samp(t) / nullif(avg(t),0) from rec), 1.0),
            coalesce((select var_samp(a) / nullif(avg(a),0) from rush), 1.0),
            coalesce((select avg(att) from pass), 0),
            coalesce((select sum(comp)::double / nullif(sum(att),0) from pass), 0),
            coalesce((select var_samp(att) / nullif(avg(att),0) from pass), 1.0),
            coalesce((select sum(tds)::double / nullif(sum(att),0) from pass), 0),
            coalesce((select sum(att) from pass), 0)
    """, [player_id, player_id, player_id]).fetchone()

    (games, tpg, cr, cpg, t_disp, c_disp, apg, comp_rate, a_disp, td_rate,
     total_att) = row
    if not games or games < min_games:
        raise InsufficientHistory(
            f"{player_id}: {games or 0} prior games, need {min_games}"
        )

    ypc = np.array([r[0] for r in con.execute(f"""
        select yards_gained from read_parquet('{pbp_path}')
        where receiver_player_id = ? and complete_pass = 1
          and season_type = '{season_type}' {wk}
    """, [player_id]).fetchall()], dtype=float)

    # Kneels included for the same reason: they are attempts the market settles on,
    # and their yardage (-1.06 on average) belongs in the efficiency draw rather than
    # being quietly dropped from it.
    ypcarry = np.array([r[0] for r in con.execute(f"""
        select yards_gained from read_parquet('{pbp_path}')
        where rusher_player_id = ? and season_type = '{season_type}'
          and coalesce(two_point_attempt, 0) = 0 {wk}
    """, [player_id]).fetchall()], dtype=float)

    ypcomp = np.array([r[0] for r in con.execute(f"""
        select yards_gained from read_parquet('{pbp_path}')
        where passer_player_id = ? and complete_pass = 1
          and season_type = '{season_type}' {wk}
    """, [player_id]).fetchall()], dtype=float)

    return PlayerInputs(
        player_id=player_id,
        games=int(games),
        targets_per_game=float(tpg),
        catch_rate=float(cr),
        carries_per_game=float(cpg),
        yards_per_catch=ypc,
        yards_per_carry=ypcarry,
        # dispersion is var/mean; below 1 the negative binomial is undefined, and
        # Poisson is the honest fallback rather than forcing overdispersion
        target_dispersion=max(float(t_disp), 1.0),
        carry_dispersion=max(float(c_disp), 1.0),
        # REGRESSED TOWARD THE LEAGUE. Every quarterback rate here is weakly
        # persistent -- the strongest explains 24% of the next season -- and every one
        # was previously carried forward at full strength. Cam Ward's rookie 2.52%
        # touchdown rate became a 0.9-touchdown projection and a 98%-confident under;
        # Stafford's 7.7% became 2.8 a game. See features/rates.py for the fit and the
        # attempts floor that keeps these off non-passers.
        attempts_per_game=float(shrink(apg, "attempts_per_game", total_att) or 0.0),
        completion_rate=float(shrink(comp_rate, "completion_rate", total_att) or 0.0),
        yards_per_completion=shrink_samples(ypcomp, "yards_per_completion", total_att),
        attempt_dispersion=max(float(a_disp), 1.0),
        pass_td_rate=float(shrink(float(td_rate), "pass_td_rate", total_att) or 0.0),
    )
