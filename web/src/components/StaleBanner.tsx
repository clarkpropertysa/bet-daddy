import { isStale, relativeAge } from "@/lib/format";

/**
 * Section 12: if a pipeline job fails, the UI must show the data is stale rather
 * than silently serving yesterday's numbers. This renders on every data surface.
 */
export function StaleBanner({
  lastRun,
  job,
  maxMins = 45,
}: {
  lastRun: Date | string | null;
  job: string;
  maxMins?: number;
}) {
  if (!isStale(lastRun, maxMins)) {
    return (
      <p className="text-xs text-zinc-500">
        {job} updated {relativeAge(lastRun)}
      </p>
    );
  }
  return (
    <div className="rounded border border-amber-600/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
      <strong className="font-semibold">Stale data.</strong>{" "}
      {job} last succeeded {relativeAge(lastRun)}
      {lastRun ? "" : " (never run)"}. Prices and edges below may be out of date.
    </div>
  );
}
