import Link from "next/link";
import { notFound } from "next/navigation";
import { Empty } from "@/components/Empty";
import { GameLog } from "@/components/GameLog";
import { PageHeader } from "@/components/PageHeader";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { PropBoard, type Row } from "@/components/PropBoard";
import { SplitsPanel } from "@/components/SplitsPanel";
import { labelFor } from "@/lib/markets";
import {
  getPlayer,
  getPlayerGameLog,
  getPlayerMarkets,
  getPlayerSplits,
  type GameLogRow,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

/** Which stat a market family settles on, so a hit rate counts the right column. */
const OUTCOME: Record<string, keyof GameLogRow> = {
  rec_yds: "receivingYards",
  receptions: "receptions",
  rush_yds: "rushingYards",
  pass_yds: "passingYards",
  pass_tds: "passingTds",
};

/**
 * How often this player cleared a line, in the games we have.
 *
 * Strict "more than", matching how the market settles -- an exact number is a loss,
 * not a push. Returns null below four games rather than reporting "1 of 2", which reads
 * as 50% and means nothing.
 */
function clearance(rows: GameLogRow[], marketType: string, strike: number | null) {
  const key = OUTCOME[marketType];
  if (!key || strike === null) return null;
  const vals = rows
    .map((r) => r[key])
    .filter((v): v is number => typeof v === "number");
  if (vals.length < 4) return null;
  return { hits: vals.filter((v) => v > strike).length, n: vals.length };
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ gsisId: string }>;
}) {
  const { gsisId } = await params;
  const player = await getPlayer(decodeURIComponent(gsisId));
  if (!player) notFound();

  const [log, splits, markets] = await Promise.all([
    getPlayerGameLog(player.gsisId),
    getPlayerSplits(player.gsisId),
    getPlayerMarkets(player.gsisId),
  ]);

  const season = log[0]?.season ?? null;
  // History accumulated at another team describes a role this player no longer holds --
  // the same failure the starter filter exists to prevent. Say it plainly.
  const loggedTeams = [...new Set(log.map((r) => r.team))];
  const movedTeams =
    player.team !== null && loggedTeams.length > 0 && !loggedTeams.includes(player.team);

  const role = [player.depthPos, player.depthRank].filter(Boolean).join("");

  return (
    <div>
      <PageHeader
        title={player.fullName}
        sub={
          [
            player.teamName ?? player.team,
            role && `depth ${role}`,
            player.isStarter ? "starter" : "backup",
          ]
            .filter(Boolean)
            .join(" · ") || undefined
        }
        right={
          <Link href="/players" className="text-[11px] text-steel underline-offset-2 hover:underline">
            ← all players
          </Link>
        }
      />

      <div className="mb-4 flex items-center gap-3 rounded border border-line bg-card px-4 py-3">
        <PlayerAvatar name={player.fullName} url={player.headshotUrl} size={44} />
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-ink">{player.fullName}</p>
          <p className="text-[11.5px] text-ink-2">
            {player.position ?? "—"} · {player.team ?? "no team"}
            {role ? ` · ${role} on the depth chart` : ""}
          </p>
          {player.promotedFor && (
            <p className="mt-0.5 text-[11px] text-warn">
              in for {player.promotedFor}
            </p>
          )}
        </div>
      </div>

      {movedTeams && (
        <div className="mb-4 rounded border border-warn/50 bg-warn/[0.07] px-4 py-3">
          <p className="text-[11.5px] leading-relaxed text-warn">
            <strong className="font-semibold">Different team.</strong> The history below
            was accumulated at {loggedTeams.join(", ")}, and {player.fullName} is now
            listed with {player.team}. Usage describes the role he had there, not the one
            he has now.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <section>
            <h2 className="display mb-2 text-[14px] text-ink">Open markets</h2>
            {markets.length > 0 ? (
              <PropBoard rows={markets as unknown as Row[]} />
            ) : (
              /* PropBoard's own empty state explains the board-wide census, which is
                 the wrong question here -- the board can be full while this one player
                 has nothing priced. */
              <Empty
                title="No open markets for this player"
                source="Signal (Neon)"
                hint={`Either no market for ${player.fullName} is currently quoted, or the projection refused it — a backup's usage describes a role he no longer holds, and too little history is refused rather than guessed. The Prop Board shows what is priced across the league.`}
              />
            )}
          </section>

          {log.length > 0 ? (
            <GameLog rows={log} position={player.position} />
          ) : (
            <section className="rounded border border-dashed border-line-2 bg-card px-4 py-6">
              <p className="text-[12px] leading-relaxed text-ink-2">
                No game log for this player. Either he has not played a regular-season
                snap in a synced season, or his usage never crossed the threshold that
                records a row.
              </p>
            </section>
          )}
        </div>

        <div className="space-y-4">
          <SplitsPanel splits={splits} />

          {markets.length > 0 && season !== null && (
            <section className="rounded border border-line bg-card">
              <div className="border-b border-line px-4 py-3">
                <h2 className="display text-[14px] text-ink">Against these lines</h2>
                <p className="eyebrow mt-0.5">{season} · context, not the reason</p>
              </div>
              <ul className="divide-y divide-line-2">
                {markets.map((m) => {
                  const c = clearance(log, m.marketType, m.strike);
                  return (
                    <li key={m.signalId} className="px-4 py-2.5">
                      <p className="text-[12px] text-ink">
                        {labelFor(m.marketType)} {m.strike ?? "—"}
                      </p>
                      <p className="mt-0.5 text-[11px] text-ink-2">
                        {c
                          ? `cleared in ${c.hits} of ${c.n} games`
                          : "too few games to count"}
                      </p>
                    </li>
                  );
                })}
              </ul>
              {/* rationale.py frames a hit rate this way and the page must not
                  quietly upgrade it into a reason. */}
              <p className="border-t border-line px-4 py-3 text-[11px] leading-relaxed text-ink-3">
                A hit rate is what happened, not what the model predicts. It ignores
                opponent, role changes and game script — all of which the projection
                accounts for and this count does not.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
