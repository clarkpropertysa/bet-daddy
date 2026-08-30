export type TierName = "UNVALIDATED" | "PROVISIONAL" | "VALIDATED";

const STYLES: Record<TierName, string> = {
  VALIDATED: "border-pos bg-steel-100 text-pos",
  PROVISIONAL: "border-warn/50 bg-warn/[0.08] text-warn",
  // Dashed and muted: an unvalidated signal must not read as a recommendation.
  UNVALIDATED: "border-dashed border-line-2 bg-paper text-ink-3",
};

/**
 * Section 2: unvalidated signals render in a visually distinct state WITH the sample
 * size shown. `n` is required, so a tier cannot be displayed without it.
 */
export function Tier({ tier, n }: { tier: TierName; n: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-[3px] border px-1.5 py-[3px] text-[9px] font-medium uppercase tracking-[0.1em] ${STYLES[tier]}`}
      title={
        tier === "UNVALIDATED"
          ? `No forward track record yet (${n} settled contracts). Not actionable.`
          : `${n} settled contracts with positive closing line value.`
      }
    >
      {tier.toLowerCase()}
      <span className="tnum opacity-60">{n}</span>
    </span>
  );
}
