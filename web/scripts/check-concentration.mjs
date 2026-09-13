/**
 * A list of picks that is really one bet on one game must say so.
 *
 * Week 2: four of the ten Top Picks were Arizona at the Chargers -- Chargers receiver
 * unders and a Cardinals over, which is one game script ("Arizona keeps it close")
 * whatever the yes/no of each row. The first banner tested "same side" and would have
 * read that block as split.
 */
import { scriptConcentration } from "../src/lib/concentration.ts";
import { gameFromTicker } from "../src/lib/markets.ts";

let fails = 0;
const check = (n, c, d = "") => {
  if (!c) { fails++; console.log(`  FAIL ${n} ${d}`); } else console.log(`  ok   ${n} ${d}`);
};
const row = (game, team, side, i = 0) =>
  ({ marketTicker: `KXNFLREC-${game}-P${i}-5`, team, side });

console.log("=== one game script, read by lean rather than by side ===");
const week2 = [
  row("26SEP13DENKC", "KC", "no", 1),
  row("26SEP13GBMIN", "GB", "no", 2),
  row("26SEP13MIALV", "LV", "no", 3),
  row("26SEP13ARILAC", "LAC", "no", 4),   // Chargers under -> leans ARI
  row("26SEP13ARILAC", "LAC", "no", 5),   // Chargers under -> leans ARI
  row("26SEP13ARILAC", "LAC", "no", 6),   // Chargers under -> leans ARI
  row("26SEP13ARILAC", "ARI", "yes", 7),  // Cardinals over -> leans ARI
  row("26SEP13GBMIN", "MIN", "no", 8),
  row("26SEP13GBMIN", "GB", "yes", 9),
  row("26SEP13DALNYG", "DAL", "no", 10),
];
const got = scriptConcentration(week2, gameFromTicker, "picks");
check("Arizona at the Chargers is flagged", got?.headline.includes("ARI at LAC"), got?.headline);
check("all four lean the same way, toward ARI", got?.headline.includes("4 of those lean the same way, toward ARI"));

console.log("\n=== a genuinely split game is not one script ===");
const split = [
  row("26SEP13ARILAC", "LAC", "yes", 1),  // leans LAC
  row("26SEP13ARILAC", "LAC", "no", 2),   // leans ARI
  row("26SEP13ARILAC", "ARI", "yes", 3),  // leans ARI
  row("26SEP13ARILAC", "ARI", "no", 4),   // leans LAC
  row("26SEP13GBMIN", "GB", "yes", 5),
  row("26SEP13DENKC", "KC", "no", 6),
  row("26SEP13MIALV", "LV", "yes", 7),
  row("26SEP13DALNYG", "DAL", "no", 8),
  row("26SEP13NYJTEN", "TEN", "yes", 9),
  row("26SEP13BUFHOU", "BUF", "no", 10),
];
check("a 2-2 game and a balanced slate stay quiet", scriptConcentration(split, gameFromTicker) === null);

console.log("\n=== slate-wide tilt when no single game dominates ===");
const tilt = ["DENKC", "GBMIN", "MIALV", "ARILAC", "DALNYG", "NYJTEN", "BUFHOU", "NODET", "TBCIN", "CHICAR"]
  .map((g, i) => row(`26SEP13${g}`, null, i < 8 ? "no" : "yes", i));
const t = scriptConcentration(tilt, gameFromTicker, "picks");
check("8 of 10 unders across ten games is flagged", t?.headline === "8 of the top 10 picks are unders.", t?.headline);

console.log("\n=== the spellings that have bitten before ===");
const jax = [1, 2, 3].map((i) => row("26SEP13CLEJAC", "JAX", "yes", i))
  .concat([4, 5, 6, 7].map((i) => row(`26SEP13${["DENKC", "GBMIN", "MIALV", "DALNYG"][i - 4]}`, null, i % 2 ? "yes" : "no", i)));
const j = scriptConcentration(jax, gameFromTicker);
check("nflverse JAX is placed in a Kalshi JAC game", j?.headline.includes("toward JAX"), j?.headline);

console.log("\n=== too short to mean anything ===");
check("four rows is never a pattern", scriptConcentration(week2.slice(3, 7), gameFromTicker) === null);

console.log(fails ? `\n${fails} FAILED` : "\nALL CHECKS PASS");
process.exit(fails ? 1 : 0);
