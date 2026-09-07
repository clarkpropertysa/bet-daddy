-- The injury report, and why a player carries no signal. Both existed only inside the
-- pipeline: the model refused to price players for reasons no page could state.
CREATE TABLE "Injury" (
    "id" TEXT NOT NULL,
    "playerId" TEXT NOT NULL,
    "season" INTEGER NOT NULL,
    "week" INTEGER NOT NULL,
    "reportStatus" TEXT,
    "practiceStatus" TEXT,
    "primaryInjury" TEXT,
    "pInactive" DECIMAL(6,4),
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Injury_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "Injury_playerId_season_week_key" ON "Injury"("playerId","season","week");
CREATE INDEX "Injury_season_week_idx" ON "Injury"("season","week");
ALTER TABLE "Injury" ADD CONSTRAINT "Injury_playerId_fkey"
  FOREIGN KEY ("playerId") REFERENCES "Player"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

CREATE TABLE "ProjectionRefusal" (
    "id" TEXT NOT NULL,
    "playerId" TEXT NOT NULL,
    "gameId" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "detail" TEXT NOT NULL,
    "runTs" TIMESTAMP(3) NOT NULL,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ProjectionRefusal_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "ProjectionRefusal_playerId_gameId_reason_key"
  ON "ProjectionRefusal"("playerId","gameId","reason");
CREATE INDEX "ProjectionRefusal_runTs_idx" ON "ProjectionRefusal"("runTs");
ALTER TABLE "ProjectionRefusal" ADD CONSTRAINT "ProjectionRefusal_playerId_fkey"
  FOREIGN KEY ("playerId") REFERENCES "Player"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
