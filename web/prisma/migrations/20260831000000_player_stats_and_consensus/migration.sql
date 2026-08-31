-- Player history the web app can actually read. Raw Parquet is gitignored and the
-- deployed Next app has no DuckDB, so the player page needs these synced into Postgres.
CREATE TABLE "PlayerGameStat" (
    "id" TEXT NOT NULL,
    "playerId" TEXT NOT NULL,
    "gameId" TEXT NOT NULL,
    "season" INTEGER NOT NULL,
    "week" INTEGER NOT NULL,
    "team" TEXT NOT NULL,
    "opponent" TEXT,
    "offenseSnaps" INTEGER,
    "offensePct" DOUBLE PRECISION,
    "targets" INTEGER,
    "receptions" INTEGER,
    "receivingYards" DOUBLE PRECISION,
    "receivingTds" INTEGER,
    "airYards" DOUBLE PRECISION,
    "carries" INTEGER,
    "rushingYards" DOUBLE PRECISION,
    "rushingTds" INTEGER,
    "passingYards" DOUBLE PRECISION,
    "passingTds" INTEGER,
    "interceptions" INTEGER,
    "targetShare" DOUBLE PRECISION,
    "airYardsShare" DOUBLE PRECISION,
    "carryShare" DOUBLE PRECISION,
    "wopr" DOUBLE PRECISION,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PlayerGameStat_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "PlayerGameStat_playerId_gameId_key" ON "PlayerGameStat"("playerId", "gameId");
CREATE INDEX "PlayerGameStat_playerId_season_week_idx" ON "PlayerGameStat"("playerId", "season", "week");

-- Splits are stored WITH their gate flags rather than pre-filtered, so the UI can say
-- "no trustworthy split" instead of rendering a blank.
CREATE TABLE "PlayerSplit" (
    "id" TEXT NOT NULL,
    "playerId" TEXT NOT NULL,
    "teammateId" TEXT NOT NULL,
    "team" TEXT NOT NULL,
    "metric" TEXT NOT NULL,
    "season" INTEGER NOT NULL,
    "nWith" INTEGER NOT NULL,
    "nWithout" INTEGER NOT NULL,
    "meanWith" DOUBLE PRECISION NOT NULL,
    "meanWithout" DOUBLE PRECISION NOT NULL,
    "delta" DOUBLE PRECISION NOT NULL,
    "ciLow" DOUBLE PRECISION NOT NULL,
    "ciHigh" DOUBLE PRECISION NOT NULL,
    "significant" BOOLEAN NOT NULL,
    "suppressed" BOOLEAN NOT NULL,
    "confoundRegularsOut" BOOLEAN NOT NULL DEFAULT false,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PlayerSplit_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "PlayerSplit_playerId_teammateId_metric_season_key" ON "PlayerSplit"("playerId", "teammateId", "metric", "season");
CREATE INDEX "PlayerSplit_playerId_significant_idx" ON "PlayerSplit"("playerId", "significant");

-- Reference only: Kalshi's game price vs the consensus nflverse already ships.
-- Never a Signal, never an edge. Answers DECISIONS.md D8's own revisit trigger.
CREATE TABLE "GameMarketCompare" (
    "id" TEXT NOT NULL,
    "gameId" TEXT NOT NULL,
    "ts" TIMESTAMP(3) NOT NULL,
    "kalshiProbHome" DOUBLE PRECISION,
    "vegasProbHome" DOUBLE PRECISION,
    "diffPts" DOUBLE PRECISION,
    "kalshiOverround" DOUBLE PRECISION,
    "vegasOverround" DOUBLE PRECISION,
    "kalshiQuoted" BOOLEAN NOT NULL DEFAULT false,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "GameMarketCompare_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "GameMarketCompare_gameId_ts_key" ON "GameMarketCompare"("gameId", "ts");
CREATE INDEX "GameMarketCompare_gameId_ts_idx" ON "GameMarketCompare"("gameId", "ts");
