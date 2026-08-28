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
  { href: "/track-record", label: "Track Record" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-zinc-950 text-zinc-200 antialiased">
        <header className="border-b border-zinc-800 bg-zinc-950/90 backdrop-blur sticky top-0 z-20">
          <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-4 py-2.5">
            <Link href="/" className="text-sm font-semibold tracking-tight text-zinc-100">
              Bet&nbsp;Daddy
            </Link>
            <nav className="flex gap-4 text-sm">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href}
                      className="text-zinc-400 transition-colors hover:text-zinc-100">
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
