"""Guards on the projection job."""
from pipeline.model.project import (
    IMPLAUSIBLE_DIVERGENCE,
    MAX_TRADEABLE_ASK,
    MIN_TRADEABLE_ASK,
    _is_preseason,
)


def test_preseason_tickers_are_recognised():
    assert _is_preseason("KXNFLPASSYDS-26AUG27PITBUF-BUFSBUECHELE6-250")
    assert not _is_preseason("KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350")
    assert not _is_preseason("KXNFLRECYDS-26NOV23DALNYG-DALCLAMB88-70")


def test_malformed_ticker_is_not_treated_as_preseason():
    assert not _is_preseason("GARBAGE")


def test_untradeable_price_bounds_exclude_the_extremes():
    """A 0c ask is not a fillable price -- it is an empty or one-sided book reported
    as a number. 48% of preseason entry prices sat at these extremes."""
    assert MIN_TRADEABLE_ASK > 0
    assert MAX_TRADEABLE_ASK < 1


def test_divergence_threshold_is_set():
    """When model and market disagree by more than this, the model is missing
    something the market knows -- not finding free money."""
    assert 0 < IMPLAUSIBLE_DIVERGENCE < 1
