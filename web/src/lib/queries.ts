import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/db";
import { computeEdge, pOverAtStrike } from "@/lib/edge";
import { getLiveQuotes, type LiveQuoteBook } from "@/lib/livePrices";

/** Same threshold the Python job applies. Recomputed here because a live price can
 *  move a signal across it in either direction, and a stale flag is worse than none. */
const IMPLAUSIBLE_DIVERGENCE = 0.5;

/**
 * Replace a row's stored price with the market's current one and recompute the edge.
 *
 * Only the price half is refreshed. The model half -- the simulated distribution --
 * is left exactly as the Python job produced it, because that is what CLV grading
 * scored and re-deriving it here would put two different models on the same screen.
 */
function reprice(r: BoardRow, book: LiveQuoteBook): BoardRow {
  const q = book.quotes.get(r.marketTicker);
  const pOver = pOverAtStrike(r.pOverByStrike, r.strike);
  // No quote, or no stored probability at this exact strike: keep what was stored and
  // say so. Interpolating a probability would be inventing the number the edge is
  // built from.
  if (!q || q.yesAsk === null || pOver === null) return { ...r, priceSource: "stored" };

  const e = computeEdge(pOver, q.yesAsk);
  return {
    ...r,
    side: e.side,
    modelProb: e.modelProb,
    marketProb: e.marketProb,
    feeCents: e.feeCents,
    edgeCentsNet: e.edgeCentsNet,
    kelly: e.kelly,
    implausible: Math.abs(e.modelProb - e.marketProb) > IMPLAUSIBLE_DIVERGENCE,
    priceAsOf: q.fetchedAt,
    priceSource: "live",
  };
}

export type BoardRow = {
  signalId: string;
  marketTicker: string;
  player: string;
  headshotUrl: string | null;
  position: string | null;
  depthPos: string | null;
  depthRank: number | null;
  isStarter: boolean;
  team: string | null;
  marketType: string;
  gameId: string;
  strike: number | null;
  side: string;
  modelProb: number;
  marketProb: number;
  feeCents: number;
  edgeCentsNet: number;
  kelly: number;
  tier: "UNVALIDATED" | "PROVISIONAL" | "VALIDATED";
  sampleN: number;
  runTs: Date;
  closeTime: Date | null;
  priceAsOf: Date | null;
  reason: unknown;
  implausible: boolean;
  modelVersion: string;
  /** strike -> P(over), the stored model curve. Used to reprice against a live ask. */
  pOverByStrike?: unknown;
  /** "live" when the ask came from the market just now, "stored" when it did not. */
  priceSource: "live" | "stored";
};

/** Why the board is empty, taken from the last projection run rather than guessed. */
export type BoardStatus = {
  listed: number;
  quoted: number;
  fresh: number;
  maxPriceAgeMins: number;
  mode: string | null;
  ranAt: Date | null;
};

/**
 * Latest signal per market for markets that have NOT closed yet.
 *
 * The close-time filter is the whole point. Without it the board serves the most
 * recent run per ticker forever, which means a game that finished last month sits at
 * the top of the board looking like a live recommendation. A null closeTime fails the
 * comparison and drops out, which is the correct treatment for rows written before
 * the live board existed -- they were all settled backtest signals.
 */
export async function getBoard(limit = 200, gameId?: string): Promise<BoardRow[]> {
  const rows = await prisma.$queryRaw<BoardRow[]>`
    with latest as (
      select distinct on (s."marketTicker") s.*
      from "Signal" s
      where s."closeTime" > now()
      order by s."marketTicker", s."runTs" desc
    )
    select
      l.id                as "signalId",
      l."marketTicker"    as "marketTicker",
      coalesce(p."fullName", 'unresolved') as player,
      p."headshotUrl"     as "headshotUrl",
      p.position          as position,
      p."depthPos"        as "depthPos",
      p."depthRank"       as "depthRank",
      p."isStarter"       as "isStarter",
      t.abbrev            as team,
      pr."marketType"     as "marketType",
      pr."gameId"         as "gameId",
      -- MarketSnapshot is not mirrored into Postgres (the archive is Parquet), so
      -- the strike is parsed off the ticker: ...-SFBPURDY13-350 -> 350
      nullif(regexp_replace(l."marketTicker", '^.*-', ''), '')::float8 as strike,
      l.side              as side,
      l."modelProb"::float8   as "modelProb",
      l."marketProb"::float8  as "marketProb",
      l."feeCents"::float8    as "feeCents",
      l."edgeCentsNet"::float8 as "edgeCentsNet",
      l."kellyFraction"::float8 as kelly,
      l.tier::text        as tier,
      l."sampleN"         as "sampleN",
      l."runTs"           as "runTs",
      l."closeTime"       as "closeTime",
      l."priceAsOf"       as "priceAsOf",
      pr."pOverByStrike"  as "pOverByStrike",
      l.reason            as reason,
      coalesce((l.reason->>'implausible')::boolean, false) as implausible,
      l."modelVersion"    as "modelVersion"
    from latest l
    join "Projection" pr on pr.id = l."projectionId"
    left join "Player" p on p.id = pr."playerId"
    left join "Team" t on t.id = p."teamId"
    order by l."edgeCentsNet" desc
  `;

  // Repriced BEFORE the limit is applied. Cutting to the top N on the stored edge and
  // then repricing would rank by a number the board does not show -- a market whose
  // price moved into a real edge would be missing entirely, which is the one case
  // worth seeing.
  const book = await getLiveQuotes();
  const priced = rows.map((r) => reprice(r, book));
  priced.sort((a, b) => b.edgeCentsNet - a.edgeCentsNet);
  return priced.slice(0, limit);
}

