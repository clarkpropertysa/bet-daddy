/**
 * How much a stated probability has been worth, measured on settled contracts.
 *
 * The page already prints the model's own number. What a reader actually needs is whether
 * to believe it, and that is not a matter of opinion: every claim the model has ever made
 * has been graded, so the same kind of claim can be looked up.
 *
 * Measured over Week 1, the model's confidence is worth very different amounts depending
 * on what it is claiming:
 *
 *     receptions  under  60%+   said 66%   happened 44%   (n=45)
 *     rush_yds    under  60%+   said 65%   happened 35%   (n=23)
 *     rec_yds     under  90%+   said 95%   happened 87%   (n=201)
 *     rec_yds     over   80%+   said 84%   happened 88%   (n=25)
 *
 * So a cell is (market family, side, 10-point band of the stated probability), and a claim
 * is scored against the cell it belongs to. Falls back to the side-and-band cell, then to
 * the band alone, then says UNTESTED -- never silently to a number from a different kind
 * of claim.
 *
 * The adjusted figure is shrunk toward what the model said, by the weight of evidence
 * behind the cell, so a 20-contract cell cannot drag a number far on its own. That is the
 * same discipline as the anchor weight: the correction has to be earned by sample.
 */

export type Cell = { n: number; stated: number; actual: number };
/** family|side|band -> cell, plus "*|side|band" and "*|*|band" fallbacks. */
export type ReliabilityTable = Map<string, Cell>;

/** Contracts at which the measured rate carries as much weight as the model's claim. */
export const EVIDENCE_HALF_WEIGHT = 40;

export type Grade = "solid" | "shaky" | "poor" | "untested";

export type Confidence = {
  /** What the model said. */
  stated: number;
  /** What claims like it have actually done, shrunk toward the claim by sample size. */
  adjusted: number;
  grade: Grade;
  /** The evidence behind it: null when nothing comparable has settled. */
  basis: Cell | null;
};

export function bandOf(p: number): number {
  // 10-point bands from 50%. Below 50% a "claim" is the other side's claim.
  // The epsilon is not decoration: 0.6 - 0.5 is 0.09999999999999998 in binary floating
  // point, so a claim sitting exactly on a boundary fell into the band below it.
  return Math.min(4, Math.max(0, Math.floor((p - 0.5) * 10 + 1e-9)));
}

export function cellKey(family: string, side: string, p: number): string {
  return `${family}|${side}|${bandOf(p)}`;
}

/**
 * Below this a cell is not its own evidence -- it FALLS THROUGH rather than being used.
 *
 * The exact cell used to win on specificity alone, so passing yards (13 settled contracts
 * in a band) reported "untested" while a 161-contract cell for the same side and band sat
 * unused one step down the chain. Specific beats general only when the specific cell has
 * enough behind it to say anything.
 */
export const MIN_CELL = 25;

export function lookup(
  table: ReliabilityTable, family: string, side: string, p: number,
): Cell | null {
  const b = bandOf(p);
  for (const key of [`${family}|${side}|${b}`, `*|${side}|${b}`, `*|*|${b}`]) {
    const cell = table.get(key);
    if (cell && cell.n >= MIN_CELL) return cell;
  }
  return null;
}

export function confidenceOf(
  table: ReliabilityTable, family: string, side: string, stated: number,
): Confidence {
  const basis = lookup(table, family, side, stated);
  if (!basis || basis.n <= 0) {
    return { stated, adjusted: stated, grade: "untested", basis: null };
  }
  // The cell's own miss, applied to this claim and damped by how much evidence it has.
  const weight = basis.n / (basis.n + EVIDENCE_HALF_WEIGHT);
  const miss = basis.actual - basis.stated;
  const adjusted = Math.min(0.99, Math.max(0.01, stated + weight * miss));
  const drop = stated - adjusted;
  const grade: Grade =
    basis.n < MIN_CELL ? "untested" : drop <= 0.04 ? "solid" : drop <= 0.10 ? "shaky" : "poor";
  return { stated, adjusted, grade, basis };
}

export const GRADE_WORDS: Record<Grade, string> = {
  solid: "has held up",
  shaky: "runs hot",
  poor: "runs well over",
  untested: "untested",
};
