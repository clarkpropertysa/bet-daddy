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
        <h1 className="text-lg font-semibold text-zinc-100">Track Record</h1>
        <p className="mt-0.5 text-xs text-zinc-500">
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
        <div className="overflow-x-auto rounded border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900/70 text-left text-[11px] uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-3 py-2 font-medium">Confidence</th>
                <th className="px-3 py-2 text-right font-medium">Settled</th>
                <th className="px-3 py-2 text-right font-medium">Mean CLV</th>
                <th className="px-3 py-2 text-right font-medium">Mean P&amp;L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/70">
              {summary.map((s) => {
                const clv = s.mean_clv ?? 0;
                return (
                  <tr key={s.tier}>
                    <td className="px-3 py-2 text-zinc-300">{s.tier.toLowerCase()}</td>
                    <td className="px-3 py-2 text-right font-mono text-zinc-400">
                      {Number(s.n)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-mono font-semibold ${
                        clv > 0 ? "text-emerald-400" : "text-red-400"
                      }`}
                    >
                      {signedCents(clv)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-zinc-400">
                      {signedCents(s.mean_pnl)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-zinc-600">
        {results.length} graded signal{results.length === 1 ? "" : "s"} on record.
        Negative CLV is reported as-is; signal families that show it are killed rather
        than hidden.
      </p>
    </div>
  );
}
