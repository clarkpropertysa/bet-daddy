/**
 * The model's claim is read off its own curve, and never invented between rungs.
 */
import { CONFIDENT, expectationFrom } from "../src/lib/expectation.ts";

let fails = 0;
const check = (n, c, d = "") => {
  if (!c) { fails++; console.log(`  FAIL ${n} ${d}`); } else console.log(`  ok   ${n} ${d}`);
};

// A receiving-yards ladder: P(over) falls as the line rises.
const ladder = [
  { strike: 14.5, pOver: 0.93 },
  { strike: 24.5, pOver: 0.86 },
  { strike: 39.5, pOver: 0.78 },
  { strike: 49.5, pOver: 0.62 },
  { strike: 59.5, pOver: 0.44 },
  { strike: 79.5, pOver: 0.24 },
  { strike: 99.5, pOver: 0.11 },
];

console.log("=== the two statements ===");
const e = expectationFrom(ladder);
check("floor is the HIGHEST line it is confident of clearing", e.floor?.strike === 39.5, JSON.stringify(e.floor));
check("ceiling is the LOWEST line it is confident of staying under", e.ceiling?.strike === 79.5, JSON.stringify(e.ceiling));
check("ceiling probability is stated as the under", Math.abs((e.ceiling?.p ?? 0) - 0.76) < 1e-9);
check("rung count is carried", e.rungs === 7);

console.log("\n=== nothing is invented between rungs ===");
const sparse = [{ strike: 49.5, pOver: 0.62 }];
const s = expectationFrom(sparse);
check("a curve with no confident rung claims nothing", s.floor === null && s.ceiling === null);
check("...and says how little was behind it", s.rungs === 1);

console.log("\n=== the bar itself ===");
check("exactly at the bar counts", expectationFrom([{ strike: 10, pOver: CONFIDENT }]).floor?.strike === 10);
check("just under does not", expectationFrom([{ strike: 10, pOver: CONFIDENT - 0.001 }]).floor === null);
const strict = expectationFrom(ladder, 0.9);
// At a 90% bar the 99.5 rung is only 89% under, so there is no ceiling to state.
check("a stricter bar states less", strict.floor?.strike === 14.5 && strict.ceiling === null,
  JSON.stringify(strict));

console.log("\n=== junk in the curve is dropped, never rendered ===");
const junk = expectationFrom([
  { strike: NaN, pOver: 0.99 },
  { strike: 20, pOver: Number.POSITIVE_INFINITY },
  { strike: 30, pOver: 0.95 },
]);
check("only the real rung survives", junk.rungs === 1 && junk.floor?.strike === 30);

console.log(fails ? `\n${fails} FAILED` : "\nALL CHECKS PASS");
process.exit(fails ? 1 : 0);
