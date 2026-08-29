export type TierName = "UNVALIDATED" | "PROVISIONAL" | "VALIDATED";

const STYLES: Record<TierName, string> = {
  VALIDATED: "border-pos/40 bg-pos/10 text-pos",
  PROVISIONAL: "border-warn/40 bg-warn/10 text-warn",
  // Dashed and desaturated on purpose: an unvalidated signal must not read as a
  // recommendation at a glance.
  UNVALIDATED: "border-dashed border-line-strong bg-surface-2 text-ink-3",
};

const LABEL: Record<TierName, string> = {
  VALIDATED: "validated",
  PROVISIONAL: "provisional",
  UNVALIDATED: "unvalidated",
};

/**
 * Section 2: unvalidated signals render in a visually distinct state WITH the
 * sample size shown. `n` is a required prop, so a tier cannot be displayed
 * without it -- the constraint is structural rather than a convention.
 */
export function Tier({ tier, n }: { tier: TierName; n: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded border px-1.5 py-[3px] text-[10px] font-medium tracking-wide ${STYLES[tier]}`}
      title={
        tier === "UNVALIDATED"
          ? `No forward track record yet (${n} settled contracts). Not actionable.`
          : `${n} settled contracts with positive closing line value.`
      }
    >
      {LABEL[tier]}
      <span className="font-mono opacity-60">{n}</span>
    </span>
  );
}
