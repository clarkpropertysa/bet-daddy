"""How much of the model's probability belongs in a forecast, measured against the market.

Week 1 was the first time the model met Kalshi prices head to head -- the 2025 backtest
beat the box score by 21% but had no prices to beat, because Kalshi keeps no settled prop
markets across seasons. Over 2,718 settled markets the MARKET was the better forecaster
(Brier 0.1506 against the model's 0.1583), in every family but passing touchdowns. On the
bets the board actually offered, the model's picks were priced at 37%, it said 53%, and
37% of them landed. Blending the two, every amount of model made the forecast worse.

The reason is selection. The model is roughly calibrated across every strike, but a pick
exists only where it DISAGREES with the price, and disagreement is where its errors
concentrate: the larger the claimed edge, the wider the gap between what it said and
what happened.

So a pick is no longer ranked on the model's probability. It is ranked on

    p = w * p_model + (1 - w) * p_market

with the market taken at the MID of the book, and w FITTED -- the single weight that
minimises Brier over every settled market so far. Nothing is chosen by hand:

  * it is refitted every projection run, from games already played, and applied to games
    not yet played, so each week is an out-of-sample test by construction;
  * a blend must beat the market by MIN_Z standard errors on the same bets, so a lucky
    week earns the model nothing;
  * below MIN_SETTLED graded markets the weight is zero -- the market until proven
    otherwise.

With w = 0 the anchored edge is mid - ask - fee, which is negative on any book with a
spread. The page is empty, and it says why, until settled contracts show the model
knows something the price does not.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

#: Graded markets needed before the model may be given any weight at all.
MIN_SETTLED = 500

#: One parameter, searched coarsely. A finer grid would fit the noise in a week.
GRID = [i / 20 for i in range(21)]

#: The fit's inputs: the model's probability for the side it picked, the market's mid
#: for that same side, and whether that side won.
TRIPLES_SQL = """
    select s."modelProb"::float8,
           (case when s.side = 'yes' then (s."yesAsk" + s."yesBid") / 2
                 else 1 - (s."yesAsk" + s."yesBid") / 2 end)::float8,
           (r."settledResult" = s.side)::int
    from "SignalResult" r
    join "Signal" s on s.id = r."signalId"
    where r."settledResult" in ('yes', 'no')
      and s."yesAsk" is not null and s."yesBid" is not null
      and s."yesAsk" < 1 and s."yesBid" > 0
"""


@dataclass(frozen=True)
class AnchorFit:
    weight: float
    n: int
    brier_market: float | None
    brier_model: float | None
    brier_blend: float | None

    def as_dict(self) -> dict:
        return {k: (round(v, 5) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


#: What a run carries when the fit cannot be computed: the market, and no claim.
NO_EVIDENCE = AnchorFit(0.0, 0, None, None, None)


def blend(p_model: float, p_market: float, weight: float) -> float:
    return weight * p_model + (1.0 - weight) * p_market


def _brier(triples: list[tuple[float, float, int]], weight: float) -> float:
    return sum((blend(m, k, weight) - o) ** 2 for m, k, o in triples) / len(triples)


#: How many standard errors a blend must beat the market by before the model gets weight.
#:
#: NOT the lowest Brier. Pure noise beat a market that priced the exact truth -- weight
#: 0.05, by 0.0001 of Brier, over 4,000 synthetic bets -- because a finite set of
#: outcomes never matches its true probabilities, and a sliver of anything can fit the
#: difference. A lucky week would then start printing picks built on noise.
#:
#: Three rather than two because the bets are not independent: every prop in a game is
#: priced from one simulated game, so 2,700 markets are far fewer independent views and
#: the naive standard error is too small. A stricter bar is the cheap correction.
MIN_Z = 3.0


def fit_anchor(
    triples: list[tuple[float, float, int]], min_settled: int = MIN_SETTLED,
) -> AnchorFit:
    n = len(triples)
    if n < min_settled:
        return AnchorFit(0.0, n, None, None, None)
    market_err = [(k - o) ** 2 for _, k, o in triples]
    scores = {w: _brier(triples, w) for w in GRID}

    best = 0.0
    for w in GRID[1:]:
        # Paired: the same bets scored both ways, so the comparison is sharp.
        d = [(blend(m, k, w) - o) ** 2 - e for (m, k, o), e in zip(triples, market_err)]
        mean = sum(d) / n
        var = sum((x - mean) ** 2 for x in d) / (n - 1)
        se = (var / n) ** 0.5
        if mean < 0 and se > 0 and -mean / se >= MIN_Z and scores[w] < scores[best]:
            best = w
    return AnchorFit(best, n, scores[0.0], scores[1.0], scores[best])


def load_fit(conn) -> AnchorFit:
    with conn.cursor() as cur:
        cur.execute(TRIPLES_SQL)
        rows = cur.fetchall()
    return fit_anchor([(float(m), float(k), int(o)) for m, k, o in rows])


def main() -> None:
    import psycopg

    from pipeline.common import config

    with psycopg.connect(config.DATABASE_URL) as conn:
        fit = load_fit(conn)
    print(f"anchor weight={fit.weight} on n={fit.n} settled markets")
    if fit.brier_market is not None:
        print(f"  Brier  market {fit.brier_market:.4f}  model {fit.brier_model:.4f}  "
              f"blend {fit.brier_blend:.4f}")


if __name__ == "__main__":
    main()
