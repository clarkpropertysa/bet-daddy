import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { SlateGames, TopEdges } from "@/components/SlateBoard";
import { StaleBanner } from "@/components/StaleBanner";
import { getJobHealth, getNextSlate, getTopEdges } from "@/lib/queries";
import { relativeAge } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Section 9.1 — the at-a-glance dashboard. Everything that changes what is worth
 * looking at today, before any individual prop: who plays, on what rest, in what
 * conditions, with how much the market expects to happen.
 */
export default async function SlatePage() {
  const [games, edges, health] = await Promise.all([
    getNextSlate(), getTopEdges(), getJobHealth(),
  ]);

  const first = games[0]?.gameDate;
  const daysOut = first
    ? Math.ceil((new Date(first).getTime() - Date.now()) / 86_400_000)
    : null;

  return (
    <div>
      <PageHeader
        index="00"
        title="Slate"
        sub="What is worth looking at, before any individual prop: who plays, on what rest, in what conditions, and how much scoring the market expects."
        right={
          <StaleBanner
            lastRun={health.find((h) => h.job === "kalshi_archiver")?.startedAt ?? null}
            job="Archiver"
          />
        }
      />

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
            Leans come from prior-season EPA ratings converted to points by a fitted
            scale. Single-game margins carry a ±11.7 point error, so a lean is a
            starting point, not a verdict — and games inside that band show none.
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
            <Link
              href="/board"
              className="display mt-3 inline-block rounded bg-steel px-3 py-1.5 text-[12px] text-white transition-colors hover:bg-steel-700"
            >
              Open Prop Board
            </Link>
          </section>
        </aside>
      </div>
    </div>
  );
}
