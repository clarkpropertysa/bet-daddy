import { MARKET_FAMILIES, MARKET_GROUPS } from "@/lib/markets";

/**
 * The board's structure, shown explicitly.
 *
 * Rendered above the table so the organisation is legible even with zero rows —
 * which is the state until week 1 is quoted. Counts come from live signals.
 */
export function MarketMap({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <section className="mb-4 rounded border border-line bg-card p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="display text-[13px] text-ink">Markets covered</h2>
        <span className="eyebrow tnum">
          {total} live {total === 1 ? "market" : "markets"}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {MARKET_GROUPS.map((g) => (
          <div key={g}>
            <p className="eyebrow mb-1.5">{g}</p>
            <ul className="space-y-1">
              {MARKET_FAMILIES.filter((f) => f.group === g).map((f) => {
                const n = counts[f.key] ?? 0;
                return (
                  <li
                    key={f.key}
                    className="flex items-baseline justify-between gap-2"
                    title={f.note}
                  >
                    <span
                      className={`text-[12px] ${
                        f.modelled ? "text-ink" : "text-ink-3 line-through decoration-line-2"
                      }`}
                    >
                      {f.label}
                    </span>
                    {f.modelled ? (
                      <span className="tnum text-[11px] text-ink-3">{n}</span>
                    ) : (
                      <span className="eyebrow shrink-0 !text-[8px]">not modelled</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-3 border-t border-line pt-2.5 text-[11px] leading-relaxed text-ink-2">
        Struck-through families are offered by the market but not yet simulated — shown
        rather than hidden, so a market we cannot price is distinguishable from one
        that does not exist. Every market is an over/under on a strike; the board
        picks whichever side carries the edge.
      </p>
    </section>
  );
}
