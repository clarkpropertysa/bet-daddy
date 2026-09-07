-- The book has one width, and measuring it needs both yes quotes. Deriving the missing
-- one from marketProb returned exactly zero on every "no" pick, because 1 - no_ask is
-- yes_bid on a well-formed book -- so the spread gate never filtered an under.
ALTER TABLE "Signal" ADD COLUMN "yesAsk" DECIMAL(6,4);
