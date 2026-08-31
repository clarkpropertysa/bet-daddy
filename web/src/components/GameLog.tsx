"use client";

import { useMemo, useState } from "react";
import { Sparkline } from "@/components/Sparkline";
import type { GameLogRow } from "@/lib/queries";

/** Which columns matter depends on the position. A quarterback's target share is noise. */
type Shape = "receiving" | "rushing" | "passing";

function shapeFor(pos: string | null, rows: GameLogRow[]): Shape {
  if (pos === "QB") return "passing";
  if (pos === "RB" || pos === "FB") return "rushing";
  if (pos === "WR" || pos === "TE") return "receiving";
  // Unknown position: let the data decide rather than guessing from a label.
  const tot = rows.reduce(
    (a, r) => ({
      rec: a.rec + (r.targets ?? 0),
      rush: a.rush + (r.carries ?? 0),
      pass: a.pass + (r.passingYards ?? 0),
    }),
    { rec: 0, rush: 0, pass: 0 },
  );
  if (tot.pass > 200) return "passing";
  return tot.rush > tot.rec ? "rushing" : "receiving";
}

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
const num = (v: number | null) => (v === null || v === undefined ? "—" : String(v));
const yds = (v: number | null) =>
  v === null || v === undefined ? "—" : String(Math.round(v));

export function GameLog({
  rows,
  position,
}: {
  rows: GameLogRow[];
  position: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const shape = useMemo(() => shapeFor(position, rows), [position, rows]);

  if (rows.length === 0) return null;

  const season = rows[0].season;
  const shown = expanded ? rows : rows.slice(0, 10);

  // Oldest-first for the trend line: a sparkline that reads right-to-left is a lie
  // about direction.
  const chron = [...rows].reverse();
  const trendKey = shape === "rushing" ? "carryShare" : "targetShare";
  const trend = chron
    .map((r) => (shape === "passing" ? r.passingYards : r[trendKey]))
    .filter((v): v is number => typeof v === "number");

  const headers =
    shape === "passing"
      ? ["Wk", "Opp", "Snap%", "Yds", "TD", "INT"]
      : shape === "rushing"
        ? ["Wk", "Opp", "Snap%", "Att", "Yds", "TD", "Tgt", "Car%"]
        : ["Wk", "Opp", "Snap%", "Tgt", "Rec", "Yds", "TD", "Tgt%"];

  return (
    <section className="rounded border border-line bg-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <h2 className="display text-[14px] text-ink">Game log</h2>
          {/* The season is stated, never implied. A 2025 line for a player who changed
              team describes a job he no longer holds. */}
          <p className="eyebrow mt-0.5">{season} regular season · {rows.length} games</p>
        </div>
        {trend.length > 1 && (
          <div className="flex items-center gap-2">
            <span className="eyebrow">
              {shape === "passing" ? "pass yds" : shape === "rushing" ? "carry share" : "target share"}
            </span>
            <Sparkline values={trend} width={80} height={20} />
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-[12px]">
          <thead>
            <tr className="border-b border-line text-left">
              {headers.map((h) => (
                <th key={h} className="px-3 py-2 font-medium text-ink-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.gameId} className="border-b border-line-2 last:border-0">
                <td className="px-3 py-2 text-ink-2">{r.week}</td>
                <td className="px-3 py-2 text-ink-2">{r.opponent ?? "—"}</td>
                <td className="px-3 py-2 text-ink-2">{pct(r.offensePct)}</td>
                {shape === "passing" && (
                  <>
                    <td className="px-3 py-2 font-medium text-ink">{yds(r.passingYards)}</td>
                    <td className="px-3 py-2 text-ink-2">{num(r.passingTds)}</td>
                    <td className="px-3 py-2 text-ink-2">{num(r.interceptions)}</td>
                  </>
                )}
                {shape === "rushing" && (
                  <>
                    <td className="px-3 py-2 text-ink-2">{num(r.carries)}</td>
                    <td className="px-3 py-2 font-medium text-ink">{yds(r.rushingYards)}</td>
                    <td className="px-3 py-2 text-ink-2">{num(r.rushingTds)}</td>
                    <td className="px-3 py-2 text-ink-2">{num(r.targets)}</td>
                    <td className="px-3 py-2 text-ink-2">{pct(r.carryShare)}</td>
                  </>
                )}
                {shape === "receiving" && (
                  <>
                    <td className="px-3 py-2 text-ink-2">{num(r.targets)}</td>
                    <td className="px-3 py-2 text-ink-2">{num(r.receptions)}</td>
                    <td className="px-3 py-2 font-medium text-ink">{yds(r.receivingYards)}</td>
                    <td className="px-3 py-2 text-ink-2">{num(r.receivingTds)}</td>
                    <td className="px-3 py-2 text-ink-2">{pct(r.targetShare)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > 10 && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full border-t border-line px-4 py-2 text-[11px] text-steel hover:bg-steel-100"
        >
          {expanded ? "Show fewer" : `Show all ${rows.length} games`}
        </button>
      )}
    </section>
  );
}
