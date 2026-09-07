-- Actual kickoff, so the board can stop serving picks for games already played.
-- Kalshi's close_time is a settlement deadline about two days after kickoff, and the
-- board was filtering on it: a Wednesday-night game stayed listed until Saturday.
ALTER TABLE "Signal" ADD COLUMN "kickoff" TIMESTAMP(3);
CREATE INDEX "Signal_kickoff_idx" ON "Signal"("kickoff");
