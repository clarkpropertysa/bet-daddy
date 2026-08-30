import Link from "next/link";
import { MarketMap } from "@/components/MarketMap";
import { gameLabel, gameWeek } from "@/lib/markets";
import { ModelBanner } from "@/components/ModelBanner";
import { PageHeader } from "@/components/PageHeader";
import { PropBoard, type Row } from "@/components/PropBoard";
import { StaleBanner } from "@/components/StaleBanner";
import { getBoard, getJobHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function BoardPage({
  searchParams,
}: {
  searchParams: Promise<{ game?: string }>;
}) {
  const { game } = await searchParams;
  const [rows, health] = await Promise.all([getBoard(200, game), getJobHealth()]);
  const archiver = health.find((h) => h.job === "kalshi_archiver");
  const modelVersion = rows.length ? (rows[0] as { modelVersion?: string }).modelVersion ?? null : null;
  const counts = rows.reduce<Record<string, number>>((acc, r) => {
    acc[r.marketType] = (acc[r.marketType] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <PageHeader
        index="01"
        title="Prop Board"
        sub="Model probability against the market ask, net of the exact fee. Sorted on net edge, because gross edge is not a bet. Click any row for the full reasoning chain."
        right={<StaleBanner lastRun={archiver?.startedAt ?? null} job="Archiver" />}
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
      <PropBoard rows={rows as unknown as Row[]} />
    </div>
  );
}
