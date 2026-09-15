/**
 * A pick is ranked on the model blended with the market, at the weight the model earned.
 *
 * The property that matters most: at weight zero NOTHING is a pick. The anchored edge is
 * then mid - ask - fee, negative on any book with a spread, so an empty Top Picks is the
 * correct output of a model that has not beaten the price -- not a bug.
 */
import { anchorFit, anchorWeight, anchoredEdge } from "../src/lib/anchor.ts";

let fails = 0;
const check = (n, c, d = "") => {
  if (!c) { fails++; console.log(`  FAIL ${n} ${d}`); } else console.log(`  ok   ${n} ${d}`);
};
const near = (a, b, tol = 1e-9) => Math.abs(a - b) < tol;

// A yes pick: model 70%, book 0.45/0.47, pays the 0.47 ask, 1.75c fee.
const yesPick = { side: "yes", modelProb: 0.7, marketProb: 0.47, feeCents: 1.75, yesAsk: 0.47, yesBid: 0.45 };
// A no pick on the same book: pays 1 - 0.45 = 0.55.
const noPick = { side: "no", modelProb: 0.7, marketProb: 0.55, feeCents: 1.73, yesAsk: 0.47, yesBid: 0.45 };

console.log("=== weight zero: the market, and no pick can exist ===");
for (const [label, p] of [["yes side", yesPick], ["no side", noPick]]) {
  const e = anchoredEdge({ ...p, weight: 0 });
  check(`${label} is negative`, e.edgeCents < 0, `${e.edgeCents.toFixed(2)}c`);
  check(`${label} costs exactly half the spread plus the fee`, near(e.edgeCents, -1 - p.feeCents, 1e-9));
}

console.log("\n=== weight one: the model's own edge ===");
const full = anchoredEdge({ ...yesPick, weight: 1 });
check("equals model prob minus price minus fee", near(full.edgeCents, (0.7 - 0.47) * 100 - 1.75));

console.log("\n=== in between is linear ===");
const half = anchoredEdge({ ...yesPick, weight: 0.5 });
check("probability is the midpoint", near(half.prob, (0.7 + 0.46) / 2));

console.log("\n=== no mid, no anchor ===");
check("missing bid", anchoredEdge({ ...yesPick, yesBid: null, weight: 0.5 }) === null);
check("zero bid is no bid", anchoredEdge({ ...yesPick, yesBid: 0, weight: 0.5 }) === null);
check("a $1.00 ask is not a price", anchoredEdge({ ...yesPick, yesAsk: 1, weight: 0.5 }) === null);

console.log("\n=== the weight comes from the run, never invented ===");
check("missing anchor is the market", anchorWeight({}) === 0);
check("null reason is the market", anchorWeight(null) === 0);
check("read when present", anchorWeight({ anchor: { weight: 0.35 } }) === 0.35);
check("clamped above", anchorWeight({ anchor: { weight: 7 } }) === 1);
check("a string is not a weight", anchorWeight({ anchor: { weight: "0.5" } }) === 0);
const fit = anchorFit({ anchor: { weight: 0, n: 2718, brier_market: 0.1506, brier_model: 0.1583 } });
check("fit details surface for the empty state", fit?.n === 2718 && fit?.brierMarket === 0.1506);

console.log(fails ? `\n${fails} FAILED` : "\nALL CHECKS PASS");
process.exit(fails ? 1 : 0);