/** Most recent successful run per job, for the staleness banner. */
export async function getJobHealth() {
  const rows = await prisma.pipelineRun.findMany({
    where: { status: "ok" },
    orderBy: { startedAt: "desc" },
    distinct: ["job"],
    select: { job: true, startedAt: true, finishedAt: true, rowsWritten: true },
  });
  return rows;
}

/**
 * What the last projection run saw. An empty board has three unrelated causes --
 * nothing listed for the upcoming week, listed but unquoted, or quotes gone stale
 * because the archiver stopped -- and they are indistinguishable to someone looking
 * at a blank page. The run already counted them, so the UI reads the count instead
 * of inventing an explanation.
 */
export async function getBoardStatus(): Promise<BoardStatus | null> {
  const run = await prisma.pipelineRun.findFirst({
    where: { job: "projection", status: "ok" },
    orderBy: { startedAt: "desc" },
    select: { meta: true, startedAt: true },
  });
  if (!run) return null;
  const meta = (run.meta ?? {}) as {
    mode?: string;
    census?: { listed?: number; quoted?: number; fresh?: number; max_price_age_mins?: number };
  };
  const c = meta.census;

  // The run's census was true when the run happened, which on a throttled scheduler
  // can be hours ago. The live book knows what is listed and quoted RIGHT NOW, so it
  // wins where it is available -- an empty board should explain the market as it is,
  // not as it was.
  const book = await getLiveQuotes();
  if (!book.error && book.seen > 0) {
    return {
      listed: book.seen,
      quoted: book.quoted,
      fresh: book.quoted,
      maxPriceAgeMins: 0,
      mode: "live",
      ranAt: book.fetchedAt,
    };
  }

  if (!c) return null;
  return {
    listed: c.listed ?? 0,
    quoted: c.quoted ?? 0,
    fresh: c.fresh ?? 0,
    maxPriceAgeMins: c.max_price_age_mins ?? 0,
    mode: meta.mode ?? null,
    ranAt: run.startedAt,
  };
}

export async function getTrackRecord() {
  const results = await prisma.signalResult.findMany({
    include: { signal: true },
    orderBy: { gradedTs: "desc" },
    take: 500,
  });
  return results;
}

/** Aggregate CLV by tier -- the number the whole project is judged on. */
export async function getClvSummary() {
  return prisma.$queryRaw<
    { tier: string; n: bigint; mean_clv: number | null; mean_pnl: number | null }[]
  >`
    select s.tier::text as tier,
           count(*)              as n,
           avg(r."clvCents")::float8  as mean_clv,
           avg(r."pnlIfBet")::float8  as mean_pnl
    from "SignalResult" r
    join "Signal" s on s.id = r."signalId"
    where r."clvCents" is not null
    group by s.tier
    order by s.tier
  `;
}


export type PlayerRow = {
  id: string;
  fullName: string;
  position: string | null;
  headshotUrl: string | null;
  team: string | null;
  depthPos: string | null;
  depthRank: number | null;
  isStarter: boolean;
  promotedFor: string | null;
};

/**
 * Depth-charted skill players. Starters first.
 *
 * 2,887 rostered players carry props for about 220 -- the rest never see a
 * meaningful snap. Depth rank is what separates them.
 */
export async function getPlayers(limit = 1200): Promise<PlayerRow[]> {
  return prisma.$queryRaw<PlayerRow[]>`
    select p.id, p."fullName", p.position, p."headshotUrl", t.abbrev as team,
           p."depthPos", p."depthRank", p."isStarter", p."promotedFor"
    from "Player" p
    left join "Team" t on t.id = p."teamId"
    where p."depthPos" is not null and p."teamId" is not null
    order by p."isStarter" desc,
      case p."depthPos" when 'QB' then 1 when 'RB' then 2
                        when 'WR' then 3 else 4 end,
      p."depthRank", p."fullName"
    limit ${limit}
  `;
}


