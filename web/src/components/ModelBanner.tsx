/**
 * Says which model produced the rows below.
 *
 * The board can be populated by a non-production model -- the preseason smoke run
 * exists to exercise the pipeline on real prices, and its usage assumptions are known
 * to be wrong. Rows from it look like enormous edges. Without this banner the surface
 * reads as a board full of great bets when it is a board full of model error, which
 * is the exact failure Section 2 warns about.
 */
export function ModelBanner({ version }: { version: string | null }) {
  if (!version) return null;
  const production = !/smoke|test|v0\b|dev/i.test(version);
  if (production) {
    return (
      <p className="text-[11px] text-ink-3">
        model <span className="font-mono text-ink-2">{version}</span>
      </p>
    );
  }
  return (
    <div className="flex items-start gap-2.5 rounded-md border border-neg/40 bg-neg/[0.07] px-3 py-2.5">
      <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-neg" aria-hidden="true" />
      <p className="text-[11px] leading-relaxed text-neg">
        <strong className="font-semibold">Non-production model.</strong> These rows come
        from <span className="font-mono">{version}</span>, a pipeline smoke run against
        real preseason prices. Its usage assumptions are invalid for preseason — starters
        play a series or two — so the large edges below are model error, not opportunity.
        Do not trade them.
      </p>
    </div>
  );
}
