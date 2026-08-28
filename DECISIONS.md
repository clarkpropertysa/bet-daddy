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
