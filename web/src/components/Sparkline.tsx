/**
 * Inline trend sparkline. Server-renderable plain SVG -- a chart library for a
 * 60px glyph would cost more than it explains.
 *
 * No axes, no labels: a sparkline's job is shape, and the numeric value it
 * accompanies carries the magnitude.
 */
export function Sparkline({
  values,
  width = 64,
  height = 18,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  if (!values || values.length < 2) {
    return <span className="text-ink-3">—</span>;
  }
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => {
    const x = i * step;
    const y = height - ((v - lo) / span) * (height - 3) - 1.5;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const rising = values[values.length - 1] >= values[0];

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden="true">
      <polyline
        points={pts.join(" ")}
        fill="none"
        strokeWidth={1.5}
        stroke={rising ? "var(--pos)" : "var(--neg)"}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={(values.length - 1) * step}
        cy={height - ((values[values.length - 1] - lo) / span) * (height - 3) - 1.5}
        r={2}
        fill={rising ? "var(--pos)" : "var(--neg)"}
      />
    </svg>
  );
}
