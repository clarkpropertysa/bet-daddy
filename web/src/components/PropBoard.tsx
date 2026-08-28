"use client";

import { useMemo, useState } from "react";
import { Tier, type TierName } from "@/components/Tier";
import { WhyPanel } from "@/components/WhyPanel";
import { Empty } from "@/components/Empty";
import { edgeTone, pct, priceCents, signedCents } from "@/lib/format";

export type Row = {
  signalId: string;
  marketTicker: string;
  player: string;
  position: string | null;
  team: string | null;
  marketType: string;
  strike: number | null;
  modelProb: number;
  marketProb: number;
  feeCents: number;
  edgeCentsNet: number;
  kelly: number;
  tier: TierName;
  sampleN: number;
  reason: unknown;
};

export function PropBoard({ rows }: { rows: Row[] }) {
  const [market, setMarket] = useState("all");
  const [minEdge, setMinEdge] = useState(0);
  // Off by default: hiding unvalidated signals is how a tool quietly implies
  // everything shown has a track record.
  const [validatedOnly, setValidatedOnly] = useState(false);
  const [active, setActive] = useState<Row | null>(null);

  const markets = useMemo(
    () => ["all", ...Array.from(new Set(rows.map((r) => r.marketType))).sort()],
    [rows],
  );

  const filtered = useMemo(
    () =>
      rows.filter(
        (r) =>
          (market === "all" || r.marketType === market) &&
          r.edgeCentsNet >= minEdge &&
          (!validatedOnly || r.tier === "VALIDATED"),
      ),
    [rows, market, minEdge, validatedOnly],
  );

  if (rows.length === 0) {
    return (
      <Empty
        title="No signals yet"
        source="Signal table (Neon)"
        hint="Signals appear once the projection job has run against archived Kalshi prices. The archiver is collecting; no projections have been written yet."
      />
    );
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs">
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-200"
        >
          {markets.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-zinc-400">
          min net edge
          <input
            type="number" step="0.5" value={minEdge}
            onChange={(e) => setMinEdge(Number(e.target.value))}
            className="w-16 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-200"
          />
          ¢
        </label>
        <label className="flex items-center gap-2 text-zinc-400">
          <input
            type="checkbox" checked={validatedOnly}
            onChange={(e) => setValidatedOnly(e.target.checked)}
          />
          validated only
        </label>
        <span className="ml-auto text-zinc-500">
          {filtered.length} of {rows.length}
        </span>
      </div>

      <div className="overflow-x-auto rounded border border-zinc-800">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="bg-zinc-900/70 text-left text-[11px] uppercase tracking-wide text-zinc-500">
            <tr>
              <Th>Player</Th><Th>Market</Th><Th className="text-right">Strike</Th>
              <Th className="text-right">Ask</Th><Th className="text-right">Model</Th>
              <Th className="text-right">Fee</Th><Th className="text-right">Net edge</Th>
              <Th className="text-right">Kelly</Th><Th>Confidence</Th><Th />
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/70">
            {filtered.map((r) => (
              <tr key={r.signalId} className="hover:bg-zinc-900/40">
                <Td>
                  <span className="text-zinc-100">{r.player}</span>
                  {r.team && <span className="ml-1.5 text-xs text-zinc-500">{r.team}</span>}
                </Td>
                <Td className="text-zinc-400">{r.marketType}</Td>
                <Td className="text-right font-mono text-zinc-300">{r.strike ?? "—"}</Td>
                <Td className="text-right font-mono text-zinc-300">{priceCents(r.marketProb)}</Td>
                <Td className="text-right font-mono text-zinc-300">{pct(r.modelProb)}</Td>
                <Td className="text-right font-mono text-amber-500/80">
                  −{r.feeCents.toFixed(2)}¢
                </Td>
                <Td className={`text-right font-mono font-semibold ${edgeTone(r.edgeCentsNet)}`}>
                  {signedCents(r.edgeCentsNet)}
                </Td>
                <Td className="text-right font-mono text-zinc-400">
                  {(r.kelly * 100).toFixed(1)}%
                </Td>
                <Td><Tier tier={r.tier} n={r.sampleN} /></Td>
                <Td className="text-right">
                  <button
                    onClick={() => setActive(r)}
                    className="text-xs text-zinc-500 underline-offset-2 hover:text-zinc-200 hover:underline"
                  >
                    why
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && (
        <p className="mt-3 text-xs text-zinc-500">
          No rows match these filters. {validatedOnly && "No signal has earned VALIDATED yet — that requires 200 settled contracts with positive closing line value."}
        </p>
      )}

      <WhyPanel open={active !== null} onClose={() => setActive(null)} row={active} />
    </>
  );
}

function Th({ children, className = "" }: { children?: React.ReactNode; className?: string }) {
  return <th className={`px-3 py-2 font-medium ${className}`}>{children}</th>;
}
function Td({ children, className = "" }: { children?: React.ReactNode; className?: string }) {
  return <td className={`px-3 py-2 ${className}`}>{children}</td>;
}
