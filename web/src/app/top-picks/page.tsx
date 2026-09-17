import Link from "next/link";
import { Empty } from "@/components/Empty";
import { PageHeader } from "@/components/PageHeader";
import { ScriptBanner } from "@/components/ScriptBanner";
import { TopPickList } from "@/components/TopPickList";
import { StaleBanner } from "@/components/StaleBanner";
import { getJobHealth, getModelView, getNextSlate, getProjectionBoard } from "@/lib/queries";
import { ModelView } from "@/components/ModelView";
import { isSuppressed, SUPPRESSED_LABEL, SUPPRESSED_WHY } from "@/lib/suppressed";
import { anchorFit } from "@/lib/anchor";

export const dynamic = "force-dynamic";

/** A prop has to clear its own fee to be worth listing at all. */
const MIN_EDGE_CENTS = 1.0;

/**
 * How wide a book may be before it stops being a market.
 *
 * Kalshi is an exchange: every contract needs someone on the other side. The board's
 * whole claim is "the model disagrees with the market", and on a book quoted 0.05/0.34
 * there is no market price to disagree with -- there is one participant's resting
 * offer and a 29-cent gap. Measured across the live slate the median spread is 13c and
 * a third of markets are wider than 25c, so this is not a rare edge case.
 *
 * The edge itself is still computed honestly against the ask, which is what you would
 * pay. This gate is about whether the disagreement means anything.
 */
const MAX_SPREAD_CENTS = 15;

/** How many props the page lists. The correlation banner scales its floor with this. */
const TOP_PICKS = 15;

