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


# ---------------------------------------------------------------- kneel-downs

@needs_pbp
def test_kneels_count_as_rushing_attempts_for_the_projection():
    """The market settles on official statistics, and a knee is an official carry.

    Verified against nflverse weekly stats for 2025: of the players who took at least
    one knee, 34 season totals match the kneel-INCLUSIVE figure exactly and only 7
    match kneel-free. J.J. McCarthy's official 181 yards on 37 carries is exactly his
    kneel-inclusive total; kneel-free he reads 191 on 28.

    Excluding them projected quarterbacks above what the market pays out on, always in
    the same direction.
    """
    from pipeline.model.features_for_projection import load_player_inputs

    con = duckdb.connect()
    # A quarterback with kneels and enough volume to clear the history floor.
    row = con.execute(f"""
        with p as (
            select * from read_parquet('{PBP}')
            where season_type='REG' and coalesce(two_point_attempt,0)=0
              and rusher_player_id is not null
        )
        select rusher_player_id,
               sum(coalesce(qb_kneel,0)) kneels,
               count(*) att_all,
               sum(case when coalesce(qb_kneel,0)=0 then 1 else 0 end) att_nokneel,
               count(distinct game_id) g
        from p group by 1
        having sum(coalesce(qb_kneel,0)) >= 8 and count(distinct game_id) >= 10
        order by kneels desc limit 1
    """).fetchone()
    if not row:
        pytest.skip("no quarterback with enough kneels in this file")
    pid, kneels, att_all, att_nokneel, games = row
    assert att_all > att_nokneel        # the definitions genuinely differ

    pi = load_player_inputs(str(PBP), pid)
    # carries_per_game is averaged over games with a carry, so compare against the
    # kneel-inclusive count rather than recomputing the mean.
    assert pi.carries_per_game == pytest.approx(att_all / games, rel=0.02), (
        "carries_per_game must count kneels; it is a settlement-facing rate"
    )
    assert pi.carries_per_game > att_nokneel / games


@needs_pbp
def test_kneels_do_not_leak_into_passing_or_receiving():
    """Admitting kneels is safe only because they carry no passer and no receiver."""
    n = duckdb.connect().execute(f"""
        select count(passer_player_id) + count(receiver_player_id)
        from read_parquet('{PBP}')
        where season_type='REG' and coalesce(qb_kneel,0)=1
    """).fetchone()[0]
    assert n == 0


@needs_pbp
def test_share_denominators_still_exclude_kneels_and_still_agree():
    """The two conventions coexist on purpose.

    Rate inputs face settlement and count kneels; share denominators describe football
    and do not. That is safe because team volume enters the projection only as a ratio
    of adjusted to unadjusted, where a consistent convention cancels -- but the two
    share modules must still agree with EACH OTHER, which is what this asserts.
    """
    from pipeline.features.usage import _SCRIMMAGE

    assert "qb_kneel" in _SCRIMMAGE
    tv = volume_dict(build_team_volume(str(PBP)))
    kneels_by_team = dict(duckdb.connect().execute(f"""
        select posteam, count(*) from read_parquet('{PBP}')
        where season_type='REG' and coalesce(qb_kneel,0)=1 and posteam is not null
        group by 1
    """).fetchall())
    assert sum(kneels_by_team.values()) > 0      # there are kneels to exclude
    for team, v in tv.items():
        assert v.rush_attempts > 0
        # rush_attempts is play_type='run', which never includes a kneel
        assert v.plays == pytest.approx(v.pass_attempts + v.rush_attempts)


# ---------------------------------------------------------------- role changes

def test_a_backup_promoted_to_starter_is_refused():
    """Malik Willis: 42% of Green Bay's snaps across four games in 2025, Miami's QB1
    in 2026. The QB1 snap norm is 0.922, so his prior season contains no observation
    of a starter's workload -- and the projection anchors the LEVEL on that rate, so
    it came out at 109.4 passing yards against a public consensus of 175-211, as the
    largest edge on the board."""
    from pipeline.features.role import is_unsampled, role_ratio

    assert is_unsampled(role_ratio(0.42, "QB", 1))


def test_a_demoted_receiver_is_refused():
    """Jauan Jennings at 82% of San Francisco's snaps, now Minnesota's WR3 behind
    Jefferson and Addison. Measured over 215 pairs, this direction over-projects by
    a full target per game -- the strongest signal in the table."""
    from pipeline.features.role import is_unsampled, role_ratio

    assert is_unsampled(role_ratio(0.82, "WR", 3))


def test_a_committee_back_is_NOT_refused():
    """The guard must not fire on players whose role simply is a timeshare. Jaylen
    Warren and J.K. Dobbins both took ~51% of snaps and are still RB1s in committees;
    the RB1 norm is 0.534, so nothing has changed for them. Refusing here would delete
    most of the running back board to no purpose."""
    from pipeline.features.role import is_unsampled, role_ratio

    for snap in (0.51, 0.47, 0.62):
        assert not is_unsampled(role_ratio(snap, "RB", 1)), snap


def test_an_injured_starter_keeps_his_rate():
    """Kyler Murray played five games in 2025 but at 99% of snaps. Few games is not a
    role change, and `player_volume` already measured that thin samples deserve the
    same shrinkage as full ones."""
    from pipeline.features.role import is_unsampled, role_ratio

    assert not is_unsampled(role_ratio(0.99, "QB", 1))


def test_silence_is_not_a_failure():
    """No prior snaps, an unmapped slot, or a missing depth rank must yield NO opinion.
    Refusing on absent information would empty the board rather than clean it."""
    from pipeline.features.role import is_unsampled, role_ratio

    assert role_ratio(None, "WR", 1) is None
    assert role_ratio(0.5, "WR", 9) is None          # WR9 has no measured norm
    assert role_ratio(0.5, None, 1) is None
    assert role_ratio(0.5, "WR", None) is None
    assert not is_unsampled(None)


def test_the_norms_are_ordered_by_seniority():
    """A WR1 must expect more snaps than a WR2 than a WR3. If this inverts, the table
    was transcribed wrong and every ratio is meaningless."""
    from pipeline.features.role import ROLE_SNAP_NORM as N

    assert N[("WR", 1)] > N[("WR", 2)] > N[("WR", 3)]
    assert N[("RB", 1)] > N[("RB", 2)]
    assert N[("TE", 1)] > N[("TE", 2)]
    assert N[("QB", 1)] > N[("WR", 1)]
