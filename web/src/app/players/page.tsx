import { PageHeader } from "@/components/PageHeader";
import { PlayerGrid } from "@/components/PlayerGrid";
import { Empty } from "@/components/Empty";
import { getPlayers } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function PlayersPage() {
  const players = await getPlayers();
  return (
    <div>
      <PageHeader
        title="Players"
        sub="Active skill-position players on 2026 rosters, from nflverse."
      />
      {players.length === 0 ? (
        <Empty
          title="No players loaded"
          source="Player (Neon)"
          hint="Run pipeline.ingest.sync_reference to populate teams, players and games."
        />
      ) : (
        <PlayerGrid players={players} />
      )}
    </div>
  );
}
