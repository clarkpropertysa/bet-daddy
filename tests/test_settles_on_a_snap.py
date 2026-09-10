"""A no-show is a push on Kalshi, so settlement is priced conditional on a snap.

Kalshi's rules on every player prop: "If <player> is active but never takes a snap, the
market settles to the fair market price before game start." The simulator's DNP mass
was scored as zero yards -- a win for every under -- which put two points of phantom
probability under every healthy player and forty under a Questionable one.
"""
import re
from pathlib import Path

from pipeline.features.availability import OWN_RISK_REFUSE
from pipeline.features.room import TEAMMATE_RISK
from pipeline.model.simulate import VolumeProjection, project_receptions

SRC = (Path(__file__).resolve().parents[1] / "pipeline/model/project.py").read_text()


def test_no_settlement_simulation_is_handed_the_dnp_mass():
    assert not re.search(r"p_inactive\s*=\s*p_inactive", SRC), (
        "project.py passes the DNP probability into a simulator; a no-show settles at "
        "the pre-game price, not at zero")


def test_a_player_likely_to_sit_is_refused_rather_than_priced():
    assert 'skip("own_availability_unresolved")' in SRC
    assert OWN_RISK_REFUSE == TEAMMATE_RISK


def test_the_mass_being_removed_is_what_flattered_unders():
    """Pinned so the size of the old error stays visible."""
    kw = dict(player_id="x", market="receptions", baseline=6.0, dispersion=1.5)
    played = project_receptions(VolumeProjection(**kw, p_inactive=0.0), 0.7, [2.5],
                                iterations=20_000, seed=1)
    questionable = project_receptions(VolumeProjection(**kw, p_inactive=0.42), 0.7,
                                      [2.5], iterations=20_000, seed=1)
    gap = played["p_over_by_strike"]["2.5"] - questionable["p_over_by_strike"]["2.5"]
    assert gap > 0.3
