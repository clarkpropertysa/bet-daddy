# DECISIONS

Every schema and modelling choice, with reasoning. Newest last.

---

## 2026-08-28 — Phase 0

### D1. The backtest gate is re-founded on forward CLV, not historical replay

**Finding.** Kalshi's public API does not retain settled player-prop markets across
seasons. Probed every settled market on `KXNFLPASSYDS` (266 rows, all `26AUG`),
`KXNFLRECYDS` (28), `KXNFLRSHYDS` (43), and `KXNBAPTS`/`REB`/`PRA` (0 each). Explicit
`min_close_ts`/`max_close_ts` queries over Sept 2025 – Feb 2026 returned zero rows.
**The 2025 season's prop prices do not exist and cannot be obtained.**

**Consequence.** Section 2's rule ("backtested against ≥200 settled contracts") and
Section 11's Phase 1 criterion ("a CLV number from real historical Kalshi prices") are
unachievable as written — not late, impossible.

**Decision.** Keep the two-tier UI exactly as specified, but define tier promotion on
**forward-measured closing line value** against our own archive: snapshot at T-60,
snapshot at close, grade on settlement. CLV is computable from week 1, needs no history,
and Section 8 already names it the most predictive metric. Signals stay `UNVALIDATED`
with `sampleN` rendered until enough contracts settle.

**Cost.** Every signal will be unvalidated for the first several weeks of the season.
That is the honest state of the system, not a UI defect.

---

### D2. Read nflverse release Parquet directly; nflreadpy is the fallback

`nflreadpy` 0.1.5 (Nov 2025) is current and `nfl_data_py` is stale (last release
Sept 2024) — the spec was right. But the release assets are static, fast, and
unauthenticated, and reading them directly removes the client as a failure mode.

Not hypothetical: **`depth_charts_2026` dropped `jersey_number`, `full_name` and
`depth_team`**, replacing them with `pos_abb`/`pos_slot`/`pos_rank`. Code written
against 2025 columns breaks silently on 2026 data.

**Decision.** Each dataset declares `required` columns; ingest raises `SchemaDriftError`
on drift. A 404 for a season that has not started raises `NotYetPublished` and is
reported as `pending`, so the pipeline does not cry wolf every run until week 1.

---

### D3. Money is `Decimal`, never `float`

Kalshi now returns prices as decimal-dollar strings (`"0.3100"`), not integer cents, and
volume/OI as fixed-point strings. The whole edge is ~1.75¢ wide; float rounding is not
acceptable at that scale. Postgres columns are `Decimal(6,4)` for prices,
`Decimal(18,4)` for volume.

---

### D4. Fees: exact formula, and a separate unrounded marginal rate

`taker = ceil(0.07 × C × P × (1−P))`, maker one quarter of that, rounded up **per order**.
Verified against the documented $1.75/100 contracts at P=0.50, and against series
metadata (`fee_type=quadratic, fee_multiplier=1`).

Two functions, deliberately: `taker_fee()` for actual order cost (per-order ceil), and
`marginal_fee_cents()` for edge math. Using the rounded per-order figure on a
1-contract order overstates the true rate (2.00¢ vs 1.75¢ at midprice) and would
mis-filter the Prop Board.

**Discovered by the discovery job:** `KXNFLANYTD` uses `quadratic_with_maker_fees`,
unlike every other NFL series. Fee handling must be per-series, not global.

---

### D5. Player identity: structured ticker parse, not fuzzy name matching

Kalshi encodes the player in the ticker as `TEAM + FirstInitial + SURNAME + Jersey`
(`SFBPURDY13`). That is a structured key — far stronger than the name matching
Section 12 warns about.

Measured on live markets:

| approach | match rate |
|---|---|
| naive regex (greedy team split) | 55.1% |
| team-anchored + alias map (`LAR→LA`) | 92.3% |
| + `football_name` initial fallback | 93.8% |

Two bugs this surfaced, both worth recording:

1. **Team boundary is ambiguous.** `SFBPURDY13` parses as `SFB`+`PURDY` under a greedy
   regex. Must anchor on the known team set, longest code first.
