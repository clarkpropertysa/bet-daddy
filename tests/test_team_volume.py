"""Team volume and share x volume player projection."""
import pyarrow as pa
import pytest

from pipeline.model.player_volume import (
    MAX_SPLIT_SWING,
    OWN_RATE_PRIOR,
    project_player_volume,
    split_adjustment,
)
from pipeline.model.team_volume import (
    LEAGUE_PASS_RATE,
    LEAGUE_PLAYS_PER_GAME,
    PLAYS_SHRINKAGE,
    build_team_volume,
    project_for_game,
    volume_dict,
)

pytestmark = pytest.mark.network
PBP = "data/raw/nflverse/pbp_2025.parquet"


@pytest.fixture(scope="module")
def vols():
    return volume_dict(build_team_volume(PBP))


def test_all_teams_present(vols):
    assert len(vols) == 32


def test_play_counts_are_shrunk_hard_toward_league_mean(vols):
    """Team play count carries r=0.144 year over year -- 2% of variance -- so a
    prior-season pace is worth almost nothing and must collapse toward the mean.
    Leaving it unshrunk would import last year's pace as if it were this year's."""
    spread = max(v.plays for v in vols.values()) - min(v.plays for v in vols.values())
    assert spread < 5.0, "play counts should be tightly clustered after shrinkage"
    assert all(abs(v.plays - LEAGUE_PLAYS_PER_GAME) < 4 for v in vols.values())


def test_pass_rate_retains_more_spread_than_pace(vols):
    """Pass rate is the most stable team trait (r=0.446), so it survives shrinkage
    with real between-team variation while pace does not."""
    rate_spread = max(v.pass_rate for v in vols.values()) - min(v.pass_rate for v in vols.values())
    assert rate_spread > 0.03


def test_underdogs_throw_more(vols):
    """Game script, in the measured direction: pass_rate falls as a team is more
    heavily favoured."""
    v = vols["KC"]
    fav = project_for_game(v, team_spread=7.0)
    dog = project_for_game(v, team_spread=-7.0)
    assert dog.pass_attempts > fav.pass_attempts
    assert dog.pass_rate > fav.pass_rate


def test_game_script_leaves_total_plays_alone(vols):
    """Only the split moves. The projected game total does not predict play count
    (r=0.030 over 1,632 team-games), so nothing here should change pace."""
    v = vols["KC"]
    assert project_for_game(v, 7.0).plays == pytest.approx(v.plays)
    assert project_for_game(v, -7.0).plays == pytest.approx(v.plays)


def test_pass_rate_is_bounded(vols):
    """A 30-point spread must not push the rate somewhere never observed."""
    for sp in (-30.0, 30.0):
        r = project_for_game(vols["KC"], sp).pass_rate
        assert 0.30 <= r <= 0.80


def test_attempts_split_sums_to_plays(vols):
    v = project_for_game(vols["BAL"], -3.0)
    assert v.pass_attempts + v.rush_attempts == pytest.approx(v.plays)


# ---------------------------------------------------------------- splits gate
SPLIT_SCHEMA = pa.schema([
    ("player_id", pa.string()), ("teammate_id", pa.string()),
    ("delta", pa.float64()), ("n_without", pa.int64()),
    ("confound_regulars_out", pa.float64()),
    ("significant", pa.bool_()), ("suppressed", pa.bool_()),
])


def _splits(rows):
    return pa.Table.from_pylist(rows, schema=SPLIT_SCHEMA)


def test_suppressed_split_is_ignored():
    """Section 5.2: most with/without splits are noise. A split that failed its own
    sample gate must not be applied just because the teammate is absent."""
    t = _splits([{"player_id": "P", "teammate_id": "M", "delta": 0.20,
                  "n_without": 2, "confound_regulars_out": 1.0,
                  "significant": False, "suppressed": True}])
    assert split_adjustment(t, "P", ["M"]) == (0.0, None)


def test_significant_unsuppressed_split_is_applied():
    t = _splits([{"player_id": "P", "teammate_id": "M", "delta": 0.06,
                  "n_without": 6, "confound_regulars_out": 1.0,
                  "significant": True, "suppressed": False}])
    delta, mate = split_adjustment(t, "P", ["M"])
    assert delta == pytest.approx(0.06)
    assert mate == "M"


def test_split_swing_is_capped():
    t = _splits([{"player_id": "P", "teammate_id": "M", "delta": 0.40,
                  "n_without": 6, "confound_regulars_out": 1.0,
                  "significant": True, "suppressed": False}])
    delta, _ = split_adjustment(t, "P", ["M"])
    assert delta == pytest.approx(MAX_SPLIT_SWING)


