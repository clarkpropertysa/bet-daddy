/** Display helpers. Money and probabilities are formatted in exactly one place. */

/** Prices are dollars per $1 contract; users read them as cents. */
export function priceCents(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return `${(Number(v) * 100).toFixed(0)}¢`;
}

export function pct(v: unknown, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${(Number(v) * 100).toFixed(digits)}%`;
}

/** Edges are signed: the sign is the whole message, so never drop it. */
export function signedCents(v: unknown, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}¢`;
}

/**
 * Directional glyph for an edge value. Required secondary encoding: the pos/neg
 * pair sits at CVD ΔE 6.5 for protanopia, so colour can never be the only channel.
 */
export function edgeGlyph(v: unknown): string {
  if (v === null || v === undefined) return "";
  return Number(v) > 0 ? "▲" : "▼";
}

export function edgeTone(v: unknown): string {
  if (v === null || v === undefined) return "text-ink-3";
  const n = Number(v);
  if (n > 0) return "text-pos";
  return "text-neg";
}

/** Staleness is a first-class UI concern (Section 12): never serve stale silently. */
export function relativeAge(ts: Date | string | null | undefined): string {
  if (!ts) return "never";
  const mins = Math.floor((Date.now() - new Date(ts).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function isStale(ts: Date | string | null | undefined, maxMins = 45): boolean {
  if (!ts) return true;
  return (Date.now() - new Date(ts).getTime()) / 60000 > maxMins;
}

/**
 * How the market itself states a strike.
 *
 * Kalshi lists "8+ receptions" and settles it on MORE THAN 7.5, so `floor_strike` is
 * 7.5 and the title says 8. Rendering the floor as "over 8" -- which the board did --
 * reads as needing NINE, and is wrong in the same direction on every count market.
 * The yes side is stated the way the market states it; the no side is its complement,
 * where "under 8" is already exactly right.
 */
export function strikeLabel(strike: number | null, side: string): string {
  if (strike === null || strike === undefined) return "—";
  const stated = Math.ceil(strike);
  return side === "no" ? `under ${stated}` : `${stated}+`;
}

/**
 * A projected quantity, at the precision the quantity deserves.
 *
 * Yards carry no useful decimal -- a receiver projected for 94.26 yards is projected
 * for 94 -- while receptions and touchdowns do, because the whole line moves in ones.
 */
export function projected(value: number | null, marketType: string): string {
  if (value === null || value === undefined) return "—";
  const coarse = marketType.endsWith("_yds") || marketType.endsWith("_yards");
  return coarse ? value.toFixed(0) : value.toFixed(1);
}

/**
 * Contracts traded, at a glance. 1597 -> "1.6k".
 *
 * Volume is the only thing on the board that says whether anyone is actually trading
 * this market. Kalshi is an exchange, not a bookmaker: a contract with no volume has
 * no counterparty, and an edge against a price nobody has ever taken is a different
 * claim from an edge against a price hundreds of people have.
 */
export function compactCount(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const n = Math.round(Number(v));
  if (n < 1000) return String(n);
  if (n < 10000) return `${(n / 1000).toFixed(1)}k`;
  return `${Math.round(n / 1000)}k`;
}
