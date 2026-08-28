"""Player identity resolution. Section 12 calls this the biggest hidden time sink."""
import polars as pl

from pipeline.features.crosswalk import build_crosswalk, parse_player_key

TEAMS = {"SF", "LA", "LAR", "SEA", "NE", "KC"}


def test_parses_ambiguous_team_boundary():
    # SFBPURDY13 must not become team=SFB. Greedy regex gets this wrong and drops
    # the match rate from 92% to 55%.
    p = parse_player_key("SFBPURDY13", TEAMS)
    assert (p.team, p.first_initial, p.surname, p.jersey) == ("SF", "B", "PURDY", 13)


def test_applies_team_alias():
    # Kalshi uses LAR; nflverse uses LA.
    p = parse_player_key("LARPNACUA12", TEAMS)
    assert p.team == "LA" and p.surname == "NACUA"


def test_rejects_unparseable_key():
    assert parse_player_key("NOTATEAM", TEAMS) is None


def _roster(rows):
    return pl.DataFrame(rows, schema={
        "team": pl.Utf8, "jersey_number": pl.Int32, "full_name": pl.Utf8,
        "first_name": pl.Utf8, "last_name": pl.Utf8, "gsis_id": pl.Utf8,
        "football_name": pl.Utf8,
    })


def test_matches_on_football_name_not_legal_first_name():
    """Matthew Stafford's legal first_name is 'John'. Kalshi keys on 'M'.

    Without football_name fallback this class of player silently fails to match.
    """
    roster = _roster([{
        "team": "LA", "jersey_number": 9, "full_name": "Matthew Stafford",
        "first_name": "John", "last_name": "Stafford",
        "gsis_id": "00-0026498", "football_name": "Matthew",
    }])
    x = build_crosswalk(["KXNFLPASSYDS-26SEP10SFLAR-LARMSTAFFORD9-300"], roster)
    row = x.row(0, named=True)
    assert row["gsis_id"] == "00-0026498"
    assert row["method"] == "EXACT"


def test_unresolved_is_surfaced_not_dropped():
    """An unmatched player must appear with UNRESOLVED, never vanish silently."""
    roster = _roster([{
        "team": "SF", "jersey_number": 23, "full_name": "Christian McCaffrey",
        "first_name": "Christian", "last_name": "McCaffrey",
        "gsis_id": "00-0033280", "football_name": "Christian",
    }])
    x = build_crosswalk(["KXNFLRECYDS-26SEP10SFLAR-SFDSAMUEL19-50"], roster)
    assert x.height == 1
    assert x.row(0, named=True)["method"] == "UNRESOLVED"
    assert x.row(0, named=True)["gsis_id"] is None


def test_surname_normalisation_handles_punctuation():
    roster = _roster([{
        "team": "NE", "jersey_number": 1, "full_name": "A.J. Brown",
        "first_name": "A.J.", "last_name": "Brown",
        "gsis_id": "00-0035676", "football_name": "A.J.",
    }])
    x = build_crosswalk(["KXNFLRECYDS-26SEP09NESEA-NEABROWN1-90"], roster)
    assert x.row(0, named=True)["gsis_id"] == "00-0035676"
