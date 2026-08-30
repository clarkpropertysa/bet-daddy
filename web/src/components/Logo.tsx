/**
 * The Odds Crown (brand sheet, direction 1A).
 *
 * Five bars — odds columns — read as a crown, sitting on a base rule. Per the sheet:
 * it draws at 16px, and below 20px the base rule is dropped so the mark stays legible.
 */
export function OddsCrown({
  size = 24,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  // Bar heights as fractions of the mark height, forming the crown silhouette.
  const bars = [0.55, 0.78, 1.0, 0.72, 0.48];
  const showRule = size >= 20;
  const gap = size * 0.07;
  const barW = (size - gap * (bars.length - 1)) / bars.length;
  const ruleH = showRule ? Math.max(1.5, size * 0.09) : 0;
  const ruleGap = showRule ? size * 0.08 : 0;
  const barArea = size - ruleH - ruleGap;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={className}
      role="img"
      aria-label="Bet Daddy"
    >
      {bars.map((h, i) => {
        const bh = barArea * h;
        return (
          <rect
            key={i}
            x={i * (barW + gap)}
            y={barArea - bh}
            width={barW}
            height={bh}
            fill={i === 2 ? "var(--steel-900)" : "var(--steel)"}
            rx={size * 0.03}
          />
        );
      })}
      {showRule && (
        <rect
          x={0}
          y={size - ruleH}
          width={size}
          height={ruleH}
          fill="var(--steel-900)"
          rx={ruleH / 2}
        />
      )}
    </svg>
  );
}

export function Wordmark({ size = 15 }: { size?: number }) {
  return (
    <span
      className="display leading-none text-ink"
      style={{ fontSize: size, letterSpacing: "0.005em" }}
    >
      Bet Daddy
    </span>
  );
}
