/**
 * Tier badge. Section 2: a signal is not actionable until it has a track record,
 * and unvalidated signals must render in a visually distinct state WITH the sample
 * size shown. This component is the enforcement point -- it cannot render a tier
 * without also rendering n.
 */
export type TierName = "UNVALIDATED" | "PROVISIONAL" | "VALIDATED";

const STYLES: Record<TierName, string> = {
  VALIDATED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  PROVISIONAL: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  // deliberately muted: unvalidated must not look like a recommendation
  UNVALIDATED: "border-zinc-700 bg-zinc-800/50 text-zinc-400 border-dashed",
};

export function Tier({ tier, n }: { tier: TierName; n: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${STYLES[tier]}`}
      title={
        tier === "UNVALIDATED"
          ? `No forward track record yet (${n} settled). Not actionable.`
          : `${n} settled contracts with positive closing line value.`
      }
    >
      {tier === "UNVALIDATED" ? "unvalidated" : tier.toLowerCase()}
      <span className="font-mono opacity-70">n={n}</span>
    </span>
  );
}
