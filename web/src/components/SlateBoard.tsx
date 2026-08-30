import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Tier, type TierName } from "@/components/Tier";
import { labelFor } from "@/lib/markets";
import { signedCents } from "@/lib/format";
import type { SlateGame } from "@/lib/queries";

const WIND_THRESHOLD = 15;

function fmtDate(d: Date) {
  return new Date(d).toLocaleDateString("en-US", {
    weekday: "long", month: "short", day: "numeric", timeZone: "UTC",
  });
}

/** Rest/venue facts worth flagging on a game. Only real ones — no filler chips. */
function flags(g: SlateGame): { label: string; tone: "warn" | "steel" | "neg" }[] {
  const f: { label: string; tone: "warn" | "steel" | "neg" }[] = [];
  if (g.isNeutral) f.push({ label: "neutral site", tone: "warn" });
  if (g.homeShortWeek || g.awayShortWeek) {
    const who = g.homeShortWeek && g.awayShortWeek ? "both" : g.homeShortWeek ? g.homeTeam : g.awayTeam;
    f.push({ label: `short week · ${who}`, tone: "warn" });
  }
  if (g.homePostBye || g.awayPostBye) {
    const who = g.homePostBye && g.awayPostBye ? "both" : g.homePostBye ? g.homeTeam : g.awayTeam;
    f.push({ label: `post-bye · ${who}`, tone: "steel" });
  }
  // Section 5.5: wind is the weather variable that matters, not temperature.
  if (g.windMph !== null && g.windMph >= WIND_THRESHOLD)
    f.push({ label: `wind ${Math.round(g.windMph)}mph`, tone: "neg" });
  if (g.divGame) f.push({ label: "division", tone: "steel" });
  return f;
}

const TONE: Record<string, string> = {
  warn: "border-warn/50 bg-warn/[0.08] text-warn",
  steel: "border-steel-300 bg-steel-100 text-steel-800",
  neg: "border-neg bg-neg/[0.07] text-neg",
};

export function SlateGames({ games }: { games: SlateGame[] }) {
  const byDay = games.reduce<Record<string, SlateGame[]>>((acc, g) => {
    const k = fmtDate(g.gameDate);
    (acc[k] ||= []).push(g);
    return acc;
  }, {});

  return (
    <div className="space-y-5">
      {Object.entries(byDay).map(([day, gs]) => (
        <div key={day}>
          <p className="eyebrow mb-2">{day}</p>
          <div className="overflow-hidden rounded border border-line bg-card">
            {gs.map((g) => {
              const fl = flags(g);
              return (
                <div
                  key={g.gameId}
                  className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2.5 last:border-0"
                >
                  <span className="display min-w-[140px] text-[14px] text-ink">
                    {g.awayTeam} <span className="text-ink-3">@</span> {g.homeTeam}
                  </span>

                  <span className="flex items-center gap-1.5">
                    <span className="eyebrow">total</span>
                    <span className="odds-box text-[12px]">
                      {g.totalLine ?? "—"}
                    </span>
                    <span className="eyebrow ml-1">spread</span>
                    <span className="odds-box text-[12px]">
                      {g.spreadLine !== null
                        ? `${g.spreadLine > 0 ? "+" : ""}${g.spreadLine}`
                        : "—"}
                    </span>
                  </span>

                  <span className="flex flex-wrap gap-1">
                    {fl.map((x) => (
                      <span
                        key={x.label}
                        className={`rounded-[3px] border px-1.5 py-[2px] text-[9px] uppercase tracking-[0.08em] ${TONE[x.tone]}`}
                      >
                        {x.label}
                      </span>
                    ))}
                  </span>

                  <span className="ml-auto flex items-center gap-3">
                    <span className="eyebrow">
                      {g.venue ?? "venue tbd"}
                      {g.roof ? ` · ${g.roof}` : ""}
                    </span>
                    <span className="tnum text-[11px] text-ink-3">
                      {g.signalCount} {g.signalCount === 1 ? "signal" : "signals"}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function TopEdges({
  edges,
}: {
  edges: { player: string; marketType: string; strike: number | null; side: string;
           edgeCentsNet: number; tier: string; headshotUrl: string | null }[];
}) {
  if (edges.length === 0) {
    return (
      <p className="text-[12px] leading-relaxed text-ink-2">
        No positive-edge signals yet. Signals appear once Kalshi quotes the slate and
        the projection job runs — markets are listed well before they are priced.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-line">
      {edges.map((e, i) => (
        <li key={i} className="flex items-center gap-3 py-2">
          <PlayerAvatar name={e.player} url={e.headshotUrl} size={26} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-ink">
              {e.player}
            </span>
            <span className="eyebrow">
              {labelFor(e.marketType)} · {e.side} {e.strike ?? ""}
            </span>
          </span>
          <Tier tier={e.tier as TierName} n={0} />
          <span className="odds-box odds-box--pos shrink-0 text-[12px] font-semibold">
            {signedCents(e.edgeCentsNet)}
          </span>
        </li>
      ))}
    </ul>
  );
}
