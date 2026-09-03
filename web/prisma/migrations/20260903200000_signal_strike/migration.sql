-- The market's real strike (Kalshi `floor_strike`), so the board stops parsing it off
-- the ticker suffix. The two differ by 0.5 on every count market, which displayed the
-- wrong line AND silently disabled live repricing: `Projection.pOverByStrike` is keyed
-- on the floor strike, so a lookup for "8" never matched the stored "7.5".
ALTER TABLE "Signal" ADD COLUMN "strike" DECIMAL(10,2);
