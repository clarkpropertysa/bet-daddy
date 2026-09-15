"""The model earns weight against the market only by being right on settled contracts."""
import random

from pipeline.model.anchor import GRID, MIN_SETTLED, blend, fit_anchor


def _world(n, model_skill, market_noise=0.06, seed=7):
    """Outcomes drawn from a true probability. The market sees it with noise; the model
    sees it with noise scaled by `model_skill` (0 = pure noise, 1 = the truth)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        truth = rng.uniform(0.05, 0.95)
        market = min(max(truth + rng.gauss(0, market_noise), 0.01), 0.99)
        model = min(max(model_skill * truth + (1 - model_skill) * rng.uniform(0, 1), 0.01), 0.99)
        out.append((model, market, 1 if rng.random() < truth else 0))
    return out


def test_a_model_that_knows_nothing_gets_no_weight():
    """Against a market that already prices the truth, noise can only hurt.

    (Against a NOISY market, pure noise centred on 50% earns a sliver of weight -- it
    acts as shrinkage toward even. That is real, and it is why the fit is measured on
    settled outcomes rather than assumed.)"""
    fit = fit_anchor(_world(4000, model_skill=0.0, market_noise=0.0))
    assert fit.weight == 0.0
    assert fit.brier_blend == fit.brier_market


def test_a_model_that_knows_the_truth_is_trusted():
    fit = fit_anchor(_world(4000, model_skill=1.0))
    assert fit.weight >= 0.5
    assert fit.brier_blend < fit.brier_market


def test_no_evidence_means_the_market():
    fit = fit_anchor(_world(MIN_SETTLED - 1, model_skill=1.0))
    assert fit.weight == 0.0
    assert fit.brier_market is None


def test_equal_accuracy_is_not_evidence_for_the_model():
    """A model identical to the market scores the same at every weight; the tie goes
    to the market."""
    rows = [(p, p, o) for p, _, o in _world(2000, model_skill=0.0)]
    assert fit_anchor(rows).weight == 0.0


def test_blend_is_linear_between_the_two():
    assert blend(0.8, 0.4, 0.0) == 0.4
    assert blend(0.8, 0.4, 1.0) == 0.8
    assert abs(blend(0.8, 0.4, 0.25) - 0.5) < 1e-12
    assert GRID[0] == 0.0 and GRID[-1] == 1.0


def test_a_lucky_sliver_is_not_evidence():
    """The failure this guards against: against a market pricing the exact truth, pure
    noise lowered Brier by 0.0001 at weight 0.05 over 4,000 bets. Chance, not skill."""
    from pipeline.model.anchor import _brier
    rows = _world(4000, model_skill=0.0, market_noise=0.0)
    assert _brier(rows, 0.05) < _brier(rows, 0.0), "the lucky sliver is really there"
    assert fit_anchor(rows).weight == 0.0, "and it earns nothing"
