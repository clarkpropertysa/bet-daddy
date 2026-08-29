"use client";

import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import type { PlayerRow } from "@/lib/queries";

const POSITIONS = ["all", "QB", "RB", "WR", "TE"];

export function PlayerGrid({ players }: { players: PlayerRow[] }) {
  const [pos, setPos] = useState("all");
  const [q, setQ] = useState("");

  const shown = useMemo(
    () =>
      players.filter(
        (p) =>
          (pos === "all" || p.position === pos) &&
          (q === "" || p.fullName.toLowerCase().includes(q.toLowerCase())),
      ),
    [players, pos, q],
  );

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="filter player…"
          className="w-48 rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-3 focus:border-line-strong focus:outline-none"
        />
        <div className="flex gap-0.5 rounded-md border border-line bg-surface-1 p-0.5">
          {POSITIONS.map((p) => (
            <button
              key={p}
              onClick={() => setPos(p)}
              className={`rounded px-2 py-1 text-xs transition-colors ${
                pos === p ? "bg-surface-3 text-ink" : "text-ink-3 hover:text-ink-2"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        <span className="ml-auto font-mono text-[11px] text-ink-3">
          {shown.length}/{players.length}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {shown.map((p) => (
          <div
            key={p.id}
            className="flex items-center gap-2.5 rounded-lg border border-line bg-surface-1 p-2.5 transition-colors hover:border-line-strong hover:bg-surface-2"
          >
            <PlayerAvatar name={p.fullName} url={p.headshotUrl} size={36} />
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium leading-tight text-ink">
                {p.fullName}
              </div>
              <div className="text-[10px] leading-tight text-ink-3">
                {[p.position, p.team].filter(Boolean).join(" · ")}
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
