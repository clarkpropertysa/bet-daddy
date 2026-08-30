"use client";

import { useMemo, useState } from "react";
import { Empty } from "@/components/Empty";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { pct, priceCents } from "@/lib/format";
import { labelFor } from "@/lib/markets";
import { CONFIDENCE_COPY, rateParlay, type Leg } from "@/lib/parlay";

const MIN_LEGS = 2;
const MAX_LEGS = 5;

const CONF_STYLE: Record<string, string> = {
  LOW: "border-pos bg-steel-100 text-pos",
  MODERATE: "border-steel bg-steel-100 text-steel-800",
  SPECULATIVE: "border-warn/50 bg-warn/[0.08] text-warn",
  REMOTE: "border-neg bg-neg/[0.06] text-neg",
};

export type PickRow = Leg & { headshotUrl: string | null; position: string | null };

export function ParlayBuilder({ available }: { available: PickRow[] }) {
  const [picked, setPicked] = useState<string[]>([]);
  const [target, setTarget] = useState(3);
  const [q, setQ] = useState("");

  const legs = useMemo(
    () => picked.map((id) => available.find((a) => a.signalId === id)!).filter(Boolean),
    [picked, available],
  );
  const rating = useMemo(
    () => (legs.length >= MIN_LEGS ? rateParlay(legs) : null),
    [legs],
  );

  const shown = useMemo(
    () =>
      available.filter(
        (a) =>
          !picked.includes(a.signalId) &&
          (q === "" || a.player.toLowerCase().includes(q.toLowerCase())),
      ),
    [available, picked, q],
  );

  const toggle = (id: string) =>
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : p.length < target ? [...p, id] : p,
    );

  if (available.length === 0) {
    return (
      <Empty
        title="No legs available"
        source="Signal (Neon)"
        hint="A parlay is built from priced signals. None exist until Kalshi quotes week 1 markets and the projection job runs."
      />
    );
  }

  const understatement =
    rating && rating.independent > 0
      ? (rating.joint - rating.independent) / rating.independent
      : 0;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      {/* ---------------- picker ---------------- */}
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="filter player…"
            className="w-44 rounded border border-line-2 bg-card px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-3 focus:border-steel focus:outline-none"
          />
          <div className="flex items-center gap-1.5 rounded border border-line-2 bg-card px-2.5 py-1.5">
            <span className="eyebrow">legs</span>
            {[2, 3, 4, 5].map((n) => (
              <button
                key={n}
                onClick={() => {
                  setTarget(n);
                  setPicked((p) => p.slice(0, n));
                }}
                className={`tnum rounded-[2px] px-1.5 py-0.5 text-xs transition-colors ${
                  target === n ? "bg-steel text-white" : "text-ink-2 hover:bg-steel-100"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <span className="eyebrow tnum ml-auto">
            {picked.length}/{target} selected
          </span>
        </div>

        <div className="overflow-hidden rounded border border-line bg-card">
          {shown.slice(0, 60).map((a) => (
            <button
              key={a.signalId}
              onClick={() => toggle(a.signalId)}
              disabled={picked.length >= target}
              className="flex w-full items-center gap-3 border-b border-line px-3 py-2 text-left transition-colors last:border-0 hover:bg-steel-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <PlayerAvatar name={a.player} url={a.headshotUrl} size={26} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-ink">
                  {a.player}
                </span>
                <span className="eyebrow">
                  {labelFor(a.marketType)} · {a.side} {a.strike ?? ""}
                </span>
              </span>
              <span className="odds-box shrink-0 text-[12px]">{pct(a.modelProb, 0)}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ---------------- ticket ---------------- */}
      <aside className="h-fit rounded border border-line bg-steel-900 p-4 lg:sticky lg:top-20">
        <h2 className="display text-[14px] tracking-[0.1em] text-white">Ticket</h2>

        {legs.length === 0 ? (
          <p className="mt-3 text-[12px] leading-relaxed text-steel-300">
            Pick {MIN_LEGS}–{MAX_LEGS} legs. Correlated legs — same player, same team —
            change the joint probability materially, so the rating is not a product of
            the individual numbers.
          </p>
        ) : (
          <ul className="mt-3 space-y-1">
            {legs.map((l) => (
              <li
                key={l.signalId}
                className="flex items-center gap-2 rounded border border-white/10 bg-white/[0.04] px-2.5 py-2"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12px] text-white">{l.player}</span>
                  <span className="block text-[10px] text-steel-400">
                    {labelFor(l.marketType)} · {l.side} {l.strike ?? ""}
                  </span>
                </span>
                <span className="tnum shrink-0 text-[11px] text-steel-300">
                  {pct(l.modelProb, 0)}
                </span>
                <button
                  onClick={() => toggle(l.signalId)}
                  className="shrink-0 text-[11px] text-steel-400 hover:text-white"
                  aria-label="remove leg"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}

        {rating && rating.contradictions.length > 0 && (
          <div className="mt-4 rounded border border-neg bg-neg/[0.1] px-3 py-2.5">
            <p className="display text-[12px] tracking-[0.1em] text-neg">
              Cannot both win
            </p>
            <ul className="mt-1.5 space-y-0.5">
              {rating.contradictions.map(([a, b], i) => (
                <li key={i} className="text-[10.5px] leading-relaxed text-neg">
                  {a.player} {a.side} {a.strike} and {b.side} {b.strike} —{" "}
                  {labelFor(a.marketType)}, same game.
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-[10.5px] leading-relaxed text-neg/80">
              Remove one. A copula would happily price this pair; it only sees two
              probabilities, not that they contradict.
            </p>
          </div>
        )}

        {rating && rating.contradictions.length === 0 && (
          <>
            <div
              className={`mt-4 rounded border px-3 py-2.5 ${CONF_STYLE[rating.confidence]}`}
            >
              <div className="flex items-baseline justify-between">
                <span className="display text-[12px] tracking-[0.1em]">
                  {rating.confidence}
                </span>
                <span className="tnum text-[18px] font-semibold">
                  {pct(rating.joint, 1)}
                </span>
              </div>
              <p className="mt-1 text-[10.5px] leading-relaxed opacity-90">
                {CONFIDENCE_COPY[rating.confidence]}
              </p>
            </div>

            <dl className="mt-3 overflow-hidden rounded border border-white/10">
              <Row k="Model joint probability" v={pct(rating.joint, 2)} strong />
              <Row
                k="If legs were independent"
                v={pct(rating.independent, 2)}
                tone="text-steel-400"
              />
              <Row k="Mean leg correlation" v={rating.meanRho.toFixed(2)} />
              <Row k="Fair decimal odds" v={rating.fairOdds.toFixed(2)} />
              <Row k="Market-implied joint" v={pct(rating.marketJoint, 2)} />
            </dl>

            {Math.abs(understatement) > 0.02 && (
              <p className="mt-2 text-[10.5px] leading-relaxed text-steel-400">
                Treating these legs as independent would be{" "}
                <span className="tnum text-white">
                  {Math.abs(understatement * 100).toFixed(0)}%
                </span>{" "}
                {understatement > 0 ? "too pessimistic" : "too optimistic"} — they are{" "}
                {rating.meanRho > 0 ? "positively" : "negatively"} correlated.
              </p>
            )}

            <p className="mt-3 border-t border-white/10 pt-2.5 text-[10px] leading-relaxed text-steel-400">
              Kalshi lists these as <span className="text-steel-300">combos</span>
              (KXMVENFLSINGLEGAME, minimum 2 legs) — a combo resolves YES only if every
              leg does, which is exactly what is rated here. Correlation values are
              documented priors, not fitted: that needs settled multi-leg outcomes the
              archive does not yet hold.
            </p>
          </>
        )}
      </aside>
    </div>
  );
}

function Row({
  k, v, tone, strong,
}: { k: string; v: string; tone?: string; strong?: boolean }) {
  return (
    <div
      className={`flex items-baseline justify-between gap-3 px-3 py-2 ${
        strong ? "border-b border-white/20 bg-white/[0.09]" : "bg-white/[0.04]"
      }`}
    >
      <dt className="text-[12px] text-steel-300">{k}</dt>
      <dd className={`tnum text-[12px] ${tone ?? "text-white"} ${strong ? "font-semibold" : ""}`}>
        {v}
      </dd>
    </div>
  );
}
