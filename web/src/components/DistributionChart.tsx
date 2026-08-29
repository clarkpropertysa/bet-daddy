"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Simulated outcome distribution with the market strike marked (Section 9.9).
 *
 * Form is EMPHASIS, not categorical: one hue for the distribution, a neutral rule for
 * the strike. The reader's job is "where does the strike fall in this spread", which
 * is a single-series question -- a categorical palette here would imply the two sides
 * are different entities and would also drag in the red/green CVD pair unnecessarily.
 *
 * Percentile markers are direct-labelled rather than legended: there is one series,
 * so a legend box would name nothing the title does not.
 */
export function DistributionChart({
  percentiles,
  strike,
  mean,
}: {
  percentiles: Record<string, number>;
  strike: number | null;
  mean?: number;
}) {
  const pts = Object.entries(percentiles)
    .map(([p, v]) => ({ p: Number(p), value: Number(v) }))
    .filter((d) => Number.isFinite(d.p) && Number.isFinite(d.value))
    .sort((a, b) => a.p - b.p);

  if (pts.length < 3) {
    return (
      <p className="text-xs text-ink-3">
        No simulated distribution stored for this signal.
      </p>
    );
  }

  // Percentile -> outcome is the inverse CDF; plotting outcome on x makes the
  // strike comparison direct, which is the question being asked.
  const data = pts.map((d) => ({ outcome: d.value, cum: d.p }));
  const lo = data[0].outcome;
  const hi = data[data.length - 1].outcome;

  return (
    <div className="h-44 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {/* top margin clears the "mean" reference label; left clears the p100 tick */}
        <AreaChart data={data} margin={{ top: 14, right: 10, bottom: 2, left: 0 }}>
          <defs>
            <linearGradient id="distFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="outcome"
            type="number"
            domain={[lo, hi]}
            tick={{ fill: "var(--ink-3)", fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: "var(--line)" }}
          />
          <YAxis
            dataKey="cum"
            tick={{ fill: "var(--ink-3)", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `p${v}`}
            width={34}
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
          />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }}
            contentStyle={{
              background: "var(--surface-3)",
              border: "1px solid var(--line-strong)",
              borderRadius: 6,
              fontSize: 11,
              color: "var(--ink)",
            }}
            labelFormatter={(v) => `outcome ${Number(v).toFixed(1)}`}
            formatter={(v) => [`${v}th percentile`, ""] as [string, string]}
          />
          <Area
            // No mount animation: this is a reference chart the reader scans against
            // a strike, not a reveal. It also makes the rendered state deterministic
            // for screenshots and tests.
            isAnimationActive={false}
            type="monotone"
            dataKey="cum"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#distFill)"
            dot={{ r: 2.5, fill: "var(--accent)", stroke: "var(--surface-1)", strokeWidth: 2 }}
            activeDot={{ r: 4 }}
          />
          {mean !== undefined && (
            <ReferenceLine
              x={mean}
              stroke="var(--ink-3)"
              strokeDasharray="3 3"
              label={{ value: "mean", position: "top", fill: "var(--ink-3)", fontSize: 9 }}
            />
          )}
          {strike !== null && (
            <ReferenceLine
              x={strike}
              stroke="var(--ink)"
              strokeWidth={1.5}
              label={{
                value: `strike ${strike}`,
                position: "insideTopRight",
                fill: "var(--ink)",
                fontSize: 10,
              }}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
