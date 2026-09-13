import { scriptConcentration, type ScriptRow } from "@/lib/concentration";
import { gameFromTicker } from "@/lib/markets";

/**
 * The warning that a list of picks is one bet on one game. Shared by Top Picks and the
 * board so the two cannot describe the same slate differently. See lib/concentration.
 */
export function ScriptBanner({ rows, noun }: { rows: ScriptRow[]; noun: "rows" | "picks" }) {
  const c = scriptConcentration(rows, gameFromTicker, noun);
  if (!c) return null;
  return (
    <p className="mb-3 rounded border border-warn/40 bg-warn/[0.06] px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
      <strong className="font-medium text-warn">{c.headline}</strong>{" "}
      Every prop in a game is priced from a single simulated game, so picks from one game
      rise and fall together. Backing several is one position at several times the stake,
      not a spread of bets — size them as one.
    </p>
  );
}
