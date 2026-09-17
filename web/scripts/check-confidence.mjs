/**
 * A confidence score has to be MEASURED, and it has to be earned by sample.
 */
import {
  EVIDENCE_HALF_WEIGHT, bandOf, confidenceOf, lookup,
} from "../src/lib/confidence.ts";

let fails = 0;
const check = (n, c, d = "") => {
  if (!c) { fails++; console.log(`  FAIL ${n} ${d}`); } else console.log(`  ok   ${n} ${d}`);
};
const near = (a, b, tol = 1e-6) => Math.abs(a - b) < tol;

const table = new Map([
  // the real Week 1 cells
  ["receptions|no|1", { n: 45, stated: 0.66, actual: 0.44 }],
  ["rec_yds|no|4", { n: 201, stated: 0.95, actual: 0.87 }],
  ["rec_yds|yes|3", { n: 25, stated: 0.84, actual: 0.88 }],
  ["*|no|2", { n: 300, stated: 0.75, actual: 0.63 }],
  ["*|*|0", { n: 500, stated: 0.55, actual: 0.50 }],
]);

console.log("=== bands ===");
check("50-59% is band 0", bandOf(0.55) === 0);
check("90%+ is band 4", bandOf(0.95) === 4 && bandOf(0.999) === 4);
check("a number at the boundary lands up", bandOf(0.6) === 1);

console.log("\n=== the claim is scored against ITS OWN kind ===");
const rec = confidenceOf(table, "receptions", "no", 0.66);
check("a receptions under uses the receptions cell", rec.basis?.n === 45);
check("and is marked down hard", rec.grade === "poor", `${(rec.adjusted * 100).toFixed(0)}%`);
const big = confidenceOf(table, "rec_yds", "no", 0.95);
check("a well-evidenced small miss is solid-ish", big.grade === "shaky", `${(big.adjusted * 100).toFixed(0)}%`);
const good = confidenceOf(table, "rec_yds", "yes", 0.84);
check("a cell that beat its claim is not marked down", good.adjusted >= good.stated && good.grade === "solid");

console.log("\n=== fallbacks, in order, never across kinds ===");
check("falls back to side+band", lookup(table, "pass_yds", "no", 0.75)?.n === 300);
// The real failure: a 13-contract cell for passing yards beat a 161-contract fallback and
// reported "untested" on every quarterback row.
table.set("pass_yds|no|2", { n: 13, stated: 0.75, actual: 0.31 });
check("a cell too thin to mean anything falls THROUGH", lookup(table, "pass_yds", "no", 0.75)?.n === 300);
check("...and the claim is scored on the fallback", confidenceOf(table, "pass_yds", "no", 0.75).grade !== "untested");
check("then to band alone", lookup(table, "pass_yds", "yes", 0.55)?.n === 500);
check("then admits it has nothing", lookup(table, "pass_yds", "yes", 0.85) === null);
check("...and says untested", confidenceOf(table, "pass_yds", "yes", 0.85).grade === "untested");
check("untested does not move the number",
  confidenceOf(table, "pass_yds", "yes", 0.85).adjusted === 0.85);

console.log("\n=== the correction is earned by sample ===");
const thin = new Map([["x|no|2", { n: EVIDENCE_HALF_WEIGHT, stated: 0.75, actual: 0.55 }]]);
const c = confidenceOf(thin, "x", "no", 0.75);
check("at the half-weight sample the miss counts half", near(c.adjusted, 0.65, 1e-9), `${c.adjusted}`);
const tiny = new Map([["x|no|2", { n: 10, stated: 0.75, actual: 0.35 }]]);
const t = confidenceOf(tiny, "x", "no", 0.75);
check("ten contracts cannot swing it far", t.adjusted > 0.66, `${t.adjusted.toFixed(3)}`);
check("...and ten contracts is called untested", t.grade === "untested");

console.log(fails ? `\n${fails} FAILED` : "\nALL CHECKS PASS");
process.exit(fails ? 1 : 0);
