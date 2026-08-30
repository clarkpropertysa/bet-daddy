import { MarketMap } from "@/components/MarketMap";
import { ModelBanner } from "@/components/ModelBanner";
import { PageHeader } from "@/components/PageHeader";
import { PropBoard, type Row } from "@/components/PropBoard";
import { StaleBanner } from "@/components/StaleBanner";
import { getBoard, getJobHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function BoardPage() {
  const [rows, health] = await Promise.all([getBoard(), getJobHealth()]);
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
        sub="Model probability against the Kalshi ask, net of the exact fee. Sorted on net edge, because gross edge is not a bet. Click any row for the full reasoning chain."
        right={<StaleBanner lastRun={archiver?.startedAt ?? null} job="Archiver" />}
      />
      <MarketMap counts={counts} />
      <div className="mb-3">
        <ModelBanner version={modelVersion} />
      </div>
      <PropBoard rows={rows as unknown as Row[]} />
    </div>
  );
}
