-- The board filters on closeTime so a signal stops being served when its game
-- starts. Nullable on purpose: signals written before the live board existed have
-- no close time, and `closeTime > now()` is false for NULL, so they drop out
-- rather than needing a backfill.
ALTER TABLE "Signal" ADD COLUMN "closeTime" TIMESTAMP(3);
ALTER TABLE "Signal" ADD COLUMN "priceAsOf" TIMESTAMP(3);
CREATE INDEX "Signal_closeTime_idx" ON "Signal"("closeTime");
