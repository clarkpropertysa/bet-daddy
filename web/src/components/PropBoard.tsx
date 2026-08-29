"use client";

import { useMemo, useState } from "react";
import { Empty } from "@/components/Empty";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Tier, type TierName } from "@/components/Tier";
import { WhyPanel, type WhyRow } from "@/components/WhyPanel";
import { edgeGlyph, pct, priceCents, signedCents } from "@/lib/format";

export type Row = WhyRow & {
  signalId: string;
  marketTicker: string;
  position: string | null;
  tier: TierName;
  sampleN: number;
  implausible: boolean;
  modelVersion: string;
  headshotUrl: string | null;
};

type SortKey = "edge" | "player" | "model" | "ask" | "kelly";

export function PropBoard({ rows }: { rows: Row[] }) {
  const [market, setMarket] = useState("all");
  const [minEdge, setMinEdge] = useState(0);
  // OFF by default: defaulting this on would hide every unvalidated signal and
  // quietly imply that everything visible has a track record.
  const [validatedOnly, setValidatedOnly] = useState(false);
  const [q, setQ] = useState("");
  // ON by default. A +91c edge is not an opportunity, it is the model missing
  // something the market knows. Showing those unflagged at the top of a board
  // sorted by edge would make the tool look confident precisely where it is broken.
  const [hideImplausible, setHideImplausible] = useState(true);
  const [sort, setSort] = useState<SortKey>("edge");
  const [asc, setAsc] = useState(false);
  const [active, setActive] = useState<Row | null>(null);

  const markets = useMemo(
    () => ["all", ...Array.from(new Set(rows.map((r) => r.marketType))).sort()],
    [rows],
  );

  const filtered = useMemo(() => {
    const out = rows.filter(
      (r) =>
        (market === "all" || r.marketType === market) &&
        r.edgeCentsNet >= minEdge &&
        (!validatedOnly || r.tier === "VALIDATED") &&
        (!hideImplausible || !r.implausible) &&
        (q === "" || r.player.toLowerCase().includes(q.toLowerCase())),
    );
    const pick = (r: Row) =>
      sort === "player" ? r.player
      : sort === "model" ? r.modelProb
      : sort === "ask" ? r.marketProb
      : sort === "kelly" ? r.kelly
      : r.edgeCentsNet;
    return out.sort((a, b) => {
      const x = pick(a), y = pick(b);
      const c = typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number);
      return asc ? c : -c;
    });
  }, [rows, market, minEdge, validatedOnly, hideImplausible, q, sort, asc]);

  const toggle = (k: SortKey) => {
    if (sort === k) setAsc(!asc);
    else { setSort(k); setAsc(false); }
  };

  if (rows.length === 0) {
    return (
      <Empty
        title="No signals yet"
        source="Signal (Neon)"
        hint="Signals appear once the projection job runs against archived Kalshi prices. The archiver is collecting; no projections have been written."
      />
    );
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="filter player…"
          className="w-44 rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-3 focus:border-line-strong focus:outline-none"
        />
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-xs text-ink focus:border-line-strong focus:outline-none"
        >
          {markets.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <label className="flex items-center gap-1.5 rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-xs text-ink-2">
          min edge
          <input
            type="number" step="0.5" value={minEdge}
            onChange={(e) => setMinEdge(Number(e.target.value))}
            className="w-12 bg-transparent text-right font-mono text-ink focus:outline-none"
          />
          ¢
        </label>
        <button
          onClick={() => setHideImplausible(!hideImplausible)}
          title="Hide signals where the model disagrees with the market by more than 50 points — almost always a model failure, not an edge."
          className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
            hideImplausible
              ? "border-line bg-surface-1 text-ink-2 hover:border-line-strong"
              : "border-neg/40 bg-neg/10 text-neg"
          }`}
        >
          {hideImplausible ? "implausible hidden" : "implausible shown"}
        </button>
        <button
          onClick={() => setValidatedOnly(!validatedOnly)}
          className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
            validatedOnly
              ? "border-pos/40 bg-pos/10 text-pos"
              : "border-line bg-surface-1 text-ink-2 hover:border-line-strong"
          }`}
        >
          validated only
        </button>
        <span className="ml-auto font-mono text-[11px] text-ink-3">
          {filtered.length}/{rows.length}
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[880px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line bg-surface-2 text-[10px] uppercase tracking-[0.06em] text-ink-3">
              <Th onClick={() => toggle("player")} active={sort === "player"} asc={asc}>Player</Th>
              <Th>Market</Th>
              <Th align="right">Strike</Th>
              <Th align="right" onClick={() => toggle("ask")} active={sort === "ask"} asc={asc}>Ask</Th>
              <Th align="right" onClick={() => toggle("model")} active={sort === "model"} asc={asc}>Model</Th>
              <Th align="right">Fee</Th>
              <Th align="right" onClick={() => toggle("edge")} active={sort === "edge"} asc={asc}>Net edge</Th>
              <Th align="right" onClick={() => toggle("kelly")} active={sort === "kelly"} asc={asc}>Kelly</Th>
              <Th>Confidence</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr
                key={r.signalId}
                onClick={() => setActive(r)}
                className="cursor-pointer border-b border-line/60 transition-colors last:border-0 hover:bg-surface-2"
              >
                <Td>
                  <span className="flex items-center gap-2.5">
                    <PlayerAvatar name={r.player} url={r.headshotUrl} size={28} />
                    <span className="min-w-0">
                      <span className="block truncate font-medium leading-tight text-ink">
                        {r.player}
                      </span>
                      <span className="block text-[10px] leading-tight text-ink-3">
                        {[r.position, r.team].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </span>
                </Td>
                <Td className="text-ink-2">{r.marketType}</Td>
                <Td align="right" mono>{r.strike ?? "—"}</Td>
                <Td align="right" mono>{priceCents(r.marketProb)}</Td>
                <Td align="right" mono>{pct(r.modelProb)}</Td>
                <Td align="right" mono className="text-warn/80">−{r.feeCents.toFixed(2)}¢</Td>
                <Td align="right" mono className={`font-semibold ${
                  r.implausible ? "text-ink-3" : r.edgeCentsNet > 0 ? "text-pos" : "text-neg"
                }`}>
                  {/* glyph + explicit sign: colour alone fails protanopia on this pair */}
                  <span aria-hidden="true" className="mr-0.5">{edgeGlyph(r.edgeCentsNet)}</span>
                  {signedCents(r.edgeCentsNet)}
                  {r.implausible && (
                    <span
                      title="Model disagrees with the market by >50 points. Treat as a model failure, not an edge."
                      className="ml-1.5 rounded border border-neg/40 bg-neg/10 px-1 py-px text-[9px] font-normal text-neg"
                    >
                      ?
                    </span>
                  )}
                </Td>
                <Td align="right" mono className="text-ink-2">{(r.kelly * 100).toFixed(1)}%</Td>
                <Td><Tier tier={r.tier} n={r.sampleN} /></Td>
                <Td align="right">
                  <span className="text-[11px] text-ink-3">why →</span>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && (
        <p className="mt-3 text-[11px] text-ink-3">
          Nothing matches these filters.
          {hideImplausible && " Implausible signals are hidden — the preseason smoke model disagrees wildly with the market on most of these."}
          {validatedOnly && " No signal has earned VALIDATED yet — that needs 200 settled contracts with positive closing line value."}
        </p>
      )}

      <WhyPanel row={active} onClose={() => setActive(null)} />
    </>
  );
}

function Th({
  children, align = "left", onClick, active, asc,
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  onClick?: () => void;
  active?: boolean;
  asc?: boolean;
}) {
  return (
    <th
      onClick={onClick}
      className={`px-3 py-2 font-medium ${align === "right" ? "text-right" : "text-left"} ${
        onClick ? "cursor-pointer select-none hover:text-ink-2" : ""
      } ${active ? "text-ink" : ""}`}
    >
      {children}
      {active && <span className="ml-1">{asc ? "↑" : "↓"}</span>}
    </th>
  );
}

function Td({
  children, align = "left", mono, className = "",
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  mono?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`px-3 py-2 ${align === "right" ? "text-right" : "text-left"} ${
        mono ? "font-mono text-xs" : ""
      } ${className}`}
    >
      {children}
    </td>
  );
}
