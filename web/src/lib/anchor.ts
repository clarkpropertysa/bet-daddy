/**
 * The market-anchored edge: what a pick is worth once the model's probability is blended
 * with the market's, at the weight the model has EARNED on settled contracts.
 *
 *     p = w * p_model + (1 - w) * p_market_mid
 *
 * `w` is fitted by the projection run (pipeline/model/anchor.py) and carried on every
 * signal's reason, so the page never invents it. Week 1 measured it at zero: over 2,718
 * settled markets the price was the better forecaster, and on the picks the board
 * offered the model said 53%, the market 37%, and 37% landed.
 *
 * Dependency-free so scripts/check-anchor.mjs runs it under plain node.
 */

/** The fitted weight, or 0 -- the market -- when a signal carries none. */
export function anchorWeight(reason: unknown): number {
  const w = (reason as { anchor?: { weight?: unknown } } | null)?.anchor?.weight;
  return typeof w === "number" && Number.isFinite(w) ? Math.min(Math.max(w, 0), 1) : 0;
}

export type AnchorFitInfo = {
  weight: number;
  n: number;
  brierMarket: number | null;
  brierModel: number | null;
};

/** The fit behind the weight, for the page that has to explain an empty list. */
export function anchorFit(reason: unknown): AnchorFitInfo | null {
  const a = (reason as { anchor?: Record<string, unknown> } | null)?.anchor;
  if (!a || typeof a.n !== "number") return null;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    weight: anchorWeight(reason),
    n: a.n,
    brierMarket: num(a.brier_market),
    brierModel: num(a.brier_model),
  };
}

/**
 * The anchored probability and net edge FOR THE SIDE THE MODEL PICKED.
 *
 * Kept on the model's side rather than re-choosing a side: a pick is a claim about one
 * side, and the question is whether that claim survives being anchored to the price.
 *
 * Null without both quotes -- with no bid there is no market mid to anchor to, and
 * inventing one is inventing the number the edge is built from.
 */
export function anchoredEdge(a: {
  side: string;
  modelProb: number;   // the model's probability for `side`
  marketProb: number;  // the price paid for `side`
  feeCents: number;
  yesAsk: number | null;
  yesBid: number | null;
  weight: number;
}): { prob: number; edgeCents: number } | null {
  const { yesAsk, yesBid } = a;
  if (yesAsk === null || yesBid === null) return null;
  if (!(yesAsk > 0 && yesAsk < 1 && yesBid > 0 && yesBid < 1)) return null;
  const midYes = (yesAsk + yesBid) / 2;
  const marketSide = a.side === "no" ? 1 - midYes : midYes;
  const prob = a.weight * a.modelProb + (1 - a.weight) * marketSide;
  return { prob, edgeCents: (prob - a.marketProb) * 100 - a.feeCents };
}
