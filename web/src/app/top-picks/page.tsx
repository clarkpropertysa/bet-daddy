import Link from "next/link";
import { Empty } from "@/components/Empty";
import { PageHeader } from "@/components/PageHeader";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { StaleBanner } from "@/components/StaleBanner";
import { Tier } from "@/components/Tier";
import { signedCents } from "@/lib/format";
import { gameFromTicker, labelFor } from "@/lib/markets";
import { getBoard, getJobHealth, getNextSlate } from "@/lib/queries";

export const dynamic = "force-dynamic";

/** A prop has to clear its own fee to be worth listing at all. */
const MIN_EDGE_CENTS = 1.0;

export default async function TopPicksPage() {
  const [rows, slate, health] = await Promise.all([
    getBoard(200),
    getNextSlate(),
    getJobHealth(),
  ]);

  const props = rows
    .filter((r) => r.edgeCentsNet >= MIN_EDGE_CENTS && !r.implausible)
    .slice(0, 10);

  /**
   * A pick is a DISAGREEMENT with the market, which is not what `leanConfident`
   * means: that flag says the model projects a meaningful MARGIN, so a game the
   * market already prices identically still sets it. Ranking on it listed a
   * 1.9-point disagreement as a top pick.
   *
   * The sign matters more. `disagreement = projected margin - market spread`, both
   * from the home team's perspective, so a NEGATIVE value means the model likes the
   * home team LESS than the market does -- and the side with value is the away team.
   * Naming `leanTeam` there would recommend the exact team the model is fading.
   */
  const leans = slate
    .filter(
      (g) =>
        g.leanDisagreement !== null &&
        Math.abs(g.leanDisagreement) >= 3.5 &&
        g.spreadLine !== null,
    )
    .map((g) => {
      const d = g.leanDisagreement as number;
      const takeHome = d > 0;
      return {
        game: g,
        gap: Math.abs(d),
        side: takeHome ? g.homeTeam : g.awayTeam,
        // The number that side is getting, from its own perspective.
        line: takeHome ? -(g.spreadLine as number) : (g.spreadLine as number),
      };
    })
    .sort((a, b) => b.gap - a.gap)
    .slice(0, 6);

  /**
   * Scoring environment, straight from the market. The implied team totals are the
   * half that bears on a prop: total/2 +/- spread/2 is what each side is expected to
   * score, and nothing else in the app derives it.
   */
  const totals = slate
    .filter((g) => g.totalLine !== null && g.spreadLine !== null)
    .map((g) => {
      const total = g.totalLine as number;
      const spread = g.spreadLine as number;   // positive = home favoured
      return {
        gameId: g.gameId,
        home: g.homeTeam,
        away: g.awayTeam,
        total,
        homeImplied: total / 2 + spread / 2,
        awayImplied: total / 2 - spread / 2,
        roof: g.roof,
        wind: g.windMph,
      };
    })
    .sort((a, b) => b.total - a.total);

  const archiver = health.find((h) => h.job === "kalshi_archiver");
  const newestPrice = props.reduce<Date | null>((acc, r) => {
    const t = r.priceAsOf ? new Date(r.priceAsOf) : null;
    return t && (!acc || t > acc) ? t : acc;
  }, null);

  return (
    <div>
      <PageHeader
        title="Top Picks"
        sub="The strongest disagreements between the model and the market right now, ranked within each kind. Nothing here is ranked across kinds — a prop edge is measured in cents after fees and a game lean in points, and inventing a common score would hide which is which."
        right={
          <StaleBanner
            lastRun={newestPrice ?? archiver?.startedAt ?? null}
            job={newestPrice ? "Prices" : "Archiver"}
            maxMins={180}
          />
        }
      />

      {/* ---------------------------------------------------------------- props */}
      <section className="mb-6">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h2 className="display text-[14px] text-ink">Player props</h2>
          <span className="eyebrow">net of fees · {props.length} clearing the bar</span>
        </div>

        {props.length === 0 ? (
          <Empty
            title="No prop clears its own fee"
            source="Signal (Neon)"
            hint="A prop only appears here when the model's probability beats the ask by more than the fee it would cost to take. Either no market is quoted yet, or nothing is currently mispriced enough to be worth listing."
          />
        ) : (
          <ol className="space-y-2">
            {props.map((r, i) => (
              <li
                key={r.signalId}
                className="flex items-center gap-3 rounded border border-line bg-card p-3"
              >
                <span className="display w-5 shrink-0 text-[15px] text-steel">{i + 1}</span>
                <PlayerAvatar name={r.player} url={r.headshotUrl} size={34} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-ink">
                    {r.player}{" "}
                    <span className="font-normal text-ink-2">
                      {r.side === "no" ? "under" : "over"} {r.strike ?? "—"}{" "}
                      {labelFor(r.marketType).toLowerCase()}
                    </span>
                  </p>
                  <p className="mt-0.5 text-[11px] text-ink-3">
                    {/* gameLabel parses the nflverse form (2026_01_NE_SEA); a board
                        row carries the Kalshi ticker, which it would print raw. */}
                    {r.team ?? "—"} ·{" "}
                    {gameFromTicker(r.marketTicker)?.label ?? r.gameId} · model{" "}
                    {(r.modelProb * 100).toFixed(0)}% vs market{" "}
                    {(r.marketProb * 100).toFixed(0)}%
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="display text-[15px] text-pos">
                    {signedCents(r.edgeCentsNet)}
                  </p>
                  <p className="eyebrow">per contract</p>
                </div>
                <div className="hidden shrink-0 sm:block">
                  <Tier tier={r.tier} n={r.sampleN} />
                </div>
              </li>
            ))}
          </ol>
        )}
        <p className="mt-2 text-[11px] leading-relaxed text-ink-3">
          Edge is what remains after the exact taker fee. Every one of these is{" "}
          <strong className="font-medium">unvalidated</strong> until 200 settled
          contracts show positive closing-line value — the tier badge says where each
          one stands. <Link href="/board" className="text-steel underline-offset-2 hover:underline">Full board →</Link>
        </p>
      </section>

      {/* ---------------------------------------------------------------- spreads */}
      <section className="mb-6">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h2 className="display text-[14px] text-ink">Game leans</h2>
          <span className="eyebrow">vs the market spread</span>
        </div>

        {leans.length === 0 ? (
          <Empty
            title="No game disagrees with the market enough"
            source="team ratings"
            hint="A lean is listed only when the projected margin differs from the market spread by more than 3.5 points — a disagreement, not merely a confident margin. The model carries a ±14 point out-of-sample error on a single game, so a smaller gap is inside its own noise and would be a coin flip dressed as a read."
          />
        ) : (
          <ol className="space-y-2">
            {leans.map(({ game: g, gap, side, line }, i) => (
              <li key={g.gameId} className="rounded border border-line bg-card p-3">
                <div className="flex items-baseline gap-3">
                  <span className="display w-5 shrink-0 text-[15px] text-steel">{i + 1}</span>
                  <p className="flex-1 text-[13px] text-ink">
                    <span className="font-medium">
                      {side} {line > 0 ? `+${line}` : line}
                    </span>{" "}
                    <span className="text-ink-2">
                      in {g.awayTeam} @ {g.homeTeam}
                    </span>
                  </p>
                  <p className="shrink-0 text-right">
                    <span className="display text-[15px] text-ink">
                      {gap.toFixed(1)} pts
                    </span>
                    <span className="eyebrow block">off the market</span>
                  </p>
                </div>
                {/* Both sides stated from whoever each one favours. "market has them
                    by -3.5" is a sentence nobody reads correctly. */}
                <p className="ml-8 mt-1 text-[11px] text-ink-3">
                  model:{" "}
                  {(g.projMargin ?? 0) >= 0 ? g.homeTeam : g.awayTeam} by{" "}
                  {Math.abs(g.projMargin ?? 0).toFixed(1)} · market:{" "}
                  {(g.spreadLine ?? 0) >= 0 ? g.homeTeam : g.awayTeam} by{" "}
                  {Math.abs(g.spreadLine ?? 0).toFixed(1)}
                </p>
                {g.leanWhy?.length ? (
                  <p className="ml-8 mt-1 text-[11.5px] leading-relaxed text-ink-2">
                    {g.leanWhy[0]}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* ---------------------------------------------------------------- totals */}
      <section>
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h2 className="display text-[14px] text-ink">Scoring environment</h2>
          <span className="eyebrow">context, not a pick</span>
        </div>

        {totals.length === 0 ? (
          <Empty
            title="No lines posted yet"
            source="nflverse schedules"
            hint="Totals and spreads appear as the market posts them, usually a few days out."
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded border border-line bg-card">
              <table className="w-full min-w-[440px] text-[12px]">
                <thead>
                  <tr className="border-b border-line text-left">
                    <th className="px-3 py-2 font-medium text-ink-3">Game</th>
                    <th className="px-3 py-2 font-medium text-ink-3">Total</th>
                    <th className="px-3 py-2 font-medium text-ink-3">Implied</th>
                    <th className="px-3 py-2 font-medium text-ink-3">Venue</th>
                  </tr>
                </thead>
                <tbody>
                  {totals.map((t) => (
                    <tr key={t.gameId} className="border-b border-line-2 last:border-0">
                      <td className="px-3 py-2 text-ink">
                        {t.away} @ {t.home}
                      </td>
                      <td className="px-3 py-2 font-medium text-ink">
                        {t.total.toFixed(1)}
                      </td>
                      {/* The half that matters for a prop: how many points each side
                          is expected to score, not the game total. */}
                      <td className="px-3 py-2 text-ink-2">
                        {t.away} {t.awayImplied.toFixed(1)} · {t.home}{" "}
                        {t.homeImplied.toFixed(1)}
                      </td>
                      <td className="px-3 py-2 text-ink-3">
                        {t.roof === "dome" || t.roof === "closed" ? "indoors" : "outdoors"}
                        {t.wind !== null ? ` · ${Math.round(t.wind)}mph` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="mt-2 text-[11.5px] leading-relaxed text-ink-3">
              These are the <strong className="font-medium text-ink-2">market&apos;s</strong>{" "}
              numbers, not the model&apos;s, and there is no over/under pick here on
              purpose. Measured across 1,087 games, the closing total misses the actual
              score by <strong className="font-medium text-ink-2">13.0 points</strong>{" "}
              against 13.6 for always guessing the league average — the market explains
              only <strong className="font-medium text-ink-2">8.7%</strong> of the
              variance in game totals, and adding this model&apos;s team ratings improves
              that by 0.027 points with the coefficient the wrong sign. A total pick
              would be a coin flip presented as a read.
            </p>
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-3">
              The <strong className="font-medium text-ink-2">implied</strong> column is
              the useful part: <span className="text-ink-2">total ÷ 2 ± spread ÷ 2</span>{" "}
              is how many points each side is expected to score, and a receiver on a team
              implied for 30 has more to play for than one on a team implied for 17.
              Wind is shown where the schedule carries it, though the market prices it
              already — outdoor games above 15mph land just 0.9 points under the line.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
