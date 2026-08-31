import type { ConsensusSummary } from "@/lib/queries";

/**
 * How Kalshi's game prices compare to the sportsbook consensus.
 *
 * REFERENCE ONLY, and labelled as such. No edge, no Kelly, no fee — a sportsbook price
 * cannot go through the edge maths, which assumes a $1 binary contract with no vig, and
 * pretending otherwise would put a number on the board that no grade could ever match.
 */
export function ConsensusNote({ summary }: { summary: ConsensusSummary | null }) {
  if (!summary) return null;

  const body =
    summary.quoted === 0 ? (
      <>
        {summary.games} game markets are listed but none are quoted yet, so there is
        nothing to compare. Game markets are usually priced earlier than props, so this
        should fill in first.
      </>
    ) : (
      <>
        Across {summary.quoted} quoted {summary.quoted === 1 ? "game" : "games"}, this
        venue sits{" "}
        <span className="font-medium text-ink">
          {summary.meanAbsDiffPts?.toFixed(1)} points
        </span>{" "}
        from the consensus on average
        {summary.meanDiffPts !== null && (
          <> ({summary.meanDiffPts >= 0 ? "+" : ""}
          {summary.meanDiffPts.toFixed(1)} signed)</>
        )}
        , worst {summary.maxAbsDiffPts?.toFixed(1)}.
      </>
    );

  return (
    <div className="mb-3 rounded border border-line bg-card px-4 py-3">
      <p className="eyebrow mb-1">price check · reference only</p>
      <p className="text-[11.5px] leading-relaxed text-ink-2">{body}</p>
    </div>
  );
}
