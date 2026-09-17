"use client";

import { useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { WhyPanel, type WhyRow } from "@/components/WhyPanel";
import { projected, strikeLabel } from "@/lib/format";
import { labelFor } from "@/lib/markets";
import { isSuppressed } from "@/lib/suppressed";
import { confidenceOf, GRADE_WORDS, type ReliabilityTable } from "@/lib/confidence";
import type { ModelClaim, ModelGame } from "@/lib/queries";

/**
 * What the model expects, game by game. No prices, no edges, no ranking by disagreement.
 *
 * A TABLE WITH HEADERS, because two unlabelled chips do not tell a reader which side to
 * take. Every projection states the same four things in the same places: what it expects,
 * the highest line it is confident he CLEARS, the lowest line it is confident he STAYS
 * UNDER, and which of those two it is surer about.
 *
 * A projection with neither is still listed, as "no confident call" -- that is information
 * about the model, and dropping the row would make the page look surer than the model is.
 */
export function ModelView({
  games, reliability,
}: { games: ModelGame[]; reliability: ReliabilityTable }) {
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

            <div className="overflow-x-auto rounded border border-line bg-card">
              <table className="w-full min-w-[660px] text-[12px]">
                <thead>
                  <tr className="border-b border-line text-left">
                    <th className="eyebrow px-3 py-2">Player</th>
                    <th className="eyebrow px-3 py-2 text-right">Projects</th>
                    {/* Named as the two sides a reader would take, not as jargon. */}
                    <th className="eyebrow px-3 py-2">Over it clears</th>
                    <th className="eyebrow px-3 py-2">Under it stays</th>
                    <th className="eyebrow px-3 py-2 text-right">Surer side</th>
                    {/* Not the model's opinion of itself: what claims like it have done. */}
                    <th className="eyebrow px-3 py-2 text-right">Track record says</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {g.claims.map((c) => (
                    <Row
                      key={c.key}
                      c={c}
                      reliability={reliability}
                      onOpen={() => setActive(c.row)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
      <WhyPanel row={active} onClose={() => setActive(null)} />
    </>
  );
}

function Row({
  c, reliability, onOpen,
}: { c: ModelClaim; reliability: ReliabilityTable; onOpen: () => void }) {
  const { floor, ceiling } = c.expectation;
  // Both sides clear the same bar, so name the one the model is more sure of and say it
  // as a side -- "over" or "under" -- rather than leaving it to be inferred from a colour.
  const surer =
    floor && ceiling
      ? floor.p >= ceiling.p
        ? { word: "over", p: floor.p }
        : { word: "under", p: ceiling.p }
      : floor
        ? { word: "over", p: floor.p }
        : ceiling
          ? { word: "under", p: ceiling.p }
          : null;

  // What the track record makes of the side it is surer about.
  const conf = surer
    ? confidenceOf(reliability, c.marketType, surer.word === "over" ? "yes" : "no", surer.p)
    : null;

  return (
    <tr
      className="cursor-pointer border-b border-line-2 transition-colors last:border-0 hover:bg-steel-100/40"
      onClick={onOpen}
    >
      <td className="px-3 py-2">
        <span className="flex items-center gap-2">
          <span className="hidden shrink-0 sm:block">
            <PlayerAvatar name={c.player} url={c.headshotUrl} size={26} />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-ink">
              {c.player}
            </span>
            <span className="block text-[11px] text-ink-3">
              {c.team ?? "—"} · {labelFor(c.marketType).toLowerCase()}
              {isSuppressed(c.marketType) && (c.projMean ?? 0) >= 40 ? (
                <span className="text-warn"> · runs low on high-volume backs</span>
              ) : null}
            </span>
          </span>
        </span>
      </td>

      <td className="px-3 py-2 text-right">
        <span className="display block text-[15px] text-ink">
          {projected(c.projMean, c.marketType)}
        </span>
        {c.projMedian !== null && (
          <span className="eyebrow">median {projected(c.projMedian, c.marketType)}</span>
        )}
      </td>

      <td className="px-3 py-2">
        {floor ? (
          <>
            <span className="display text-[13px] text-ink">
              {strikeLabel(floor.strike, "yes")}
            </span>
            <span className="tnum ml-1.5 text-[12px] text-ink-2">
              {(floor.p * 100).toFixed(0)}%
            </span>
          </>
        ) : (
          <span className="text-ink-3">—</span>
        )}
      </td>

      <td className="px-3 py-2">
        {ceiling ? (
          <>
            <span className="display text-[13px] text-ink">
              {strikeLabel(ceiling.strike, "no")}
            </span>
            <span className="tnum ml-1.5 text-[12px] text-ink-2">
              {(ceiling.p * 100).toFixed(0)}%
            </span>
          </>
        ) : (
          <span className="text-ink-3">—</span>
        )}
      </td>

      <td className="px-3 py-2 text-right">
        {surer ? (
          <span
            className={`display inline-flex rounded-[3px] px-1.5 py-[3px] text-[11.5px] uppercase tracking-[0.04em] ${
              surer.word === "over"
                ? "bg-steel-900 text-white"
                : "bg-steel-200 text-steel-900"
            }`}
          >
            {surer.word} {(surer.p * 100).toFixed(0)}%
          </span>
        ) : (
          <span className="eyebrow">no confident call</span>
        )}
      </td>

      <td className="px-3 py-2 text-right">
        {conf ? (
          <>
            <span
              className={`display block text-[13px] ${
                conf.grade === "solid"
                  ? "text-ink"
                  : conf.grade === "shaky"
                    ? "text-warn"
                    : conf.grade === "poor"
                      ? "text-neg"
                      : "text-ink-3"
              }`}
            >
              {conf.grade === "untested"
                ? "untested"
                : `${(conf.adjusted * 100).toFixed(0)}%`}
            </span>
            <span className="eyebrow" title={
              conf.basis
                ? `Claims like this one: said ${(conf.basis.stated * 100).toFixed(0)}%, happened ${(conf.basis.actual * 100).toFixed(0)}% over ${conf.basis.n} settled contracts.`
                : "No settled contracts of this kind yet."
            }>
              {conf.grade === "untested"
                ? "no settled sample"
                : `${GRADE_WORDS[conf.grade]} · n=${conf.basis?.n ?? 0}`}
            </span>
          </>
        ) : (
          <span className="text-ink-3">—</span>
        )}
      </td>

      <td className="px-3 py-2 text-right">
        <span className="eyebrow text-steel">why →</span>
      </td>
    </tr>
  );
}
