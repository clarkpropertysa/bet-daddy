import { Empty } from "@/components/Empty";
import { signedCents } from "@/lib/format";
import { getClvSummary, getTrackRecord } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * Section 9.8 -- "This page never gets hidden or softened."
 *
 * It reports whatever the archive says, including negative CLV. Per the build
 * spec: a tool that reports negative CLV has told the truth, which is the
 * second-best outcome and much better than a dashboard that lies.
 */
export default async function TrackRecordPage() {
  const [summary, results] = await Promise.all([getClvSummary(), getTrackRecord()]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="display flex items-baseline gap-2 text-[22px] leading-none text-ink">
          <span className="text-steel">03 —</span>Track Record
        </h1>
        <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-ink-2">
          Every signal ever emitted, settled or not. Closing line value is the primary
          metric: it measures whether the market moved toward the bet, and it is
          readable long before win rate is.
        </p>
      </div>

      {summary.length === 0 ? (
        <Empty
          title="No graded signals yet"
          source="SignalResult table (Neon)"
          hint="CLV is computed once a market closes and the archive holds both an entry and a closing snapshot. The 2026 season opens 9 September."
        />
      ) : (
        <div className="overflow-x-auto rounded border border-line bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left">
              <tr>
                <th className="eyebrow px-3 py-2.5">Confidence</th>
                <th className="eyebrow px-3 py-2.5 text-right">Settled</th>
                <th className="eyebrow px-3 py-2.5 text-right">Mean CLV</th>
                <th className="eyebrow px-3 py-2.5 text-right">Mean P&amp;L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {summary.map((s) => {
                const clv = s.mean_clv ?? 0;
                return (
                  <tr key={s.tier}>
                    <td className="px-3 py-2 text-ink">{s.tier.toLowerCase()}</td>
                    <td className="tnum px-3 py-2 text-right text-ink-2">
                      {Number(s.n)}
                    </td>
                    <td
                      className={`tnum px-3 py-2 text-right font-semibold ${
                        clv > 0 ? "text-pos" : "text-neg"
                      }`}
                    >
                      {signedCents(clv)}
                    </td>
                    <td className="tnum px-3 py-2 text-right text-ink-2">
                      {signedCents(s.mean_pnl)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11.5px] text-ink-2">
        {results.length} graded signal{results.length === 1 ? "" : "s"} on record.
        Negative CLV is reported as-is; signal families that show it are killed rather
        than hidden.
      </p>
    </div>
  );
}
