-- Liquidity, so the board can tell a market from a resting offer. All three are
-- already captured on every archive snapshot and none had ever been read downstream.
ALTER TABLE "Signal" ADD COLUMN "yesBid" DECIMAL(6,4);
ALTER TABLE "Signal" ADD COLUMN "volume" DECIMAL(18,4);
ALTER TABLE "Signal" ADD COLUMN "openInterest" DECIMAL(18,4);
