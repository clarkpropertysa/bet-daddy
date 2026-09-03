import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Tier, type TierName } from "@/components/Tier";
import { labelFor } from "@/lib/markets";
import { signedCents, strikeLabel } from "@/lib/format";
import Link from "next/link";
import { TeamLogo } from "@/components/TeamLogo";
import { readableOn, teamColor } from "@/lib/teamColor";
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
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
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
                <Link
                  key={g.gameId}
                  href={`/board?game=${encodeURIComponent(g.gameId)}`}
                  className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2.5 transition-colors last:border-0 hover:bg-steel-100"
                >
                  <span className="flex min-w-[168px] items-center gap-1.5">
                    <TeamLogo url={g.awayLogo} team={g.awayTeam} size={22} />
                    <span className="display text-[14px] text-ink">{g.awayTeam}</span>
                    <span className="text-ink-3">@</span>
                    <TeamLogo url={g.homeLogo} team={g.homeTeam} size={22} />
                    <span className="display text-[14px] text-ink">{g.homeTeam}</span>
                  </span>

                  {/* The model's lean, shown only when it clears its own noise floor.
                      Out-of-sample RMSE is ~14 points, so anything under 3.5 is not
                      a view worth stating. */}
                  {g.leanTeam && (
                    <span className="flex items-center gap-1.5">
                      {g.leanConfident ? (
                        // Filled in the favoured team's own colour, with the label
                        // colour chosen by luminance -- team primaries run from
                        // #FFB612 to #002244 and a fixed label is unreadable on half.
                        <span
                          className="flex items-center gap-1.5 rounded-[3px] px-1.5 py-[3px] text-[10px] font-medium uppercase tracking-[0.08em]"
                          style={{
                            background: teamColor(
                              g.leanTeam === g.homeTeam ? g.homeColor : g.awayColor,
                            ),
                            color: readableOn(
                              g.leanTeam === g.homeTeam ? g.homeColor : g.awayColor,
                            ),
                          }}
                        >
                          <TeamLogo
                            url={g.leanTeam === g.homeTeam ? g.homeLogo : g.awayLogo}
                            team={g.leanTeam ?? ""}
                            size={13}
                          />
                          {g.leanTeam} by {Math.abs(g.projMargin ?? 0).toFixed(1)}
                        </span>
                      ) : (
                        <span className="eyebrow" title="Projected margin is inside the model's own error bar.">
                          no lean
                        </span>
                      )}
                      {g.leanConfident &&
                        g.leanDisagreement !== null &&
                        Math.abs(g.leanDisagreement) >= 3 && (
                          <span
                            className="rounded-[3px] border border-warn/50 bg-warn/[0.08] px-1.5 py-[2px] text-[9px] uppercase tracking-[0.08em] text-warn"
                            title="Gap between the model's projected margin and the market spread."
                          >
                            {Math.abs(g.leanDisagreement).toFixed(1)} off market
                          </span>
                        )}
                    </span>
                  )}

                  <span className="flex items-center gap-1.5">
                    <span className="eyebrow">total</span>
                    <span className="odds-box text-[12px]">
                      {g.totalLine ?? "—"}
                    </span>
                    <span className="eyebrow ml-1">spread</span>
                    {/* NAME THE TEAM. nflverse spread_line is positive when the HOME
                        team is favoured, so a bare "+3.5" on "NE @ SEA" reads most
                        naturally as NE getting points -- the exact opposite of what
                        it means. Rendered the way a sportsbook would: favourite and
                        the number it lays. */}
                    <span className="odds-box text-[12px]">
                      {g.spreadLine !== null && g.spreadLine !== 0
                        ? `${g.spreadLine > 0 ? g.homeTeam : g.awayTeam} -${Math.abs(
                            g.spreadLine,
                          )}`
                        : g.spreadLine === 0
                          ? "pick'em"
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
                    <span className="tnum text-[11px] text-steel">
                      {g.signalCount} {g.signalCount === 1 ? "prop" : "props"} →
                    </span>
                  </span>

                  {/* The reasoning, in the row rather than a tooltip. A lean nobody
                      can inspect is just an assertion. */}
                  {g.leanConfident && g.leanWhy && g.leanWhy.length > 0 && (
                    <span className="basis-full text-[11px] leading-relaxed text-ink-2">
                      {g.leanWhy.join(" · ")}
                      {g.leanDisagreement !== null &&
                        Math.abs(g.leanDisagreement) >= 3 && (
                          <span className="text-warn">
                            {" "}
                            · market has it {Math.abs(g.leanDisagreement).toFixed(1)}{" "}
                            points the other way
                          </span>
                        )}
                    </span>
                  )}
                  {!g.leanConfident && g.leanTeam && (
                    <span className="basis-full text-[11px] leading-relaxed text-ink-3">
                      Projected margin is under 3.5 points, inside the model&apos;s
                      own ±14 point out-of-sample error, so no side is favoured.
                    </span>
                  )}
                </Link>
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
        No positive-edge signals yet. Signals appear once the slate is quoted and
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
              {labelFor(e.marketType)} · {strikeLabel(e.strike, e.side)}
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
