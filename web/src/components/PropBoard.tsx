"use client";

import { useMemo, useState } from "react";
import { Empty } from "@/components/Empty";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Tier, type TierName } from "@/components/Tier";
import { WhyPanel, type WhyRow } from "@/components/WhyPanel";
import { EdgeVerdict, Prediction, ProbabilityGap } from "@/components/Prediction";
import { gameFromTicker, labelFor } from "@/lib/markets";

export type Row = WhyRow & {
  signalId: string;
  marketTicker: string;
  position: string | null;
  tier: TierName;
  sampleN: number;
  implausible: boolean;
  modelVersion: string;
  headshotUrl: string | null;
  depthPos: string | null;
  depthRank: number | null;
  isStarter: boolean;
};

type SortKey = "edge" | "player" | "model" | "ask" | "kelly";

export type BoardStatus = {
  listed: number;
  quoted: number;
  fresh: number;
  maxPriceAgeMins: number;
  mode: string | null;
  ranAt: Date | string | null;
};

/**
 * An empty board has several unrelated causes and they are indistinguishable to
 * someone staring at a blank page. Each one below is a different thing to do about
 * it -- wait, wait longer, or go fix the archiver -- so each gets its own words. The
 * counts come from what the projection run actually saw, never from a guess.
 */
function emptyCopy(status?: BoardStatus | null): {
  title: string;
  source: string;
  hint: string;
} {
  if (!status) {
    return {
      title: "No signals yet",
      source: "Signal (Neon)",
      hint: "No projection run has recorded what it saw. Once the projection job runs, this page explains exactly why it is empty rather than showing nothing.",
    };
  }
  if (status.listed === 0) {
    return {
      title: "No upcoming markets listed",
      source: "market archive",
      hint: "The archive holds no markets that are still open. Markets for a given week are usually listed several days out; until then there is nothing to project.",
    };
  }
  if (status.quoted === 0) {
    return {
      title: `${status.listed} markets listed, none quoted yet`,
      source: "market archive",
      hint: "The upcoming markets exist but nobody is making a price on them yet — no bid, no ask, no open interest. An edge is the distance between our number and a real price, so with no price there is no edge to report. This is the market's state, not a failure here. Quotes typically appear as the game approaches.",
    };
  }
  if (status.fresh === 0) {
    return {
      title: "Every quote is stale",
      source: "archive-markets job",
      hint: `${status.quoted} markets are quoted, but the newest price on hand is older than the ${status.maxPriceAgeMins}-minute limit. Rather than present an old price as current, the board shows nothing. The snapshot job has most likely stopped — check its run history.`,
    };
  }
  return {
    title: "Every market was refused",
    source: "projection gates",
    hint: `${status.fresh} markets had a fresh price, but all of them were refused — a backup rather than a starter, too little usage history, or a market family that is not modelled. The run's skip counts say which.`,
  };
}

