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
        index="02"
        title="Players"
        sub="Depth-charted skill players on 2026 rosters. Starters only by default — QB1, RB1-2, WR1-3, TE1 — since the rest never draw a priceable snap. When a starter is ruled out, his backup is promoted and labelled."
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
