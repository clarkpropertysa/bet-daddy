/**
 * Parlay joint probability with correlation.
 *
 * THE POINT OF THIS MODULE: multiplying leg probabilities is wrong, and wrong in the
 * direction that flatters the bet. Parlay legs are correlated — a quarterback's
 * passing yards and his WR1's receiving yards rise and fall together — so the naive
 * product understates the joint probability for positively correlated legs and
 * overstates it for negatively correlated ones. Books price the correlation; a tool
 * that ignores it will systematically mis-rate every multi-leg ticket.
 *
 * Method: a Gaussian copula. Each leg's marginal probability p maps to a latent
 * normal threshold z = Φ⁻¹(p); the legs are given a correlation matrix; the joint
 * hit probability is P(all Z_i ≤ z_i) under a multivariate normal, evaluated by
 * Monte Carlo (the orthant probability has no closed form above two dimensions).
 *
 * THE CORRELATION VALUES ARE PRIORS, NOT FITTED. They cannot be fitted until the
 * archive holds enough settled multi-leg outcomes. They are deliberately moderate:
 * an overstated correlation makes same-game parlays look better than they are, which
 * is the expensive direction of error.
 *
 * Multi-leg tickets are a real tradeable product on prediction exchanges (minimum 2
 * legs, resolving YES only if every associated market resolves YES), so this rating
 * maps onto something you can actually buy rather than a hypothetical.
 */

export type Leg = {
  signalId: string;
  player: string;
  playerId: string;
  gameId: string;
  team: string | null;
  marketType: string;
  strike: number | null;
  side: string;
  modelProb: number;
  marketProb: number;
};

/** Correlation priors. Documented, moderate, and replaceable once data exists. */
export const RHO = {
  /** Two markets on the SAME player in the same game (receptions & rec yards). */
  samePlayer: 0.55,
  /** Different players, same team (QB yards & WR1 yards move together). */
  sameTeam: 0.3,
  /** Opposing teams in one game: game script pulls them apart slightly. */
  sameGameOpposing: -0.1,
  /** Different games. */
  independent: 0,
};

export function pairRho(a: Leg, b: Leg): number {
  if (a.playerId === b.playerId && a.gameId === b.gameId) return RHO.samePlayer;
  if (a.gameId !== b.gameId) return RHO.independent;
  if (a.team && b.team && a.team === b.team) return RHO.sameTeam;
  return RHO.sameGameOpposing;
}

/** Inverse standard normal CDF (Acklam's rational approximation, ~1e-9 accurate). */
export function probit(p: number): number {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
             1.383577518672690e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
             6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
             -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
             3.754408661907416];
  const pl = 0.02425;
  let q: number, r: number;
  if (p < pl) {
    q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
           ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);
  }
  if (p > 1 - pl) {
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);
  }
  q = p - 0.5;
  r = q * q;
  return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q /
         (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
}

/** Cholesky with a jitter fallback: prior-built matrices can be non-PSD. */
function cholesky(m: number[][]): number[][] {
  const n = m.length;
  for (let jitter = 0; jitter < 6; jitter++) {
    const L = Array.from({ length: n }, () => new Array(n).fill(0));
    let ok = true;
    const eps = jitter === 0 ? 0 : Math.pow(10, -8 + jitter);
    for (let i = 0; i < n && ok; i++) {
      for (let j = 0; j <= i; j++) {
        let s = m[i][j] + (i === j ? eps : 0);
        for (let k = 0; k < j; k++) s -= L[i][k] * L[j][k];
        if (i === j) {
          if (s <= 0) { ok = false; break; }
          L[i][i] = Math.sqrt(s);
        } else {
          L[i][j] = s / L[j][j];
        }
      }
    }
    if (ok) return L;
  }
  // fully degenerate: fall back to independence rather than returning nonsense
  return Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)));
}

