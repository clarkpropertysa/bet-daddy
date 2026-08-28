"use client";

import { useState } from "react";
import { priceCents, pct, signedCents } from "@/lib/format";

type Step = { step: string; multiplier?: number; value: number; detail?: string };

/**
 * Section 9.9 -- the feature that makes the tool worth using over guessing.
 * Shows the full chain: baseline, each named adjustment, the simulated
 * distribution, the market price, the fee, and the net edge.
 *
 * Every number here comes from the stored signal, not a recomputation. Recomputing
 * at read time would show what the model thinks NOW, not what it thought when the
 * signal fired -- which is the question the panel exists to answer.
 */
export function WhyPanel({
  open,
  onClose,
  row,
}: {
  open: boolean;
  onClose: () => void;
  row: {
    player: string;
    marketType: string;
    strike: number | null;
    modelProb: number;
    marketProb: number;
    feeCents: number;
    edgeCentsNet: number;
    reason: unknown;
  } | null;
}) {
  if (!open || !row) return null;

  const reason = (row.reason ?? {}) as {
    explain?: Step[];
    percentiles?: Record<string, number>;
    mean?: number;
    adjustments?: Step[];
  };
  const chain = reason.explain ?? reason.adjustments ?? [];
  const gross = (row.modelProb - row.marketProb) * 100;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <aside
        className="h-full w-full max-w-xl overflow-y-auto border-l border-zinc-800 bg-zinc-950 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-zinc-100">{row.player}</h2>
            <p className="text-xs text-zinc-500">
              {row.marketType} {row.strike !== null ? `· strike ${row.strike}` : ""}
            </p>
          </div>
          <button onClick={onClose} className="text-xs text-zinc-500 hover:text-zinc-200">
            close
          </button>
        </div>

        <section className="mt-5">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
            Volume chain
          </h3>
          {chain.length === 0 ? (
            <p className="mt-2 text-xs text-zinc-600">
              No adjustment chain stored for this signal.
            </p>
          ) : (
            <ol className="mt-2 space-y-1">
              {chain.map((s, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="text-zinc-400">
                    {s.step}
                    {s.detail && (
                      <span className="ml-2 text-xs text-zinc-600">{s.detail}</span>
                    )}
                  </span>
                  <span className="font-mono text-xs text-zinc-300">
                    {s.multiplier !== undefined && (
                      <span className="mr-2 text-zinc-500">×{s.multiplier.toFixed(3)}</span>
                    )}
                    {s.value.toFixed(2)}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>

        {reason.percentiles && (
          <section className="mt-5">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
              Simulated distribution
            </h3>
            <div className="mt-2 grid grid-cols-5 gap-2 text-center">
              {["10", "25", "50", "75", "90"].map((p) => (
                <div key={p} className="rounded bg-zinc-900 py-2">
                  <div className="text-[10px] text-zinc-500">p{p}</div>
                  <div className="font-mono text-sm text-zinc-200">
                    {reason.percentiles![p]?.toFixed(0) ?? "—"}
                  </div>
                </div>
              ))}
            </div>
            {row.strike !== null && (
              <p className="mt-2 text-xs text-zinc-500">
                Strike {row.strike} sits at the{" "}
                {reason.percentiles["50"] !== undefined &&
                row.strike > reason.percentiles["50"]
                  ? "upper"
                  : "lower"}{" "}
                half of the simulated outcomes.
              </p>
            )}
          </section>
        )}

        <section className="mt-5">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
            Edge arithmetic
          </h3>
          <dl className="mt-2 space-y-1 text-sm">
            <Row k="Model probability" v={pct(row.modelProb)} />
            <Row k="Market ask" v={priceCents(row.marketProb)} />
            <Row k="Gross edge" v={signedCents(gross)} />
            <Row k="Kalshi fee" v={`−${row.feeCents.toFixed(2)}¢`} tone="text-amber-400" />
            <div className="mt-1 border-t border-zinc-800 pt-1">
              <Row
                k="Net edge"
                v={signedCents(row.edgeCentsNet)}
                tone={row.edgeCentsNet > 0 ? "text-emerald-400" : "text-red-400"}
                bold
              />
            </div>
          </dl>
          <p className="mt-3 text-xs text-zinc-600">
            The fee is charged on entry and is largest at mid-price (1.75¢ at 50¢).
            An edge smaller than the fee is a losing bet, however good the model looks.
          </p>
        </section>
      </aside>
    </div>
  );
}

function Row({ k, v, tone, bold }: { k: string; v: string; tone?: string; bold?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-zinc-400">{k}</dt>
      <dd className={`font-mono text-xs ${tone ?? "text-zinc-200"} ${bold ? "font-bold" : ""}`}>
        {v}
      </dd>
    </div>
  );
}
