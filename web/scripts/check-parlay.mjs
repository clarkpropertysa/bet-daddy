/**
 * Parlay math checks.
 *
 * The correlation model is the whole point of this module and it can fail SILENTLY:
 * a wrong gameId made every leg look like it was in a different game, which zeroed
 * all correlation while still returning plausible numbers. These assertions pin the
 * behaviour that bug slipped past.
 *
 *   node --experimental-strip-types scripts/check-parlay.mjs
 */
import { rateParlay, contradictoryPairs, RHO } from "../src/lib/parlay.ts";
const leg = (o) => ({
  signalId: o.id, player: o.pl ?? o.id, playerId: o.pid ?? o.id, gameId: o.g ?? "G1",
  team: o.t ?? "AAA", marketType: o.m ?? "pass_yds", strike: o.s ?? 50,
  side: o.side ?? "yes", modelProb: o.p, marketProb: o.p,
});
let fails = 0;
const check = (n, c, d="") => { if(!c){fails++;console.log(`  FAIL ${n} ${d}`);} else console.log(`  ok   ${n} ${d}`); };

console.log("=== same player, same game now correlates ===");
const r = rateParlay([
  leg({id:"a", pid:"P1", g:"26SEP10SFLAR", m:"pass_yds", s:250, p:0.6}),
  leg({id:"b", pid:"P1", g:"26SEP10SFLAR", m:"pass_tds", s:1, p:0.5}),
]);
check("meanRho = samePlayer", Math.abs(r.meanRho - RHO.samePlayer) < 1e-9, `rho=${r.meanRho}`);
check("joint > product", r.joint > r.independent, `${r.joint.toFixed(4)} > ${r.independent.toFixed(4)}`);

console.log("\n=== over 100 and under 75, same player+game: impossible ===");
const bad = rateParlay([
  leg({id:"a", pid:"P1", g:"G1", m:"pass_yds", s:100, side:"yes", p:0.5}),
  leg({id:"b", pid:"P1", g:"G1", m:"pass_yds", s:75, side:"no", p:0.4}),
]);
check("flagged contradictory", bad.contradictions.length === 1);
check("joint = 0", bad.joint === 0, `joint=${bad.joint}`);

console.log("\n=== over 50 / under 100 same player+game is NOT contradictory ===");
const okpair = rateParlay([
  leg({id:"a", pid:"P1", g:"G1", m:"pass_yds", s:50, side:"yes", p:0.7}),
  leg({id:"b", pid:"P1", g:"G1", m:"pass_yds", s:100, side:"no", p:0.6}),
]);
check("not flagged", okpair.contradictions.length === 0);
check("joint > 0", okpair.joint > 0, `joint=${okpair.joint.toFixed(4)}`);

console.log("\n=== same player, DIFFERENT games stays independent ===");
const diff = rateParlay([
  leg({id:"a", pid:"P1", g:"G1", p:0.6}), leg({id:"b", pid:"P1", g:"G2", p:0.5}),
]);
check("rho = 0", diff.meanRho === 0);
check("no contradiction", diff.contradictions.length === 0);

console.log("\n=== same team, different players correlates ===");
const team = rateParlay([
  leg({id:"a", pid:"P1", t:"SF", g:"G1", p:0.6}), leg({id:"b", pid:"P2", t:"SF", g:"G1", p:0.6}),
]);
check("rho = sameTeam", Math.abs(team.meanRho - RHO.sameTeam) < 1e-9, `rho=${team.meanRho}`);

console.log(fails===0 ? "\nALL CHECKS PASS" : `\n${fails} FAILED`);
process.exit(fails?1:0);
