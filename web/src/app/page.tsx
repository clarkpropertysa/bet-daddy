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
        <h1 className="text-lg font-semibold text-zinc-100">Slate</h1>
        <p className="mt-0.5 text-xs text-zinc-500">
          2026 season opens Wednesday 9 September — NE at SEA, Lumen Field.
          {days > 0 && ` ${days} day${days === 1 ? "" : "s"} out.`}
        </p>
      </div>

      <StaleBanner
        lastRun={health.find((h) => h.job === "kalshi_archiver")?.startedAt ?? null}
        job="Market archiver"
      />

      <section className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
        <h2 className="text-sm font-medium text-zinc-200">Pipeline health</h2>
        {health.length === 0 ? (
          <p className="mt-2 text-xs text-zinc-500">
            No pipeline runs recorded yet. The archiver writes Parquet and uploads to
            blob storage; run records land here once the DB writer is wired.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-xs">
            {health.map((h) => (
              <li key={h.job} className="flex justify-between gap-4 font-mono text-zinc-400">
                <span>{h.job}</span>
                <span>{h.rowsWritten} rows</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link
        href="/board"
        className="inline-block rounded border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-900"
      >
        Open Prop Board →
      </Link>
    </div>
  );
}
