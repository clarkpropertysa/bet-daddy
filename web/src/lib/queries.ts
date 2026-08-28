import { prisma } from "@/lib/db";

export type BoardRow = {
  signalId: string;
  marketTicker: string;
  player: string;
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
      p.position          as position,
      t.abbrev            as team,
      pr."marketType"     as "marketType",
      ms.strike           as strike,
      'yes'               as side,
      l."modelProb"::float8   as "modelProb",
      l."marketProb"::float8  as "marketProb",
      l."feeCents"::float8    as "feeCents",
      l."edgeCentsNet"::float8 as "edgeCentsNet",
      l."kellyFraction"::float8 as kelly,
      l.tier::text        as tier,
      l."sampleN"         as "sampleN",
      l."runTs"           as "runTs",
      l.reason            as reason
    from latest l
    join "Projection" pr on pr.id = l."projectionId"
    left join "Player" p on p.id = pr."playerId"
    left join "Team" t on t.id = p."teamId"
    left join lateral (
      select strike from "MarketSnapshot"
      where "marketTicker" = l."marketTicker"
      order by ts desc limit 1
    ) ms on true
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
