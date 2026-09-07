"use client";

import { useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Tier } from "@/components/Tier";
import { WhyPanel, type WhyRow } from "@/components/WhyPanel";
import {
  compactCount,
  payoutMultiple,
  priceCents,
  projected,
  signedCents,
  strikeLabel,
} from "@/lib/format";
import { gameFromTicker, labelFor } from "@/lib/markets";
import type { ProjectionRow } from "@/lib/queries";

/**
 * The Top Picks list, as a client component so a row can open the Why panel.
 *
 * The panel is the thing that makes the tool worth using over guessing, and it was
 * reachable only from the Prop Board -- the page a reader is most likely to act from
 * had no way to ask why. The row markup is unchanged; only the wrapper moved.
 *
 * `WhyPanel` reads the STORED signal, so what it shows is what the model thought when
 * the pick fired, not a fresh recomputation.
 */
export function TopPickList({ picks }: { picks: ProjectionRow[] }) {
  const [active, setActive] = useState<WhyRow | null>(null);

  return (
    <>
            <ol className="space-y-2">
              {picks.map((r, i) => (
                <li key={r.signalId}>
                  <button
                    type="button"
                    onClick={() => setActive(r)}
                    aria-label={`Why ${r.player} ${labelFor(r.marketType).toLowerCase()}`}
                    className="flex w-full items-center gap-3 rounded border border-line bg-card p-3 text-left transition-colors hover:border-line-2 hover:bg-steel-100/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-steel"
                  >
                  <span className="display w-5 shrink-0 text-[15px] text-steel">{i + 1}</span>
                  {/* Hidden on a phone: the avatar costs 46px of a 375px row and the
                      name was truncating to "Bro..." to pay for it. */}
                  <span className="hidden shrink-0 sm:block">
                    <PlayerAvatar name={r.player} url={r.headshotUrl} size={34} />
                  </span>
                  <div className="min-w-0 flex-1">
                    {/* THE PICK LEADS, and it sits in a fixed position so the column of
                        chips can be scanned down without reading any of the prose.
                        Previously the bet itself was the tail of the third line, after
                        the team and the fixture -- the reader had to parse a sentence to
                        learn what was being recommended. */}
                    <p className="flex items-baseline gap-2 text-[15px]">
                      <span
                        /* Fixed width so the names below it line up into a column: a
                           "3+" chip and an "UNDER 50" chip are very different sizes, and
                           a ragged left edge is what makes a list slow to scan. */
                        className={`display inline-flex shrink-0 justify-center rounded-[3px] px-1.5 py-[3px] text-[13px] tracking-[0.02em] sm:min-w-[4.75rem] ${
                          r.side === "no"
                            ? "bg-steel-200 text-steel-900"
                            : "bg-steel-900 text-white"
                        }`}
                      >
                        {/* The market's own notation. "3+" settles at three; rendering
                            it as "over 3" asks for four. */}
                        {strikeLabel(r.strike, r.side)}
                      </span>
                      <span className="truncate font-semibold text-ink">{r.player}</span>
                    </p>
                    {/* Why the pick, in one line: what the model expects, and how far
                        that sits from what the market is charging. */}
                    <p className="mt-1 text-[12px] text-ink-2">
                      {/* The market type lives here rather than beside the name: on a
                          narrow column two truncating spans fight and both lose, and
                          "Matth... pas..." tells the reader nothing at all. */}
                      <span className="text-ink">{labelFor(r.marketType).toLowerCase()}</span>
                      {" · projects "}
                      <strong className="font-medium text-ink">
                        {projected(r.projMean, r.marketType)}
                      </strong>
                      {r.projMedian !== null ? (
                        <span className="text-ink-3">
                          {" "}
                          (median {projected(r.projMedian, r.marketType)})
                        </span>
                      ) : null}
                      {" · "}
                      <strong className="font-medium text-ink">
                        {(r.modelProb * 100).toFixed(0)}%
                      </strong>{" "}
                      vs {priceCents(r.marketProb)} market
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink-3">
                      {/* gameLabel parses the nflverse form (2026_01_NE_SEA); a board
                          row carries the Kalshi ticker, which it would print raw. */}
                      {r.team ?? "—"} ·{" "}
                      {gameFromTicker(r.marketTicker)?.label ?? r.gameId} · best of{" "}
                      {r.ladderRungs} {r.ladderRungs === 1 ? "line" : "lines"}
                      {/* Whether there is anyone to trade with. Kalshi is an exchange,
                          so a contract nobody has traded has no counterparty yet. */}
                      {" · "}
                      <span className={r.volume ? "" : "text-warn"}>
                        {compactCount(r.volume)} traded
                      </span>
                      {r.spreadCents !== null ? ` · ${r.spreadCents.toFixed(0)}¢ spread` : ""}
                    </p>
                  </div>
                  {/* Two numbers answering two questions: what a dollar comes back as
                      if it hits, and whether the model thinks it is worth taking. The
                      multiple is the figure Kalshi itself shows, so it is stated gross
                      of fees to match; the edge is net of the exact taker fee. */}
                  <div className="shrink-0 text-right">
                    <p className="display text-[15px] text-ink">
                      {payoutMultiple(r.marketProb)}
                    </p>
                    <p className="eyebrow">if it hits</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="display text-[15px] text-pos">
                      {signedCents(r.edgeCentsNet)}
                    </p>
                    <p className="eyebrow">edge</p>
                  </div>
                  <div className="hidden shrink-0 sm:block">
                    <Tier tier={r.tier} n={r.sampleN} />
                  </div>
                  <span className="eyebrow hidden shrink-0 text-steel sm:block">
                    why →
                  </span>
                  </button>
                </li>
              ))}
            </ol>
      <WhyPanel row={active} onClose={() => setActive(null)} />
    </>
  );
}