2. **Legal first name ≠ playing name.** Matthew Stafford's `first_name` is **"John"**.
   nflverse carries `football_name` for exactly this. Matching on `first_name` alone
   silently fails for a whole class of players.

Unresolved keys are written with `method=UNRESOLVED` and surfaced as a review queue —
never dropped, never guessed.

---

### D6. Raw layer in Parquet, Neon holds engineered outputs only

Per Section 6, and confirmed by size: 2025 pbp alone is ~20MB/season against a ~0.5GB
Neon free tier. DuckDB queries the Parquet directly. Postgres gets features, splits,
market snapshots, projections, signals, results.

---

### D7. Archive writes Parquet first, database second

The market archive is the only irreplaceable asset in the system. A DB outage must
never cost a snapshot, so the archiver writes local Parquet (partitioned by UTC date)
and uploads it as a CI artifact regardless of database state.

Orderbook depth is fetched only where a quote exists — the listing's `volume` field is
**null even for markets that genuinely traded** (confirmed: a preseason market showing
`volume: null` had 726 contracts in its candlesticks). Quote presence, not the listing
volume, is the liquidity signal.

---

### D8. Deferred: The Odds API

500 credits/month metered per market × bookmaker × event is roughly one slate of prop
pulls. The budget-tracking and hard-stop machinery costs more than the reference data is
worth, and Kalshi is the venue actually being traded. Revisit if the archive shows
Kalshi pricing diverging from consensus.

---

### D9. Open risk: stats.nba.com is unreachable

`stats.nba.com` **hung completely** from a residential connection (two attempts, 25s and
60s timeouts, full browser headers). `cdn.nba.com` returned 403. Section 4.2's fallback
plan assumed local ingestion would work; currently it does not. NBA is Phase 4 — this
needs a real investigation before October, not an assumption.

Kalshi NBA prop series all exist (`KXNBAPTS`/`REB`/`AST`/`3PT`/`PRA`/`BLK`/`STL`), so the
market side is ready when the stats side is solved.

---

### D10. Adaptive snapshot cadence, and Blob for the archive

**Storage question resolved.** Vercel deprecated its own Postgres in Dec 2024 and
migrated to Neon, so "Vercel vs Neon" is not a real choice -- Vercel Postgres *is*
Neon. Provisioning through the Vercel Marketplace is preferred: one account, and
DATABASE_URL/DIRECT_URL auto-inject into the project.

**Blob cannot replace the database.** No SQL, no indexes, no partial updates. Signal
grading mutates rows after settlement (closingPrice, clvCents), which in Parquet means
rewriting whole partitions. The Prop Board needs indexed filtered reads.

**But Blob is the right home for the archive**, and it closes a real hole: the archive
currently persists in CI only as a GitHub Actions artifact with 90-day retention. The
one irreplaceable asset in the system was set to silently expire after three months.

**Cadence.** Kalshi lists markets ~15 days before close. Flat 15-minute sampling costs
1,440 snapshots per market and 3.91 GB/season with orderbooks -- over every free tier.
CLV is measured at T-60m, so density far from close buys almost nothing:

    <= 6h   every 15 min   (captures T-60m precisely)
    6-48h   every 60 min
    > 48h   every 6h

118 snapshots per market instead of 1,440. 0.32 GB/season, inside Blob's 1 GB free tier
four times over. Due-ness is computed from the archive itself (max(ts) per market), so
there is no side state to drift out of sync with the data.

Escape hatch if the archive outgrows 1 GB: Cloudflare R2 (10 GB free, S3-compatible).

---

### D11. polars removed; duckdb + pyarrow only

polars ships a **189 MB** native library. macOS validates code signatures on load, and
that validation is not cached across processes: with the machine under load, a single
`import polars` blocked for **minutes**, every time. Measured Gatekeeper evaluation on
one .so was 3.5s. duckdb (43 MB) and pyarrow import in 0.09s.

The rewrite was cheap because duckdb was already a dependency for the raw Parquet
layer, and the crosswalk/rest logic is clearer as SQL than as dataframe chains.
Interchange type is now `pyarrow.Table`; all querying goes through duckdb.

