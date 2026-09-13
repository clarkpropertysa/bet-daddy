/**
 * When a list of picks is really one bet on one game.
 *
 * Every prop in a game is priced from a SINGLE simulated game, so when the model's view
 * of that game differs from the market's, every prop inside it moves together. On Week 2
 * the top of the board was New Orleans at Detroit stated a dozen ways, and four of the
 * ten Top Picks were Arizona at the Chargers. Backing several of those is one position at
 * several times the stake.
 *
 * "SAME SIDE" IS THE WRONG TEST, and the first version of this used it. An under on a
 * Chargers receiver and an over on a Cardinals receiver are the same bet -- Arizona keeps
 * it close -- though one is a yes and the other a no. So each pick is read as the team it
 * LEANS TOWARD: an over leans to the player's own team, an under to the opponent. Where a
 * team cannot be placed in the game (a code the ticker spells differently, a missing
 * team) the pick falls back to plain over/under, which can only make the warning quieter.
 *
 * Pure and dependency-free on purpose: `gameOf` is injected so the page passes the real
 * ticker parser and scripts/check-concentration.mjs can run this under plain node.
 */

export type ScriptRow = { marketTicker: string; side?: string; team: string | null };
export type GameOf = (ticker: string) => { label: string } | null;

/** Kalshi spells three franchises differently from nflverse. */
const CANON: Record<string, string> = { JAC: "JAX", LAR: "LA", WSH: "WAS" };
const canon = (code: string) => CANON[code] ?? code;

/** Share of a block that must lean one way before it counts as one script. */
const SAME_WAY = 0.7;

function leanOf(r: ScriptRow, away: string | null, home: string | null): string {
  const over = r.side === "yes";
  const team = r.team ? canon(r.team) : null;
  if (team && away && home) {
    if (team === away) return over ? away : home;
    if (team === home) return over ? home : away;
  }
  return over ? "overs" : "unders";
}

export function scriptConcentration(
  rows: ScriptRow[],
  gameOf: GameOf,
  noun: "rows" | "picks" = "rows",
): { headline: string } | null {
  const n = rows.length;
  if (n < 5) return null;

  const games = new Map<string, { rows: ScriptRow[]; label: string }>();
  for (const r of rows) {
    const key = r.marketTicker.split("-")[1] ?? "?";
    const g = games.get(key) ?? { rows: [], label: gameOf(r.marketTicker)?.label ?? "one game" };
    g.rows.push(r);
    games.set(key, g);
  }

  let biggest: { rows: ScriptRow[]; label: string } | null = null;
  for (const g of games.values()) {
    if (!biggest || g.rows.length > biggest.rows.length) biggest = g;
  }

  // Proportional floor: 3 of a 10-pick list, 4 of a 20-row board. A fixed floor tuned
  // to one list size went silent on the other -- and the board reprices through the
  // day, so a threshold tuned to one snapshot stops firing exactly when it matters.
  const floor = Math.max(3, Math.ceil(n * 0.2));
  if (biggest && biggest.rows.length >= floor) {
    const m = /^([A-Z]+) at ([A-Z]+)/.exec(biggest.label);
    const away = m ? canon(m[1]) : null;
    const home = m ? canon(m[2]) : null;
    const leans = new Map<string, number>();
    for (const r of biggest.rows) {
      const l = leanOf(r, away, home);
      leans.set(l, (leans.get(l) ?? 0) + 1);
    }
    let dir = "";
    let same = 0;
    for (const [k, v] of leans) {
      if (v > same) { dir = k; same = v; }
    }
    const k = biggest.rows.length;
    if (same >= Math.ceil(k * SAME_WAY)) {
      const way = dir === "overs" || dir === "unders" ? `(${dir})` : `toward ${dir}`;
      return {
        headline: `${k} of the top ${n} ${noun} are ${biggest.label}, and ${same} of those lean the same way, ${way}.`,
      };
    }
  }

  // No one game dominates, but a list can still be one bet: a slate-wide tilt to overs
  // or unders is the same correlation one level up.
  const overs = rows.filter((r) => r.side === "yes").length;
  const same = Math.max(overs, n - overs);
  if (same >= Math.ceil(n * SAME_WAY)) {
    return { headline: `${same} of the top ${n} ${noun} are ${overs >= same ? "overs" : "unders"}.` };
  }
  return null;
}
