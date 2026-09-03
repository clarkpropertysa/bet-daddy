"""The share and the volume it multiplies must count the same plays.

`player_targets = team_targets x target_share` is an identity, and the two halves are
computed in different modules: `features/usage.py` supplies the share, `model/team_volume.py`
supplies the volume. Nothing connected them, so they drifted:

    target_share denominator   team TARGETS   (no sacks, no throwaways)
    what it was multiplied by  pass PLAYS     (sacks and throwaways included)

Targets are 89.1% of pass plays league-wide, so every receiving baseline was inflated
about 11%, always upward, on top of every other adjustment. On Seattle -- a low-volume
passing offence -- that plus mean-reverted team volume put Jaxon Smith-Njigba at 12.0
projected targets against a 9.6 season average, which manufactured a positive edge on
all fourteen rungs of his receiving-yards ladder at once.

These tests pin the identity itself rather than any one player's number.
"""
from pathlib import Path

import duckdb
import pytest

from pipeline.features.usage import _SCRIMMAGE, build_player_game_usage
from pipeline.model.team_volume import (
    LEAGUE_TARGET_RATIO,
    build_team_volume,
    project_for_game,
    volume_dict,
)

DATA = Path("data/raw/nflverse")
PBP = DATA / "pbp_2025.parquet"
needs_pbp = pytest.mark.skipif(not PBP.exists(), reason="nflverse pbp not ingested")


@needs_pbp
def test_team_targets_matches_the_share_denominator():
    """THE regression test. `TeamVolume.targets` must equal what usage.py divides by.

    Compared unshrunk (the season's own value) so this measures the unit, not the
    prior: build_team_volume shrinks toward the league mean by design.
    """
    usage = build_player_game_usage(str(PBP))
    con = duckdb.connect()
    con.register("u", usage)
    # team_targets is carried on every player row for its (game, team)
    per_team = dict(con.execute("""
        select team, avg(team_targets) from (
            select distinct game_id, team, team_targets from u
        ) group by 1
    """).fetchall())

    raw = dict(duckdb.connect().execute(f"""
        with p as (select * from read_parquet('{PBP}')
                   where season_type = 'REG' and posteam is not null and {_SCRIMMAGE})
        select posteam,
               sum(case when play_type='pass' and receiver_player_id is not null
                        then 1.0 else 0 end) / count(distinct game_id)
        from p group by 1
    """).fetchall())

    assert per_team and raw
    for team, want in sorted(per_team.items()):
        assert team in raw
        assert raw[team] == pytest.approx(want, rel=0.01), team


@needs_pbp
def test_targets_are_not_pass_plays():
    """The bug in one line: they differ by ~11%, so the two are not interchangeable."""
    tv = volume_dict(build_team_volume(str(PBP)))
    for v in tv.values():
        assert v.targets < v.pass_attempts
        assert v.targets == pytest.approx(v.pass_attempts * v.target_ratio)
    ratios = [v.target_ratio for v in tv.values()]
    assert 0.85 < sum(ratios) / len(ratios) < 0.93


@needs_pbp
def test_carry_share_denominator_also_matches():
    """`team_carries` vs `rush_attempts` -- same class of error, caught by the same
    invariant. These disagreed on kneels until the scrimmage filters were aligned."""
    usage = build_player_game_usage(str(PBP))
    con = duckdb.connect()
    con.register("u", usage)
    per_team = dict(con.execute("""
        select team, avg(team_carries) from (
            select distinct game_id, team, team_carries from u
        ) group by 1
    """).fetchall())

    tv = volume_dict(build_team_volume(str(PBP)))
    # Shrunk toward the league mean, so this is a direction-and-scale check, not
    # equality: the units must match even though the estimate is deliberately pulled.
    for team, want in per_team.items():
        if team not in tv:
            continue
        assert tv[team].rush_attempts == pytest.approx(want, rel=0.25), team


@needs_pbp
def test_the_spread_adjustment_reaches_targets():
    """Targets are derived from pass_attempts, so game script must flow through.

    If `targets` were stored as an absolute number instead, a seven-point underdog
    would throw more without any receiver seeing an extra target.
    """
    tv = volume_dict(build_team_volume(str(PBP)))
    base = next(iter(tv.values()))
    dog = project_for_game(base, team_spread=-7.0)
    fav = project_for_game(base, team_spread=+7.0)
    assert dog.targets > base.targets > fav.targets
    assert dog.target_ratio == base.target_ratio


def test_target_ratio_defaults_to_the_league_rate():
    """A team with no measured ratio must not silently become 1.0 -- that is the
    original bug wearing a default value."""
    from pipeline.model.team_volume import TeamVolume

    tv = TeamVolume("XX", plays=61.3, pass_attempts=35.0, rush_attempts=26.3,
                    pass_rate=0.574, games_current=0, prior_only=True)
    assert tv.target_ratio == LEAGUE_TARGET_RATIO
    assert tv.targets < tv.pass_attempts
