/**
 * Text colour for a filled team-colour chip.
 *
 * Team primaries span nearly the whole lightness range — Pittsburgh's is #FFB612,
 * New England's is #002244 — so a fixed white or black label is unreadable on
 * roughly half the league. Relative luminance picks the right one.
 */
export function readableOn(hex: string | null | undefined): string {
  if (!hex) return "#FFFFFF";
  const h = hex.replace("#", "");
  if (h.length !== 6) return "#FFFFFF";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  // WCAG contrast against white vs black; pick whichever clears by more.
  return (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.05) ? "#FFFFFF" : "#111111";
}

/** Team colour, falling back to brand steel when a team has none. */
export function teamColor(hex: string | null | undefined): string {
  return hex && /^#[0-9a-f]{6}$/i.test(hex) ? hex : "var(--steel)";
}