export function PropBoard({ rows, status }: { rows: Row[]; status?: BoardStatus | null }) {
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

  /**
   * ONE GAME SCRIPT, SLICED TWENTY WAYS.
   *
   * The exchange lists a hundred props per game and the model prices every one of them
   * from a SINGLE simulated game. So when its view of that game differs from the
   * market's, every prop inside it moves together: on this slate the top twenty edges
   * in New Orleans at Detroit were eighteen on the same side, and Arizona at the
   * Chargers is "Arizona keeps it close" stated thirteen ways.
   *
   * Taking thirty of those is not thirty positions. It is one position at thirty times
   * the stake, and the board sorted by edge said nothing about it -- which is the same
   * error `getProjectionBoard` already fixes WITHIN a player (twenty rungs of one
   * ladder are one opinion) carried up to the level of the game.
   */
  const concentration = useMemo(() => {
    const TOP = 20;
    const top = filtered.slice(0, TOP);
    if (top.length < 8) return null;

    const byGame = new Map<string, { n: number; yes: number; ticker: string }>();
    let overYes = 0;
    for (const r of top) {
      const key = r.marketTicker.split("-")[1] ?? "?";
      const e = byGame.get(key) ?? { n: 0, yes: 0, ticker: r.marketTicker };
      e.n += 1;
      if (r.side === "yes") { e.yes += 1; overYes += 1; }
      byGame.set(key, e);
    }

    // The game holding the most of these rows. The floor is deliberately low: the
    // board reprices against live quotes before sorting, so the composition shifts
    // through the day, and a threshold tuned to one snapshot silently stops firing.
    let biggest: { n: number; yes: number; ticker: string } | null = null;
    for (const e of byGame.values()) {
      if (!biggest || e.n > biggest.n) biggest = e;
    }
    if (biggest && biggest.n >= 4) {
      const same = Math.max(biggest.yes, biggest.n - biggest.yes);
      if (same >= Math.ceil(biggest.n * 0.7)) {
        return {
          headline:
            `${biggest.n} of the top ${top.length} rows are ${gameFromTicker(biggest.ticker)?.label ?? "one game"}`
            + `, and ${same} of those take the same side of one game script.`,
        };
      }
    }

    // No single game dominates, but the board can still be one bet: a slate-wide tilt
    // to overs or unders is the same correlation one level up.
    const same = Math.max(overYes, top.length - overYes);
    if (same >= Math.ceil(top.length * 0.7)) {
      return {
        headline:
          `${same} of the top ${top.length} rows take the same side`
          + `${overYes >= same ? " (overs)" : " (unders)"} across the slate.`,
      };
    }
    return null;
  }, [filtered]);

  if (rows.length === 0) {
    return <Empty {...emptyCopy(status)} />;
  }

  return (
    <>
      {concentration && (
        <p className="mb-3 rounded border border-warn/40 bg-warn/[0.06] px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
          <strong className="font-medium text-warn">{concentration.headline}</strong>{" "}
          Every prop in a game is priced from a single simulated game, so they rise and
          fall together — and this board lists every strike, so one opinion can fill a
          screen. Backing several is one position at several times the stake, not a
          spread of bets.
        </p>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="filter player…"
          className="w-44 rounded border border-line-2 bg-card px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-3 focus:border-steel focus:outline-none"
        />
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="rounded border border-line-2 bg-card px-2.5 py-1.5 text-xs text-ink focus:border-steel focus:outline-none"
        >
          {markets.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <label className="flex items-center gap-1.5 rounded border border-line-2 bg-card px-2.5 py-1.5 text-xs text-ink-2">
          min edge
          <input
            type="number" step="0.5" value={minEdge}
            onChange={(e) => setMinEdge(Number(e.target.value))}
            className="tnum w-12 bg-transparent text-right text-ink focus:outline-none"
          />
          ¢
        </label>
        <button
          onClick={() => setHideImplausible(!hideImplausible)}
          title="Hide signals where the model disagrees with the market by more than 50 points — almost always a model failure, not an edge."
          className={`rounded border px-2.5 py-1.5 text-xs transition-colors ${
            hideImplausible
              ? "border-line-2 bg-card text-ink-2 hover:border-steel"
              : "border-neg bg-neg/[0.08] text-neg"
          }`}
        >
          {hideImplausible ? "implausible hidden" : "implausible shown"}
        </button>
        <button
          onClick={() => setValidatedOnly(!validatedOnly)}
          className={`rounded border px-2.5 py-1.5 text-xs transition-colors ${
            validatedOnly
              ? "border-pos bg-steel-100 text-pos"
              : "border-line-2 bg-card text-ink-2 hover:border-steel"
          }`}
        >
          validated only
        </button>
        <span className="eyebrow tnum ml-auto">
          {filtered.length}/{rows.length}
        </span>
      </div>

      <div className="overflow-x-auto rounded border border-line bg-card">
        <table className="w-full min-w-[860px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line">
              <Th onClick={() => toggle("player")} active={sort === "player"} asc={asc}>Player</Th>
              <Th>The call</Th>
              <Th onClick={() => toggle("model")} active={sort === "model"} asc={asc}>
                Model vs market
              </Th>
              <Th onClick={() => toggle("edge")} active={sort === "edge"} asc={asc}>
                Worth it?
              </Th>
              <Th>Track record</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr
                key={r.signalId}
                onClick={() => setActive(r)}
                className="cursor-pointer border-b border-line transition-colors last:border-0 hover:bg-steel-100"
              >
                <Td>
                  <span className="flex items-center gap-2.5">
                    <PlayerAvatar name={r.player} url={r.headshotUrl} size={28} />
                    <span className="min-w-0">
                      <span className="block truncate font-medium leading-tight text-ink">
                        {r.player}
                      </span>
                      <span className="flex items-center gap-1.5 text-[10px] leading-tight text-ink-3">
                        {/* Depth role, always shown. A backup's usage history
                            describes a job he no longer holds, so which one he is
                            must never be a hidden field. */}
                        {r.depthPos && r.depthRank && (
                          <span
                            className={`rounded-[2px] px-1 py-px font-medium ${
                              r.isStarter
                                ? "bg-steel-100 text-steel-800"
                                : "bg-warn/15 text-warn"
                            }`}
                          >
                            {r.depthPos}{r.depthRank}
                          </span>
                        )}
                        <span>{[r.position, r.team].filter(Boolean).join(" · ")}</span>
                      </span>
                    </span>
                  </span>
                </Td>
                <Td>
                  <Prediction
                    side={r.side}
                    strike={r.strike}
                    marketType={r.marketType}
                    marketTicker={r.marketTicker}
                  />
                </Td>
                <Td>
                  <ProbabilityGap modelProb={r.modelProb} marketProb={r.marketProb} />
                </Td>
                <Td>
                  <EdgeVerdict
                    netCents={r.edgeCentsNet}
                    feeCents={r.feeCents}
                    implausible={r.implausible}
                    // "Strong" is a claim about evidence, not arithmetic.
                    tier={r.tier}
                    sampleN={r.sampleN}
                    // And a family Top Picks withholds cannot shout here.
                    marketType={r.marketType}
                  />
                </Td>
                <Td><Tier tier={r.tier} n={r.sampleN} /></Td>
                <Td align="right">
                  <span className="eyebrow text-steel">why →</span>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && (
        <p className="mt-3 text-[11.5px] text-ink-2">
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
      className={`eyebrow px-3 py-2.5 ${align === "right" ? "text-right" : "text-left"} ${
        onClick ? "cursor-pointer select-none hover:text-steel" : ""
      } ${active ? "!text-steel-800" : ""}`}
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
        mono ? "tnum text-xs" : ""
      } ${className}`}
    >
      {children}
    </td>
  );
}