Also: **keep this project out of iCloud-synced folders.** Running `npm install` inside
`~/Desktop` put ~750 MB of small files under Desktop & Documents sync, drove load
average to 32 on 8 cores, and triggered an iCloud migration that relocated the working
tree mid-session. The repo now lives at `~/Bet Daddy`, outside the synced tree, with
`.metadata_never_index` on the heavy directories.

---

### D12. Rest context: bye weeks are structural, and window bounds are off-by-one traps

Three bugs the 2026 schedule caught, all of which would have silently poisoned rest
splits:

1. **A bye is a missing week, not a rest-day threshold.** Detecting post-bye via
   `days_rest >= 12` finds only 30 of 32 teams: a bye followed by a Thursday game
   leaves **10 days**. Now derived from the week gap (`week - lag(week) > 1`), with
   the days-based rule kept only as the NBA/no-week fallback.

2. **"3 games in 4 nights" means a 4-CALENDAR-DAY span** -- today plus 3 prior days.
   Using `interval 4 day preceding` counts the Sunday game before a Thursday game and
   produced 33 false positives across the NFL season, where the true count is zero.

3. **Not every Thursday game is a short week.** KC and LA play Thursday-to-Thursday
   after Thanksgiving 2026, on 7 and 8 days rest.

`games_in_last_6` firing on short weeks is correct and is the signal -- it flags
exactly the 39 games played on 4-5 days rest.

---

### D13. Usage features: the target denominator must require a receiver

`target_share` is the core opportunity metric, so its denominator has to be exact.
Counting all pass plays includes sacks and throwaways, which have no
`receiver_player_id`; shares then sum to **0.885** per team-game instead of 1.0.
Fixed to count only pass plays with an intended receiver. Now sums to 1.0 to within
1e-9, and pbp-derived targets/receptions match nflverse's official weekly stat lines
exactly across the 2025 season -- two independent products agreeing.

`air_yards_share` legitimately exceeds 1.0 and must NOT be clamped. Air yards are
signed (screens are negative), so a deep threat can hold more than his team's net
total. Clamping would distort WOPR.

Route participation is deliberately absent: it needs FTN charting data with its own
coverage gaps, and a fabricated proxy would be worse than the gap (Section 0 rule 3).

---

### D14. With/without splits are confounded, and the tool says so

This is the signal Section 5.2 calls most exploitable, and the one most able to
manufacture confident losing bets.

**Sample discipline.** Of 6,247 (player, teammate) pairs in 2025, 85% are suppressed
on sample size and only 1.3% are both unsuppressed and significant at 95%. That is
the honest base rate. Suppressed rows are returned flagged, never dropped.

**Availability comes from snap counts, not targets.** A receiver who played 40 snaps
and drew zero targets is present. Inferring absence from missing targets would
manufacture the exact effect being measured. This required a pfr_id -> gsis_id
crosswalk: the `players` release maps them at **99.7%**, weekly rosters only 65.9%.

**Position gate.** Before restricting teammates to skill positions, two of the five
largest 2025 splits were driven by OFFENSIVE TACKLES. An OT's absence has no
mechanism to free targets -- those games merely coincided with other injuries.

**Residual confounding is measured, not hidden.** Pairwise splits still attribute
joint absences to each teammate separately. `confound_regulars_out` reports the mean
number of other regulars absent in the "without" games, and it discriminates sharply:
the largest 2025 split (Michael Wilson without Marvin Harrison Jr., +17.7pp) has
**4.6** other regulars out, while Drake London without Kirk Cousins (+13.0pp) has
**1.3**. The smaller delta is the more trustworthy read. Proper causal attribution
needs a multivariate model and is deliberately not claimed here.

---

### D15. Defense grades are inferred, and "unknown" is not a gap

True shadow-coverage data is not free, so pass defense is graded from what a defense
actually allowed, split by target depth band (short <10 air yards, intermediate 10-19,
deep 20+) and receiver position. Every row carries `provenance='inferred_from_pbp'`;
the UI must label it that way rather than implying charted coverage.

EPA per target is primary, not yards allowed: yards are confounded by volume, and a
defense facing 40 targets a game looks worse than one facing 25 regardless of quality.

