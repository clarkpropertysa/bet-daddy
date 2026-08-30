import { prisma } from "@/lib/db";

export type BoardRow = {
  signalId: string;
  marketTicker: string;
  player: string;
  headshotUrl: string | null;
  position: string | null;
  team: string | null;
  marketType: string;
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
  reason: unknown;
  implausible: boolean;
  modelVersion: string;
};

/** Latest signal per market, newest first. One row per market, not per run. */
export async function getBoard(limit = 200): Promise<BoardRow[]> {
  const rows = await prisma.$queryRaw<BoardRow[]>`
    with latest as (
      select distinct on (s."marketTicker") s.*
      from "Signal" s
      order by s."marketTicker", s."runTs" desc
    )
    select
      l.id                as "signalId",
      l."marketTicker"    as "marketTicker",
      coalesce(p."fullName", 'unresolved') as player,
      p."headshotUrl"     as "headshotUrl",
      p.position          as position,
      t.abbrev            as team,
      pr."marketType"     as "marketType",
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
      l.reason            as reason,
      coalesce((l.reason->>'implausible')::boolean, false) as implausible,
      l."modelVersion"    as "modelVersion"
    from latest l
    join "Projection" pr on pr.id = l."projectionId"
    left join "Player" p on p.id = pr."playerId"
    left join "Team" t on t.id = p."teamId"
    order by l."edgeCentsNet" desc
    limit ${limit}
  `;
  return rows;
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
};

/** Rostered skill-position players, for the player index. */
export async function getPlayers(limit = 400): Promise<PlayerRow[]> {
  return prisma.$queryRaw<PlayerRow[]>`
    select p.id, p."fullName", p.position, p."headshotUrl", t.abbrev as team
    from "Player" p
    left join "Team" t on t.id = p."teamId"
    where p.position in ('QB','RB','WR','TE')
      and p."teamId" is not null
    order by
      case p.position when 'QB' then 1 when 'RB' then 2
                      when 'WR' then 3 else 4 end,
      p."fullName"
    limit ${limit}
  `;
}
