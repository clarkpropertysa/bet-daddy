"use client";

import { useEffect } from "react";
import { DistributionChart } from "@/components/DistributionChart";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { pct, priceCents, signedCents } from "@/lib/format";

type Step = { step: string; multiplier?: number; value: number; detail?: string };

export type WhyRow = {
  player: string;
  headshotUrl?: string | null;
  side?: string;
  team: string | null;
  marketType: string;
  strike: number | null;
  modelProb: number;
  marketProb: number;
  feeCents: number;
  edgeCentsNet: number;
  kelly: number;
  reason: unknown;
};

/**
 * Section 9.9 -- the feature that makes the tool worth using over guessing.
 *
 * Every number is read from the STORED signal, never recomputed. Recomputing at read
 * time would answer "what does the model think now", when the question the panel
 * exists for is "what did it think when this fired".
 */
export function WhyPanel({
  row,
  onClose,
}: {
  row: WhyRow | null;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!row) return null;

  type Claim = { kind: string; claim: string; evidence: string };
  const reason = (row.reason ?? {}) as {
    explain?: Step[];
    percentiles?: Record<string, number>;
    mean?: number;
    p_over?: number;
    rationale?: Claim[];
  };
  const side = row.side ?? "yes";
  const chain = reason.explain ?? [];
  const gross = (row.modelProb - row.marketProb) * 100;
  const feeShare = gross > 0 ? Math.min(row.feeCents / gross, 1) : 1;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-[2px]"
      onClick={onClose}
    >
      {/* The brand's action panel: steel, per "odds board on paper, bet slip on
          steel". Data surfaces inside it revert to paper cards. */}
      <aside
        className="flex h-full w-full max-w-2xl flex-col overflow-y-auto bg-steel-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-white/10 bg-steel-900 px-5 py-4">
          <div className="flex items-center gap-3">
            <PlayerAvatar name={row.player} url={row.headshotUrl} size={40} />
            <div>
            <h2 className="display text-[17px] leading-none text-white">
              {row.player}
              {row.team && <span className="ml-2 text-xs font-normal text-steel-300">{row.team}</span>}
            </h2>
            <p className="mt-1 flex items-center gap-2 text-xs text-steel-300">
              <span>
                {row.marketType}
                {row.strike !== null && (
                  <> · strike <span className="tnum text-white">{row.strike}</span></>
                )}
              </span>
              <span className={`display rounded-[3px] px-1.5 py-[2px] text-[10px] tracking-[0.1em] ${
                side === "yes" ? "bg-steel text-white" : "bg-white text-steel-900"
              }`}>
                {side === "yes" ? "over" : "under"}
              </span>
            </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-white/20 px-2 py-1 text-[10px] uppercase tracking-widest text-steel-300 transition-colors hover:border-white/40 hover:text-white"
          >
            esc
          </button>
        </header>

        <div className="space-y-6 px-5 py-5">
          {reason.rationale && reason.rationale.length > 0 && (
            <Section
              title="Why"
              note="Each claim carries the number behind it, so you can disagree with a specific one rather than the whole thing."
            >
              <ul className="space-y-2">
                {reason.rationale.map((c, i) => (
                  <li
                    key={i}
                    className={`rounded border-l-2 bg-white/[0.04] py-2 pl-3 pr-3 ${
                      c.kind === "caveat"
                        ? "border-l-[#E0B066]"
                        : c.kind === "sensitivity"
                          ? "border-l-white/30"
                          : c.kind === "driver"
                            ? "border-l-steel-300"
                            : "border-l-white/15"
                    }`}
                  >
                    <p className="text-[12.5px] leading-snug text-white">{c.claim}</p>
                    <p className="mt-1 text-[11px] leading-relaxed text-steel-400">
                      {c.evidence}
                    </p>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex flex-wrap gap-3">
                <Key swatch="bg-steel-300" label="what drives it" />
                <Key swatch="bg-white/30" label="what would change it" />
                <Key swatch="bg-[#E0B066]" label="reason to disagree" />
              </div>
            </Section>
          )}

          <Section
            title="Volume chain"
            note="Each adjustment is a named multiplier applied to the baseline."
          >
            {chain.length === 0 ? (
              <p className="text-xs text-steel-400">No adjustment chain stored.</p>
            ) : (
              <ol className="overflow-hidden rounded border border-white/10">
                {chain.map((s, i) => {
                  const isBase = i === 0;
                  return (
                    <li
                      key={i}
                      className="flex items-baseline justify-between gap-3 border-b border-white/[0.07] bg-white/[0.04] px-3 py-2 last:border-0"
                    >
                      <span className="min-w-0 text-[13px]">
                        <span className={isBase ? "text-steel-300" : "text-white"}>{s.step}</span>
                        {s.detail && (
                          <span className="ml-2 text-[11px] text-steel-400">{s.detail}</span>
                        )}
                      </span>
                      <span className="tnum shrink-0 text-xs">
                        {s.multiplier !== undefined && (
                          <span
                            className={
                              s.multiplier > 1
                                ? "mr-2 text-steel-300"
                                : s.multiplier < 1
                                  ? "mr-2 text-[#E08A66]"
                                  : "mr-2 text-steel-400"
                            }
                          >
                            {s.multiplier > 1 ? "↑" : s.multiplier < 1 ? "↓" : "·"}
                            {s.multiplier.toFixed(3)}
                          </span>
                        )}
                        <span className="text-white">{s.value.toFixed(2)}</span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
          </Section>

          {/* An empty object is truthy, so `reason.percentiles &&` let anytime-TD
              signals through -- they are a binary outcome and store no distribution,
              which rendered a chart placeholder above five dashes. A distribution
              section is meaningless for a yes/no market, so it is omitted. */}
          {reason.percentiles && Object.keys(reason.percentiles).length > 0 && (
            <Section
              title="Simulated distribution"
              note="20,000 Monte Carlo draws. Efficiency bootstrapped from this player's own outcomes, so the right tail is preserved."
            >
              <div className="rounded border border-white/10 bg-paper p-2">
                <DistributionChart
                  percentiles={reason.percentiles}
                  strike={row.strike}
                  mean={reason.mean}
                />
              </div>
              <div className="mt-3 grid grid-cols-5 gap-1.5">
                {["10", "25", "50", "75", "90"].map((p) => (
                  <div key={p} className="rounded border border-white/10 bg-white/[0.04] py-1.5 text-center">
                    <div className="text-[10px] text-steel-400">p{p}</div>
                    <div className="tnum text-[13px] text-white">
                      {reason.percentiles![p]?.toFixed(0) ?? "—"}
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          <Section title="Edge arithmetic">
            <dl className="overflow-hidden rounded border border-white/10">
              {/* Labelled by SIDE. The stored modelProb is the probability of the
                  chosen side, so calling it "model probability" next to an over
                  distribution reads as a contradiction on every NO row. */}
              <KV
                k={`Model P(${side === "yes" ? "over" : "under"} ${row.strike ?? ""})`}
                v={pct(row.modelProb)}
              />
              {reason.p_over !== undefined && side === "no" && (
                <KV k="…which is P(over)" v={pct(reason.p_over)} tone="text-steel-400" />
              )}
              <KV k={`Market ask (${side})`} v={priceCents(row.marketProb)} />
              <KV k="Gross edge" v={signedCents(gross)} />
              <KV k="Fee" v={`−${row.feeCents.toFixed(2)}¢`} tone="text-[#E0B066]" />
              <KV
                k="Net edge"
                v={signedCents(row.edgeCentsNet)}
                tone={row.edgeCentsNet > 0 ? "text-steel-300" : "text-[#E08A66]"}
                strong
              />
              <KV k="Kelly fraction" v={`${(row.kelly * 100).toFixed(1)}%`} />
            </dl>

            {gross > 0 && (
              <div className="mt-3">
                <div className="mb-1 flex justify-between text-[10px] text-steel-400">
                  <span>fee as share of gross edge</span>
                  <span className="tnum">{(feeShare * 100).toFixed(0)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-[#E0B066]"
                    style={{ width: `${feeShare * 100}%` }}
                  />
                </div>
              </div>
            )}

            <p className="mt-3 text-[11px] leading-relaxed text-steel-400">
              The fee is charged on entry and peaks at mid-price — 1.75¢ at 50¢. An
              edge smaller than the fee is a losing bet however good the model looks,
              which is why the board sorts on net rather than gross.
            </p>
          </Section>
        </div>
      </aside>
    </div>
  );
}

function Key({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2 w-0.5 rounded-full ${swatch}`} aria-hidden="true" />
      <span className="text-[10px] text-steel-400">{label}</span>
    </span>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="display text-[12px] tracking-[0.12em] text-steel-300">{title}</h3>
      {note && (
        <p className="mb-2 mt-1 text-[11px] leading-relaxed text-steel-400">{note}</p>
      )}
      <div className={note ? "" : "mt-2"}>{children}</div>
    </section>
  );
}

function KV({
  k,
  v,
  tone,
  strong,
}: {
  k: string;
  v: string;
  tone?: string;
  strong?: boolean;
}) {
  return (
    <div
      className={`flex items-baseline justify-between gap-3 px-3 py-2 ${
        strong ? "border-t border-white/20 bg-white/[0.09]" : "bg-white/[0.04]"
      }`}
    >
      <dt className="text-[13px] text-steel-300">{k}</dt>
      <dd
        className={`tnum text-xs ${tone ?? "text-white"} ${strong ? "text-[14px] font-semibold" : ""}`}
      >
        {v}
      </dd>
    </div>
  );
}
