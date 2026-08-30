import Link from "next/link";
import { StaleBanner } from "@/components/StaleBanner";
import { getJobHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";

const KICKOFF = new Date("2026-09-09T20:20:00-07:00");

export default async function SlatePage() {
  const health = await getJobHealth();
  const days = Math.ceil((KICKOFF.getTime() - Date.now()) / 86_400_000);

  return (
    <div className="space-y-5">
      <div>
        <p className="mt-0.5 text-xs text-ink-2">
          2026 season opens Wednesday 9 September — NE at SEA, Lumen Field.
          {days > 0 && ` ${days} day${days === 1 ? "" : "s"} out.`}
        </p>
      </div>

      <StaleBanner
        lastRun={health.find((h) => h.job === "kalshi_archiver")?.startedAt ?? null}
        job="Market archiver"
      />

      <section className="rounded border border-line bg-card p-4">
        <h2 className="display text-[13px] text-ink">Pipeline health</h2>
        {health.length === 0 ? (
          <p className="mt-2 text-xs text-ink-2">
            No pipeline runs recorded yet. The archiver writes Parquet and uploads to
            blob storage; run records land here once the DB writer is wired.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-xs">
            {health.map((h) => (
              <li key={h.job} className="tnum flex justify-between gap-4 text-ink-2">
                <span>{h.job}</span>
                <span>{h.rowsWritten} rows</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link
        href="/board"
        className="display inline-block rounded bg-steel px-4 py-2 text-[13px] text-white transition-colors hover:bg-steel-700"
      >
        Open Prop Board →
      </Link>
    </div>
  );
}