def test_overlapping_absences_take_the_largest_not_the_sum():
    """Summing double-counts: two teammates out together is the confounding that
    features/splits.py measures, not two independent effects."""
    t = _splits([
        {"player_id": "P", "teammate_id": "A", "delta": 0.05, "n_without": 6,
         "confound_regulars_out": 1.0, "significant": True, "suppressed": False},
        {"player_id": "P", "teammate_id": "B", "delta": 0.04, "n_without": 6,
         "confound_regulars_out": 1.0, "significant": True, "suppressed": False},
    ])
    delta, _ = split_adjustment(t, "P", ["A", "B"])
    assert delta == pytest.approx(0.05)


# ---------------------------------------------------------------- fallback
USAGE_SCHEMA = pa.schema([("player_id", pa.string()), ("target_share", pa.float64())])


def test_thin_share_falls_back_to_the_players_own_rate():
    """An unreliable share multiplied by team volume is worse than the count it
    replaced, so below the games floor the player's own rate carries the projection.

    It is SHRUNK toward the pool rather than used raw: 0.84 of the way, measured on
    411 player-seasons (`player_volume.OWN_RATE_PRIOR`). The share is what is
    discarded here, not the regression to the mean.
    """
    u = pa.Table.from_pylist(
        [{"player_id": "P", "target_share": 0.3}] * 2, schema=USAGE_SCHEMA)
    pv = project_player_volume(u, None, "P", 36.0, fallback_per_game=7.0,
                               position="WR")
    pool, k = OWN_RATE_PRIOR[("target_share", "WR")]
    assert pv.projected == pytest.approx(pool + (7.0 - pool) * k)
    assert pv.projected < 7.0          # a high rate regresses down
    assert "his own per-game rate" in pv.notes


def test_a_low_rate_regresses_upward():
    """Shrinkage is toward the pool, not downward. A below-pool player must rise."""
    u = pa.Table.from_pylist(
        [{"player_id": "P", "target_share": 0.05}] * 2, schema=USAGE_SCHEMA)
    pv = project_player_volume(u, None, "P", 36.0, fallback_per_game=2.0,
                               position="WR")
    assert 2.0 < pv.projected < OWN_RATE_PRIOR[("target_share", "WR")][0]


def test_the_level_no_longer_tracks_team_volume():
    """The anchor is the player's own rate, so doubling team volume with no game-script
    ratio must NOT double his targets. That coupling is what inflated a Seattle
    receiver to 12.0 targets against a 9.6 season average."""
    u = pa.Table.from_pylist(
        [{"player_id": "P", "target_share": 0.3}] * 8, schema=USAGE_SCHEMA)
    lo = project_player_volume(u, None, "P", 20.0, fallback_per_game=7.0,
                               position="WR")
    hi = project_player_volume(u, None, "P", 40.0, fallback_per_game=7.0,
                               position="WR")
    assert lo.projected == pytest.approx(hi.projected)


def test_game_script_ratio_is_the_only_team_channel():
    """What a spread or a wind forecast is allowed to do: move the level proportionally."""
    u = pa.Table.from_pylist(
        [{"player_id": "P", "target_share": 0.3}] * 8, schema=USAGE_SCHEMA)
    flat = project_player_volume(u, None, "P", 30.0, fallback_per_game=7.0,
                                 position="WR")
    windy = project_player_volume(
        u, None, "P", 27.0, fallback_per_game=7.0, game_script_ratio=0.9,
        position="WR")
    assert windy.projected == pytest.approx(flat.projected * 0.9)


def test_a_quarterback_is_not_shrunk_toward_the_running_back_pool():
    """The bug this keying exists to prevent.

    Pooling every rusher gives a mean of 9.01 carries a game -- a running back's
    number. Shrinking a quarterback toward it inflated Sam Darnold's rushing
    projection to twice his own rate and put him top of the board.
    """
    u = pa.Table.from_pylist(
        [{"player_id": "P", "carry_share": 0.05}] * 8,
        schema=pa.schema([("player_id", pa.string()), ("carry_share", pa.float64())]))
    qb = project_player_volume(u, None, "P", 26.0, metric="carry_share",
                               fallback_per_game=2.5, position="QB")
    rb = project_player_volume(u, None, "P", 26.0, metric="carry_share",
                               fallback_per_game=2.5, position="RB")
    assert qb.projected < rb.projected
    assert qb.projected < 2 * 2.5


def test_an_unmeasured_position_is_left_unshrunk_rather_than_guessed():
    """A receiving fullback has no fitted pool. Not shrinking costs accuracy; shrinking
    toward someone else's pool costs correctness."""
    u = pa.Table.from_pylist(
        [{"player_id": "P", "target_share": 0.1}] * 8, schema=USAGE_SCHEMA)
    pv = project_player_volume(u, None, "P", 30.0, fallback_per_game=3.0,
                               position="FB")
    assert pv.projected == pytest.approx(3.0)
