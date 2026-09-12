"""A game a player barely appeared in must not count as a game in a per-game rate.

Burrow 2025: a full week 1, THIRTY PERCENT of the snaps in week 2 before leaving injured,
ten weeks out, then six healthy starts. Flat-averaged that is 34.5 attempts a game; his
healthy starts averaged 39.2. The board sold the difference as a 21c edge on an under.
"""
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.features.rates import shrink
from pipeline.features.snaps import (
    MIN_GAMES_FOR_MEDIAN,
    applies_to,
    truncated_games,
)
from pipeline.model.features_for_projection import load_player_inputs

QB = "00-0036442"
PFR = "BurrJo01"


def _files(tmp_path, shares, attempts):
    """One game per week: `shares` is his snap share, `attempts` his pass attempts."""
    pq.write_table(pa.table({
        "pfr_id": [PFR], "gsis_id": [QB],
    }), tmp_path / "players.parquet")

    pq.write_table(pa.table({
        "game_id": [f"g{i}" for i in range(len(shares))],
        "season": [2025] * len(shares),
        "game_type": ["REG"] * len(shares),
        "week": list(range(1, len(shares) + 1)),
        "pfr_player_id": [PFR] * len(shares),
        "offense_snaps": [60.0 * s for s in shares],
        "offense_pct": list(shares),
    }), tmp_path / "snaps.parquet")

    rows = {"game_id": [], "season_type": [], "week": [], "play_type": [],
            "passer_player_id": [], "receiver_player_id": [], "rusher_player_id": [],
            "complete_pass": [], "pass_touchdown": [], "yards_gained": [],
            "two_point_attempt": []}
    for i, n in enumerate(attempts):
        for _ in range(n):
            rows["game_id"].append(f"g{i}")
            rows["season_type"].append("REG")
            rows["week"].append(i + 1)
            rows["play_type"].append("pass")
            rows["passer_player_id"].append(QB)
            rows["receiver_player_id"].append(None)
            rows["rusher_player_id"].append(None)
            rows["complete_pass"].append(1)
            rows["pass_touchdown"].append(0)
            rows["yards_gained"].append(10.0)
            rows["two_point_attempt"].append(0)
    pq.write_table(pa.table(rows), tmp_path / "pbp.parquet")
    return (str(tmp_path / "pbp.parquet"), str(tmp_path / "snaps.parquet"),
            str(tmp_path / "players.parquet"))


BURROW_SHARES = [1.0, 0.30, 1.0, 1.0, 1.0, 0.90, 0.83, 0.99]
BURROW_ATTEMPTS = [26, 15, 47, 37, 42, 34, 34, 41]


def test_the_game_he_left_injured_is_identified(tmp_path):
    _, snaps, players = _files(tmp_path, BURROW_SHARES, BURROW_ATTEMPTS)
    assert truncated_games(snaps, players, QB) == {"g1"}


def test_a_rotational_player_is_not_truncated(tmp_path):
    """38% of snaps every week is a WR3 doing his job, not a player leaving early."""
    shares = [0.38, 0.41, 0.36, 0.39, 0.42, 0.37]
    _, snaps, players = _files(tmp_path, shares, [4] * 6)
    assert truncated_games(snaps, players, QB) == set()


def test_too_few_games_to_judge_excludes_nothing(tmp_path):
    shares = [1.0, 0.2, 0.9][:MIN_GAMES_FOR_MEDIAN - 1]
    _, snaps, players = _files(tmp_path, shares, [20] * len(shares))
    assert truncated_games(snaps, players, QB) == set()


def test_the_median_and_the_games_it_judges_stop_at_through_week(tmp_path):
    _, snaps, players = _files(tmp_path, BURROW_SHARES, BURROW_ATTEMPTS)
    # weeks 1-2 only: two games is under the floor, so nothing is excluded
    assert truncated_games(snaps, players, QB, through_week=3) == set()
    # the whole season is visible by week 9
    assert truncated_games(snaps, players, QB, through_week=9) == {"g1"}


def test_the_per_game_rate_drops_the_truncated_game(tmp_path):
    pbp, snaps, players = _files(tmp_path, BURROW_SHARES, BURROW_ATTEMPTS)
    flat = load_player_inputs(pbp, QB, min_games=4)
    filtered = load_player_inputs(pbp, QB, min_games=4,
                                  exclude_games=truncated_games(snaps, players, QB))
    # The returned rate is regressed toward the league (features/rates.py), so the
    # expectation is shrunk the same way rather than compared to the raw mean.
    healthy = [a for a, s in zip(BURROW_ATTEMPTS, BURROW_SHARES) if s != 0.30]
    assert flat.attempts_per_game == pytest.approx(
        shrink(np.mean(BURROW_ATTEMPTS), "attempts_per_game", sum(BURROW_ATTEMPTS)),
        rel=1e-3)
    assert filtered.attempts_per_game == pytest.approx(
        shrink(np.mean(healthy), "attempts_per_game", sum(healthy)), rel=1e-3)
    assert filtered.attempts_per_game > flat.attempts_per_game


def test_efficiency_still_draws_on_every_play(tmp_path):
    """A short appearance does not bias a per-PLAY rate, so the bootstrap keeps them."""
    pbp, snaps, players = _files(tmp_path, BURROW_SHARES, BURROW_ATTEMPTS)
    flat = load_player_inputs(pbp, QB, min_games=4)
    filtered = load_player_inputs(pbp, QB, min_games=4,
                                  exclude_games=truncated_games(snaps, players, QB))
    assert len(filtered.yards_per_completion) == len(flat.yards_per_completion)


def test_the_filter_is_quarterbacks_only():
    """Applied to everyone the 2025 replay got WORSE: Brier 0.1470 against 0.1466, with
    receptions 0.1486 -> 0.1495 and rec_yds 0.1424 -> 0.1429. A quarterback is
    all-or-nothing, so a 30%-snap game is an exit; a receiver's low games are mostly
    real low-usage games, and dropping them keeps only the ones that went well."""
    assert applies_to("QB")
    for p in ("WR", "TE", "RB", "FB", None, ""):
        assert not applies_to(p), f"{p} snap shares vary by role, not only by injury"


def test_a_thin_history_keeps_every_game(tmp_path):
    """Dropping games must never take a player below the floor that prices him."""
    shares = [1.0, 0.1, 0.1, 0.1, 1.0]
    attempts = [30, 5, 6, 7, 32]
    pbp, snaps, players = _files(tmp_path, shares, attempts)
    got = load_player_inputs(pbp, QB, min_games=4,
                             exclude_games=truncated_games(snaps, players, QB))
    assert got.games == 5
    assert got.attempts_per_game == pytest.approx(np.mean(attempts), rel=1e-3)
