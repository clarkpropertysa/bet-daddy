import Link from "next/link";
import { MarketMap } from "@/components/MarketMap";
import { gameLabel, gameWeek } from "@/lib/markets";
import { ModelBanner } from "@/components/ModelBanner";
import { PageHeader } from "@/components/PageHeader";
import { PropBoard, type Row } from "@/components/PropBoard";
import { StaleBanner } from "@/components/StaleBanner";
import { getBoard, getBoardStatus, getJobHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function BoardPage({
  searchParams,
}: {
  searchParams: Promise<{ game?: string }>;
}) {
  const { game } = await searchParams;
  const [rows, health, status] = await Promise.all([
    getBoard(200, game),
    getJobHealth(),
    getBoardStatus(),
  ]);
  const archiver = health.find((h) => h.job === "kalshi_archiver");
  // The honest staleness number for this page is the age of the PRICE being shown,
  // not the age of a job. A job can succeed while finding nothing, and a price can
  // be current while some unrelated job is behind. Fall back to the archiver only
  // when there are no prices to date.
  const newestPrice = rows.reduce<Date | null>((acc, r) => {
    const t = r.priceAsOf ? new Date(r.priceAsOf) : null;
    return t && (!acc || t > acc) ? t : acc;
  }, null);
  const modelVersion = rows.length ? (rows[0] as { modelVersion?: string }).modelVersion ?? null : null;
  const counts = rows.reduce<Record<string, number>>((acc, r) => {
    acc[r.marketType] = (acc[r.marketType] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <PageHeader
        title="Prop Board"
        sub="What the model thinks will happen, and how far that sits from the market. Sorted by how much the gap is worth after fees — gross edge is not a bet. Click any row for the reasoning behind it."
        right={
          <StaleBanner
            lastRun={newestPrice ?? archiver?.startedAt ?? null}
            job={newestPrice ? "Prices" : "Archiver"}
            // The same limit the projection enforces when selecting a quote, so the
            // banner and the selector cannot disagree about what counts as stale.
            maxMins={status?.maxPriceAgeMins || 180}
          />
        }
      />
      {game && (
        <div className="mb-3 flex items-center gap-3 rounded border border-steel-300 bg-steel-100 px-3 py-2">
          <span className="text-[12px] text-steel-800">
            Showing props for{" "}
            <span className="display text-[13px]">{gameLabel(game)}</span>
            <span className="ml-2 text-ink-3">{gameWeek(game)}</span>
          </span>
          <Link href="/board" className="ml-auto text-[11px] text-steel underline-offset-2 hover:underline">
            clear filter
          </Link>
        </div>
      )}
      <MarketMap counts={counts} />
      <div className="mb-3">
        <ModelBanner version={modelVersion} />
      </div>
      <PropBoard rows={rows as unknown as Row[]} status={status} />
    </div>
  );
}
