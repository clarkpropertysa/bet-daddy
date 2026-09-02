import "server-only";

/**
 * Current quotes, read straight from the market at request time.
 *
 * The snapshot archive is written by a GitHub Actions job, and GitHub throttles
 * scheduled workflows hard on a private repo — a cron asking for every 15 minutes
 * actually fires every two to three hours. That is an acceptable cadence for the
 * MODEL, which only moves when an injury or depth chart moves. It is a bad cadence
 * for a PRICE, which moves all day and is half of every edge on the board.
 *
 * So the price is fetched here instead of waited for. Reads are public — no key, no
 * auth — which is what makes this possible at all.
 */

const API_BASE =
  process.env.KALSHI_API_BASE?.replace(/\/$/, "") ??
  "https://api.elections.kalshi.com/trade-api/v2";

/** Same series map the archiver uses. Kept in sync deliberately, not derived. */
const NFL_PROP_SERIES = [
  "KXNFLPASSYDS",
  "KXNFLRECYDS",
  "KXNFLRSHYDS",
  "KXNFLREC",
  "KXNFLPASSTDS",
  "KXNFLANYTD",
] as const;

export type LiveQuote = {
  yesBid: number | null;
  yesAsk: number | null;
  fetchedAt: Date;
};

export type LiveQuoteBook = {
  quotes: Map<string, LiveQuote>;
  fetchedAt: Date;
  /** Markets seen at all, whether or not anyone is quoting them. */
  seen: number;
  /** Markets carrying a usable two-sided or one-sided ask. */
  quoted: number;
  /** Set when the market could not be reached; the board then falls back to stored. */
  error: string | null;
};

const EMPTY = (error: string | null): LiveQuoteBook => ({
  quotes: new Map(),
  fetchedAt: new Date(),
  seen: 0,
  quoted: 0,
  error,
});

/**
 * Kalshi renamed every price field, appending `_dollars`: `yes_ask` is now
 * `yes_ask_dollars` and the old key is ABSENT. Reading the old name returns undefined
 * for every market, so the board filtered them all out and reported "listed but nobody
 * is quoting them yet" while the exchange was quoting all 396 of them.
 *
 * Both spellings are read, new first, so a rollback or partial rollout keeps working.
 */
const PRICE_KEYS: Record<string, string[]> = {
  yes_ask: ["yes_ask_dollars", "yes_ask"],
  yes_bid: ["yes_bid_dollars", "yes_bid"],
};

function priceField(m: Record<string, unknown>, name: string): unknown {
  for (const key of PRICE_KEYS[name] ?? [name]) {
    if (key in m) return m[key];
  }
  return undefined;
}

/** Does this object carry a price KEY at all? Distinguishes "quoted at nothing" from
 *  "we are reading the wrong key" -- the second is schema drift and must be loud. */
function hasPriceField(m: Record<string, unknown>): boolean {
  return Object.values(PRICE_KEYS).some((keys) => keys.some((k) => k in m));
}

/**
 * A 0c or 100c ask is an empty or one-sided book reported as a number, not a price
 * anyone could be filled at. Same bounds the projection enforces.
 *
 * Values arrive as decimal-dollar STRINGS ("0.0700"), so they are coerced.
 */
function tradeable(v: unknown): number | null {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return null;
  const dollars = n > 1 ? n / 100 : n; // the API quotes cents on some endpoints
  return dollars > 0.01 && dollars < 0.99 ? dollars : null;
}

async function fetchSeries(series: string): Promise<Record<string, unknown>[]> {
  const out: Record<string, unknown>[] = [];
  let cursor: string | undefined;
  // Bounded: a runaway cursor must not hold a page render open indefinitely.
  for (let page = 0; page < 10; page++) {
    const url = new URL(`${API_BASE}/markets`);
    url.searchParams.set("series_ticker", series);
    url.searchParams.set("status", "open");
    url.searchParams.set("limit", "200");
    if (cursor) url.searchParams.set("cursor", cursor);

    const res = await fetch(url, {
      headers: { "User-Agent": "bet-daddy/0.1 (personal research)" },
      signal: AbortSignal.timeout(6000),
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`${series}: HTTP ${res.status}`);
    const body = (await res.json()) as { markets?: Record<string, unknown>[]; cursor?: string };
    out.push(...(body.markets ?? []));
    cursor = body.cursor || undefined;
    if (!cursor) break;
  }
  return out;
}

/**
 * Short in-process cache. Pages are force-dynamic, so without this every page load —
 * and every refresh — would fan out six requests to the market. Thirty seconds is far
 * fresher than the hours the archive job manages, while keeping a team clicking around
 * to roughly one fetch each.
 */
const TTL_MS = 30_000;
let cached: { book: LiveQuoteBook; at: number } | null = null;

export async function getLiveQuotes(): Promise<LiveQuoteBook> {
  if (cached && Date.now() - cached.at < TTL_MS) return cached.book;
  const book = await fetchLiveQuotes();
  // A failed fetch is cached too, briefly. Otherwise an outage turns every page load
  // into six more timeouts and the board gets slower exactly when it is degraded.
  cached = { book, at: Date.now() };
  return book;
}

/**
 * Every open NFL prop quote, keyed by market ticker.
 *
 * Never throws. A market-data outage must degrade the board to its stored prices with
 * the age shown, not take the page down — the same rule the pipeline follows for blob
 * and Postgres.
 */
async function fetchLiveQuotes(): Promise<LiveQuoteBook> {
  const fetchedAt = new Date();
  const quotes = new Map<string, LiveQuote>();
  let seen = 0;
  let quoted = 0;
  // Whether ANY market carried a recognised price key. Zero across a full slate means
  // the schema moved, which is indistinguishable from an unquoted market otherwise.
  let sawPriceField = false;

  const results = await Promise.allSettled(NFL_PROP_SERIES.map(fetchSeries));
  const failures = results.filter((r) => r.status === "rejected");
  // Partial success is still useful: one dead series must not blank the board.
  if (failures.length === results.length) {
    const first = failures[0] as PromiseRejectedResult | undefined;
    return EMPTY(first ? String(first.reason).slice(0, 200) : "no series reachable");
  }

  for (const r of results) {
    if (r.status !== "fulfilled") continue;
    for (const m of r.value) {
      const ticker = m.ticker;
      if (typeof ticker !== "string") continue;
      seen++;
      if (hasPriceField(m)) sawPriceField = true;
      const yesAsk = tradeable(priceField(m, "yes_ask"));
      const yesBid = tradeable(priceField(m, "yes_bid"));
      if (yesAsk === null && yesBid === null) continue;
      quoted++;
      quotes.set(ticker, { yesBid, yesAsk, fetchedAt });
    }
  }

  return {
    quotes,
    fetchedAt,
    seen,
    quoted,
    error: failures.length
      ? `${failures.length} of ${results.length} series failed`
      : seen > 0 && !sawPriceField
        ? "no market carried a recognised price field — Kalshi has likely renamed them again"
        : null,
  };
}
