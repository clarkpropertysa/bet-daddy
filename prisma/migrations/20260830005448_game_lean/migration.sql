-- AlterTable
ALTER TABLE "Game" ADD COLUMN     "leanConfident" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "leanDisagreement" DOUBLE PRECISION,
ADD COLUMN     "leanTeam" TEXT,
ADD COLUMN     "leanWhy" JSONB,
ADD COLUMN     "projMargin" DOUBLE PRECISION;
