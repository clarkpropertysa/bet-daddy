import { isStale, relativeAge } from "@/lib/format";

/** Section 12: a failed job surfaces as visibly stale, never silently served. */
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
      <div className="flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-pos" aria-hidden="true" />
        <span className="eyebrow">
          {job} · {relativeAge(lastRun)}
        </span>
      </div>
    );
  }
  return (
    <div className="flex max-w-md items-start gap-2.5 rounded border border-warn/50 bg-warn/[0.07] px-3 py-2.5">
      <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-warn" aria-hidden="true" />
      <p className="text-[11.5px] leading-relaxed text-warn">
        <strong className="font-semibold">Stale data.</strong> {job} last succeeded{" "}
        {relativeAge(lastRun)}
        {lastRun ? "" : " (never run)"}. Prices and edges below may be out of date.
      </p>
    </div>
  );
}
