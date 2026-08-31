/**
 * The board's per-game filter spans two identifier spaces.
 *
 * Projection.gameId holds a Kalshi event ticker (26SEP09NESEA); the Slate links an
 * nflverse game id (2026_01_NE_SEA). Nothing mapped between them, so getBoard accepted
 * a `gameId` and silently ignored it -- the page rendered a "Showing props for NE at
 * SEA" chip above the entire league's board. These pin the mapping, including the two
 * alias cases that have already caused a franchise to disappear once.
 */
import { tickerMatchesGame, gameFromTicker } from "../src/lib/markets.ts";

let fails = 0;
const check = (n, c, d = "") => {
  if (!c) { fails++; console.log(`  FAIL ${n} ${d}`); } else console.log(`  ok   ${n} ${d}`);
};

console.log("=== ticker <-> nflverse game id ===");
check("same game matches", tickerMatchesGame("KXNFLPASSYDS-26SEP09NESEA-X-1", "2026_01_NE_SEA"));
check("different game does not", !tickerMatchesGame("KXNFLPASSYDS-26SEP09NESEA-X-1", "2026_01_TB_CIN"));
check("home/away reversed does not", !tickerMatchesGame("KXNFLPASSYDS-26SEP09NESEA-X-1", "2026_01_SEA_NE"));

console.log("\n=== the alias cases that have bitten before ===");
check("Kalshi JAC == nflverse JAX", tickerMatchesGame("KXNFLRECYDS-26SEP13CLEJAC-X-70", "2026_01_CLE_JAX"));
check("Kalshi LAR == nflverse LA", tickerMatchesGame("KXNFLGAME-26SEP21NYGLAR-NYG", "2026_03_NYG_LA"));
check("unequal-length codes split correctly", tickerMatchesGame("KXNFLPASSYDS-26SEP13ARILV-X-1", "2026_01_ARI_LV"));

console.log("\n=== malformed input is false, never a throw ===");
check("garbage ticker", !tickerMatchesGame("GARBAGE", "2026_01_NE_SEA"));
check("garbage game id", !tickerMatchesGame("KXNFLPASSYDS-26SEP09NESEA-X-1", "nonsense"));
check("empty strings", !tickerMatchesGame("", ""));

console.log("\n=== labels come from the right parser ===");
const lbl = gameFromTicker("KXNFLPASSYDS-26SEP09NESEA-X-1")?.label;
check("Kalshi ticker -> readable label", lbl === "NE at SEA, Sep 9", lbl);

console.log(fails === 0 ? "\nALL CHECKS PASS" : `\n${fails} FAILED`);
process.exit(fails ? 1 : 0);
