/**
 * The model's own claim about a player, without reference to any price.
 *
 * A projection is a distribution, and the number a reader wants from it is not the mean
 * alone: it is what the model is CONFIDENT about. So each projection is reduced to two
 * statements taken from its own probability curve --
 *
 *     floor    the highest line it gives at least CONFIDENT odds of clearing
 *     ceiling  the lowest line it gives at least CONFIDENT odds of staying under
 *
 * Both are read off the stored curve. Nothing is interpolated: a strike the pipeline did
 * not price is a strike this does not claim, because inventing one would be inventing the
 * number the whole statement rests on.
 *
 * WHAT THESE ARE NOT. They are not bets. Kalshi prices the same outcomes, and over Week 1
 * the price was the better forecaster -- when the model said 53% on the picks it published,
 * 37% happened. A floor at 78% is the model's opinion of an outcome the market has already
 * priced, usually at about the same number or better. Read them as expectations.
 */

export type LadderPoint = { strike: number; pOver: number };

export type Expectation = {
  floor: { strike: number; p: number } | null;
  ceiling: { strike: number; p: number } | null;
  /** Strikes the pipeline priced for this projection -- how much curve is behind it. */
  rungs: number;
};

/** The bar for stating a claim at all. Below this the model is not saying much. */
export const CONFIDENT = 0.7;

export function expectationFrom(
  ladder: LadderPoint[],
  confident: number = CONFIDENT,
): Expectation {
  const clean = ladder.filter(
    (p) => Number.isFinite(p.strike) && Number.isFinite(p.pOver),
  );
  let floor: { strike: number; p: number } | null = null;
  let ceiling: { strike: number; p: number } | null = null;
  for (const { strike, pOver } of clean) {
    if (pOver >= confident && (floor === null || strike > floor.strike)) {
      floor = { strike, p: pOver };
    }
    if (1 - pOver >= confident && (ceiling === null || strike < ceiling.strike)) {
      ceiling = { strike, p: 1 - pOver };
    }
  }
  return { floor, ceiling, rungs: clean.length };
}
