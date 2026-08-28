-- CreateEnum
CREATE TYPE "Sport" AS ENUM ('nfl', 'nba');

-- CreateEnum
CREATE TYPE "MatchMethod" AS ENUM ('EXACT', 'FALLBACK', 'MANUAL', 'UNRESOLVED');

-- CreateEnum
CREATE TYPE "Tier" AS ENUM ('UNVALIDATED', 'PROVISIONAL', 'VALIDATED');

-- CreateEnum
CREATE TYPE "RunStatus" AS ENUM ('ok', 'pending', 'error');

-- CreateTable
CREATE TABLE "Team" (
    "id" TEXT NOT NULL,
    "sport" "Sport" NOT NULL,
    "abbrev" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "conference" TEXT,
    "division" TEXT,
    "venue" TEXT,
    "timezone" TEXT,
    "altitudeFt" INTEGER,

    CONSTRAINT "Team_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Player" (
    "id" TEXT NOT NULL,
    "sport" "Sport" NOT NULL,
    "fullName" TEXT NOT NULL,
    "position" TEXT,
    "teamId" TEXT,
    "gsisId" TEXT,
    "nbaPersonId" INTEGER,
    "externalIds" JSONB NOT NULL DEFAULT '{}',
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Player_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PlayerAlias" (
    "id" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "rawKey" TEXT NOT NULL,
    "team" TEXT NOT NULL,
    "firstInit" TEXT NOT NULL,
    "surname" TEXT NOT NULL,
    "jerseyNum" INTEGER,
    "playerId" TEXT,
    "method" "MatchMethod" NOT NULL,
    "confidence" DOUBLE PRECISION NOT NULL,
    "firstSeen" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastSeen" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "PlayerAlias_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Game" (
    "id" TEXT NOT NULL,
    "sport" "Sport" NOT NULL,
    "season" INTEGER NOT NULL,
    "week" INTEGER,
    "gameDate" TIMESTAMP(3) NOT NULL,
    "kickoffUtc" TIMESTAMP(3),
    "homeTeamId" TEXT NOT NULL,
    "awayTeamId" TEXT NOT NULL,
    "venue" TEXT,
    "roof" TEXT,
    "surface" TEXT,
    "isNeutral" BOOLEAN NOT NULL DEFAULT false,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Game_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "GameContext" (
    "id" TEXT NOT NULL,
    "gameId" TEXT NOT NULL,
    "teamId" TEXT NOT NULL,
    "daysRest" INTEGER,
    "isB2b" BOOLEAN NOT NULL DEFAULT false,
    "b2bLeg" INTEGER,
    "gamesInLast4" INTEGER,
    "gamesInLast6" INTEGER,
    "travelMiles" DOUBLE PRECISION,
    "tzShift" INTEGER,
    "isPostBye" BOOLEAN NOT NULL DEFAULT false,
    "isShortWeek" BOOLEAN NOT NULL DEFAULT false,
    "altitudeFt" INTEGER,
    "windMph" DOUBLE PRECISION,
    "tempF" DOUBLE PRECISION,
    "precip" DOUBLE PRECISION,
    "projectedTotal" DOUBLE PRECISION,
    "projectedSpread" DOUBLE PRECISION,
    "projectedPossessions" DOUBLE PRECISION,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "GameContext_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MarketSnapshot" (
    "id" BIGSERIAL NOT NULL,
    "marketTicker" TEXT NOT NULL,
    "seriesTicker" TEXT NOT NULL,
    "eventTicker" TEXT,
    "sport" "Sport" NOT NULL,
    "marketType" TEXT NOT NULL,
    "ts" TIMESTAMP(3) NOT NULL,
    "yesBid" DECIMAL(6,4),
    "yesAsk" DECIMAL(6,4),
    "lastPrice" DECIMAL(6,4),
    "volume" DECIMAL(18,4),
    "openInterest" DECIMAL(18,4),
    "strike" DOUBLE PRECISION,
    "status" TEXT,
    "closeTime" TIMESTAMP(3),
    "minsToClose" INTEGER,
    "result" TEXT,
    "orderbook" JSONB,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "MarketSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MarketSettlement" (
    "marketTicker" TEXT NOT NULL,
    "settledTs" TIMESTAMP(3) NOT NULL,
    "result" TEXT NOT NULL,
    "settlementValue" DECIMAL(18,4),
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "MarketSettlement_pkey" PRIMARY KEY ("marketTicker")
);

-- CreateTable
CREATE TABLE "Projection" (
    "id" TEXT NOT NULL,
    "playerId" TEXT NOT NULL,
    "gameId" TEXT NOT NULL,
    "marketType" TEXT NOT NULL,
    "modelVersion" TEXT NOT NULL,
    "runTs" TIMESTAMP(3) NOT NULL,
    "mean" DOUBLE PRECISION NOT NULL,
    "stdev" DOUBLE PRECISION NOT NULL,
    "distribution" JSONB NOT NULL,
    "pOverByStrike" JSONB NOT NULL,
    "featureAsOf" TIMESTAMP(3) NOT NULL,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Projection_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Signal" (
    "id" TEXT NOT NULL,
    "projectionId" TEXT NOT NULL,
    "marketTicker" TEXT NOT NULL,
    "runTs" TIMESTAMP(3) NOT NULL,
    "modelProb" DECIMAL(6,4) NOT NULL,
    "marketProb" DECIMAL(6,4) NOT NULL,
    "feeCents" DECIMAL(8,4) NOT NULL,
    "edgeCentsNet" DECIMAL(8,4) NOT NULL,
    "kellyFraction" DECIMAL(6,4) NOT NULL,
    "tier" "Tier" NOT NULL,
    "sampleN" INTEGER NOT NULL,
    "reason" JSONB NOT NULL,
    "modelVersion" TEXT NOT NULL,
    "featureAsOf" TIMESTAMP(3) NOT NULL,
    "source" TEXT NOT NULL,
    "ingestedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Signal_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SignalResult" (
    "signalId" TEXT NOT NULL,
    "closingPrice" DECIMAL(6,4),
    "clvCents" DECIMAL(8,4),
    "settledResult" TEXT,
    "pnlIfBet" DECIMAL(10,4),
    "gradedTs" TIMESTAMP(3),

    CONSTRAINT "SignalResult_pkey" PRIMARY KEY ("signalId")
);

-- CreateTable
CREATE TABLE "PipelineRun" (
    "id" TEXT NOT NULL,
    "job" TEXT NOT NULL,
    "startedAt" TIMESTAMP(3) NOT NULL,
    "finishedAt" TIMESTAMP(3),
    "status" "RunStatus" NOT NULL,
    "rowsWritten" INTEGER NOT NULL DEFAULT 0,
    "error" TEXT,
    "meta" JSONB,

    CONSTRAINT "PipelineRun_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Team_sport_abbrev_key" ON "Team"("sport", "abbrev");

-- CreateIndex
CREATE UNIQUE INDEX "Player_gsisId_key" ON "Player"("gsisId");

-- CreateIndex
CREATE UNIQUE INDEX "Player_nbaPersonId_key" ON "Player"("nbaPersonId");

-- CreateIndex
CREATE INDEX "Player_sport_fullName_idx" ON "Player"("sport", "fullName");

-- CreateIndex
CREATE INDEX "PlayerAlias_playerId_idx" ON "PlayerAlias"("playerId");

-- CreateIndex
CREATE INDEX "PlayerAlias_method_idx" ON "PlayerAlias"("method");

-- CreateIndex
CREATE UNIQUE INDEX "PlayerAlias_source_rawKey_key" ON "PlayerAlias"("source", "rawKey");

-- CreateIndex
CREATE INDEX "Game_sport_season_week_idx" ON "Game"("sport", "season", "week");

-- CreateIndex
CREATE INDEX "Game_gameDate_idx" ON "Game"("gameDate");

-- CreateIndex
CREATE UNIQUE INDEX "GameContext_gameId_teamId_key" ON "GameContext"("gameId", "teamId");

-- CreateIndex
CREATE INDEX "MarketSnapshot_marketTicker_minsToClose_idx" ON "MarketSnapshot"("marketTicker", "minsToClose");

-- CreateIndex
CREATE INDEX "MarketSnapshot_sport_marketType_ts_idx" ON "MarketSnapshot"("sport", "marketType", "ts");

-- CreateIndex
CREATE UNIQUE INDEX "MarketSnapshot_marketTicker_ts_key" ON "MarketSnapshot"("marketTicker", "ts");

-- CreateIndex
CREATE INDEX "Projection_playerId_gameId_marketType_idx" ON "Projection"("playerId", "gameId", "marketType");

-- CreateIndex
CREATE INDEX "Projection_runTs_idx" ON "Projection"("runTs");

-- CreateIndex
CREATE INDEX "Signal_marketTicker_runTs_idx" ON "Signal"("marketTicker", "runTs");

-- CreateIndex
CREATE INDEX "Signal_tier_runTs_idx" ON "Signal"("tier", "runTs");

-- CreateIndex
CREATE INDEX "PipelineRun_job_startedAt_idx" ON "PipelineRun"("job", "startedAt");

-- AddForeignKey
ALTER TABLE "Player" ADD CONSTRAINT "Player_teamId_fkey" FOREIGN KEY ("teamId") REFERENCES "Team"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PlayerAlias" ADD CONSTRAINT "PlayerAlias_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "Player"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GameContext" ADD CONSTRAINT "GameContext_gameId_fkey" FOREIGN KEY ("gameId") REFERENCES "Game"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Signal" ADD CONSTRAINT "Signal_projectionId_fkey" FOREIGN KEY ("projectionId") REFERENCES "Projection"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SignalResult" ADD CONSTRAINT "SignalResult_signalId_fkey" FOREIGN KEY ("signalId") REFERENCES "Signal"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