/** Deterministic PRNG so a given ticket always rates the same. */
function mulberry32(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function normalPair(rnd: () => number): [number, number] {
  const u = Math.max(rnd(), 1e-12);
  const v = rnd();
  const r = Math.sqrt(-2 * Math.log(u));
  return [r * Math.cos(2 * Math.PI * v), r * Math.sin(2 * Math.PI * v)];
}

/**
 * Legs that cannot both win. Same player, same game, same market, with thresholds
 * that contradict — "over 100 yards" and "under 75 yards" is not a 12% parlay, it
 * is impossible. The copula happily returns a positive number for these because it
 * only sees two marginal probabilities, so they must be caught structurally.
 */
export function contradictoryPairs(legs: Leg[]): [Leg, Leg][] {
  const bad: [Leg, Leg][] = [];
  for (let i = 0; i < legs.length; i++) {
    for (let j = i + 1; j < legs.length; j++) {
      const a = legs[i], b = legs[j];
      if (a.playerId !== b.playerId) continue;
      if (a.gameId !== b.gameId) continue;
      if (a.marketType !== b.marketType) continue;
      if (a.strike === null || b.strike === null) {
        bad.push([a, b]);
        continue;
      }
      const aOver = a.side === "yes", bOver = b.side === "yes";
      if (aOver === bOver) {
        // same direction on the same market: the tighter one subsumes the other,
        // so the pair adds no information and double-counts the correlation
        bad.push([a, b]);
      } else {
        // opposite directions: impossible when the "over" bar sits at or above the
        // "under" bar
        const overStrike = aOver ? a.strike : b.strike;
        const underStrike = aOver ? b.strike : a.strike;
        if (overStrike >= underStrike) bad.push([a, b]);
      }
    }
  }
  return bad;
}

export type ParlayRating = {
  legs: number;
  /** Joint probability WITH correlation — the honest number. */
  joint: number;
  /** Naive product, shown for contrast. */
  independent: number;
  /** Fair decimal odds implied by the joint probability. */
  fairOdds: number;
  /** What the combined market price implies, for comparison. */
  marketJoint: number;
  /** Mean pairwise correlation across the ticket. */
  meanRho: number;
  confidence: "LOW" | "MODERATE" | "SPECULATIVE" | "REMOTE";
  /** Non-empty when the ticket contains legs that cannot both win. */
  contradictions: [Leg, Leg][];
};

export function rateParlay(legs: Leg[], iterations = 40000): ParlayRating {
  const n = legs.length;
  const independent = legs.reduce((a, l) => a * l.modelProb, 1);
  const marketJoint = legs.reduce((a, l) => a * l.marketProb, 1);

  const contradictions = contradictoryPairs(legs);

  if (n === 0) {
    return { legs: 0, joint: 0, independent: 0, fairOdds: 0, marketJoint: 0,
             meanRho: 0, confidence: "REMOTE", contradictions };
  }
  if (contradictions.length > 0) {
    // Refuse to rate rather than return a plausible-looking number for a ticket
    // that cannot win.
    return { legs: n, joint: 0, independent, marketJoint, fairOdds: Infinity,
             meanRho: 0, confidence: "REMOTE", contradictions };
  }
  if (n === 1) {
    return { legs: 1, joint: legs[0].modelProb, independent, marketJoint,
             fairOdds: 1 / legs[0].modelProb, meanRho: 0,
             confidence: band(legs[0].modelProb), contradictions };
  }

  const R = Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => (i === j ? 1 : pairRho(legs[i], legs[j]))));
  let rhoSum = 0, pairs = 0;
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) { rhoSum += R[i][j]; pairs++; }

  const L = cholesky(R);
  const z = legs.map((l) => probit(l.modelProb));
  const rnd = mulberry32(0x5EED);

  let hits = 0;
  const raw = new Array(n);
  const cor = new Array(n);
  for (let it = 0; it < iterations; it++) {
    for (let i = 0; i < n; i += 2) {
      const [x, y] = normalPair(rnd);
      raw[i] = x;
      if (i + 1 < n) raw[i + 1] = y;
    }
    let all = true;
    for (let i = 0; i < n; i++) {
      let s = 0;
      for (let k = 0; k <= i; k++) s += L[i][k] * raw[k];
      cor[i] = s;
      if (cor[i] > z[i]) { all = false; break; }
    }
    if (all) hits++;
  }

  const joint = hits / iterations;
  return {
    legs: n,
    joint,
    independent,
    marketJoint,
    fairOdds: joint > 0 ? 1 / joint : Infinity,
    meanRho: pairs ? rhoSum / pairs : 0,
    confidence: band(joint),
    contradictions,
  };
}

/**
 * Confidence bands. Deliberately blunt and pessimistic in their language: a 22%
 * ticket is not "moderate confidence" in any everyday sense, and a generous label
 * on a long-odds parlay is how a research tool starts flattering bad bets.
 */
function band(p: number): ParlayRating["confidence"] {
  if (p >= 0.5) return "LOW";          // still a coin flip or better
  if (p >= 0.25) return "MODERATE";
  if (p >= 0.1) return "SPECULATIVE";
  return "REMOTE";
}

export const CONFIDENCE_COPY: Record<ParlayRating["confidence"], string> = {
  LOW: "Better than a coin flip. Still a multi-leg bet.",
  MODERATE: "Roughly one in three. Most tickets at this level lose.",
  SPECULATIVE: "Around one in six. Priced as a lottery ticket for a reason.",
  REMOTE: "Under one in ten. The payout is the only reason to be here.",
};
