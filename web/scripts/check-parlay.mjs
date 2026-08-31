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

console.log("\n=== same team is NOT one relationship ===");
// This replaced a single sameTeam=0.30 that was applied to every same-team pair.
// Measured over 2024-25: a quarterback and his receiver do move together (+0.30), but
// two receivers compete for the same targets (-0.02) and two backs split the same
// carries (-0.15). Treating those as +0.30 overstates the joint probability, which is
// the direction that flatters the ticket.
const qbWr = rateParlay([
  leg({id:"a", pid:"QB", t:"SF", g:"G1", m:"pass_yds", p:0.6}),
  leg({id:"b", pid:"WR", t:"SF", g:"G1", m:"rec_yds", p:0.6}),
]);
check("passer + his receiver correlates", Math.abs(qbWr.meanRho - RHO.passerToReceiver) < 1e-9, `rho=${qbWr.meanRho}`);

const twoWr = rateParlay([
  leg({id:"a", pid:"W1", t:"SF", g:"G1", m:"rec_yds", p:0.6}),
  leg({id:"b", pid:"W2", t:"SF", g:"G1", m:"receptions", p:0.6}),
]);
check("two receivers do NOT stack", Math.abs(twoWr.meanRho - RHO.sameTeamOther) < 1e-9, `rho=${twoWr.meanRho}`);

const twoRb = rateParlay([
  leg({id:"a", pid:"R1", t:"SF", g:"G1", m:"rush_yds", p:0.6}),
  leg({id:"b", pid:"R2", t:"SF", g:"G1", m:"rush_yds", p:0.6}),
]);
check("two backs are NEGATIVELY correlated", twoRb.meanRho < 0, `rho=${twoRb.meanRho}`);

console.log("\n=== a correlated stack must beat an uncorrelated one ===");
// The reason correlation is modelled at all: positively correlated legs hit together
// more often than independence implies, negatively correlated legs less often.
check("qb+wr joint > two-back joint", qbWr.joint > twoRb.joint,
      `${qbWr.joint.toFixed(4)} vs ${twoRb.joint.toFixed(4)}`);

console.log("\n=== opposing quarterbacks ===");
const shootout = rateParlay([
  leg({id:"a", pid:"Q1", t:"SF", g:"G1", m:"pass_yds", p:0.6}),
  leg({id:"b", pid:"Q2", t:"LA", g:"G1", m:"pass_yds", p:0.6}),
]);
check("opposing passers correlate mildly", Math.abs(shootout.meanRho - RHO.opposingPassers) < 1e-9, `rho=${shootout.meanRho}`);
check("less than a same-team stack", shootout.meanRho < RHO.passerToReceiver);

console.log(fails===0 ? "\nALL CHECKS PASS" : `\n${fails} FAILED`);
process.exit(fails?1:0);
