/**
 * Names the model behind the rows below, and warns loudly when it is not a
 * production model. Without it a board of model error reads as a board of great
 * bets -- the exact failure Section 2 describes.
 */
export function ModelBanner({ version }: { version: string | null }) {
  if (!version) return null;
  const production = !/smoke|test|v0\b|dev/i.test(version);
  if (production) {
    return <p className="eyebrow">model · {version}</p>;
  }
  return (
    <div className="flex items-start gap-2.5 rounded border border-neg/50 bg-neg/[0.06] px-3 py-2.5">
      <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-neg" aria-hidden="true" />
      <p className="text-[11.5px] leading-relaxed text-neg">
        <strong className="font-semibold">Non-production model.</strong> These rows come
        from <span className="tnum">{version}</span>, a pipeline smoke run. Its usage
        assumptions are invalid, so the edges below are model error, not opportunity.
        Do not trade them.
      </p>
    </div>
  );
}
