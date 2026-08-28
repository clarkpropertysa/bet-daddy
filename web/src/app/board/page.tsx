import { PropBoard, type Row } from "@/components/PropBoard";
import { StaleBanner } from "@/components/StaleBanner";
import { getBoard, getJobHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function BoardPage() {
  const [rows, health] = await Promise.all([getBoard(), getJobHealth()]);
  const archiver = health.find((h) => h.job === "kalshi_archiver");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Prop Board</h1>
        <p className="mt-0.5 text-xs text-zinc-500">
          Model probability against the Kalshi ask, net of the exact fee. Every row is
          clickable through to its reasoning.
        </p>
      </div>
      <StaleBanner lastRun={archiver?.startedAt ?? null} job="Market archiver" />
      <PropBoard rows={rows as unknown as Row[]} />
    </div>
  );
}