/** Priced signals usable as parlay legs. */
export async function getParlayLegs(limit = 300) {
  return prisma.$queryRaw<
    {
      signalId: string; player: string; playerId: string; gameId: string;
      team: string | null; marketType: string; strike: number | null;
      side: string; modelProb: number; marketProb: number;
      headshotUrl: string | null; position: string | null;
    }[]
  >`
    with latest as (
      select distinct on (s."marketTicker") s.*
      from "Signal" s where s."closeTime" > now()
      order by s."marketTicker", s."runTs" desc
    )
    select
      l.id as "signalId",
      coalesce(p."fullName", 'unresolved') as player,
      coalesce(pr."playerId", '') as "playerId",
      coalesce(pr."gameId", '') as "gameId",
      t.abbrev as team,
      pr."marketType" as "marketType",
      nullif(regexp_replace(l."marketTicker", '^.*-', ''), '')::float8 as strike,
      l.side as side,
      l."modelProb"::float8 as "modelProb",
      l."marketProb"::float8 as "marketProb",
      p."headshotUrl" as "headshotUrl",
      p.position as position
    from latest l
    join "Projection" pr on pr.id = l."projectionId"
    left join "Player" p on p.id = pr."playerId"
    left join "Team" t on t.id = p."teamId"
    where coalesce((l.reason->>'implausible')::boolean, false) = false
    order by l."edgeCentsNet" desc
    limit ${limit}
  `;
}


export type SlateGame = {
  gameId: string;
  gameDate: Date;
  kickoff: string | null;
  week: number | null;
  homeTeam: string;
  awayTeam: string;
  venue: string | null;
  roof: string | null;
  isNeutral: boolean;
  divGame: boolean;
  totalLine: number | null;
  spreadLine: number | null;
  windMph: number | null;
  tempF: number | null;
  homeRest: number | null;
  awayRest: number | null;
  homeShortWeek: boolean;
  awayShortWeek: boolean;
  homePostBye: boolean;
  awayPostBye: boolean;
  signalCount: number;
  leanTeam: string | null;
  projMargin: number | null;
  leanConfident: boolean;
  leanDisagreement: number | null;
  leanWhy: string[] | null;
  homeColor: string | null;
  awayColor: string | null;
  homeLogo: string | null;
  awayLogo: string | null;
};

/**
 * The next slate: the earliestunplayed game date and everything sharing its week.
 * Rest, lines and venue come from GameContext/Game, both synced from nflverse.
 */
export async function getNextSlate(): Promise<SlateGame[]> {
  return prisma.$queryRaw<SlateGame[]>`
    with next_week as (
      select season, week from "Game"
      where "gameDate" >= current_date - interval '1 day'
      order by "gameDate" limit 1
    )
    select
      g.id as "gameId", g."gameDate", g."kickoffUtc"::text as kickoff, g.week,
      ht.abbrev as "homeTeam", at.abbrev as "awayTeam",
      ht.color as "homeColor", at.color as "awayColor",
      ht."logoUrl" as "homeLogo", at."logoUrl" as "awayLogo",
      g.venue, g.roof, g."isNeutral", g."divGame",
      g."totalLine", g."spreadLine", g."windMph", g."tempF",
      g."leanTeam", g."projMargin", g."leanConfident", g."leanDisagreement",
      g."leanWhy",
      hc."daysRest" as "homeRest", ac."daysRest" as "awayRest",
      coalesce(hc."isShortWeek", false) as "homeShortWeek",
      coalesce(ac."isShortWeek", false) as "awayShortWeek",
      coalesce(hc."isPostBye", false) as "homePostBye",
      coalesce(ac."isPostBye", false) as "awayPostBye",
      -- distinct on the TICKER, and open markets only. count(*) counted one row
      -- per run, so the Slate promised three times as many props as the board
      -- could show after three runs, and kept counting games already played.
      (select count(distinct s."marketTicker") from "Signal" s
        join "Projection" p on p.id = s."projectionId"
        where p."gameId" = g.id and s."closeTime" > now())::int as "signalCount"
    -- CROSS JOIN, not a comma: with "Game" g, next_week nw the following JOINs
    -- bind to next_week rather than to g, and the query fails to resolve g.
    from "Game" g
    join "Team" ht on ht.id = g."homeTeamId"
    join "Team" at on at.id = g."awayTeamId"
    left join "GameContext" hc on hc."gameId" = g.id and hc."teamId" = g."homeTeamId"
    left join "GameContext" ac on ac."gameId" = g.id and ac."teamId" = g."awayTeamId"
    cross join next_week nw
    where g.season = nw.season and g.week = nw.week
    order by g."gameDate", g.id
  `;
}

/** Highest-edge validated signals, for the slate's headline list. */
export async function getTopEdges(limit = 6) {
  return prisma.$queryRaw<
    { player: string; marketType: string; strike: number | null; side: string;
      edgeCentsNet: number; tier: string; headshotUrl: string | null }[]
  >`
    with latest as (
      select distinct on (s."marketTicker") s.*
      from "Signal" s where s."closeTime" > now()
      order by s."marketTicker", s."runTs" desc
    )
    select coalesce(p."fullName",'unresolved') as player,
           pr."marketType" as "marketType",
           nullif(regexp_replace(l."marketTicker", '^.*-', ''), '')::float8 as strike,
           l.side, l."edgeCentsNet"::float8 as "edgeCentsNet",
           l.tier::text as tier, p."headshotUrl" as "headshotUrl"
    from latest l
    join "Projection" pr on pr.id = l."projectionId"
    left join "Player" p on p.id = pr."playerId"
    where coalesce((l.reason->>'implausible')::boolean,false) = false
      and l."edgeCentsNet" > 0
    order by l."edgeCentsNet" desc
    limit ${limit}
  `;
}