export default async function TopPicksPage() {
  const [rows, expected, slate, health] = await Promise.all([
    // One row per PROJECTION. A ticker is unique per strike, so ranking raw signals
    // let a single player's twenty-rung ladder take most of the list -- twenty copies
    // of one opinion, presented as twenty opportunities.
    // Wide enough that 15 survive the fee, book-width and rushing gates: the query
    // reads the same 1,000 board rows whatever this number is, so it costs nothing.
    getProjectionBoard(80),
    // What the model expects, with no reference to price -- the page's lead section.
    getModelView(),
    getNextSlate(),
    getJobHealth(),
  ]);

  const props = rows
    .filter(
      (r) =>
        // RANKED AND GATED ON THE MARKET-ANCHORED EDGE (lib/anchor), not the model's own.
        // Week 1 was the first time the model met prices: the market was the better
        // forecaster, and on the picks offered the model said 53%, the market 37%, and
        // 37% landed. A pick now has to survive being blended with the price at the weight
        // the model has earned on settled contracts.
        r.anchoredEdgeCents !== null &&
        r.anchoredEdgeCents >= MIN_EDGE_CENTS &&
        !r.implausible &&
        // A null spread means we could not measure the book, which is not the same as
        // a tight one and must not pass silently.
        r.spreadCents !== null &&
        r.spreadCents <= MAX_SPREAD_CENTS &&
        // A family the measurements say the model gets wrong is not a pick, however
        // large its edge looks -- and the largest edges on this board were exactly
        // those. Still listed on /board, just not recommended here.
        !isSuppressed(r.marketType),
    )
    .slice(0, TOP_PICKS);

  // "HELD BACK" MEANS IT WOULD HAVE MADE THE LIST. Counted over the whole candidate
  // pool, the rushing figure jumped from 8 to 18 the moment the pool widened for a
  // 15-pick page -- the number described the query, not the picks. Only rows whose
  // edge would have ranked among the listed ones count.
  const cutoff = props.length === TOP_PICKS
    ? (props[props.length - 1].anchoredEdgeCents as number)
    : MIN_EDGE_CENTS;
  const fit = rows.length ? anchorFit(rows[0].reason) : null;
  const pct = (w: number) => `${Math.round(w * 100)}%`;

  const wideBooks = rows.filter(
    (r) =>
      (r.anchoredEdgeCents ?? -Infinity) >= cutoff &&
      !r.implausible &&
      r.spreadCents !== null &&
      r.spreadCents > MAX_SPREAD_CENTS,
  ).length;

  /** Clears every gate on its own merits, and is withheld anyway. See lib/suppressed. */
  const withheld = rows.filter(
    (r) =>
      (r.anchoredEdgeCents ?? -Infinity) >= cutoff &&
      !r.implausible &&
      r.spreadCents !== null &&
      r.spreadCents <= MAX_SPREAD_CENTS &&
      isSuppressed(r.marketType),
  ).length;

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
  // A lean on a game already played is not a pick. Day-level, because per-game kickoff
  // is not populated ahead of time: this listed "IND +3.5 in BAL @ IND" two days after
  // the game.
  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);
  const leans = slate
    .filter(
      (g) =>
        new Date(g.gameDate).getTime() >= today.getTime() &&
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
  // Read off what is ON THE PAGE. It used to read the picks list, which is now usually
  // empty, so a current page reported the archiver's age instead of the price's.
  const newestPrice = expected
    .flatMap((g) => g.claims)
    .reduce<Date | null>((acc, c) => {
      const t = c.row.priceAsOf ? new Date(c.row.priceAsOf) : null;
      return t && (!acc || t > acc) ? t : acc;
    }, null);

  return (
    <div>
      <PageHeader
        title="Top Picks"
        sub="What the model expects to happen this week, game by game, with no reference to any price: the projection, and the lines its own distribution is confident about. Prices come second — a separate section says where a projection also beats the ask, which on current evidence is nowhere. Nothing is ranked across kinds, because a prop is cents after fees and a game lean is points."
        right={
          <StaleBanner
            lastRun={newestPrice ?? archiver?.startedAt ?? null}
            job={newestPrice ? "Prices" : "Archiver"}
            maxMins={180}
          />
        }
      />

      {/* ------------------------------------------------- what the model expects */}
      <section className="mb-6">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h2 className="display text-[14px] text-ink">What the model expects</h2>
          <span className="eyebrow">
            {expected.reduce((n, g) => n + g.claims.length, 0)} projections ·{" "}
            {expected.length} {expected.length === 1 ? "game" : "games"}
          </span>
        </div>

        {/* THE CALIBRATION WARNING STAYS ON THE PAGE, not in a footnote. These are the
            model's own percentages, and Week 1 measured exactly how far they lean. */}
        <p className="mb-3 rounded border border-line bg-steel-100/50 px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
          <strong className="font-medium text-ink">Expectations, not recommendations.</strong>{" "}
          These are the model&apos;s own numbers with no reference to any price. Against the
          honest baseline — how often a player has already cleared a line — the projections
          beat the box score by 21% over 2025. The percentages run confident: across Week 1
          the model said 53% on the calls it wanted to make and 37% of them happened, so
          read a 78% as &quot;likely&quot;, not as 78 in 100.
        </p>

        {expected.length === 0 ? (
          <Empty
            title="Nothing projected for the next slate"
            source="Projection (Neon)"
            hint="Projections appear once the week's markets are listed and the projection job has run. Markets are listed well before they are priced."
          />
        ) : (
          <ModelView games={expected} />
        )}
      </section>

      {/* --------------------------------------------------- and where it beats a price */}
      <section className="mb-6">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h2 className="display text-[14px] text-ink">Where it also beats the price</h2>
          <span className="eyebrow">
            {props.length} clearing the bar
            {wideBooks > 0 ? ` · ${wideBooks} held back on a wide book` : ""}
            {withheld > 0 ? ` · ${withheld} held back on ${SUPPRESSED_LABEL}` : ""}
          </span>
        </div>

        {props.length === 0 ? (
          <p className="rounded border border-line bg-card px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
            Nothing, right now. A projection only lands here when it still beats the ask
            after the fee once blended with the market at the weight the model has earned
            on settled contracts
            {fit && fit.n > 0
              ? ` — across ${fit.n.toLocaleString()} settled markets the market forecast better${
                  fit.brierMarket !== null && fit.brierModel !== null
                    ? ` (Brier ${fit.brierMarket.toFixed(4)} against ${fit.brierModel.toFixed(4)})`
                    : ""
                }, so that weight is ${pct(fit.weight)}`
              : ""}
            . That is a statement about <em>prices</em>, not about the projections above:
            the market has already priced what the model expects.{" "}
            <Link href="/track-record" className="text-steel underline-offset-2 hover:underline">
              Track record →
            </Link>
          </p>
        ) : (
          <>
            <ScriptBanner rows={props} noun="picks" />
            <TopPickList picks={props} />
          </>
        )}
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
                    <span className="display text-[15px] text-ink-2">
                      {gap.toFixed(1)} pts
                    </span>
                    <span className="eyebrow block">disagreement</span>
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
