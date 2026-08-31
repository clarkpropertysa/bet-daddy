import { PlayerAvatar } from "@/components/PlayerAvatar";
import type { SplitRow } from "@/lib/queries";

const METRIC_LABEL: Record<string, string> = {
  target_share: "target share",
  carry_share: "carry share",
  air_yards_share: "air yards share",
};

/**
 * How this player's role changes when a specific teammate does not play.
 *
 * Only splits that clear both gates in features/splits.py reach here: at least four
 * games each way, and a Welch interval that excludes zero. Of roughly 6,200 computed
 * pairs about 84 qualify, and the empty state says so rather than leaving a gap --
 * "no separable effect" is a finding, not a missing feature.
 */
export function SplitsPanel({ splits }: { splits: SplitRow[] }) {
  return (
    <section className="rounded border border-line bg-card">
      <div className="border-b border-line px-4 py-3">
        <h2 className="display text-[14px] text-ink">Without a teammate</h2>
        <p className="eyebrow mt-0.5">measured, not assumed</p>
      </div>

      {splits.length === 0 ? (
        <p className="px-4 py-5 text-[12px] leading-relaxed text-ink-2">
          No current teammate&apos;s absence has a separable effect on this
          player&apos;s role. That is the usual outcome: it needs at least four games
          each way and a confidence interval that excludes zero, and most absences
          coincide with everything else that changed that week. Splits against players
          who have since left the league are excluded — they cannot recur, and cannot be
          checked against an injury report.
        </p>
      ) : (
        <ul className="divide-y divide-line-2">
          {splits.map((s) => {
            const dir = s.delta > 0 ? "rises" : "falls";
            const label = METRIC_LABEL[s.metric] ?? s.metric.replace(/_/g, " ");
            return (
              <li key={`${s.teammate}-${s.metric}`} className="flex gap-3 px-4 py-3">
                <PlayerAvatar name={s.teammate} url={s.teammateHeadshot} size={28} />
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] leading-snug text-ink">
                    With <span className="font-medium">{s.teammate}</span> out, his{" "}
                    {label} {dir}{" "}
                    <span className="font-medium">
                      {(Math.abs(s.delta) * 100).toFixed(1)} points
                    </span>
                    .
                  </p>
                  {/* Sample sizes and the interval travel with the claim, always. */}
                  <p className="mt-1 text-[11px] text-ink-3">
                    {(s.meanWith * 100).toFixed(1)}% across {s.nWith}{" "}
                    {s.nWith === 1 ? "game" : "games"} together ·{" "}
                    {(s.meanWithout * 100).toFixed(1)}% across {s.nWithout} without ·
                    95% CI {(s.ciLow * 100).toFixed(1)} to {(s.ciHigh * 100).toFixed(1)}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
