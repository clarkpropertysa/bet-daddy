"use client";

import { labelFor } from "@/lib/markets";

/**
 * The prediction as a sentence, not a row of fields.
 *
 * The board previously showed strike, ask, model, fee, net edge and Kelly as six
 * separate numbers and left the reader to assemble the claim. The claim is the
 * product; the numbers are its support.
 */
export function Prediction({
  side, strike, marketType,
}: { side: string | undefined; strike: number | null; marketType: string }) {
  // Defaults to the over: compute_edge only records "no" when it picked that side,
  // so an absent value means yes.
  const over = (side ?? "yes") === "yes";
  return (
    <span className="flex items-baseline gap-1.5">
      <span
        className={`display rounded-[3px] px-1.5 py-[3px] text-[11px] tracking-[0.08em] ${
          over ? "bg-steel-900 text-white" : "bg-steel-200 text-steel-900"
        }`}
      >
        {over ? "over" : "under"}
      </span>
      <span className="tnum text-[15px] font-semibold text-ink">{strike ?? "—"}</span>
      <span className="text-[12px] text-ink-2">{labelFor(marketType).toLowerCase()}</span>
    </span>
  );
}

/**
 * Model probability against market probability, as one picture.
 *
 * Two aligned bars on a shared scale: the reader sees the gap without subtracting
 * two percentages. The gap IS the bet, so it gets the emphasis.
 */
export function ProbabilityGap({
  modelProb, marketProb,
}: { modelProb: number; marketProb: number }) {
  const gap = (modelProb - marketProb) * 100;
  const w = (p: number) => `${Math.max(0, Math.min(1, p)) * 100}%`;
  return (
    <span className="block w-[132px]">
      <span className="mb-1 flex items-baseline justify-between">
        <span className="eyebrow !text-[9px]">model</span>
        <span className="tnum text-[12px] font-semibold text-ink">
          {(modelProb * 100).toFixed(0)}%
        </span>
      </span>
      <span className="block h-1.5 overflow-hidden rounded-full bg-line">
        <span className="block h-full rounded-full bg-steel-700" style={{ width: w(modelProb) }} />
      </span>
      <span className="mb-1 mt-1.5 flex items-baseline justify-between">
        <span className="eyebrow !text-[9px]">market</span>
        <span className="tnum text-[11px] text-ink-2">
          {(marketProb * 100).toFixed(0)}%
        </span>
      </span>
      <span className="block h-1.5 overflow-hidden rounded-full bg-line">
        <span className="block h-full rounded-full bg-line-2" style={{ width: w(marketProb) }} />
      </span>
      <span
        className={`mt-1 block text-[10px] ${gap > 0 ? "text-pos" : "text-neg"}`}
      >
        {gap > 0 ? "model is " : "model is "}
        <span className="tnum font-semibold">{Math.abs(gap).toFixed(0)} pts</span>
        {gap > 0 ? " higher" : " lower"}
      </span>
    </span>
  );
}

/**
 * What the edge means, in words, with the number beside it.
 *
 * Bands are set by the fee, not by taste: the fee peaks at 1.75c, so an edge under
 * ~2c is mostly fee and saying so is more useful than printing "+1.40¢".
 */
export function EdgeVerdict({
  netCents, feeCents, implausible,
}: { netCents: number; feeCents: number; implausible: boolean }) {
  if (implausible) {
    return (
      <span className="block">
        <span className="display text-[12px] text-neg">model disagrees wildly</span>
        <span className="mt-0.5 block text-[10px] leading-snug text-ink-3">
          likely missing something the market knows
        </span>
      </span>
    );
  }
  const band =
    netCents <= 0 ? { label: "no edge", tone: "text-ink-3",
                      note: "the fee eats the difference" }
    : netCents < 2 ? { label: "thin", tone: "text-ink-2",
                       note: `${feeCents.toFixed(2)}¢ of it is fee` }
    : netCents < 5 ? { label: "modest edge", tone: "text-pos",
                       note: "worth a look, not a shout" }
    : { label: "strong edge", tone: "text-pos", note: "large disagreement with the market" };

  return (
    <span className="block">
      <span className={`display text-[12px] ${band.tone}`}>
        {band.label}
        {netCents > 0 && (
          <span className="tnum ml-1.5 font-semibold">+{netCents.toFixed(1)}¢</span>
        )}
      </span>
      <span className="mt-0.5 block text-[10px] leading-snug text-ink-3">{band.note}</span>
    </span>
  );
}
