/**
 * Market taxonomy — the organising spine of the Prop Board.
 *
 * Mirrors the ingest layer's series map. Declared here in full so the board
 * can show its own structure BEFORE any signals exist: an empty board that lists the
 * families it will carry tells you far more than a blank page.
 *
 * `modelled` marks families the simulator actually covers. A family the market lists but
 * we cannot price yet is shown greyed rather than hidden — a silently missing market
 * looks the same as one that does not exist.
 */
export type MarketFamily = {
  key: string;
  label: string;
  group: "Passing" | "Rushing" | "Receiving" | "Scoring" | "Defense";
  unit: "yards" | "count";
  modelled: boolean;
  note?: string;
};

export const MARKET_FAMILIES: MarketFamily[] = [
  { key: "pass_yds", label: "Passing yards", group: "Passing", unit: "yards", modelled: true },
  { key: "pass_tds", label: "Passing TDs", group: "Passing", unit: "count", modelled: true },
  { key: "pass_int", label: "Interceptions", group: "Passing", unit: "count", modelled: false,
    note: "needs an INT-rate model; not simulated yet" },
  { key: "rush_yds", label: "Rushing yards", group: "Rushing", unit: "yards", modelled: true },
  { key: "rec_yds", label: "Receiving yards", group: "Receiving", unit: "yards", modelled: true },
  { key: "receptions", label: "Receptions", group: "Receiving", unit: "count", modelled: true },
  { key: "longest_rec", label: "Longest reception", group: "Receiving", unit: "yards", modelled: false,
    note: "an extreme-value problem, not a total; needs its own model" },
  { key: "anytime_td", label: "Anytime TD", group: "Scoring", unit: "count", modelled: true },
  { key: "sacks", label: "Sacks", group: "Defense", unit: "count", modelled: false,
    note: "defensive props need a pass-rush model" },
];

export const MARKET_GROUPS = ["Passing", "Rushing", "Receiving", "Scoring", "Defense"] as const;

export function familyFor(key: string): MarketFamily | undefined {
  return MARKET_FAMILIES.find((f) => f.key === key);
}

export function labelFor(key: string): string {
  return familyFor(key)?.label ?? key;
}


/**
 * "2026_01_SF_LA" -> "SF @ LA". The game id is a stable key, not a label; showing it
 * raw in a filter chip leaks the schema into the UI.
 */
export function gameLabel(gameId: string): string {
  const parts = gameId.split("_");
  if (parts.length < 4) return gameId;
  const [, , away, home] = parts;
  return `${away} @ ${home}`;
}

export function gameWeek(gameId: string): string | null {
  const parts = gameId.split("_");
  return parts.length >= 2 ? `Week ${Number(parts[1])}` : null;
}


const TEAM_CODES = new Set([
  "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU",
  "IND","JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT",
  "SEA","SF","TB","TEN","WAS","JAC","LA","WSH",
]);

/**
 * "KXNFLPASSYDS-26AUG15CARBUF-..." -> { label: "CAR at BUF, Aug 15", preseason: true }
 *
 * A strike is unreadable without its game. "Over 50 passing yards" is absurd in
 * week 3 and routine in a preseason game where a starter plays one series.
 * The matchup is split by anchoring on real team codes: a midpoint split turns
 * ARILV into AR/ILV.
 */
export function gameFromTicker(
  ticker: string,
): { label: string; preseason: boolean } | null {
  const parts = ticker.split("-");
  if (parts.length < 2) return null;
  const m = /^\d{2}([A-Z]{3})(\d{2})([A-Z]{4,8})$/.exec(parts[1]);
  if (!m) return null;
  const [, mon, day, teams] = m;
  let away: string | null = null;
  for (const code of [...TEAM_CODES].sort((a, b) => b.length - a.length)) {
    if (teams.startsWith(code) && TEAM_CODES.has(teams.slice(code.length))) {
      away = code;
      break;
    }
  }
  if (!away) return null;
  const home = teams.slice(away.length);
  const month = mon.charAt(0) + mon.slice(1).toLowerCase();
  return {
    label: `${away} at ${home}, ${month} ${Number(day)}`,
    preseason: mon === "AUG" || mon === "JUL",
  };
}
