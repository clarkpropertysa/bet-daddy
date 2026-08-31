"""Event-ticker parsing.

This module absorbed four duplicated regexes and two team-code tables from project.py.
Every anchoring bug found in this project lived in one of those copies while the others
stayed wrong, so the cases below are the actual historical failures, pinned.
"""
from pipeline.common import tickers


def test_unequal_length_codes_split_correctly():
    """ARILV at the midpoint gives AR/ILV. Anchored it gives ARI/LV."""
    assert tickers.split_matchup("ARILV") == ("ARI", "LV")


def test_longest_code_wins():
    """LAR must be tried before LA, or SFLAR splits as SF/LA plus a stray R."""
    assert tickers.split_matchup("SFLAR") == ("SF", "LAR")
    assert tickers.split_matchup("LACLA") == ("LAC", "LA")


def test_unknown_matchup_returns_none_rather_than_guessing():
    """A wrong split is worse than no split: it produces a plausible team that never
    matches anything, and nothing errors."""
    assert tickers.split_matchup("XXYY") is None
    assert tickers.split_matchup("") is None


def test_event_date_parses():
    assert tickers.event_date("KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350") == "2026-09-10"
    assert tickers.event_date("KXNFLGAME-26SEP21NYGLAR-NYG") == "2026-09-21"


def test_malformed_tickers_never_raise():
    for bad in ["GARBAGE", "", "A-B", "KXNFL-NOTADATE-X"]:
        assert tickers.event_date(bad) is None
        assert tickers.game_label(bad) is None
        assert tickers.parse_event(bad) is None


def test_opponent_is_anchored_not_subtracted():
    """The Rams bug. "SFLAR".replace("LA","") gives "SFR", a team that does not exist,
    which silently disabled the opponent adjustment for the whole franchise."""
    t = "KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350"
    assert tickers.opponent_of(t, "LA") == "SF"
    assert tickers.opponent_of(t, "SF") == "LA"


def test_opponent_returns_nflverse_codes():
    """Grades are keyed on pbp `defteam`. Returning Kalshi's LAR would miss every Rams
    defensive grade -- the failure this was written to fix."""
    e = tickers.parse_event("KXNFLGAME-26SEP21NYGLAR-NYG")
    assert e.home == "LA"          # normalised
    assert e.raw_home == "LAR"     # Kalshi spelling preserved for round-tripping


def test_opponent_of_a_team_not_in_the_game_is_none():
    assert tickers.opponent_of("KXNFLGAME-26SEP21NYGLAR-NYG", "DAL") is None
    assert tickers.opponent_of("KXNFLGAME-26SEP21NYGLAR-NYG", "") is None


def test_game_label_reads_as_a_matchup():
    assert tickers.game_label("KXNFLPASSYDS-26AUG15CARBUF-X-1") == "CAR at BUF, Aug 15"


def test_preseason_months_are_recognised():
    assert tickers.is_preseason("KXNFLPASSYDS-26AUG27PITBUF-BUFSBUECHELE6-250")
    assert not tickers.is_preseason("KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350")
    assert not tickers.is_preseason("KXNFLRECYDS-26NOV23DALNYG-DALCLAMB88-70")
    assert not tickers.is_preseason("GARBAGE")


def test_game_and_prop_tickers_parse_identically():
    """The reason the consensus job needs no parser of its own."""
    game = tickers.parse_event("KXNFLGAME-26SEP21NYGLAR-NYG")
    prop = tickers.parse_event("KXNFLRECYDS-26SEP21NYGLAR-NYGMNABERS1-70")
    assert (game.date, game.away, game.home) == (prop.date, prop.away, prop.home)


def test_kalshi_jac_becomes_nflverse_jax():
    """The direction matters and was reversed. Comparing all 32 codes from live Kalshi
    game markets against schedules.parquet: KALSHI writes JAC and LAR, NFLVERSE writes
    JAX and LA.

    Written the wrong way round, Kalshi's JAC passed through untouched and never matched
    nflverse's JAX, so every Jacksonville player resolved UNRESOLVED -- and unresolved
    players are skipped silently. A whole franchise absent from the board, nothing
    raised. Same failure mode as the Rams `.replace()` bug.
    """
    e = tickers.parse_event("KXNFLGAME-26SEP13CLEJAC-JAC")
    assert e.home == "JAX", "Kalshi's JAC must normalise to nflverse's JAX"
    assert e.raw_home == "JAC", "the Kalshi spelling must survive for round-tripping"
    assert tickers.opponent_of("KXNFLRECYDS-26SEP13CLEJAC-X-70", "JAX") == "CLE"
    assert tickers.opponent_of("KXNFLRECYDS-26SEP13CLEJAC-X-70", "CLE") == "JAX"


def test_rams_normalise_the_same_way():
    e = tickers.parse_event("KXNFLGAME-26SEP21NYGLAR-NYG")
    assert e.home == "LA"
    assert e.raw_home == "LAR"


def test_normalisation_targets_are_codes_nflverse_actually_uses():
    """Guards the direction generically. Every value must be a real nflverse code and
    every key must not be -- an alias pointing at a code that exists nowhere resolves
    to nothing, silently, which is exactly how this bug survived.
    """
    NFLVERSE_2026 = {
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
        "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO",
        "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    }
    for kalshi, nflverse in tickers.TO_NFLVERSE.items():
        assert nflverse in NFLVERSE_2026, f"{nflverse} is not an nflverse code"
        assert kalshi not in NFLVERSE_2026, f"{kalshi} needs no alias"
