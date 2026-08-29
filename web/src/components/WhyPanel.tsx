"use client";

import { useEffect } from "react";
import { DistributionChart } from "@/components/DistributionChart";
import { pct, priceCents, signedCents } from "@/lib/format";

type Step = { step: string; multiplier?: number; value: number; detail?: string };

export type WhyRow = {
  player: string;
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

  const reason = (row.reason ?? {}) as {
    explain?: Step[];
    percentiles?: Record<string, number>;
    mean?: number;
  };
  const chain = reason.explain ?? [];
  const gross = (row.modelProb - row.marketProb) * 100;
  const feeShare = gross > 0 ? Math.min(row.feeCents / gross, 1) : 1;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <aside
        className="flex h-full w-full max-w-2xl flex-col overflow-y-auto border-l border-line-strong bg-surface-1 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-line bg-surface-1/95 px-5 py-4 backdrop-blur">
          <div>
            <h2 className="text-[15px] font-semibold tracking-tight text-ink">
              {row.player}
              {row.team && <span className="ml-2 text-xs font-normal text-ink-3">{row.team}</span>}
            </h2>
            <p className="mt-0.5 text-xs text-ink-3">
              {row.marketType}
              {row.strike !== null && (
                <> · strike <span className="font-mono text-ink-2">{row.strike}</span></>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-line px-2 py-1 text-[11px] text-ink-3 transition-colors hover:border-line-strong hover:text-ink"
          >
            esc
          </button>
        </header>

        <div className="space-y-6 px-5 py-5">
          <Section
            title="Volume chain"
            note="Each adjustment is a named multiplier applied to the baseline."
          >
            {chain.length === 0 ? (
              <p className="text-xs text-ink-3">No adjustment chain stored.</p>
            ) : (
              <ol className="space-y-px overflow-hidden rounded border border-line">
                {chain.map((s, i) => {
                  const isBase = i === 0;
                  return (
                    <li
                      key={i}
                      className="flex items-baseline justify-between gap-3 bg-surface-2 px-3 py-2"
                    >
                      <span className="min-w-0 text-[13px]">
                        <span className={isBase ? "text-ink-2" : "text-ink"}>{s.step}</span>
                        {s.detail && (
                          <span className="ml-2 text-[11px] text-ink-3">{s.detail}</span>
                        )}
                      </span>
                      <span className="shrink-0 font-mono text-xs">
                        {s.multiplier !== undefined && (
                          <span
                            className={
                              s.multiplier > 1
                                ? "mr-2 text-pos"
                                : s.multiplier < 1
                                  ? "mr-2 text-neg"
                                  : "mr-2 text-ink-3"
                            }
                          >
                            {s.multiplier > 1 ? "↑" : s.multiplier < 1 ? "↓" : "·"}
                            {s.multiplier.toFixed(3)}
                          </span>
                        )}
                        <span className="text-ink">{s.value.toFixed(2)}</span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
          </Section>

          {reason.percentiles && (
            <Section
              title="Simulated distribution"
              note="20,000 Monte Carlo draws. Efficiency bootstrapped from this player's own outcomes, so the right tail is preserved."
            >
              <DistributionChart
                percentiles={reason.percentiles}
                strike={row.strike}
                mean={reason.mean}
              />
              <div className="mt-3 grid grid-cols-5 gap-1.5">
                {["10", "25", "50", "75", "90"].map((p) => (
                  <div key={p} className="rounded border border-line bg-surface-2 py-1.5 text-center">
                    <div className="text-[10px] text-ink-3">p{p}</div>
                    <div className="font-mono text-[13px] text-ink">
                      {reason.percentiles![p]?.toFixed(0) ?? "—"}
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          <Section title="Edge arithmetic">
            <dl className="overflow-hidden rounded border border-line">
              <KV k="Model probability" v={pct(row.modelProb)} />
              <KV k="Kalshi ask" v={priceCents(row.marketProb)} />
              <KV k="Gross edge" v={signedCents(gross)} />
              <KV k="Kalshi fee" v={`−${row.feeCents.toFixed(2)}¢`} tone="text-warn" />
              <KV
                k="Net edge"
                v={signedCents(row.edgeCentsNet)}
                tone={row.edgeCentsNet > 0 ? "text-pos" : "text-neg"}
                strong
              />
              <KV k="Kelly fraction" v={`${(row.kelly * 100).toFixed(1)}%`} />
            </dl>

            {gross > 0 && (
              <div className="mt-3">
                <div className="mb-1 flex justify-between text-[10px] text-ink-3">
                  <span>fee as share of gross edge</span>
                  <span className="font-mono">{(feeShare * 100).toFixed(0)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                  <div
                    className="h-full rounded-full bg-warn"
                    style={{ width: `${feeShare * 100}%` }}
                  />
                </div>
              </div>
            )}

            <p className="mt-3 text-[11px] leading-relaxed text-ink-3">
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
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-2">
        {title}
      </h3>
      {note && <p className="mb-2 mt-0.5 text-[11px] leading-relaxed text-ink-3">{note}</p>}
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
        strong ? "border-t border-line-strong bg-surface-3" : "bg-surface-2"
      }`}
    >
      <dt className="text-[13px] text-ink-2">{k}</dt>
      <dd
        className={`font-mono text-xs ${tone ?? "text-ink"} ${strong ? "text-[13px] font-semibold" : ""}`}
      >
        {v}
      </dd>
    </div>
  );
}
