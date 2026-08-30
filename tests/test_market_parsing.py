"""Parsing a market ticker into a game, and why the naive split is wrong.

A strike without its game is unreadable: "over 50 passing yards" is absurd in week 3
and routine in a preseason game where a starter plays one series. Josh Allen's only
archived market is a 50-yard line in an August game -- correct, and it looked broken
purely because the board never said which game it was.
"""
import pytest

from pipeline.model.project import _game_label, _is_preseason, _split_matchup


def test_splits_equal_length_codes():
    assert _split_matchup("CARBUF") == ("CAR", "BUF")
    assert _split_matchup("DALNYG") == ("DAL", "NYG")


def test_splits_unequal_length_codes():
    """The case a midpoint split gets wrong: ARILV becomes AR/ILV.

    Same failure mode as splitting SFBPURDY13 into SFB+PURDY -- team codes are 2-3
    characters and the boundary must be anchored on the real code set."""
    assert _split_matchup("ARILV") == ("ARI", "LV")
    assert _split_matchup("SFLAR") == ("SF", "LAR")
    assert _split_matchup("NESEA") == ("NE", "SEA")
    assert _split_matchup("LVHOU") == ("LV", "HOU")


def test_rejects_a_matchup_it_cannot_resolve():
    assert _split_matchup("ZZZQQQ") is None


def test_game_label_reads_as_a_matchup():
    assert _game_label("KXNFLPASSYDS-26AUG15CARBUF-BUFJALLEN17-50") == "CAR at BUF, Aug 15"
    assert _game_label("KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350") == "SF at LAR, Sep 10"


def test_game_label_tolerates_a_malformed_ticker():
    assert _game_label("GARBAGE") is None
    assert _game_label("KXNFL-NOTADATE-A-1") is None


@pytest.mark.parametrize("ticker,expected", [
    ("KXNFLPASSYDS-26AUG15CARBUF-BUFJALLEN17-50", True),
    ("KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350", False),
    ("KXNFLRECYDS-26NOV23DALNYG-DALCLAMB88-70", False),
])
def test_preseason_detection(ticker, expected):
    assert _is_preseason(ticker) is expected


# ---------------------------------------------------------------- opponent
from pipeline.model.project import _opponent_of  # noqa: E402


def test_opponent_when_one_code_contains_another():
    """The live bug this class of mistake caused.

    The crosswalk normalises LAR -> LA, so every Rams player arrived with
    team_code "LA". The previous implementation did matchup.replace(team_code, ""),
    turning "SFLAR" into "SFR" -- a team that does not exist. defense_detail then
    found nothing, so the opponent adjustment silently did nothing for an entire
    franchise.
    """
    assert _opponent_of("X-26SEP10SFLAR-A-1", "LA") == "SF"
    assert _opponent_of("X-26SEP10SFLAR-A-1", "SF") == "LA"
    assert _opponent_of("X-26SEP13ARILAC-A-1", "LAC") == "ARI"
    assert _opponent_of("X-26SEP13ARILAC-A-1", "ARI") == "LAC"


def test_opponent_returns_nflverse_codes_not_market_codes():
    """The opponent feeds defense_detail, whose grades key on pbp defteam. Returning
    Kalshi's LAR would miss every Rams defensive grade."""
    assert _opponent_of("X-26SEP10SFLAR-A-1", "SF") == "LA"


def test_opponent_handles_unequal_code_lengths():
    assert _opponent_of("X-26AUG13ARILV-A-1", "ARI") == "LV"
    assert _opponent_of("X-26AUG13ARILV-A-1", "LV") == "ARI"
    assert _opponent_of("X-26SEP09NESEA-A-1", "NE") == "SEA"


def test_opponent_is_none_when_the_team_is_not_in_the_game():
    """Returning garbage was the original failure: a nonexistent opponent silently
    disables the matchup adjustment instead of reporting that it could not resolve."""
    assert _opponent_of("X-26SEP10SFLAR-A-1", "KC") is None
    assert _opponent_of("GARBAGE", "SF") is None
