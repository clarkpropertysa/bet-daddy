"""Refusing to price a share that may be about to move.

The case: TreVeyon Henderson did not practise before Week 1 2026 (ankle), which the
measured table puts at 34.3% likely to sit. He and Rhamondre Stevenson split New
England's backfield almost evenly in 2025 -- 10.6 carries a game to 9.4 -- and the model
projected Stevenson at his committee rate and took UNDER 49.5 rushing yards at +25.8c as
its largest edge on him. If Henderson sits, that pick is on the wrong side.
"""
import pytest

from pipeline.features.room import (
    MATERIAL_SHARE,
    TEAMMATE_RISK,
    describe,
    unpriced_teammate,
)

ROOMS = {("NE", "RB"): ["stevenson", "henderson", "scrub"]}
SNAPS = {"stevenson": 0.59, "henderson": 0.46, "scrub": 0.05}
NAMES = {"henderson": "TreVeyon Henderson", "scrub": "A Practice Squad Back"}


def _p(mapping):
    return lambda gsis: mapping.get(gsis, 0.02)


def test_the_stevenson_case():
    hit = unpriced_teammate("stevenson", "NE", "RB", ROOMS,
                            _p({"henderson": 0.343}), SNAPS, NAMES)
    assert hit is not None
    assert hit[0] == "TreVeyon Henderson"
    assert hit[1] == pytest.approx(0.343)


def test_a_healthy_room_prices_normally():
    """The guard must not fire just because a room has more than one player in it."""
    assert unpriced_teammate("stevenson", "NE", "RB", ROOMS,
                             _p({}), SNAPS, NAMES) is None


def test_an_immaterial_teammate_is_ignored():
    """A fifth-string back missing practice changes nothing, however hurt he is."""
    assert unpriced_teammate("stevenson", "NE", "RB", ROOMS,
                             _p({"scrub": 0.99}), SNAPS, NAMES) is None


def test_the_risk_floor_is_respected():
    """'(none)/full participation' measures 0.119 and is ordinary; the guard must not
    fire on every player who appears on a report at all."""
    assert unpriced_teammate("stevenson", "NE", "RB", ROOMS,
                             _p({"henderson": 0.119}), SNAPS, NAMES) is None
    assert unpriced_teammate("stevenson", "NE", "RB", ROOMS,
                             _p({"henderson": TEAMMATE_RISK + 0.01}), SNAPS, NAMES)


def test_the_player_does_not_flag_himself():
    assert unpriced_teammate("stevenson", "NE", "RB", ROOMS,
                             _p({"stevenson": 0.99}), SNAPS, NAMES) is None


def test_missing_inputs_yield_no_opinion():
    """No depth chart, no snap history, an unmapped room, or an unknown player must
    produce silence. A check that fires on absent information empties the board."""
    assert unpriced_teammate("stevenson", None, "RB", ROOMS, _p({}), SNAPS) is None
    assert unpriced_teammate("stevenson", "NE", None, ROOMS, _p({}), SNAPS) is None
    assert unpriced_teammate("stevenson", "XX", "RB", ROOMS, _p({}), SNAPS) is None
    assert unpriced_teammate("nobody", "NE", "RB", ROOMS, _p({}), SNAPS) is None
    # own snap share unknown -> no floor can be computed -> no opinion
    assert unpriced_teammate("stevenson", "NE", "RB", ROOMS,
                             _p({"henderson": 0.9}), {"henderson": 0.46}) is None


def test_it_names_the_teammate_and_the_number():
    """A refusal a reader cannot check is not much better than a silent one."""
    msg = describe("RB", "TreVeyon Henderson", 0.343)
    assert "TreVeyon Henderson" in msg and "34%" in msg and "RB" in msg


def test_material_share_is_a_fraction_not_a_multiple():
    assert 0 < MATERIAL_SHARE < 1
    assert 0 < TEAMMATE_RISK < 1
