/** Display helpers. Money and probabilities are formatted in exactly one place. */

/** Kalshi prices are dollars per $1 contract; users read them as cents. */
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
