"use client";

import { useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { WhyPanel, type WhyRow } from "@/components/WhyPanel";
import { projected, strikeLabel } from "@/lib/format";
import { labelFor } from "@/lib/markets";
import { isSuppressed } from "@/lib/suppressed";
import type { ModelGame } from "@/lib/queries";

/**
 * What the model expects, game by game. No prices, no edges, no ranking by disagreement.
 *
 * Each row is a projection and the two statements its own curve supports: the highest line
 * it is at least 70% sure of clearing, and the lowest it is at least 70% sure of staying
 * under. A row with neither is still shown -- "no confident call" is information about the
 * model, and hiding it would make the page look more certain than the model is.
 */
export function ModelView({ games }: { games: ModelGame[] }) {
  const [active, setActive] = useState<WhyRow | null>(null);

  return (
    <>
      <div className="space-y-5">
        {games.map((g) => (
          <section key={g.game}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
              <h3 className="display text-[13px] text-ink">{g.label}</h3>
              <span className="eyebrow">{g.claims.length} projections</span>
            </div>
            <div className="overflow-hidden rounded border border-line bg-card">
              {g.claims.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => setActive(c.row)}
                  aria-label={`Why ${c.player} ${labelFor(c.marketType).toLowerCase()}`}
                  className="flex w-full items-center gap-3 border-b border-line-2 px-3 py-2 text-left transition-colors last:border-0 hover:bg-steel-100/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-steel"
                >
                  <span className="hidden shrink-0 sm:block">
                    <PlayerAvatar name={c.player} url={c.headshotUrl} size={28} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className="truncate text-[13.5px] font-medium text-ink">
                        {c.player}
                      </span>
                      <span className="eyebrow shrink-0">{c.team ?? "—"}</span>
                    </span>
                    <span className="mt-0.5 block text-[11.5px] text-ink-2">
                      {labelFor(c.marketType).toLowerCase()}
                      {/* Flagged where the bias was MEASURED -- on the workhorses, whose
                          projections ran 23-30 yards under. On a quarterback's 6-yard line
                          it is noise on every row. */}
                      {isSuppressed(c.marketType) && (c.projMean ?? 0) >= 40 ? (
                        <span className="text-warn"> · runs low on high-volume backs</span>
                      ) : null}
                    </span>
                  </span>

                  {/* The projection is the claim. Median beside the mean because a yardage
                      distribution is right-skewed and the two differ by enough to matter. */}
                  <span className="shrink-0 text-right">
                    <span className="display block text-[15px] text-ink">
                      {projected(c.projMean, c.marketType)}
                    </span>
                    <span className="eyebrow">
                      {c.projMedian !== null
                        ? `median ${projected(c.projMedian, c.marketType)}`
                        : "projected"}
                    </span>
                  </span>

                  {/* What it is actually confident about, read off its own curve. */}
                  <span className="hidden w-[15.5rem] shrink-0 items-center justify-end gap-1.5 sm:flex">
                    {c.expectation.floor && (
                      <span className="rounded-[3px] bg-steel-900 px-1.5 py-[3px] text-[11px] text-white">
                        {strikeLabel(c.expectation.floor.strike, "yes")}{" "}
                        <span className="opacity-70">
                          {(c.expectation.floor.p * 100).toFixed(0)}%
                        </span>
                      </span>
                    )}
                    {c.expectation.ceiling && (
                      <span className="rounded-[3px] bg-steel-200 px-1.5 py-[3px] text-[11px] text-steel-900">
                        {strikeLabel(c.expectation.ceiling.strike, "no")}{" "}
                        <span className="opacity-70">
                          {(c.expectation.ceiling.p * 100).toFixed(0)}%
                        </span>
                      </span>
                    )}
                    {!c.expectation.floor && !c.expectation.ceiling && (
                      <span className="eyebrow">no confident call</span>
                    )}
                  </span>

                  <span className="eyebrow hidden shrink-0 text-steel sm:block">why →</span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
      <WhyPanel row={active} onClose={() => setActive(null)} />
    </>
  );
}