**Bug worth recording.** Bucketing runs with a NULL `run_location` as 'unknown'
produced an average of **-2.086 EPA** across 30 teams -- a fake elite grade. Those are
128 botched snaps and aborted plays (0.9% of runs), not a gap. They are now excluded
from gap splits but retained in the team-level 'all' row, since they did happen.

Ranks are suppressed to NULL below 25 targets/carries. A rank computed off 6 targets
is a lie with a number attached.

---

### D16. Simulate the distribution; never emit a point estimate

A prop is a question about a tail, so the model draws the full distribution:

  1. Volume driver first (targets/carries) as a negative binomial -- football counts
     are overdispersed relative to Poisson, and game script alone guarantees it.
  2. P(inactive) as a DISCRETE mass at zero. A DNP is the worst outcome for an over
     and must not be smoothed into the volume distribution.
  3. Efficiency drawn from the player's OWN empirical per-catch/per-carry outcomes.
     Yards per catch is strongly right-skewed (Ja'Marr Chase 2025: mean 11.3, median
     10.0, max 64). A normal or gamma fit smooths away the breakaway tail, and that
     tail is where props settle.
  4. Every adjustment is a named, logged multiplier, so the Why panel shows the chain
     rather than a black box.

`P(over)` uses a STRICT inequality. Kalshi settles on more-than-the-strike, and `>=`
would systematically overprice every over on integer markets like receptions, where
landing exactly on the strike is common.

Runs are seeded. An unseeded model cannot be audited or replayed in a backtest.

---

### D17. Edge is priced off the ask, and tiers are earned forward

`net_edge = (model_prob - ask) * 100 - exact_fee`, evaluated on BOTH sides: an over
that is rich means the under is cheap, and either is tradeable on Kalshi.

**Price off the ask, never the midpoint.** The ask is what you actually pay; the
midpoint invents edge equal to half the spread, which on thin prop markets is most of
the apparent edge.

The economics this exposes: a model **2 points better than the market at 50c** clears
2.00c gross and nets **0.25c** after the 1.75c fee. A hit-rate tool that ignores fees
recommends that bet enthusiastically. This is the single most important number in the
product.

**Tiering is forward-CLV, per D1.** Promotion requires BOTH a sample size and a
POSITIVE mean CLV. A signal family with 900 settled contracts and -0.8c CLV is
disproven, not validated, and stays UNVALIDATED -- promoting on volume alone is how a
tool launders a losing model.

---

### D18. Point-in-time correctness is enforced, not remembered

A leaky backtest looks like a brilliant model, and the failure is silent. So the
cutoff is an explicit, tested API rather than a convention:

* `filter_as_of` keeps rows STRICTLY before the cutoff. Not `<=`: a row stamped
  exactly at the cutoff is ambiguous, and on a T-60 reconstruction the ambiguous row
  is usually the one that leaks.
* `assert_no_leakage` fails loudly, naming the offending row count and timestamp.
* `assert_features_predate_kickoff` guards the most damaging leak available here --
  building a "prediction" from the completed game's own play-by-play.

`price_at(mins_before_close)` only considers snapshots at or BEFORE the requested
horizon. Returning the nearest snapshot in absolute terms would happily hand back a
later one and leak price information from after the reconstruction time.

---

### D19. CLV is the metric that survives having no history

Kalshi retains no settled prop markets across seasons (D1), so there is no historical
price series to backtest. CLV replaces it because it is measurable FORWARD against our
own archive from week 1, and it needs no settlement:

    clv_cents = (close - entry) * 100      # sign flips for a NO position

The NO sign inversion matters: a NO holder profits when the yes price falls, so the
same move that hurts a YES helps a NO. Getting that backwards inverts the entire
Track Record page.

CLV depends only on price movement, not outcome, which is why it is readable after
dozens of contracts rather than hundreds of settlements.

Settlement P&L is tracked separately and nets the exact entry fee. A NO at a 40c
yes-price costs 60c, not 40c -- an easy and expensive thing to get wrong.

---

### D20. pytz is a real dependency, not an optional one

duckdb cannot materialise a `timestamptz` into a Python object without pytz, and
fails at fetch time with a confusing ModuleNotFoundError. Worked around it twice by
casting to epoch/varchar before accepting that the workaround was degrading the API.
It is declared now.
