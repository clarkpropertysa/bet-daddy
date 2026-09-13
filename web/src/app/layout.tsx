import type { Metadata } from "next";
import { Inter, Oswald } from "next/font/google";
import Link from "next/link";
import { OddsCrown, Wordmark } from "@/components/Logo";
import "./globals.css";

// Display face is the condensed grotesque from the brand sheet; body is a neutral
// grotesque so the two never compete.
const oswald = Oswald({ subsets: ["latin"], weight: ["500", "700"], variable: "--font-display" });
const inter = Inter({ subsets: ["latin"], variable: "--font-body" });

export const metadata: Metadata = {
  title: "Bet Daddy",
  description: "NFL and NBA player-prop research",
};

/**
 * Top Picks leads and the Prop Board is not in the nav.
 *
 * The board lists every strike of every projection -- about 400 rows on a Sunday --
 * and a reviewer read that, correctly, as 400 opportunities when many are one opinion
 * restated: NO at DET alone was 113 of 123 positive-edge rows on the same side. Top
 * Picks is the curated view: one row per projection, both book gates, rushing held
 * back with the reason stated.
 *
 * The board is DEMOTED, not deleted. It stays reachable from Top Picks ("Every
 * strike") and the Slate, because it is where a pick gets checked -- it is how the
 * Burrow and Maye projections were taken apart. Removing it saves nothing on Neon
 * either: Top Picks reads more of the board (1,000 rows) than the board page does.
 */
const NAV = [
  { href: "/top-picks", label: "Top Picks" },
  { href: "/", label: "Slate" },
  { href: "/players", label: "Players" },
  { href: "/parlay", label: "Parlay" },
  { href: "/track-record", label: "Track Record" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${oswald.variable} ${inter.variable}`}>
      <body
        className="min-h-screen bg-paper text-ink antialiased"
        style={{ fontFamily: "var(--font-body), ui-sans-serif, system-ui, sans-serif" }}
      >
        <header className="sticky top-0 z-30 border-b border-line bg-card">
          <div className="mx-auto flex max-w-[1600px] items-center gap-5 px-5 py-3">
            <Link href="/top-picks" className="flex shrink-0 items-center gap-2.5">
              <OddsCrown size={22} />
              <Wordmark size={16} />
            </Link>
            {/* Segmented control, per the brand sheet's LIVE / TODAY / PARLAYS motif */}
            <nav className="flex min-w-0 gap-0.5 overflow-x-auto rounded border border-line-2 p-0.5">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="whitespace-nowrap rounded-[2px] px-2.5 py-1 text-[12px] text-ink-2 transition-colors hover:bg-steel-100 hover:text-steel-800"
                >
                  {n.label}
                </Link>
              ))}
            </nav>
            <span className="eyebrow ml-auto hidden shrink-0 sm:inline">
              Put it on the board
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] px-5 py-6">{children}</main>
        <footer className="mx-auto mt-10 max-w-[1600px] border-t border-line px-5 py-4">
          <div className="flex justify-between">
            <span className="eyebrow">Bet Daddy — research, not a sportsbook</span>
            <span className="eyebrow">NFL 2026</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
