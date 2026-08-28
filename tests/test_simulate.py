"""Monte Carlo projection model (Section 7)."""
import numpy as np
import pytest

from pipeline.model.simulate import (
    Adjustment,
    VolumeProjection,
    project_receiving_yards,
    project_rushing_yards,
    simulate_volume,
    summarize,
)


def _vp(**kw):
    base = dict(player_id="p", market="rec_yds", baseline=10.0)
    base.update(kw)
    return VolumeProjection(**base)


def test_adjustments_compound_multiplicatively():
    vp = _vp(adjustments=[Adjustment("a", 1.10), Adjustment("b", 0.90)])
    assert vp.adjusted == pytest.approx(10.0 * 1.10 * 0.90)


def test_explain_chain_is_ordered_and_ends_at_adjusted():
    vp = _vp(adjustments=[Adjustment("a", 1.10), Adjustment("b", 0.90)])
    chain = vp.explain()
    assert [c["step"] for c in chain] == ["baseline", "a", "b"]
    assert chain[-1]["value"] == pytest.approx(vp.adjusted)


def test_p_over_is_monotone_decreasing_in_strike():
    """A higher bar can never be easier to clear. If this breaks, every edge on the
    board is suspect."""
    s = np.random.default_rng(0).gamma(4, 20, 20_000)
    out = summarize(s, [20.0, 50.0, 80.0, 120.0, 200.0])
    ps = list(out["p_over_by_strike"].values())
    assert all(a >= b for a, b in zip(ps, ps[1:]))


def test_p_over_uses_strict_inequality():
    """Kalshi settles on MORE THAN the strike. Using >= would overprice every over
    on integer markets like receptions, where landing exactly on the strike is common."""
    s = np.array([5.0] * 100)
    assert summarize(s, [5.0])["p_over_by_strike"]["5.0"] == 0.0
    assert summarize(s, [4.0])["p_over_by_strike"]["4.0"] == 1.0


def test_inactive_probability_creates_a_point_mass_at_zero():
    """A DNP is the worst outcome for an over and must be a discrete mass, not
    smoothed into the volume distribution."""
    rng = np.random.default_rng(1)
    vol = simulate_volume(_vp(baseline=10.0, p_inactive=0.25), rng, 20_000)
    zero_rate = (vol == 0).mean()
    assert 0.22 < zero_rate < 0.30


def test_no_inactive_mass_when_probability_is_zero():
    rng = np.random.default_rng(1)
    vol = simulate_volume(_vp(baseline=12.0, p_inactive=0.0), rng, 20_000)
    assert (vol == 0).mean() < 0.01


def test_overdispersion_widens_the_distribution():
    """Football counts are overdispersed relative to Poisson; game script guarantees
    it. A Poisson-width volume distribution understates tail probabilities."""
    rng = np.random.default_rng(2)
    tight = simulate_volume(_vp(baseline=10.0, dispersion=1.0), rng, 40_000)
    wide = simulate_volume(_vp(baseline=10.0, dispersion=2.5), rng, 40_000)
    assert wide.std() > tight.std() * 1.2


def test_empirical_sampling_preserves_right_skew():
    """Yards per catch is strongly right-skewed. A normal fit would smooth away the
    breakaway tail, which is exactly where props settle."""
    ypc = np.array([2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 35, 60, 80], dtype=float)
    out = project_receiving_yards(
        _vp(baseline=8.0), 0.65, ypc, [50.0], seed=7)
    assert out["mean"] > out["percentiles"]["50"]


def test_seed_makes_runs_reproducible():
    """Backtests must be replayable; an unseeded model cannot be audited."""
    ypc = np.array([5.0, 10.0, 15.0, 40.0])
    a = project_rushing_yards(_vp(baseline=15.0), ypc, [50.0], seed=99)
    b = project_rushing_yards(_vp(baseline=15.0), ypc, [50.0], seed=99)
    assert a["mean"] == b["mean"]
    assert a["p_over_by_strike"] == b["p_over_by_strike"]


def test_different_seeds_give_different_draws():
    ypc = np.array([5.0, 10.0, 15.0, 40.0])
    a = project_rushing_yards(_vp(baseline=15.0), ypc, [50.0], seed=1)
    b = project_rushing_yards(_vp(baseline=15.0), ypc, [50.0], seed=2)
    assert a["mean"] != b["mean"]


def test_empty_efficiency_sample_yields_zero_not_crash():
    """A player with no recorded catches must not blow up the slate."""
    out = project_receiving_yards(
        _vp(baseline=5.0), 0.6, np.array([]), [10.0], seed=3)
    assert out["mean"] == 0.0
    assert out["p_over_by_strike"]["10.0"] == 0.0


def test_percentiles_are_non_decreasing():
    ypc = np.array([3.0, 8.0, 12.0, 25.0, 50.0])
    out = project_receiving_yards(_vp(baseline=9.0), 0.7, ypc, [60.0], seed=11)
    vals = [out["percentiles"][k] for k in ["1", "5", "10", "25", "50", "75", "90", "95", "99"]]
    assert all(a <= b for a, b in zip(vals, vals[1:]))
