"use client";

import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import type { PlayerRow } from "@/lib/queries";

const POSITIONS = ["all", "QB", "RB", "WR", "TE"];

export function PlayerGrid({ players }: { players: PlayerRow[] }) {
  const [pos, setPos] = useState("all");
  const [q, setQ] = useState("");
  // Starters only by default. The full depth chart is mostly players who will
  // never draw a priceable snap.
  const [startersOnly, setStartersOnly] = useState(true);

  const shown = useMemo(
    () =>
      players.filter(
        (p) =>
          (pos === "all" || p.depthPos === pos) &&
          (!startersOnly || p.isStarter) &&
          (q === "" || p.fullName.toLowerCase().includes(q.toLowerCase())),
      ),
    [players, pos, q, startersOnly],
  );

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="filter player…"
          className="w-44 rounded border border-line-2 bg-card px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-3 focus:border-steel focus:outline-none"
        />
        <div className="flex gap-0.5 rounded border border-line-2 bg-card p-0.5">
          {POSITIONS.map((p) => (
            <button
              key={p}
              onClick={() => setPos(p)}
              className={`rounded-[2px] px-2 py-1 text-xs transition-colors ${
                pos === p ? "bg-steel text-white" : "text-ink-2 hover:bg-steel-100"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        <button
          onClick={() => setStartersOnly(!startersOnly)}
          className={`rounded border px-2.5 py-1.5 text-xs transition-colors ${
            startersOnly
              ? "border-steel bg-steel-100 text-steel-800"
              : "border-line-2 bg-card text-ink-2 hover:border-steel"
          }`}
        >
          starters only
        </button>
        <span className="eyebrow tnum ml-auto">
          {shown.length}/{players.length}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {shown.map((p) => (
          <div
            key={p.id}
            className={`flex items-center gap-2.5 rounded border bg-card p-2.5 transition-colors hover:border-steel hover:bg-steel-100 ${
              p.promotedFor ? "border-warn/50" : "border-line"
            }`}
          >
            <PlayerAvatar name={p.fullName} url={p.headshotUrl} size={36} />
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium leading-tight text-ink">
                {p.fullName}
              </div>
              <div className="eyebrow leading-tight">
                {[p.depthPos && `${p.depthPos}${p.depthRank ?? ""}`, p.team]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
              {/* A backup on the board without explanation looks like a bug. */}
              {p.promotedFor && (
                <div className="mt-0.5 truncate text-[9px] text-warn">
                  in for {p.promotedFor}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {shown.length === 0 && (
        <p className="mt-3 text-[11.5px] text-ink-2">
          Nothing matches. {startersOnly && "Only starters are shown — turn off “starters only” for the full depth chart."}
        </p>
      )}
    </>
  );
}
