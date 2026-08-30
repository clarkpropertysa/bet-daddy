-- AlterTable
ALTER TABLE "Player" ADD COLUMN     "depthPos" TEXT,
ADD COLUMN     "depthRank" INTEGER,
ADD COLUMN     "isStarter" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "promotedFor" TEXT;
