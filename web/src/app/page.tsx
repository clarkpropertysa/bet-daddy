import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { SlateGames, TopEdges } from "@/components/SlateBoard";
import { ConsensusNote } from "@/components/ConsensusNote";
import { StaleBanner } from "@/components/StaleBanner";
import { getConsensusSummary, getJobHealth, getNextSlate, getTopEdges } from "@/lib/queries";
import { relativeAge } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Section 9.1 — the at-a-glance dashboard. Everything that changes what is worth
 * looking at today, before any individual prop: who plays, on what rest, in what
 * conditions, with how much the market expects to happen.
 */
export default async function SlatePage() {
  const [games, edges, health, consensus] = await Promise.all([
    getNextSlate(), getTopEdges(), getJobHealth(), getConsensusSummary(),
  ]);

  const first = games[0]?.gameDate;
  const daysOut = first
    ? Math.ceil((new Date(first).getTime() - Date.now()) / 86_400_000)
    : null;

  return (
    <div>
      <PageHeader
        title="Slate"
        sub="What is worth looking at, before any individual prop: who plays, on what rest, in what conditions, and how much scoring the market expects."
        right={
          /* The Slate is built from schedule, rest and team context, not prices.
             Reporting the market archiver's age here answered a question this page
             does not ask, and went red on a page that was perfectly current. The
             context sync runs daily, so the threshold is a day and a bit. */
          <StaleBanner
            lastRun={health.find((h) => h.job === "sync_context")?.startedAt ?? null}
            job="Game context"
            maxMins={60 * 30}
          />
        }
      />

      <ConsensusNote summary={consensus} />

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div>
          <div className="mb-3 flex items-baseline gap-3">
            <h2 className="display text-[14px] text-ink">
              {games.length ? `Week ${games[0].week}` : "Next slate"}
            </h2>
            {daysOut !== null && (
              <span className="eyebrow">
                {daysOut > 0 ? `${daysOut} days out` : "in progress"} ·{" "}
                {games.length} games
              </span>
            )}
          </div>
          <p className="mb-2 text-[11px] leading-relaxed text-ink-3">
            Before week 4 the lean rests on last season, shrunk to 37% — prior-season
            EPA explains only 12% of the next season, so it is a weak prior rather
            than a read on this roster. Out-of-sample error is ±14 points on a single
            game, so anything under 3.5 shows no lean at all. Current-season play
            replaces the prior as it accumulates.
          </p>
          {games.length === 0 ? (
            <p className="text-[12px] text-ink-2">
              No scheduled games found. Run pipeline.ingest.sync_reference.
            </p>
          ) : (
            <SlateGames games={games} />
          )}
        </div>

        <aside className="space-y-5">
          <section className="rounded border border-line bg-card p-4">
            <h2 className="display mb-2 text-[13px] text-ink">Top edges</h2>
            <TopEdges edges={edges} />
          </section>

          <section className="rounded border border-line bg-card p-4">
            <h2 className="display mb-2 text-[13px] text-ink">Injury impact</h2>
            <p className="text-[12px] leading-relaxed text-ink-2">
              Nothing yet — official injury reports publish once the season starts.
              When they do, a starter ruled out promotes his backup here and on the
              Players page, with the freed-up usage attributed.
            </p>
          </section>

          <section className="rounded border border-line bg-card p-4">
            <h2 className="display mb-2 text-[13px] text-ink">Pipeline</h2>
            {health.length === 0 ? (
              <p className="text-[12px] text-ink-2">No runs recorded.</p>
            ) : (
              <ul className="space-y-1">
                {health.map((h) => (
                  <li key={h.job} className="flex justify-between gap-3 text-[11px]">
                    <span className="truncate text-ink-2">{h.job}</span>
                    <span className="tnum shrink-0 text-ink-3">
                      {relativeAge(h.startedAt)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {/* The curated view is the front door; every strike is one click further. */}
            <Link
              href="/top-picks"
              className="display mt-3 inline-block rounded bg-steel px-3 py-1.5 text-[12px] text-white transition-colors hover:bg-steel-700"
            >
              Open Top Picks
            </Link>
            <Link
              href="/board"
              className="mt-2 block text-[11px] text-steel underline-offset-2 hover:underline"
            >
              Every strike →
            </Link>
          </section>
        </aside>
      </div>
    </div>
  );
}
