/**
 * Edge maths, ported from pipeline/model/signal.py and pipeline/common/fees.py.
 *
 * This exists so the board can reprice against a LIVE quote without waiting for the
 * Python job. The split is deliberate and reflects how fast each half actually moves:
 * the simulated distribution changes when an injury or a depth chart changes, on a
 * daily cadence; the ask changes all day. Re-running a 20,000-path Monte Carlo to
 * learn that a price ticked a cent would be absurd, and waiting hours to notice is
 * worse.
 *
 * The Python side remains authoritative — it is what gets STORED and graded for CLV.
 * This recomputes the same quantities from the same stored distribution so the number
 * on screen matches the market as it is now.
 *
 * Python uses Decimal; this uses doubles. The difference is far below a cent on every
 * quantity here, and every value is rounded before display.
 */

/** Contracts settle at $1.00; prices and edges are expressed in cents of that. */
const CONTRACT_CENTS = 100;
const TAKER_RATE = 0.07;
const MAKER_RATE = 0.0175;

/**
 * Unrounded per-contract fee in cents.
 *
 * Deliberately NOT the per-order rounded figure. The ceil() in Kalshi's per-order fee
 * applies once per order, so on a 1-contract order it inflates the true economic rate
 * (2.00c vs 1.75c at P=0.50). Edge filters and EV maths must use this marginal rate.
 */
export function marginalFeeCents(priceDollars: number, maker = false): number {
  if (!(priceDollars >= 0 && priceDollars <= 1)) {
    throw new RangeError(`price must be in [0,1] dollars, got ${priceDollars}`);
  }
  const rate = maker ? MAKER_RATE : TAKER_RATE;
  return round4(rate * priceDollars * (1 - priceDollars) * 100);
}

/** Kelly fraction for a binary contract costing `price` and paying $1. */
export function kelly(modelProb: number, price: number): number {
  if (price <= 0 || price >= 1) return 0;
  const b = (1 - price) / price;
  const f = (modelProb * b - (1 - modelProb)) / b;
  return Math.max(f, 0);
}

export type LiveEdge = {
  side: "yes" | "no";
  modelProb: number;
  marketProb: number;
  grossEdgeCents: number;
  feeCents: number;
  edgeCentsNet: number;
  kelly: number;
};

/**
 * Edge on the better side of a market, net of the exact fee.
 *
 * Both sides are evaluated, because an over that is 3c rich means the under is 3c
 * cheap and either can be taken. This matters more here than in the Python job: the
 * stored signal picked a side against the price at the time, and a price that has
 * moved far enough can make the OTHER side the right one. Recomputing only the stored
 * side would keep recommending a bet the market has already taken away.
 *
 * Uses the ASK, never the midpoint or last trade — the ask is what would actually be
 * paid, and pricing off the midpoint manufactures edge equal to half the spread,
 * which on thin prop markets is most of the apparent edge.
 */
export function computeEdge(
  modelProbOver: number,
  yesAskDollars: number,
  noAskDollars: number | null = null,
  maker = false,
): LiveEdge {
  const pYes = modelProbOver;
  const yesPrice = yesAskDollars;

  // THE NO SIDE IS NEVER INFERRED -- see compute_edge in pipeline/model/signal.py.
  // `1 - yesAsk` is the no BID on any book that is not tight. Cam Ward's 4+ passing
  // touchdowns quoted yes 0.00/0.25 and no 0.75/1.0000: the no side cannot be bought,
  // and the complement of the yes ask is exactly the no bid. A null here means the no
  // side is UNAVAILABLE, not unknown, which is also what `tradeable()` means when it
  // rejects a $1.00 ask.
  const noPrice =
    noAskDollars !== null && noAskDollars > 0 && noAskDollars < 1
      ? noAskDollars
      : null;

  const yesGross = (pYes - yesPrice) * CONTRACT_CENTS;
  const yesFee = marginalFeeCents(yesPrice, maker);
  const yesNet = yesGross - yesFee;

  const pNo = 1 - pYes;
  const noGross = noPrice === null ? 0 : (pNo - noPrice) * CONTRACT_CENTS;
  const noFee = noPrice === null ? 0 : marginalFeeCents(noPrice, maker);
  const noNet = noPrice === null ? -Infinity : noGross - noFee;

  const yesWins = yesNet >= noNet;
  const side = yesWins ? "yes" : "no";
  const prob = yesWins ? pYes : pNo;
  const price = yesWins ? yesPrice : (noPrice as number);

  return {
    side,
    modelProb: prob,
    marketProb: price,
    grossEdgeCents: yesWins ? yesGross : noGross,
    feeCents: yesWins ? yesFee : noFee,
    edgeCentsNet: yesWins ? yesNet : noNet,
    kelly: kelly(prob, price),
  };
}

/**
 * P(over) at a strike, from the stored strike -> probability map.
 *
 * The projection stores the whole curve, so the exact strike is normally present.
 * Returns null rather than interpolating when it is not: an interpolated probability
 * would be an invented number, and inventing one here would put a fabricated edge on
 * the board.
 */
export function pOverAtStrike(
  pOverByStrike: unknown,
  strike: number | null,
): number | null {
  if (strike === null || pOverByStrike === null || typeof pOverByStrike !== "object") {
    return null;
  }
  const map = pOverByStrike as Record<string, unknown>;
  for (const key of [String(strike), strike.toFixed(1), strike.toFixed(0)]) {
    const v = map[key];
    if (typeof v === "number" && v >= 0 && v <= 1) return v;
  }
  return null;
}

function round4(n: number): number {
  return Math.round(n * 1e4) / 1e4;
}
