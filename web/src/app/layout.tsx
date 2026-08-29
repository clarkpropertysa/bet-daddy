import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bet Daddy",
  description: "NFL and NBA player-prop research",
};

const NAV = [
  { href: "/", label: "Slate" },
  { href: "/board", label: "Prop Board" },
  { href: "/players", label: "Players" },
  { href: "/track-record", label: "Track Record" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-ink antialiased">
        <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md">
          <div className="mx-auto flex max-w-[1600px] items-center gap-1 px-5 py-2.5">
            <Link href="/" className="mr-5 flex shrink-0 items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded bg-accent text-[11px] font-bold text-white">
                B
              </span>
              <span className="whitespace-nowrap text-[13px] font-semibold tracking-tight text-ink">
                Bet Daddy
              </span>
            </Link>
            <nav className="flex min-w-0 gap-0.5 overflow-x-auto">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="whitespace-nowrap rounded-md px-2.5 py-1.5 text-[13px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
                >
                  {n.label}
                </Link>
              ))}
            </nav>
            <span className="ml-auto hidden shrink-0 whitespace-nowrap rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-ink-3 sm:inline">
              NFL 2026
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] px-5 py-6">{children}</main>
      </body>
    </html>
  );
}
