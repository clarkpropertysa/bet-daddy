import { isStale, relativeAge } from "@/lib/format";

/**
 * Section 12: a failed job must surface as visibly stale rather than silently
 * serving yesterday's numbers. Rendered on every data surface.
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
      <div className="flex items-center gap-2 text-[11px] text-ink-3">
        <span className="h-1.5 w-1.5 rounded-full bg-pos" aria-hidden="true" />
        {job} updated {relativeAge(lastRun)}
      </div>
    );
  }
  return (
    <div className="flex max-w-md items-start gap-2.5 rounded-md border border-warn/40 bg-warn/[0.07] px-3 py-2.5">
      <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-warn" aria-hidden="true" />
      <p className="text-[11px] leading-relaxed text-warn">
        <strong className="font-semibold">Stale data.</strong> {job} last succeeded{" "}
        {relativeAge(lastRun)}
        {lastRun ? "" : " (never run)"}. Prices and edges below may be out of date.
      </p>
    </div>
  );
}
