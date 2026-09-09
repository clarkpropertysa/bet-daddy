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

---

### D21. UI: empty states name their source, and staleness is structural

Section 0 rule 3 says an unavailable source must produce an explicit empty state, not
a placeholder. Two components enforce that rather than leaving it to discipline:

* `<Empty>` requires a `source` prop, so a blank surface always says which system had
  no data ("Signal table (Neon)").
* `<Tier>` cannot render a confidence tier without also rendering `n`. Section 2
  requires the sample size beside every signal, so the component makes omitting it
  impossible rather than merely discouraged.

"Validated only" is OFF by default on the Prop Board. Defaulting it on would hide
every unvalidated signal and quietly imply that everything visible has a track record.

The Why panel reads only STORED signal fields and never recomputes. Recomputing at
read time would show what the model thinks now, not what it thought when the signal
fired -- which is the question the panel exists to answer.

**Bug the UI found.** The staleness banner correctly reported "archiver last succeeded
never": the archiver wrote Parquet and blob but never recorded a `PipelineRun`, so the
health surface had nothing to read. Section 6 requires every job to write one. Now
wrapped in `db.track()`, which records success and failure alike and never raises --
observability must not be able to fail a data job.

---

### D22. Two environment quirks, both now scripted

* **Dev runs on webpack, not Turbopack.** The Next 16 default panics here when
  spawning its pooled node worker for the PostCSS/Tailwind loader
  ("spawning node pooled process - No such file or directory"). Putting node on PATH
  does not help. Production builds are unaffected.
* **node must be on PATH for child processes**, so an absolute path to the node
  binary is not enough on its own. `scripts/dev-web.sh` handles both.

The scaffold's `body { background: var(--background) }` was also removed: a bare
element rule outranks Tailwind utilities in the cascade, so it silently overrode
`bg-zinc-950` and rendered the entire app light.

Prisma is pinned to 6.19.3 across root and /web. `create-next-app` had pulled
prisma 8.0.0-rc.12 with a mismatched client 7.10.0 -- a release candidate, into the
package that talks to the database.

---

### D23. Preseason produces no signals, by refusal

Preseason snap distribution bears no relation to the regular season -- starters play
a series or two. A smoke run projecting preseason markets from 2025 regular-season
usage produced an average net edge of **+33c**, with individual rows above +90c. Those
were not edges; they were the model being wrong against a market that was right.

The job now REFUSES preseason tickers rather than leaving it to a caller to remember,
and the blanket `preseason_usage` fudge multiplier is deleted. `--allow-preseason`
exists for diagnostics only.

**The smoke run was still worth it**: on real prices and real settlements it exposed
three genuine bugs before week 1.

1. **Untradeable entry prices.** 48% of preseason entry asks sat at 0c or 100c. A 0c
   ask is not a fillable price -- it is an empty or one-sided book reported as a
   number. Entry prices are now bounded to 1-99c.
2. **Strike rendered as "—" everywhere.** The board joined `MarketSnapshot` for the
   strike, but that table is empty by design: the archive lives in Parquet, not
   Postgres. The strike is now parsed off the ticker.
3. **No implausibility check.** A model that disagrees with the market by more than
   50 points is missing something the market knows -- a scratch, a role change,
   weather. Those rows are flagged and hidden by default, because a board sorted by
   edge would otherwise put the model's worst failures at the top and make the tool
   look most confident exactly where it is most broken.

---

### D24. Adjustments: shape from data, scale as a stated prior

Each multiplier is named, logged, and rendered in the Why panel.

`opponent_defense` derives from a team's EPA allowed relative to the league mean,
expressed in standard deviations and **saturated at ±2σ**. Saturation is not
cosmetic: without it a single outlier defence off a thin sample yields an unbounded
multiplier. NYJ (worst 2025 pass defence) resolves to 1.056; LAC to 0.948.

The SHAPE is data. The SCALE -- how far one sigma should move a projection -- is a
prior, and cannot be fitted until forward CLV exists across a few hundred settled
contracts. So the swings are deliberately small (±8% defence, ±3% rest). Given the
fee floor, an uncalibrated multiplier that is too large manufactures edge, while one
that is too small merely fails to find some. The second error is far cheaper.

Rest adjusts volume only slightly: the well-evidenced rest effects are on efficiency
and availability, not on opportunity.

---

### D25. UI: the surface must not look confident where the model is broken

- A **non-production model banner** names the model version and warns when rows come
  from a non-production run. Without it the board reads as full of great bets when it
  is full of model error -- the exact failure Section 2 describes.
- **Implausible edges are hidden by default** and badged when shown.
- Chart mount animation is disabled: this is a reference chart read against a strike,
  not a reveal, and a deterministic render is also testable.
- `--pos`/`--neg` sit at CVD ΔE 6.5 for protanopia, so **colour is never the only
  channel** -- every edge carries an explicit sign and a directional glyph.

---

### D26. The cron does not need to be reliable, because history is reconstructable

GitHub's scheduler never fired the archiver: **zero scheduled runs in 4+ hours** while
manual dispatch succeeded every time. Actions was enabled, the workflow `active`, the
cron valid, the file on the default branch. Nothing was misconfigured -- free-tier
private repos simply get their schedules dropped, and `*/15` lands on the most
contended slot on the platform.

Rather than fight it, the measurement that matters:

* **Kalshi retains settled prop markets for ~22 days.** Measured 2026-08-29: the
  reachable window ran 26AUG06 -> 26AUG27.
* **Candlesticks are fetchable retroactively at 1-MINUTE granularity** inside that
  window, and carry yes_bid, yes_ask, last price, volume and open interest.

So price history is NOT lost when a tick is missed. It is recoverable for three weeks.
This inverts the architecture:

| job | role | consequence if it misses |
|---|---|---|
| `backfill-history` (2x daily) | **durable path** | none, until 22 days elapse |
| `archive-markets` (15 min) | orderbook depth only | depth for that instant, nothing else |

Backfill granularity mirrors the adaptive cadence: hourly across a market's life, then
1-minute across the final 8 hours where CLV is actually measured. First run captured
**70,862 price rows across 323 markets**, against 2,456 for the hourly-only version.

Two smaller changes: every cron is now offset off the round hour/quarter-hour, and the
coarse and fine passes dedupe on `(market_ticker, ts)` so overlapping runs converge
rather than accumulate.

This also corrects an overstatement in D1. Prop *prices* are recoverable for ~22 days;
what is genuinely unrecoverable is orderbook **depth**, and any market older than the
retention window.

---

### D27. Player photos: the transform is the whole story

nflverse rosters carry `headshot_url` at **96.2% coverage** (97.6% of synced players),
pointing at the official NFL CDN.

**The stored originals are ~4MB PNGs.** Fifty rows on a board would be ~200MB of
transfer. They are Cloudinary-backed, so injecting a sizing transform into the
delivery segment takes the same image to **~4KB** -- a thousandfold reduction:

    .../image/upload/f_auto,q_auto/league/<id>                        ~4 MB
    .../image/upload/f_auto,q_auto,c_fill,g_face,h_96,w_96/league/<id> ~4 KB

`g_face` matters as much as the size: a plain centre crop on these images lands on
the chest, not the face.

Served with a plain `<img>` rather than next/image: the CDN already returns the exact
pixel dimensions requested, so the Next optimiser would add a second hop for nothing.

Two fallbacks, because a missing photo must never look like a data error: ~2.4% of
rostered players have no headshot, and the CDN occasionally 404s an id the roster
still carries. Both render initials.

---

### D28. Brand system applied — "one steel voice on paper"

From the Bet Daddy brand sheet (v1, Aug 2026). Canonical values:

| token | hex | role |
|---|---|---|
| STEEL / ACCENT | `#5980A6` | odds, actions, the mark |
| STEEL 900 | `#1D2D3D` | action panels, app icon, fields |
| PAPER | `#F2F2F3` | the default ground |
| INK | `#1D1F20` | all body copy |

Plus the steel ramp 100→900, sampled directly from the sheet's swatches rather than
eyeballed. **The app inverted from dark to light**: paper is the specified ground.

Structural rule carried over from the sheet's app mock ("odds board on paper, bet slip
on steel"): data surfaces are paper/white cards, action surfaces are steel 900. The
Why panel is therefore a steel panel — with the distribution chart on a paper card
inside it, because data belongs on paper.

Type: condensed grotesque (Oswald) for the wordmark, section numbers and CTAs; a
neutral grotesque (Inter) for body. The signature numeric motif is the outlined steel
box (`.odds-box`) — prices, strikes and edges never render as bare text.

The Odds Crown mark is rebuilt as SVG: five bars reading as a crown on a base rule,
and per the sheet the rule is dropped below 20px.

**Two deliberate departures, both documented:**

1. **Polarity.** The brand is monochrome, but edge needs direction. Steel — the
   brand's own "actions" colour — carries positive; a warm counterpole `#A6553F`
   carries negative. Validated on paper: CVD ΔE 14.8 deutan, 18.4 normal.
2. **Chart marks.** Brand steel sits at chroma 0.073 and *reads gray as a chart
   series*. Chart marks use a chroma-lifted `#3D7BB5` / `#B04A2F` pair (validated:
   CVD ΔE 19.9, normal 24.2); the UI keeps the brand value. This is also why charts
   live on paper rather than on the steel panel — steel-on-steel fails the chroma
   floor in every step tested.

---

### D29. The signal SIDE was never stored, and the UI was lying

`compute_edge` evaluates both sides and keeps the better one, so `modelProb` is the
probability of the CHOSEN side — not always P(over). The side was never persisted.

The Why panel therefore showed "Model probability 94.1%" beside a distribution where
the strike sat above p90 — i.e. P(over) ≈ 5.9%. Both numbers were right; the label
was wrong, and the contradiction was invisible unless you read the chart carefully.

**23% of signals (26 of 111) were NO-side and mislabelled this way.** A user acting on
the board would have taken the opposite bet.

`Signal.side` is now a stored column, rendered as a badge on every board row and as
over/under in the panel, with P(over) shown alongside on NO rows so the chart and the
arithmetic agree.

---

### D30. Starters only, with injury-driven promotion

2,887 rostered players carry props for about 220. The prop-relevant set is defined by
depth-chart rank: **QB1, RB1-2, WR1-3, TE1** — 7 per team, 224 league-wide. Everyone
else is on the depth chart but will not draw a priceable snap.

Only the LATEST depth snapshot is used. The 2026 file holds 160 dated snapshots back
to March; taking them all returns a player at every rank he has ever held.

When a starter is ruled **Out or Doubtful**, the next man up is promoted and carries
`promotedFor`, rendered as "in for <name>". A backup appearing on the board without
explanation is indistinguishable from a bug.

Promotion is wired but currently inert: `injuries_2026` is not published until the
season starts.

---

### D31. Market taxonomy is shown, not implied

The board now renders its own structure above the table — every market family it
covers, grouped Passing / Rushing / Receiving / Defense, with live counts. Families
Kalshi lists but the simulator cannot price (interceptions, longest reception,
anytime TD, sacks) are shown **struck through** rather than hidden, because a market
we cannot price otherwise looks identical to one that does not exist.

This matters most when the board is empty, which is its state until week 1 is quoted.

---

### D32. Parlay legs are correlated, and the naive product flatters the ticket

Multiplying leg probabilities is wrong in the direction that makes a bet look better.
A quarterback's passing yards and his WR1's receiving yards move together.

Method: a **Gaussian copula**. Each leg's marginal maps to a latent normal threshold
via Φ⁻¹; legs get a correlation matrix; joint hit probability is the multivariate
normal orthant probability, evaluated by Monte Carlo with a fixed seed so a ticket
always rates the same.

Correlation priors — documented, moderate, and **not fitted**, because fitting needs
settled multi-leg outcomes the archive does not yet hold:

| relationship | ρ |
|---|---|
| same player, same game | 0.55 |
| same team, same game | 0.30 |
| opposing teams, same game | −0.10 |
| different games | 0 |

Measured effect: a same-player two-leg ticket rates **0.388** against a naive product
of 0.300 — the product is 29% too pessimistic.

**Two bugs this surfaced.**

1. **The correlation model was inert.** `Projection.gameId` stored the MARKET ticker,
   which is unique per strike, so every leg looked like a different game and every ρ
   was 0. It now stores the EVENT ticker. This failed silently while returning
   plausible numbers — exactly the failure mode the checks now pin.
2. **Contradictory legs were priced.** "Over 100 yards" and "under 75 yards" for the
   same player in the same game cannot both win, but a copula sees only two marginal
   probabilities and returned a comfortable 12%. Such pairs are now detected
   structurally and the ticket is refused rather than rated.

Confidence bands are deliberately blunt: 25–50% is "MODERATE — most tickets at this
level lose". A generous label on a long-odds parlay is how a research tool starts
flattering bad bets.

Kalshi is an exchange and offers no parlays; this rates what a combination is worth.

---

### D33. Correction: Kalshi DOES list multi-leg tickets

I previously wrote that Kalshi is an exchange and offers no parlays. That was wrong,
and verified wrong:

* the exchange status carries a dedicated **Combos** index (`exchange_index 1`,
  active and trading);
* `/multivariate_event_collections` returns `KXMVENFLSINGLEGAME-*` collections
  ("What will happen in CAR Panthers at ARI Cardinals?") with `size_min: 2`;
* their functional description is *"resolves to YES only if every associated market
  resolves to YES"* — precisely a parlay.

So the parlay generator maps onto a real tradeable product, not a hypothetical, and
the copy has been corrected throughout. The correlation modelling matters MORE for
this reason: single-game combos are exactly the maximally-correlated case.

---

### D34. Arithmetic is not an argument

The Why panel showed a multiplier chain and an edge calculation. A reader cannot
agree or disagree with "×1.056". The panel now leads with a **rationale**: ordered
claims, each carrying the number behind it.

Four kinds, deliberately given equal standing:

* **driver** — what produces the projection (baseline volume, each named adjustment,
  the market disagreement)
* **context** — where the strike falls in the simulated distribution, what the fee takes
* **sensitivity** — *what would change the answer*: the break-even probability, and
  the volume assumption the whole thing rests on
* **caveat** — reasons to disagree: a thin baseline, an unvalidated tier

Two rules hold it honest. Every claim derives from a number the model actually used —
nothing is written to sound persuasive. And the caveats sit in the same list as the
drivers rather than in a footnote, because they are part of the argument.

It is generated at PROJECTION time and stored on the signal, so the rendered
explanation is what the model believed when it fired, not a recomputation against
later data.

The value shows most clearly on a bad signal: a smoke-run row now says "a 46.4 point
disagreement" and "the baseline rests on only 6 games" in plain language, which makes
the model's weakness legible without reading the chart.

---

### D35. The Slate, and using nflverse's own columns

The Slate (Section 9.1) is the pre-prop view: who plays, on what rest, in what
conditions, and how much scoring the market expects. It now renders the next week's
games grouped by day, each with the market total and spread, venue and roof, rest
flags, and a live signal count — plus top edges, injury impact and pipeline health.

**Two corrections to earlier work, both from reading the schedule columns properly.**

1. **Neutral sites.** I inferred them by comparing each game's stadium to the team's
   most-frequent stadium. That flagged **55 of 272** games in 2026, because stadiums
   get renamed: Seattle's all-time leader is "CenturyLink Field" (81 games) against
   Lumen Field's 58, so every Seattle home game read as neutral. Restricting to recent
   seasons did not fix it either. nflverse carries a `location` column with the answer
   — **8 games, all genuinely international**. I built a heuristic where the data
   already had the fact.

2. **Fields I was ignoring.** The schedule also carries `total_line`, `spread_line`,
   `temp`, `wind`, `div_game`, starting QBs, and `home_rest`/`away_rest`. Section 5.5
   calls projected total and spread the biggest drivers of prop volume after injuries,
   and they were sitting in a file already on disk.

**A validation worth recording:** my independently-derived `days_rest` agrees with
nflverse's own `home_rest`/`away_rest` on **all 538 rows** of the 2025 season.

Wind is flagged at **15mph**, per Section 5.5 — wind is the weather variable that
moves passing and kicking; temperature mostly is not.

Also: adding a column via raw SQL from a pipeline job put Prisma's migration history
into drift. Schema changes go through Prisma, always.

---

### D36. A game lean, with its error bar stated

The Slate now says which side the model favours. That needed a game-level model —
everything before this projected player props, and asserting a team lean without one
would have been invention.

Team strength is net EPA per play (offensive EPA/play minus EPA/play allowed). The
conversion to points is **fitted, not assumed**: least squares of actual margin on
rating differential across 272 games.

    42.1 points per net EPA/play
    +2.12 points home-field advantage   (consistent with the modern 2-2.5 estimate)
    R² 0.318, RMSE 11.68 points

**The RMSE is the headline, not the fit.** An 11.7-point standard error means a
single-game margin is mostly noise, so the UI does two things: games whose projected
margin is inside ±1.5 points show **"no lean"** with the reason stated, and the page
carries the error bar in plain text. A lean is a starting point, not a verdict.

Ratings for a season come from the PRIOR season, so a 2026 projection is genuinely
out of sample. The fitted constants were estimated in-sample on 2025 and are treated
as priors.

The reasoning renders **in the row**, not in a tooltip — "LA moves the ball better
(offense ranked 2) · LA defends better (defense ranked 9) · neutral site, so no
home-field credit · market has it 4.4 points the other way". A lean nobody can
inspect is just an assertion.

---

### D37. Venue-neutral UI

All user-visible references to a specific exchange are gone: "Kalshi ask" → "Market
ask", "Kalshi fee" → "Fee", and the combos copy is now generic multi-leg language.

Internal identifiers keep their real names — the archiver job is still
`kalshi_archiver`, the ingest module still `kalshi_discovery` — because renaming what
the pipeline actually talks to would obscure the data's provenance for anyone reading
the code. Neutrality is a presentation concern, not a reason to lie about the source.

Slate rows link to `/board?game=<id>`, and the filter chip renders `SF @ LA` rather
than `2026_01_SF_LA`: the game id is a stable key, not a label, and showing it raw
leaks the schema into the UI.

---

### D38. Audit findings — three real gaps

**The scheduled crons DO fire now.** Six scheduled `archive-markets` runs, two
`backfill-history`, one `ingest-nflverse`, all succeeding, all capturing rows and
uploading. Offsetting the cron off round quarter-hours appears to have helped.

But the audit found three things:

1. **The backfill never uploaded to blob.** It holds the 70,862-row minute-level
   price history — the input CLV is computed from — and it lived only on a local disk
   and a 90-day CI artifact. The blob store existed precisely to prevent that expiry
   and the most important dataset was not using it. Fixed; the durable copy went from
   0.1 MB of snapshots to 0.62 MB including the history.

2. **35 teams, not 32.** `schedules.parquet` spans back to 1999, so an unscoped team
   sync returned OAK, SD and STL — relocated franchises that no longer exist under
   those codes. Team sync is now scoped to the target season.

3. **The archiver's real cadence is 2-6 hours, not 15 minutes.** Measured gaps
   between scheduled runs: 129, 132, 156, 240, 353 minutes. GitHub drops most firings
   on a free-tier private repo. This does NOT threaten price history — candlestick
   backfill recovers it at minute resolution for 22 days — but it does mean live
   ORDERBOOK DEPTH near close will be sparse, since depth is the one thing
   candlesticks cannot reconstruct. The backfill schedule was densified to six times
   daily in response, since it is the job actually doing the durable work.

---

### D39. Prior-season ratings are a weak prior, and were being used at full strength

Measured year-over-year stability of team net EPA/play across 96 team-seasons
(2022→23, 23→24, 24→25):

    r = 0.344,  r² = 0.118,  optimal regression slope = 0.37

**Twelve percent of variance.** Offseasons change rosters, coordinators and
quarterbacks; the rating does not know that. Prior-season ratings are now shrunk to
0.37 of their distance from league average, and current-season play replaces the
prior as it accumulates (full weight by 8 games).

Refitting the margin model strictly out of sample — prior-season ratings predicting
the following season, 816 games:

| | in-sample (what I reported before) | out-of-sample (honest) |
|---|---|---|
| R² | 0.318 | **0.038** |
| RMSE | 11.68 pts | **14.05 pts** |

The earlier figures were fitted on ratings and results from the SAME season and
flattered the model badly. The lean threshold moved from 1.5 to 3.5 points as a
result, and most week-1 games now correctly show no lean at all.

A changed starting quarterback is called out explicitly, because it invalidates most
of an offensive rating.

---

### D40. The grading loop, run end to end — and the bug it found

`SignalResult` had never been populated. Running it against 111 signals on real
settled markets produced this:

    by side:  no  n=26  CLV = -50.08c
              yes n=85  CLV =  +1.55c

That asymmetry is not a model failure, it is a **units bug**. `compute_clv_cents`
takes both prices as YES prices and flips the sign itself for a NO position, but
`Signal.marketProb` stores the price of the side actually TAKEN — so a NO signal holds
(1 − yes_ask). Passing it straight through compared a NO entry against a YES close.

After the fix both sides agree at +1.54 / +1.55c, which is what correct units look
like. Regression test added.

This is the entire argument for running a pipeline end to end rather than unit-testing
its parts: every component was individually correct.

---

### D41. Calibration, and what it says about the smoke model

Reliability buckets with **Wilson** intervals (normal intervals run past 1.0 on small
extreme buckets), plus a Brier score decomposed into reliability and resolution.
Isotonic regression refuses to fit under 200 settled outcomes rather than returning an
authoritative-looking curve fitted to a handful of points.

Run against the invalid preseason model, it says exactly what it should:

    Brier 0.4532,  skill vs base rate **-0.2738**
    bucket 0.9-1.0:  n=57,  predicted 0.981,  observed **0.404**

A model worse than predicting the base rate, claiming 98% certainty and hitting 40%.
That is the harness working.

---

### D42. Anytime TD is an opportunity problem, not a volume one

P(at least one TD) is driven by red-zone and goal-line touches, not yardage between
the 20s. Structure: expected red-zone touches → per-touch conversion → simulated
P(≥1), with the touch count carrying its own variance rather than being fixed at its
mean.

Positional conversion baselines are MEASURED, not assumed:

    TE 0.296  >  QB 0.275  >  WR 0.243  >  RB 0.158   TDs per red-zone touch

Running backs take more red-zone touches but convert fewer of them — which is why a
volume model would rate them wrong. A player's own rate is used only past 25 red-zone
touches; below that the positional baseline is, because six red-zone targets is not a
rate.

---

### D43. Explanations that are specific enough to argue with

The rationale was generic — "he averaged 11.6 targets per game" is a fact, not an
argument. `pipeline/model/context.py` now loads the surrounding detail that makes a
projection contestable, each field carrying its own sample size:

* **form**: season rate against the last three games, with the direction and the
  size of the recent sample stated ("11.6 per game, 10.0 over his last 3 — trending
  down… on 3 games, a small sample that moves fast")
* **command of the offense**: target share and rank among his own receivers, because
  share survives a game script that changes how often the team throws at all
* **the specific defensive split**: not a team average but the grade for the kind of
  play this prop depends on, by receiver position or run defense
* **clearance history**: how often he has actually beaten this number

**Clearance rate is included deliberately and framed carefully.** Section 2 is
emphatic that a backward-looking hit rate is worthless as a signal because the line
has already absorbed it. It appears as context beside the model's probability with
that stated in the evidence line — "if it were the edge, everyone holding a box score
would have it" — never as a reason.

The game lean got the same treatment. It now names the specific unit matchup
("SEA throws it 8th-best into a pass defense ranked 11th"), says **which side of the
ball carries the lean** ("carried by SEA's defense, 2nd of 32, not by both units"),
and states the counter-argument ("NE is not passive — 1st throwing the ball, which is
where an upset comes from"). A defense-driven edge previously read as an offensive one
or as nothing at all.

Both are generated at projection time and stored, so the rendered argument is what the
model believed when it fired.

---

### D44. The starter filter existed but was never applied where it mattered

Caught in review: the board was showing J.J. McCarthy passing props. He started for
Minnesota in 2025 and is **QB2 behind Kyler Murray** in 2026 — the database already
knew (`isStarter = false`), because `pipeline/ingest/depth.py` had computed it.

The filter was only ever used by the Players page. **The projection job never checked
it.** So the model happily projected a backup off his prior-season starter usage —
27 attempts per game for a player who may not take a snap — and the rationale then
explained that number in confident detail.

Applying it: signals fell from **111 to 53**, with **105 markets skipped as
`backup_QB2`**. Nearly half the board was players whose usage history describes a job
they no longer hold.

Three changes so this cannot recur silently:

* the projection job loads the latest depth snapshot and refuses anyone past
  `STARTER_DEPTH` (QB1, RB1-2, WR1-3, TE1), recording the reason as `backup_QB2`
  rather than a generic skip;
* every board row renders its depth badge, starters in steel and anyone else in
  amber — which one a player is can no longer be a hidden field;
* tests pin the specific case (Murray QB1, McCarthy not) and assert exactly one QB1
  per team.

The general lesson: a correctness gate that only one surface consults is not a gate.
`isStarter` was computed, stored, tested and displayed — and still had no effect on
the numbers the tool actually emitted.

---

### D45. Audit: the same gate-nobody-consults pattern, twice more

**Injury promotion was not honoured by the projection job.** `ingest/depth.py`
computed `isStarter` WITH promotion; `model/project.py` reimplemented the rule
WITHOUT it, filtering on raw depth rank. So a backup promoted by a starter's absence
would have been refused as a backup — and Section 5.2 calls injury-driven usage
redistribution the single most exploitable signal in props. The tool would have
refused exactly the players it exists to find.

Root cause was duplication, so the fix is deduplication: `features/starters.py` is now
the only implementation, used by both. A test constructs an out-QB1 and asserts the
backup becomes projectable and carries `promoted_for`.

The rationale now leads with that when it applies — "X is starting only because Y is
out. His usage history was compiled in a smaller role, so the baseline understates
the opportunity he is about to see" — because it is the largest caveat on such a
projection.

**The implausible flag was honoured by the web queries but not by calibration.**
Calibrating on signals the board hides measures a model nobody would trade. Now
reported both ways, and the split is instructive:

| set | n | Brier | skill vs base rate |
|---|---|---|---|
| actionable only | 17 | 0.0268 | **+0.1808** |
| all signals | 53 | 0.5892 | −0.4141 |

The signals the flag excludes are precisely the ones destroying calibration. (n=17 is
far too small to conclude anything, and this is still the invalid preseason model —
but the machinery is right.)

---

### D46. The board states a prediction, not a row of fields

The board showed strike, ask, model, fee, net edge and Kelly as six separate numbers
and left the reader to assemble the claim. The claim is the product; the numbers are
its support.

Each row now reads as: **who**, **the call**, **model against market**, **is it worth
it**.

* the call is a sentence — "OVER 50 rushing yards" — with over/under styled distinctly
* model and market probabilities are two aligned bars on a shared scale, so the gap is
  seen rather than computed, with "model is 49 pts higher" stated in words
* the edge is a verdict with the number beside it, banded by the FEE rather than by
  taste: under ~2c is mostly fee, so "thin — 1.74¢ of it is fee" says more than
  "+1.90¢"
* an implausible row says "model disagrees wildly — likely missing something the
  market knows" instead of showing a large, inviting number

The raw figures remain in the Why panel, where someone checking the arithmetic will
look for them.

---

### D47. Crosswalk audit, and the line that looked wrong

**The crosswalk audit came back mostly clean.** The projection job DOES exclude
`UNRESOLVED` keys — they carry `gsis_id = None` and the lookup filters on it. But
**nothing read `confidence`**: a `FALLBACK` match at 0.85 was projected identically to
an `EXACT` at 1.00.

FALLBACK means the market's key did not match a roster jersey, so identity rests on
team + surname + first initial. A shared surname on one roster resolves to the wrong
player. One live case (`KCJFIELDS6` → Justin Fields). Now counted in the skip report
and stated in the rationale as a caveat rather than silently equated to an exact match.

**"Josh Allen over 50 passing yards" was correct, and the board was wrong to show it
without context.** His only archived market is `26AUG15CARBUF` — a preseason game
where a starter plays one series.

| | markets | min | median | max |
|---|---|---|---|---|
| regular season | 35 | 150 | 250 | 400 |
| preseason | 255 | 25 | 100 | 250 |

The strike parsing was fine. What was missing is that **a line is unreadable without
its game**. Every row now carries "ARI at LV, Aug 13" and a PRESEASON badge, and the
rationale leads with why the number is low.

**A bug caught in my own new parser before it shipped.** Splitting the matchup at the
string midpoint turns `ARILV` into `AR`/`ILV`. This is the third instance of the same
mistake — `SFBPURDY13` → `SFB`+`PURDY` was the first — so the split is anchored on the
real team-code set, longest first, in both the Python and TypeScript implementations,
with tests naming the failing case.

---

### D48. Investigating the split bug found two worse ones

Asked whether the `ARILV` -> `AR`/`ILV` mistake was worth chasing. It was: a sweep for
unanchored identifier splitting found the same pattern live in code written in the
same session, and pulling that thread exposed a second, larger fault.

**1. Opponent resolution was subtracting, not anchoring.**

    tail.replace(team_code, "")

The crosswalk normalises `LAR -> LA`, so every Rams player arrived with
`team_code = "LA"` and `"SFLAR".replace("LA", "")` produced **"SFR"** — a team that
does not exist. `defense_detail` then found nothing, so the matchup adjustment
silently did nothing **for an entire franchise**. `"ARILAC".replace("LA","")` gave
`"ARIC"` for the same reason.

Now anchored on the real team-code set, returning the NFLVERSE code, because the
opponent feeds grades keyed on pbp `defteam` — returning Kalshi's `LAR` would have
missed every Rams grade and reproduced the bug one layer down.

**2. The opponent adjustment was never applied to anything.**

    if defense_grades is not None and m.get("opponent"):

Two faults in one condition. `defense_grades` was an unused function PARAMETER
defaulting to `None`, not the `grades` built inside the function; and `m` is a market
row that has no `"opponent"` key. The condition was never true.

So **0 of 53 signals carried the adjustment while 51 of 53 explained one.** The
rationale described a matchup the arithmetic had never applied — the explanation layer
was more complete than the model it was explaining, which is the most misleading
failure mode available.

After the fix: 51 of 53 carry it, multipliers 0.948 to 1.048, inside the documented
±8% bound.

**The guard.** An adjustment that stops firing looks exactly like one that works, so
the job now reports `with_adjustments=N` on every run and warns explicitly when
signals exist but none carry an adjustment. The dead parameter that invited the
mistake is deleted.

Three instances of one root cause — `SFBPURDY13`, `ARILV`, `SFLAR` — say the lesson
plainly: **a boundary between concatenated codes can never be found positionally or by
subtraction. It must be anchored on the known set.**

---

### D49. Sweeping the feature layer for the same inertness

The `with_adjustments` counter caught one inert feature, so the whole feature layer
got the same treatment: for each module, who imports it and does its output reach a
signal.

**Found dead:**

| module | spec priority | status |
|---|---|---|
| `features/usage.py` | 5.1 "highest value, build first" | 7 tests, **imported by nobody** |
| `features/splits.py` | 5.2 "single most exploitable signal" | 9 tests, **imported by nobody** |
| `rest_adjustment` | 5.3 | documented, tested, **never called** |

And the model used raw counts only — the *explanation* cited target share twice, the
model zero times. The pattern is consistent: **the explanation layer had outrun the
model it explains.**

**Wired in this pass:**

* `rest_adjustment`, keyed on `(team, event_date)` parsed from the ticker. 71 of 544
  team-games qualify. It correctly does nothing for preseason (absent from
  `schedules.parquet`) and for week-1 openers (no prior game, so `days_rest` is NULL
  rather than zero).
* `usage_trend_adjustment`, new: recent opportunity against the season rate, shrunk
  by sample size and capped at ±10%. Now applied to 34 of 53 signals. Recent form was
  previously computed for the rationale only, so the panel described a trend the
  projection never applied.

**A bug the test caught, worth recording.** The first version shrank the trend then
capped it, so any trend large enough to reach the cap arrived at the cap regardless of
sample size — a two-game streak moved the projection exactly as much as an eight-game
one, and the shrinkage silently did nothing. Clamping before shrinking fixes it:
+40% over 2 games now gives ×1.04, over 5 games ×1.10.

**Still dead, and honestly so:** `usage.py` (WOPR, target/air-yards share) and
`splits.py` (with/without teammate). Both need a team-volume projection to be used
properly — targets modelled as `team_pass_volume × target_share` rather than raw
historical counts — which is real modelling work, not wiring. They are not claimed
anywhere in the UI.

---

### D50. Team volume, so usage and splits finally do work

`features/usage.py` and `features/splits.py` were built, tested and unused because
they compute a SHARE and nothing supplied a volume to take a share OF. That number now
exists.

    player_targets = team_pass_attempts x target_share

A raw historical count silently assumes both the team's volume and the player's role
stay put. Splitting them means the projection responds when either moves — a new
coordinator throwing ten more times a game, or a teammate's absence moving the share.

**Measured, not assumed.** Year-over-year stability across 96 team-seasons:

| metric | r | r² | optimal shrinkage |
|---|---|---|---|
| plays per game | 0.144 | 0.021 | **0.14** |
| pass attempts | 0.377 | 0.142 | 0.33 |
| pass **rate** | 0.446 | 0.199 | **0.39** |

Team play count is almost entirely unpredictable from the prior season, so it is
shrunk nearly to the league mean — after shrinkage the whole league sits inside a
5-play band, which is the honest representation of knowing almost nothing. Pass rate
is the most stable team trait and keeps real between-team variation.

**A negative result that contradicts the spec.** Section 5.5 calls the projected game
total a primary driver of prop volume. Over 1,632 team-games, **the total does not
predict play count at all: r = 0.030.** High totals come from efficiency, not more
snaps. The total is therefore deliberately absent from this model, and game script
moves only the pass/run SPLIT:

    pass_rate = 0.5735 - 0.00316 * team_spread     r = -0.188

A seven-point underdog throws ~2.2pp more often. Real, and small.

**What it changed.** 51 of 53 baselines now come from share x team volume rather than
a raw count, including quarterbacks — a starting QB is his team's passing volume, so
his attempts derive from the team projection and passing props pick up game script for
the first time.

**The splits gate is respected, not re-decided.** `split_adjustment` consumes the
`significant` and `suppressed` flags features/splits.py already computes. Only **84 of
6,247** splits (1.3%) clear both. Verified end to end on one that does: Michael Wilson
goes from 7.19 to 10.93 projected targets with Marvin Harrison Jr. out — the raw
+17.7pp delta capped at +10pp, because these splits carry wide intervals and an
uncapped one would dominate every other input. Overlapping absences take the largest
split rather than the sum, since summing double-counts the confounding.

Coverage is reported as `share_based=N` for the same reason as `with_adjustments`: a
modelling layer that stops being reached looks identical to one that is working.

---

## The board could only ever show games that had already finished

**2026-08-30.** Ten days before Week 1, the board was empty. Not because of missing
data — because of one line.

`_entry_prices` selected `where rn = 1 and result in ('yes','no')`. That is a correct
filter for a *backtest*: you can only grade a decision against a market that settled.
It is fatal for live serving, because an open market has no result yet. One query was
doing both jobs, and the backtest half won. Every signal this project ever produced
came from a game that was already over. The Prop Board was, structurally, a replay.

**The fix is two queries, not a flag.** They want opposite things and saying so in the
type system is the point:

| | entry price | ordering | filter |
|---|---|---|---|
| `_settled_prices` | the ask at T-minus-N | `mins_to_close asc` | `result in ('yes','no')` |
| `_open_prices` | the freshest quote there is | `ts desc` | `close_time > now()` |

The settled path must not see past its horizon; the live path wants the newest tick
available. A shared query cannot honour both constraints, and the attempt silently
resolved in favour of whichever filter was more restrictive.

`mins_to_close` is recomputed against the clock in the live path rather than read from
the snapshot. The stored value was true when the snapshot was taken and is wrong by
exactly the snapshot's age.

**`featureAsOf` was storing the wrong instant.** It is the point-in-time guard — no
feature may postdate it — and it was being set to `close_time`. For an open market
that is in the future, so the guard permitted every feature up to kickoff, which is
precisely the lookahead it exists to prevent. It now stores the price timestamp, the
real information boundary, in both modes.

**Two new columns, both nullable on purpose.** `Signal.closeTime` lets the board drop
a market the moment its game starts; without it the only available ordering is "most
recent run for this ticker", which happily serves a game from last month forever.
`Signal.priceAsOf` lets the UI say how old a quote is instead of implying it is
current. Nullable because every row written before this change was a settled backtest
signal, and `closeTime > now()` is false for NULL — so they drop out of the board with
no backfill and no migration risk.

**Settled mode is now deduplicated by ticker.** A settled market's entry price never
changes, so re-running the backtest re-emitted the same signal daily and the Track
Record would have counted one decision thirty times. Live mode re-emits by design —
the board wants the new quote.

### An empty board is now required to say why

Three unrelated causes look identical to someone staring at a blank page, and each
demands a different response: wait, wait longer, or go fix the archiver. The run
counts them (`listed` / `quoted` / `fresh`) and the count travels in the run record,
so the UI reads what happened instead of inventing an explanation. Today it renders
"291 markets listed, none quoted yet" — which is true, verified against the live API:
every open NFL market, game winners included, has no bid, no ask and an empty
orderbook ten days out.

### Three things that meant CI could never have worked anyway

Found while verifying the above, each independently fatal:

1. **`ingest-nflverse` had been failing every scheduled run.** nflverse reshaped depth
   charts at the 2025 boundary — 2024 publishes `club_code`/`depth_position`, 2025+
   publish `team`/`player_name`/`pos_abb`/`pos_rank`. Both are still served. The drift
   check knew only the new shape, so a 2024 file failed it and took reference sync,
   depth sync, context, projections and grading down with it, daily, since the day it
   was scheduled. Datasets can now declare `alternates`: satisfying any known schema
   passes, satisfying none is real drift. The check keeps its teeth.

2. **`pbp`, `players` and `teams` are not in the ingest default dataset list** and
   every one is required downstream — ratings and volume, the ID crosswalk, and team
   branding respectively. CI ingested "successfully" and then had no play-by-play to
   project from. They are now fetched explicitly.

3. **Nothing ever read the market archive back.** Blob storage is written by the
   archiver and read by nobody, and a CI checkout has an empty `data/`. A live run in
   CI would have found no snapshots at all. Live mode now takes its own snapshot
   (`--refresh`) before pricing, which also means the board is priced off a quote
   seconds old rather than whatever happened to be lying on disk.

**Cadence is a request, not a promise.** `archive-markets` asks for every 15 minutes
and actually fires roughly every 2–3 hours — GitHub throttles scheduled workflows hard
on a private repo. `project-live` is written as hourly and should be read as an upper
bound. This is why the board's staleness indicator now reports the age of the *price
being shown* rather than the age of a job: a job can succeed while finding nothing,
and a price can be current while some unrelated job is behind. The Slate reports
`sync_context` instead, because the Slate is built from schedule and rest, not prices,
and pointing it at the market archiver made it go red on a page that was perfectly
current.

---

## An empty assignment is not a value

**2026-08-30.** `.env.local` held `DATABASE_URL=""`. Config loaded `.env.local` and
then `.env`, and `load_dotenv` will not override a variable that is already set —
counting an empty assignment as set. So the empty string won permanently, and the real
URL in `.env` was never read.

Nothing raised. Database writes are best-effort by design, so `is_configured()`
returned False and every job skipped its writes and reported success. The pipeline
looked healthy while writing nothing.

`vercel env pull` produces exactly this file for a variable it cannot resolve, so this
was not an unlucky typo — it is the default outcome of a normal workflow. The files are
now merged explicitly, with empty values treated as "no opinion" rather than as the
empty string, and the real process environment still winning over both so CI secrets
are never overwritten by a checked-out file.

---

## Getting it deployed: four blockers, none of them the app

**2026-08-30.** The project had **zero deployments** — it had never successfully built
once. Four separate causes, found one at a time because each hid the next.

**1. Commit author email.** Every commit was authored `colinsmacbook@Colins-Air.lan`,
a hostname-derived address git invents when `user.email` is unset. Vercel blocks
deployments whose author it cannot tie to an account, so builds came back `BLOCKED`
instantly with no build log at all — indistinguishable from a plan or quota problem.

**2. Framework detection.** The repo root holds `pyproject.toml`, so Vercel decided
this was a Python project and looked for a WSGI entrypoint. Setting `framework` in
`vercel.json` got past detection but then failed on "No Next.js version detected",
because detection reads the ROOT `package.json` and `next` lives in `web/`.

**3. The Prisma schema lived above the app that owns it.** This is what made Root
Directory = `web` impossible: `web/package.json` ran
`prisma generate --schema=../prisma/schema.prisma`, reaching outside the deploy root.
Nothing in `pipeline/` reads the schema — the Python side talks to Postgres in raw SQL
through psycopg — so the schema was simply in the wrong place. Moved to `web/prisma/`,
which makes `web/` self-contained and lets the app deploy as its own root.

**4. Prisma cannot express a fallback env var.** The Neon Vercel integration does not
publish `DATABASE_URL`. It publishes `bet_daddy_archive_DATABASE_URL` (pooled) and
`..._DATABASE_URL_UNPOOLED` (direct), and `env()` in a Prisma schema names exactly one
variable. So the first genuinely successful build produced a reachable app where every
request failed on "Environment variable not found: DATABASE_URL".

Bridged in `web/src/lib/db.ts` before the client is constructed, rather than by copying
the connection string into a second Vercel variable. A duplicated secret is one the
integration cannot rotate, and it would go stale silently the first time Neon cycles
the password. The integration remains the single source of truth; the bridge only
gives its value the name Prisma expects. A local `DATABASE_URL` still wins, so
pointing a developer at their own branch keeps working.

Note the shape shared with the `.env.local` bug fixed the same day: **a value that is
present under one name and absent under another fails silently, because "unset" and
"set to nothing" are indistinguishable to code that only checks presence.**

---

## The model and the price move on different clocks

**2026-08-30.** Requirement: the board should be as close to live as possible. The
constraint discovered while meeting it: GitHub throttles scheduled workflows hard on a
private repo. `archive-markets` asks for every 15 minutes and actually fires every two
to three hours, so anything that waits for that job is hours stale by construction.

Waiting was the wrong shape anyway, because the two halves of an edge do not move at
the same speed:

| half | changes when | cadence |
|---|---|---|
| simulated distribution | an injury, a depth chart, a usage share moves | daily |
| the ask | someone quotes | all day |

Re-running a 20,000-path Monte Carlo to learn that a price ticked a cent is absurd.
Waiting three hours to notice is worse. So **the price is fetched at request time and
the edge recomputed in the web app**, against the distribution the Python job already
stored. Reads are public — no key — which is what makes it possible.

The Python side stays authoritative: it is what gets STORED and graded for CLV. The
TypeScript recomputes the same quantities from the same stored curve, so what is on
screen matches the market as it is now.

**Both sides are re-evaluated, not just the stored one.** The stored signal picked its
side against the price at the time. A price that has moved far enough makes the OTHER
side correct, and recomputing only the stored side would keep recommending a bet the
market has already taken away.

**Repricing happens before the limit is applied.** Cutting to the top N on the stored
edge and repricing afterwards would rank by a number the board does not display — a
market whose price moved *into* a real edge would be missing entirely, which is the
one case most worth seeing.

**No interpolation.** `pOverAtStrike` returns null rather than interpolating a
probability for a strike the projection did not store. An interpolated probability
would be an invented number, and the edge is built directly on it.

**Two implementations of one formula is a liability**, so `checks.yml` pins the
TypeScript to golden values generated from `signal.py` on every push. A fee rate
corrected in one and not the other would show a number that no grade will ever match.

The empty-board census now prefers the live book too: the run's census was true when
the run happened, and an empty board should explain the market as it is, not as it was.

---

## Kalshi writes JAC, nflverse writes JAX, and the alias was backwards

**2026-08-31.** Found while building the consensus job: two of 32 game markets would not
join to the schedule, both Jacksonville.

`crosswalk.py` carried `TEAM_ALIASES = {"JAX": "JAC", ...}` with the comment *"nflverse
uses LA (not LAR), JAC (not JAX)"*. The comment was wrong and the mapping was exactly
reversed. Comparing all 32 team codes from live Kalshi game markets against
`schedules.parquet` settles it in one line:

    Kalshi codes not in nflverse: ['JAC', 'LAR']
    nflverse codes not in Kalshi: ['JAX', 'LA']

**Kalshi writes JAC and LAR. nflverse writes JAX and LA.** Nothing else differs.

Written the wrong way round, Kalshi's `JAC` was never translated — it passed through
untouched and never matched nflverse's `JAX`. Confirmed against three real Jacksonville
players: every one resolved `UNRESOLVED` before the fix and `EXACT` after. The projection
job skips unresolved players *silently*, so **the entire Jaguars roster would have been
missing from the board with nothing raised** — the same failure mode as the Rams
`.replace()` bug, in a different file, found the same way.

It survived because nothing had ever exercised it: no Jacksonville prop market has been
quoted or archived yet, and the 93.8% crosswalk match rate was measured on a sample that
happened to contain none.

The regression test guards the *direction* generically rather than the single case:
every value in the alias table must be a code nflverse actually uses, and every key must
be one it does not. An alias pointing at a code that exists nowhere resolves to nothing,
silently, which is precisely how this survived.

---

## Event-ticker parsing, in one place

Extracted `pipeline/common/tickers.py`. The same event-ticker regex had been written
**four times in `project.py` alone**, alongside two copies of the team-code table and a
fifth reimplementation in TypeScript. All three anchoring bugs this project has found
came from one copy being fixed while the others stayed wrong:

- `ARILV` split at the midpoint → `AR`/`ILV`
- `"SFLAR".replace("LA","")` → `SFR`, disabling the Rams matchup adjustment all season
- `SFBPURDY13` split greedily → `SFB` + `PURDY`

`parse_event()` returns both spellings — normalised nflverse codes for joining, raw
Kalshi codes for round-tripping — because collapsing them is what produced the JAC bug.

---

## Measuring D8's own trigger, for nothing

D8 deferred paid odds data with a revisit trigger: *"Revisit if the archive shows Kalshi
pricing diverging from consensus."* That was unmeasurable, because measuring it looked
like it required the data it was gating. It does not.

Kalshi lists NFL **game** markets, and nflverse already ships closing Vegas moneylines
free — the Slate renders its spreads and totals today. Game markets carry no player, so
none of the cross-source name resolution that made the paid path expensive applies.

Priced at ~$99/month now, incidentally: the 500-credit free tier §4.4 was written around
no longer covers NFL player props. ESPN's undocumented API was checked directly — game
odds return a single provider and `/props` 404s.

**Reference only, and that is load-bearing, not deference.** `signal.py` assumes a $1
binary: the unquoted side is `1 - yes_price`, Kelly uses `b = (1-price)/price`, and
`fees.py` rejects any price outside [0,1] dollars. American odds satisfy none of that.
Keeping this out of the edge path is why none of that machinery had to change.

**Both venues get de-vigged.** Kalshi's two team markets are separate binaries whose asks
also sum above 1, by its own spread. De-vigging the book and comparing it to a raw
exchange ask would report Kalshi's spread as divergence — manufacturing the finding the
comparison exists to detect. There is a test for exactly that.

**Mean absolute divergence is reported alongside the signed mean.** The signed mean is
near zero whenever Kalshi is noisy but unbiased, which reads as agreement and is the
opposite of what noise means to someone taking those prices.

Unquoted games are written as rows with `kalshiQuoted = false` rather than skipped, so
"listed but nobody is pricing it" stays distinguishable from "the job did not run". Today
that is all 32 of them.

---

## Player statistics have to be materialised to be shown

Postgres holds engineered outputs only — Neon's free tier is ~0.5GB and 25 seasons of pbp
will not fit. Correct, and it meant the deployed app had access to **no player statistic
at all**: `data/raw/**` is gitignored and `web/package.json` has no DuckDB.

`PlayerGameStat` and `PlayerSplit` materialise what `usage.py` and `splits.py` already
compute and until now handed only to the projection job in memory. 5,225 game rows and
6,247 splits for 2025, of which **84 clear both gates** — the same 84 the volume model
uses.

Splits are stored *including* the ones that fail, flags intact. The UI filters; it does
not re-decide. Same contract `player_volume.py` honours, and it lets the page say "no
trustworthy split" rather than rendering a blank.

`executemany`, not a loop of `execute`: row-by-row over a network connection took minutes
for 11k rows and would have timed out in CI. Reconciled against the source — Ja'Marr
Chase, 2025 week 2: 16 targets, 14 receptions, 165 yards, 1 TD.

---

## Player pages, and the season they are actually describing

Players are clickable, keyed on `gsisId` rather than `Player.id` — ids are formatted
`nfl:00-0041087` and the colon needs URL-encoding. A player with no gsisId renders as a
plain cell rather than a link to a 404.

The page reuses rather than reinvents: `WhyPanel` for the reasoning behind each open
market (the full stored `reason` payload already round-trips through Postgres),
`reprice()` so a player's edges match the board exactly, and `Sparkline` — which had been
written, committed, and imported nowhere until now.

**The season is stated, never implied.** 2026 has no games played, so every game log
shows 2025. For a player who has changed team that describes a job he no longer holds —
the same failure the starter filter exists to prevent. Where the logged team differs from
the current roster team the page says so outright: *"The history below was accumulated at
TB, and Mike Evans is now listed with SF."*

**Splits against departed players are excluded.** 16 of the 84 trustworthy splits name a
teammate who played in 2025 but is on no 2026 roster. Rendered with the fallback label
those read "With a teammate out, his target share rises 13.8 points" — an effect that
cannot recur and cannot be checked against an injury report. Unactionable, so omitted,
and the empty state says why.

**The hit rate keeps `rationale.py`'s framing verbatim: context, not the reason.** It is
computed with a strict `>` to match how the market settles, and returns nothing below
four games rather than reporting "1 of 2", which reads as 50% and means nothing.

The column set follows the position — a quarterback's target share is noise — and falls
back to inspecting the data rather than trusting the position label when it is missing.

---

## The model was quieter than its own docstrings

**2026-08-31.** Asked what could be added to make the model less boring, the honest
answer turned out to be: almost nothing, and that was not the problem. Measured first:

| candidate addition | effect |
|---|---|
| game context added to volume prediction | R² 0.7164 → 0.7167 (n=11,474) |
| implied team total added to yards prediction | R² 0.2895 → 0.2913 (n=2,626) |
| player's own past efficiency → next game | r² = **0.012** receiving, 0.021 rushing |
| market families not yet modelled | **0 open markets** |

Volume prediction already sits at R²=0.716 and efficiency barely persists, so there is
nothing for a richer model to find. What an audit *did* find was two live bugs and
several layers that were built, tested, documented — and never executed.

### Two live bugs

**The injury list accumulated all season.** `injured_out()` selected `distinct gsis_id`
across the whole file: 726 players in 2025 against 48 in week 1 and 108 in week 18. By
late season ~186 skill players would have been benched and their backups promoted, and
the projection skips non-starters *silently*. Harmless only because the 2026 file does
not exist yet. Starters and absences are now resolved per week, from each market's own
event date.

**`volume_metric` was read 120 lines before it was assigned.** The first market of every
run raised `UnboundLocalError` into a bare `except` and lost all context including the
usage-trend adjustment; every market after inherited the *previous* market's driver, so
a rushing prop following a receiving prop had its "carries trend" computed from targets.
`with_adjustments` could not catch it — the adjustment fired, just off the wrong metric.
Verified on 305 real markets through a rolled-back transaction: `with_adjustments` went
51/53 → 53/53.

### Layers that never ran

**`p_inactive` was 0.0 on every projection**, and the starter filter only refuses
Out/Doubtful, so every **Questionable** player was priced as certain to play. Measured
on zero offensive snaps (not a missing stat line — a WR3 can be active with no
receptions, which inflates the base rate to 28% even for healthy players):

    Out           any   n=419  100.0%      Questionable  DNP      n= 45  48.9%
    Questionable  Ltd   n=232   41.8%      Questionable  Full     n= 83  41.0%
    (none)        Full  n=821   11.9%

On a 60-yard receiving line that moves P(over) from **0.368 to 0.220**. The model had
been overstating every Questionable player's over by about fifteen points. "Not on the
report" is kept distinct from "listed with no designation" — 2% against 11.9% —
because conflating them puts injury risk on every healthy starter in the league.

**The spread never reached the model.** `project_for_game` was called with `None` at both
sites, so `SPREAD_PASS_RATE_SLOPE` was dead and every pass/run split was the season
average — while the comment beside the call claimed an underdog throws more. The sign is
the dangerous half and is verified against outcomes: six-point favourites pass on 53.7%
of snaps against 59.5% for six-point dogs, correlation −0.200. KC now projects 37.2 pass
attempts as a 7-point dog and 34.5 as a 7-point favourite.

### Wind, which I wrongly excluded first time

Initially dismissed on availability grounds, conflating that with effect size. The
effect is real and larger than things already modelled — 1,186 outdoor team-games:

| wind | n | pass rate | yds/att | team pass yds |
|---|---|---|---|---|
| 0–4 | 263 | 0.577 | 6.74 | 235.0 |
| 15–19 | 96 | 0.556 | 6.19 | 206.7 |
| 20+ | 22 | **0.510** | 6.26 | **189.0** |

Wind ≥20mph moves pass rate 6.7 points against 2.2 for a full game-script swing, and it
hits **efficiency** too — the channel `efficiency_multiplier` was written for and never
given a value other than 1.0. Not a stadium confound: demeaning each team against its
own average, a club in wind 6mph above its own norm passes 1.48pp less and throws for
19.7 fewer yards (n=120, 32 teams).

The linear r² is 0.006 only because 68% of outdoor games sit under 10mph — a single
coefficient averages the effect away across games with no wind. Modelled as bands.

**The availability objection was half right.** nflverse backfills weather *after*
kickoff (2025 fully populated, 2026 zero of 272), so it cannot price a market. Open-Meteo
can: free, no key, 16-day hourly horizon, verified live. Coefficients are fitted on
*actual* wind and applied to a *forecast*, so they are shrunk by lead time — a
deliberate under-application, because being half-right about a 27-yard effect beats
being confidently wrong about it.

Three guards, each pinned by a test: a failed fetch returns None and applies nothing
(a silent zero is indistinguishable from calm, which is exactly how the other layers
died); domes are never adjusted; an unknown stadium yields nothing rather than a guess.
The coordinate table is checked against the real schedule in both directions — no
outdoor venue missing, no phantom key implying coverage that does not exist.

### The pattern

Four layers, all dead the same way: written, tested, documented, never called, and
invisible because absence looks exactly like "no effect this week". Every one wired here
now reports a counter — `with_p_inactive`, `with_spread`, `outdoor_games`/`with_wind` —
and wind reports games *seen* alongside adjustments *applied*, because a calm week and a
broken forecast are otherwise the same number.

---

## "Same team" was never one relationship

`parlay.ts` carried correlation priors described as "documented, moderate, and
replaceable once data exists". The data exists. Fitted over 2024-25 player-games:

| pair | prior | measured | n |
|---|---|---|---|
| same player, two markets | 0.55 | **0.82** | 8,571 |
| quarterback → his own receiver | 0.30 | 0.30 ✓ | 4,902 |
| two pass catchers, same team | 0.30 | **−0.02** | 2,078 |
| quarterback → his own back | 0.30 | **−0.08** | 1,301 |
| two backs, same team | 0.30 | **−0.15** | 1,316 |
| opposing quarterbacks | −0.10 | **+0.12** | 1,028 |
| opposing, anything else | −0.10 | +0.02 | 3,829 |

The quarterback→receiver case landing exactly on its prior is what validates the
method; the rest are genuine corrections.

**The structural error was collapsing "same team" into one number.** A quarterback and
his receiver rise together because the same completion feeds both lines. Two receivers
*compete* for the same targets and two backs split the same carries, so those legs are
independent or mildly opposed — not +0.30 correlated. Every one of these errors ran the
same direction: **overstating correlation on a same-side parlay overstates the joint
probability, which flatters the ticket.**

Roles are derived from `marketType` rather than looking up a position, because the leg
already carries the market and a second lookup would be a second source of truth for
the same fact.

The check script's `sameTeam` assertion was itself an encoding of the wrong assumption
and was rewritten rather than deleted: it now pins that a passer-receiver stack beats
two backs, that two backs come out negative, and that opposing quarterbacks correlate
but less than a same-team stack.

---

## The defensive grid reached the explanation but not the projection

`features/defense.py` computes EPA allowed by air-yard band × receiver position — 351
cells across 32 teams. `defense_adjustment` collapsed it with `kind, _ = side` and an
unweighted `avg(epa_per_target)` over every cell.

Two errors compounded. The **position split was discarded**, so the Why panel could say
"SEA allows +0.081 EPA per play against passes to TEs" while the multiplier that moved
the number was the team-wide mean across every band and position. And **rates were
averaged rather than weighted**, so a 30-target deep/TE cell counted as much as a
161-target short/WR cell — discarding the volume weighting the grid exists to enable.

For a tight end facing Seattle in 2025 those disagree by 6.7 points and point opposite
ways:

| SEA vs | z | multiplier |
|---|---|---|
| team-wide | −0.86σ | 0.966 |
| WR | −1.46σ | 0.942 |
| **TE** | **+0.83σ** | **1.033** |
| RB | −0.37σ | 0.985 |

The league comparison is made *within* the same position. If every defence concedes
more to tight ends that is a property of the position, and z-scoring against a
mixed-position distribution would read it as universal weakness.

An unresolved position falls back to the team grade rather than dropping the adjustment:
losing the matchup entirely is worse than using a coarser version of it.

This is the same failure `tests/test_adjustment_wiring.py` was written to prevent —
an explanation describing something the projection did not do — so the regression test
asserts the detail string names the split it actually used.

---

## Current-season team volume was never blended in

`build_team_volume(pbp_path)` was called with one argument, so `current_pbp_path` was
None, the blend weight was 0, and `FULL_WEIGHT_GAMES` never engaged. Team volume was
100% prior-season shrunk to the league mean — and with `PLAYS_SHRINKAGE = 0.14` that
means the entire league sat in a **1.3-play band (60.5 to 61.8)**, permanently.

The current season is now passed when the file exists, and `teams_with_current_season`
is reported out of 32. Zero before week 1 is correct; zero in November means the blend
has gone inert again.

---

## Recent form is real, and was applied four times too hard

The plan was to test `usage_trend` and then decide. The unconditional numbers argue for
deleting it: as single predictors the season mean beats recency outright (target share
r² 0.439 against 0.404 for the last three games; carries 0.539).

That is the wrong comparison. The question is not "which single predictor is better",
it is "does the DEVIATION add anything once the season mean is already known".
Regressing next-game target share on both, over 1,972 player-games:

    season mean alone           R² = 0.4276
    + recent-form deviation     R² = 0.4357     coefficient +0.248

So recent form carries real information and roughly a quarter of a deviation persists.
Keep it — but the adjustment was applying the deviation at 60–100% of face value,
because the only shrink in the code was the **sample-size weight**.

Those answer different questions. The sample-size weight asks *do I trust this estimate
of the deviation*; persistence asks *how much of a true deviation carries forward*. Both
belong, and only the first was there. A five-game trend was moving the projection about
four times more than the data supports.

`USAGE_TREND_PERSISTENCE = 0.25` now applies alongside it, capping the effective swing
at 2.5% rather than 10%.

This one could not have been evaluated before the `volume_metric` fix: the trend was
being computed from the wrong volume driver on every market after the first, so any
measurement of its value would have been measuring noise.

---

## Anytime touchdown: the module argued for goal line, then priced red zone

`anytime_td.py` opens by saying *"a back with 4 carries inside the 5 is a better
anytime-TD bet than one with 20 carries between the 20s."* It then computed
`gl_touches_per_game`, never read it, and simulated from a single pooled red-zone rate.

Measured over 2025, the pooling destroys the distinction it was written to make:

| zone | touches | TD rate | share of all TDs |
|---|---|---|---|
| inside the 5 | 1,240 | **0.437** | 40.0% |
| 6 to 20 | 3,589 | **0.131** | 34.8% |
| outside the 20 | 25,948 | 0.013 | **25.2%** |

Two separate errors. A goal-line touch scores **3.3×** more often than a red-zone touch
outside the five, and the model averaged them together. And **a quarter of all offensive
touchdowns are scored outside the 20** — which the model could not produce at all,
because it only counted red-zone touches.

The zones also interact with position, so baselines are keyed on both: a back converts
0.386 at the goal line and 0.073 in the rest of the red zone, while a receiver converts
0.453 and 0.185, and a receiver is 2.6× more dangerous than a back in the open field.
One rate per position cannot say that.

**Shrunk, not switched.** The first rewrite kept a hard 25-touch threshold and promptly
produced its own artefact: Derrick Henry went 0-for-38 outside the five, cleared the
threshold, and was assigned a conversion rate of exactly 0.000 — the model asserting he
could never score from there. Every other small-sample estimate in this project is
shrunk; this one was not. It now blends toward the positional baseline with a 25-touch
pseudo-count, and nobody is assigned an impossible zero.

The Why panel gets one row per zone, so it shows *where* the probability comes from
instead of a single pooled number.

---

## A guard that never runs is not a guard

`point_in_time.py` was written, documented, tested — and imported by nothing outside its
own test file. Its docstring names the stakes exactly: *"a leaky backtest looks like a
brilliant model."* The protection it describes did not exist.

Now wired in two places:

- **Per market:** the price being modelled against must predate kickoff. In live mode
  the close-time filter makes this nearly impossible; in settled mode it is the entire
  integrity question, because a snapshot taken after kickoff prices a game whose result
  is already known. Refused as `leakage_price_after_kickoff` rather than crashing.
- **At startup:** if the current-season play-by-play already contains a game on the
  slate, the run **fails**. That blend feeds team volume, so a file holding the game
  being priced means the model is reading the answer. This one is fatal rather than a
  warning precisely because the symptom is a model that looks excellent.

A missing or malformed file still passes — the guard has to catch leakage without
becoming a new way for the pipeline to die.

---

## Top Picks: two of the three kinds asked for

The request was props, spreads, and over/unders. Two of those exist; the third was
measured and refused.

**Ranked within each kind, never across.** A prop edge is cents per contract after
fees; a game lean is points of disagreement. Combining them into one score would hide
which is which, and the combining weight would be invented.

**Spreads exposed the sharper bug.** `GameLean.confident` means the model projects a
meaningful MARGIN — not that it disagrees with the market. Ranking on it put a
**1.9-point disagreement** at the top of the list. And `disagreement = margin −
market_spread`, both from the home team's perspective, so a **negative** value means the
model likes the home team LESS than the market does — and the side with value is the
*away* team. The first version named `leanTeam`, which would have recommended the exact
team the model was fading. ARI at LAC is the clean example: the model has LAC by 5.1
against a market spread of 10.5, so the play is **ARI +10.5**, not LAC.

Picks are now gated on |disagreement| ≥ 3.5 and the side is derived from its sign.

**Over/unders are deliberately absent, and the page says so with the numbers.**

- Across 1,087 games the closing total misses the actual score by **13.0 points**,
  against 13.6 for always guessing the league average — the market itself explains only
  **8.7%** of the variance in game totals.
- Adding this model's team ratings to that line improves the error by **0.027 points**,
  and the fitted coefficient comes out with the **wrong sign** — the signature of
  fitting noise.

A total pick would be a coin flip presented as a read.

**Shown as context instead.** The section lists the market's total per game with the
**implied team totals** derived from it — `total / 2 +/- spread / 2` — which is the half
that bears on a prop: a receiver on a team implied for 30 points has more to play for
than one on a team implied for 17. Nothing else in the app derives that number.

Wind is shown where the schedule carries it, but not as an edge. Measured on 595 outdoor
games, those above 15mph land **0.9 points under** the closing line and games under
10mph land 1.4 over — directionally right, tiny, and on 59 games. The market prices
weather already; the honest use of a wind forecast here is describing conditions, not
claiming a mispricing.

---

## Pre-launch sweep

Real users get the link before Week 1, so this pass looked specifically for things that
are invisible today and break the moment data arrives.

### The board filter spanned two identifier spaces

`getBoard(limit, gameId)` accepted a game and never filtered on it — there was no clause
in the SQL. Clicking a game on the Slate rendered a *"Showing props for NE at SEA"* chip
above the entire league's board.

The reason it was never wired is that the two sides are different identifier spaces:

    nflverse:  2026_01_NE_SEA     season_week_AWAY_HOME
    Kalshi:    26SEP09NESEA       two codes concatenated, no separator

`Projection.gameId` holds the Kalshi event ticker; the Slate links the nflverse id.
`tickerMatchesGame` now maps between them, matched on **teams rather than dates** —
nflverse dates a game by local kickoff and Kalshi by its own event day, and they
disagree on late Sunday and Monday games. It carries the JAC/JAX and LAR/LA aliases,
because that mapping has already made a franchise disappear once.

The same confusion had reached Top Picks, which called `gameLabel` (the nflverse parser)
on a Kalshi ticker and would have printed `26SEP10SFLAR` raw.

### P(inactive) would have zeroed every injured player in Week 1

The worst find, and completely silent. `build_inactivity_table` LEFT joins snap counts,
so a player with no matching snap row counts as inactive. Pair a **2026** injury report
with a **2025** snap-counts file and every cell resolves to `p_inactive = 1.000`, on
large samples, with `is_empty` False.

Every player on the injury report would then be projected as certain not to play — the
whole projection zeroed — while `with_p_inactive` reported the layer as working
perfectly.

That was the shipping default: `--snaps snap_counts_2025.parquet` with `--season 2026`.

Two fixes. The table now refuses to build unless the snap data actually covers the
season being measured, so a mismatch yields no layer rather than a confidently wrong
one. And the projection takes a separate `--current-snaps`, because the two consumers
genuinely want different files: the with/without splits are built from history, while
P(inactive) must be measured on the season being projected.

### Smaller, still user-facing

- **The Slate showed a bare spread.** `+3.5` on "NE @ SEA" with no team attached reads
  most naturally as NE getting points — the exact opposite of what it means. Now
  rendered as a sportsbook would: `SEA -3.5`.
- **Anytime-TD signals store no distribution**, and `reason.percentiles &&` let an empty
  object through, so the Why panel would have drawn a chart placeholder above five
  dashes. A distribution is meaningless for a binary market; the section is omitted.
- **The anytime-TD explanation claimed a baseline it was not using.** Rates are shrunk
  toward the positional baseline, not switched to it, so a 46% blend was being described
  as "the WR baseline". It now says which side it mostly is, with the touch count.

### What could not be tested

Two of six market families have never produced a signal: `receptions` has no settled
markets in the archive and `anytime_td` has never appeared in it at all. Both were
exercised directly rather than through the projection, and both produce valid,
JSON-safe payloads — but neither has round-tripped through Postgres into the UI.

---

## The game leans have no measured edge, and now say so

Asked to keep the spread section but make it more accurate, the honest finding is that
the predictions cannot be made more accurate — so what was made accurate is the claim.

Backtested on 544 out-of-sample games (2024 projected from 2023, 2025 from 2024), taking
every game where the model disagreed with the closing spread by 3.5 points or more:

| | |
|---|---|
| model's side covered | **46.7%** (n = 272) |
| break-even at −110 | 52.4% |
| model correlation with actual margin | +0.181 |
| closing spread correlation | +0.504 |

Four attempts to improve it, all measured, none working:

- **Refit the scale.** RMSE 14.077 against 14.091 raw. The model is not merely
  mis-scaled.
- **Add it to the market.** Regressed alongside the closing line, the model's
  coefficient comes out **negative (−0.33)** — conditional on the market it points the
  wrong way, and the disagreement correlates −0.124 with the home cover margin.
- **More prior data.** 2024 projected from 2023 covered 45.3%, worse than 48.1%.
- **Wait for in-season data.** Weeks 1–4 / 5–10 / 11–18 covered 47.4% / 54.3% / 44.3%
  — no durable pattern.

The cause is visible in the correlations: the market already contains everything this
model knows and much it does not, so a disagreement is far more likely to be model error
than a mispricing. The model's predictions also barely differentiate games at all —
sd 3.06 against the market's 5.90 and actual margins' 14.29.

n = 272 is not enough to call this reliably anti-predictive; the interval spans roughly
41% to 53%. It is more than enough to say there is no evidence of an edge.

**The record is rendered above the leans, not beneath them.** A list of teams with point
figures reads as a recommendation regardless of what a footnote says, and this list has
not earned that reading. The per-game figure is labelled "disagreement" rather than "off
the market", and `LEAN_BACKTEST` is pinned by a test that fails if the cover rate ever
crosses break-even without being re-measured — because at that point the UI copy calling
them edgeless has to change too.

The player props are a separate model against a far thinner market and do not inherit
this result. This is specifically the team-rating margin model.

---

## Kalshi renamed every price field, and the board silently went blank

**2026-09-02.** Reported as "player props are available on Kalshi and it's not showing
on the site." Correct, and the cause was ours.

Kalshi restructured the market response: prices gained a `_dollars` suffix and
quantities an `_fp` suffix. `yes_ask` became `yes_ask_dollars`, `volume` became
`volume_fp`. **The old keys are absent, not null**, so `m.get("yes_ask")` returned None
for every market on the exchange. Nulls filled the archive, `_open_prices` filtered them
all out, and the UI reported "396 markets listed, none quoted yet" — which was a
sentence the code had been carefully written to produce, and completely false.

What made it survive: an unquoted market and a misread field produce *identical* output.
The census counters, the freshness guard, the empty-state copy — every honesty mechanism
built into this project reported the same thing for both. The control that caught it was
scanning **non-NFL** series and finding zero quoted markets across the entire exchange,
which is not a believable state of the world.

Both spellings are now read, new first, via `FIELD_ALIASES` in `common/kalshi.py`, so a
rollback or partial rollout keeps working. And the guard that was missing: a snapshot
where **no market carries a recognised price key** records a `schema_drift` error rather
than a column of nulls. A market with no bid is ordinary; a slate with no bid *field* is
the exchange having moved.

### Two more bugs the live prices exposed

**The strike was off by one on every count market.** The real strike is `floor_strike`,
not the ticker suffix: "Rhamondre Stevenson: 8+" has ticker `...-8` and
`floor_strike = 7.5`, because it settles on *more than 7.5*. The simulator computes a
strict `P(> strike)`, so every receptions and touchdown line was priced as P(≥ 9) while
the market settles P(≥ 8) — a systematic error, always the same direction. Sam Darnold's
"1+ passing TDs" was priced at 42% (P(≥2)) against inputs implying 78% and an actual
2025 rate of 70.6%.

**The no-side price was invented.** `compute_edge` infers the no-side as `1 - yes_ask`,
which is fine on a two-sided book and fiction on a one-sided one. Stevenson 8+ quoted
`yes_ask 0.97` with `no_ask 1.0000`; the inferred 0.03 implied a **97-cent edge on a
contract that cannot be bought at any price**, and it sorted to the top of the board.
Kalshi publishes `no_ask_dollars`; the archive now carries it and the projection passes
it through instead of letting the maths guess.

Older snapshots have no `no_ask` column, so the selectors read the glob with
`union_by_name` and a missing value stays null rather than breaking the run.

**Result: 396 markets, 396 quoted, 359 signals on the board.**

---

## Volume was inflated ~25%, and it put one player in seven of the top ten rows

Reported from the board: too many rows were the same handful of players, and they read
as disagreements with the market rather than as forecasts. Both were true, and the first
had a cause in the model rather than in the presentation.

### Two compounding errors in `player_targets = team_targets x target_share`

**A unit mismatch.** `features/usage.py:127` defines `target_share` over team TARGETS,
and its own comment warns that counting sacks and throwaways "inflates the denominator
and makes target_share sum to ~0.88, not 1.0." `model/project.py` then multiplied that
share by `TeamVolume.pass_attempts` — pass PLAYS, sacks and throwaways included.
Measured over 2025, targets are **89.1%** of pass plays league-wide, so every receiving
baseline was inflated ~11%, always upward. The exact error the neighbouring module
documented, made one file over, because nothing tied the two halves together.

Fixed by giving `TeamVolume` a `targets` property derived from a measured per-team
`target_ratio` (year-over-year r = 0.502, shrunk 0.50). `tests/test_volume_units.py`
now pins the invariant: for every team, `usage.py`'s `team_targets` must equal
`TeamVolume.targets`. The same test caught that the two scrimmage filters disagreed on
`qb_kneel`, which biased `carry_share` the other way.

**Shrinking one half and not the other.** `PLAYS_SHRINKAGE = 0.14` pulls a team's pace
almost to the league mean, correctly, for predicting that team's own next-season pace.
But pairing a mean-reverted team volume with an un-reverted player share breaks the
identity: it lifts players on low-volume offences and drops those on high-volume ones.

Seattle threw 32.4 times a game in 2025, second-lowest in the league:

| | team targets/g | x his 0.368 share | |
|---|---|---|---|
| SEA actual | 26.8 | **9.9** | his real average: 9.6 |
| what the model used | 33.4 | **12.3** | the model stated 12.0 |

That put Jaxon Smith-Njigba's projected mean at **132.9** receiving yards against a
**105.5** season average — 106.7 even restricted to games he played 75%+ of snaps. A
mean above the whole ladder shows a positive edge on *every rung at once*, which is how
one player came to hold 14 `rec_yds` rows and 11 `receptions` rows and sweep the board.

### The measurement, and what it changed

There is an identity hiding in the formula: `share x team_volume` **equals** the
player's own per-game rate exactly, when neither half is shrunk. So the decomposition
can only earn its keep through the shrinkage. Tested on 411 player-seasons, 2022-25:

| baseline | RMSE |
|---|---|
| share x shrunk team volume (what shipped) | 1.541 |
| share x unshrunk team volume | 1.523 |
| own rate x shrunk team ratio | 1.351 |
| **own rate, shrunk to the pool** | **1.328** |

The shrinkage does not merely fail to help — it is the worst of the four. Prior-season
team volume carries r² = 0.021 for plays, so it was moving the estimate away from the
one quantity that does predict.

**The level is now the player's own rate, regressed toward the pool of players in his
own position; team volume enters only as a RATIO of adjusted to unadjusted** — spread,
wind, and teammate absence, which are genuinely new information about this game. With no
adjustment the ratio is 1.0 and the projection is the measured-best estimator.

**Position is not optional.** A single pool was tried first and is actively harmful:
pooling every rusher gives 9.01 carries a game, which is a running back's number, and
shrinking a QUARTERBACK toward it pulled Sam Darnold from his own 8.7 rushing yards to
17.5 — straight to the top of the board on an edge that was pure artefact. Pools are
fitted per (metric, position) and an unmeasured pair is left **unshrunk**, because
shrinking toward the wrong pool is worse than not shrinking.

Fitted in `scripts/fit_volume_baseline.py`; constants in `player_volume.OWN_RATE_PRIOR`.

Across all 43 projections with a 2025 comparison, the median projected-to-actual ratio
is now **0.968** and the mean **1.000**.

### A third no-op in the same family

`baseline_override = tvq.pass_attempts * own` where `own = attempts_per_game /
tvq.pass_attempts` cancels exactly, so the QB path's spread and wind terms moved nothing
while the comment above it claimed passing props were connected to game script. The
share is now taken off the *unadjusted* team volume and applied to the adjusted one.

## The board shows one row per projection, led by the projection

A Kalshi ticker is unique per strike, so the pipeline emits twenty-odd signals for one
player in one game from a **single** simulated distribution. Their errors are perfectly
correlated. `getBoard` deduped on `distinct on (marketTicker)`, which collapses repeated
runs of one market and does nothing about one player holding many.

`parlay.ts:195-222` already refuses this pairing inside a ticket — *"the tighter one
subsumes the other, so the pair adds no information"* — and that reasoning now applies
to the board. `getProjectionBoard` keeps the best rung per (player, market, game) and
reports how many lines it stood for; `getTopEdges` partitions the same way, since six
headline slots are least able to survive being six views of one opinion.

Each row leads with the model's projected number and shows the market it disagrees with
second. `/board` deliberately keeps every strike — that is what it is for.

## Two display defects the strike work exposed

**Live repricing had been dead.** `getBoard` parsed the strike off the ticker suffix
(`130`) while `Projection.pOverByStrike` is keyed on `floor_strike` (`129.5`).
`pOverAtStrike` tries `"130"`, `"130.0"`, `"130"` and never `"129.5"`, so it returned
null and every row fell back to `priceSource: "stored"`. Measured against production:
**0 of 359** rows resolved. `Signal.strike` now stores the real strike and all 359
resolve. `pOverAtStrike` still refuses to interpolate, which was never the problem.

**Every strike read one too high.** "8+ receptions" settles on more than 7.5, so
rendering the floor as "over 8" asks for nine. The yes side is now stated the way the
market states it — "at least 8" — and the no side, "under 8", was already right.

## `backfill-history` was broken by its own fix

`ace45c5` changed `_strike` to take the market dict so it could read `floor_strike`, and
`kalshi_backfill.py` still passed a ticker string. Every run from 2026-09-02T23:32
onward died with `AttributeError`. This is the **durable** path for price history — the
15-minute archiver is best-effort — so it silently stopped the one job whose data cannot
be re-fetched later. Fixed, and the archive now records 249.5 where it had been writing
250.

## The Slate reported "0 props" for every game

Found while verifying the board changes. `getNextSlate` counted a game's props with
`where p."gameId" = g.id`, but `Projection.gameId` holds a Kalshi EVENT ticker
(`26SEP09NESEA`) and `Game.id` an nflverse id (`2026_01_NE_SEA`). Different identifier
spaces, so the correlated subquery matched nothing and every game on the Slate linked
to its board saying it had none — including the only two games that had any.

This is the third instance of the same confusion (the board's gameId filter and the
parlay's same-game correlation were the first two), so the comparison now lives in one
place: `eventMatchesGame` in `markets.ts`, which `tickerMatchesGame` delegates to. The
count is joined in TypeScript because the mapping needs the team-code alias table
(Kalshi writes JAC/LAR where nflverse writes JAX/LA) and cannot be expressed as a SQL
equality. NE @ SEA now reads 183 props.

## Kneel-downs are official carries, and the projection was dropping them

Flagged while fixing the volume inflation and confirmed afterwards. `load_player_inputs`
excluded `qb_kneel = 1` from `carries_per_game` and from the yards-per-carry bootstrap.
That is the right convention for describing football and the wrong one for pricing a
market, because a Kalshi rushing-yards contract settles on the official statistic and the
NFL scores a knee as a rushing attempt for negative yards.

**Measured, not assumed.** Of the 2025 players who took at least one knee, comparing
season totals against nflverse weekly stats:

| official total matches | players |
|---|---|
| kneel-INCLUSIVE | **34** |
| kneel-free | 7 |
| neither | 18 |

J.J. McCarthy's official 181 yards on 37 carries is exactly his kneel-inclusive total;
kneel-free he reads 191 on 28. Justin Herbert, Davis Mills and Malik Willis match
exactly the same way. (The 18 "neither" cases sit *between* the two, a smaller
discrepancy of mixed sign — a handful of attempts nflverse credits differently — and are
left alone rather than guessed at.)

The cost of excluding them was small but strictly one-directional: **0.77 rushing yards
per game across 38 quarterbacks, 1.8 at worst** (Stafford), and exactly **zero** for every
running back, receiver and tight end, none of whom took a knee all season. Kneels carry
no `passer_player_id` and no `receiver_player_id` (0 of 434), so admitting them cannot
reach the passing or receiving inputs.

Sam Darnold's rushing projection falls from 12.93 to **9.02** against his official 7.9,
and drops off the board's top ten. Brock Purdy lands at 16.19 against 16.3.

**Two conventions now coexist deliberately.** Rate inputs face settlement and count
kneels; the share denominators in `features/usage.py` and `model/team_volume.py` describe
football and do not. That is safe only because of the anchoring change above — team
volume enters the projection as a RATIO of adjusted to unadjusted, where any consistent
convention cancels. `tests/test_volume_units.py` pins both halves: that the rate inputs
include kneels, and that the two share modules still agree with each other.

The QB carries pool was refitted kneel-inclusive (4.37, k 0.76, n=52; previously 4.19,
k 0.74, n=42 — more quarterbacks clear the two-a-game floor once knees count). Fitting a
pool on one definition while feeding the anchor the other is a pool the projection never
sees, and for quarterbacks the definitions differ by roughly 0.7 carries a game, which is
most of what the shrinkage does at that volume.

## Fixing the strike lookup switched on a path that still had the phantom-edge bug

The board's top row read **Stevenson under 25 receiving yards, +34c**, model 56% against
a market 21%. It was not real, and it was a bug I introduced by fixing a different one.

The stored signal for that market says model 0.562, market 0.560, net **-1.53c** — no
edge. The +34c came from live repricing. `reprice` called `computeEdge(pOver, q.yesAsk)`
with no no-side price, and `computeEdge` then infers `1 - yesAsk`.

The real quote, taken from Kalshi:

    yes   0.44 / 0.79        no   0.21 / 0.56

The complement of the yes ask is 0.21, which is **exactly the no BID** — the price
someone would pay you, not the price you pay. Buying the no side costs 0.56. Repricing
against the inferred number valued a 56-cent contract at 21 cents and turned the book's
35-cent spread into edge.

**This is the same bug already fixed in Python**, where `compute_edge` has taken the real
`no_ask` since the field-rename work. The TypeScript path never got it. It stayed
invisible because `pOverAtStrike` could not match a floor strike against a ticker suffix,
so `reprice` returned `priceSource: "stored"` on every row and the inference never ran.
Repairing the strike key turned on a code path carrying an unfixed copy of a known bug —
0 of 359 rows repriced before, 359 of 359 after.

The lesson is narrower than "port fixes to both sides": a dead code path is not a safe
one, and re-enabling it needs the same review as writing it. The edge formula being
implemented twice is exactly what `check:edge` exists to guard, and it did not cover the
no-side argument. It does now, using these measured prices and the one-sided book
(`yes_ask 0.97`, real `no_ask 1.0000`) that motivated the Python fix.

`LiveQuote` now carries `noAsk`, read through the same alias table as the other price
fields.

## The wind layer was an invisible coin flip in production

Found while auditing the board. Consecutive `project-live` runs an hour apart, on the
same slate, reported:

    outdoor=1013  with_wind=104
    outdoor=1013  with_wind=0

Same games, same forecast horizon, materially different projections for every outdoor
game — decided by whether an HTTP call to Open-Meteo happened to succeed, and recorded
nowhere. `wind_for` swallowed the exception and cached `None`, which is indistinguishable
from a calm slate.

The module docstring named this exact failure ("silently treating a failed fetch as calm
is the failure mode to design against") and the mitigation it specified — reporting
outdoor games seen alongside adjustments applied — is what surfaced it. But the pair only
supports an inference; nothing measured the fetch itself.

Two changes. `fetch_forecast` now retries a 5xx or 429 up to `ATTEMPTS` times with
backoff, and does NOT retry a 4xx, which will not fix itself. And the run meta counts
`wind_venues_tried` against `wind_venues_failed`, so a failed fetch is stated rather than
inferred: a run with failures says so loudly, and a run where every venue answered and
none was windy says *that* instead. Verified locally at `outdoor=1013 with_wind=104`.

`tests/test_wind.py` pins the part that cannot be fixed in code: below the actionable
threshold a genuine 2mph reading and a failed fetch produce the identical `NO_EFFECT`
object. The effect type cannot carry that distinction, which is precisely why the
counters must.

## The anchor assumed last season's job was this season's

An audit against public reporting found the board's largest edge was wrong. **Malik
Willis, under 149.5 passing yards, +38.9c**, off a projection of **109.4** against a
public consensus of 175-211. The cause, from our own data:

    Malik Willis 2025:  GB, 4 games, 42% of snaps, 105.5 pass yds/game
    Model projects:     109.4

He was Green Bay's backup and is Miami's starting quarterback. The model reproduced a
backup's per-game rate for a starter, and `MIN_GAMES = 4` admitted him by one game.

**This is a cost of the anchoring change above.** Moving the level onto the player's own
prior rate measured better, and it also made a stale role carry straight through, because
team volume now supplies only a ratio. The improvement and the regression are the same
edit.

**The first hypothesis was wrong and was discarded.** Sample-size-dependent shrinkage
looked obvious -- four games should count for less than seventeen -- but measured over
244 WR season pairs the optimal shrinkage is flat (0.75 / 0.75 / 0.70 / 0.80 across 2-6,
7-11, 12-14 and 15-18 prior games), and the fixed 0.78 costs 0.002 RMSE on the thinnest
bucket. Thin history is not the signal. **Role change is**, and it is invisible in the
rate history.

The signal that does see it is SNAP SHARE. Median offensive snap share by depth slot,
measured on 2025:

    QB1 0.922   RB1 0.534   RB2 0.183   TE1 0.601
    TE2 0.363   WR1 0.776   WR2 0.572   WR3 0.390

Bucketing 215 receiving pairs by prior snap share over the norm for the slot the player
occupies in the OUTCOME season:

    prior_snap / role_norm      n     RMSE     bias
    < 0.60  (role grew)        10    1.304   -0.250
    0.80-1.25  (matched)      122    1.309   +0.213
    > 1.60  (role shrank)      19    1.490   +1.053

A player whose role shrank is over-projected by a full target per game. That direction is
refused on measured evidence. The role-GREW direction is refused on weaker grounds --
n=10 and the RMSE is not worse -- so it rests on sampling rather than prediction: a
quarterback who took 42% of snaps has no observation of a starter's workload, and this
project's answer to missing data is an empty state naming the reason.

61 of 1,918 projections are now refused. Willis, Jauan Jennings (82% snaps, now WR3),
Cooper Kupp (76%, now WR3), Jordan Mason and Chris Rodriguez Jr. all drop out; committee
backs whose role did NOT change -- Warren and Dobbins at 51% against an RB1 norm of 0.534
-- are correctly kept, which a blunt snap-share floor would have deleted.

### A refusal that changed nothing

Refusing wrote no signal, and the board went on showing Willis at the top. `getBoard`
took the newest row per TICKER, so a market the latest run declined to price kept serving
the superseded opinion indefinitely.

All four board queries now scope to a single run: `runTs = max(runTs)` among open
markets. project-live reprices every open, quoted, fresh market hourly, so **absence from
the latest run is a decision**, and the board now honours it. This is the third time a
guard in this codebase did nothing because the path it guarded was not the path being
read.

Per-snap rates scaled by an expected role -- the real fix -- are deferred until after
Week 1 rather than rebuilt under time pressure.

## P(inactive) could never have fired, and the reason was in the wiring

`with_p_inactive` read 0 on every run since the layer was written, and the warning
blamed the data: "either no injury report is published yet, or the availability table
failed to build". Neither. The rate table was being built from the season being
PROJECTED:

    build_inactivity_table(injuries_2026, snap_counts_2026, players, season=2026)

That pairing is structurally empty in week 1 and always will be. The table measures how
often a given designation preceded zero snaps, which needs designations paired with
outcomes — and in week 1 no snap has been taken. The comment above the call asserted the
opposite ("P(inactive) must be measured on the season being projected") and the guard in
`features/availability.py` then correctly refused to build anything, so the layer stayed
dark while every diagnostic pointed at nflverse.

The halves are now separated explicitly, which is what the module always intended:

    rates   <- injuries_2025 + snap_counts_2025, season 2025   (what happened)
    status  <- injuries_2026, this week                        (who is listed now)

`with_p_inactive` went from 0 to **1857 of 1857**. The mismatch guard is untouched, so a
wrong `--rates-season` still yields no table rather than a table of 1.000s.

## A share that may be about to move cannot be priced

Reported from the board: Rhamondre Stevenson's picks looked wrong because TreVeyon
Henderson is expected to miss Week 1. Correct, and the model had no way to see it.

    Stevenson  14 games   9.4 carries/game   43.2 rushing yards/game
    Henderson  17 games  10.6 carries/game   53.6 rushing yards/game

Stevenson's 39.4-yard projection is his COMMITTEE rate. The model took UNDER 49.5 at
+25.8c — its largest edge on him — against a back who inherits a ten-carry role if
Henderson sits. Henderson did not practise (ankle); the measured `(none)/DNP` cell puts
that at **34.3%**.

Three mechanisms should have caught it and all three were inert:

  * `starters.injured_out` selects `report_status in ('Out','Doubtful')`. A Wednesday
    practice report carries no game designation — every `report_status` in the Week 1
    file is null — so `absent_teammates` received an empty set.
  * `splits.build_with_without` needs prior-season games where Henderson sat and
    Stevenson played. Henderson played all seventeen. The sample is empty and the
    adjustment is suppressed by its own significance gate, correctly.
  * `p_inactive` lowers a player for his OWN injury and never moves a teammate's share.

None of that is fixable by Sunday. The projection is genuinely a conditional — one
number if Henderson plays, another if he does not — and the simulator returns a single
mean, which is the one outcome that cannot occur. So `features/room.py` refuses: when a
same-position teammate holding at least half this player's prior snap share carries an
absence probability above 0.25, and no with/without history exists to price the shift,
no signal is written.

23 of 1,918 projections refused. The threshold sits between the two measured cells it has
to separate — `(none)/full participation` at 0.119, which is ordinary, and `(none)/did
not participate` at 0.343, which is not.

This is the third refusal guard in this codebase and the pattern is now explicit: where
the model cannot express a thing, it declines rather than averaging over it. The proper
fix — projecting both branches and weighting by absence probability — waits with the
per-snap rebuild until after Week 1.

## Quarterback rates were carried forward at full strength

Reported from the board: Cam Ward is Tennessee's starter and a touchdown is probable,
but the model projected **0.9 passing touchdowns** and drove a 98%-confident UNDER.

He threw 15 on 595 attempts as a rookie — a **2.52%** touchdown rate against a league
average of 4.47% — and the projection reproduced it exactly, because nothing regressed
it. The identical omission ran the other way on the same board: Stafford at a 7.7% rate
projected 2.8 a game, a 47.6-touchdown pace, above his own outlier season.

Measured over 77 quarterback season pairs, 2022-25, minimum 200 attempts:

    metric                  r      pool     best k    RMSE      unshrunk
    pass TD rate         +0.385   0.0447    0.35     0.01104    0.01375
    completion rate      +0.439   0.6156    0.35     0.02966    0.03853
    yards per completion +0.295  11.0589    0.25     0.85726    1.15939
    attempts per game    +0.489  33.7092    0.45     3.20257    3.88497

Not one of these is a strong signal — the best explains 24% of the next season — and all
four were used raw. Shrinking cuts error by a fifth to a quarter on each.

    Cam Ward          0.0252 -> 0.0379     0.88 -> 1.35 TDs/game
    Matthew Stafford  0.0770 -> 0.0550     2.80 -> 1.92

Both left the top of the board, which is the point: those edges were artefacts of last
season repeated, not reads on this one.

**The sample floor is the load-bearing part.** These priors are fitted on quarterbacks
and mean nothing for anyone else. A receiver's `attempts_per_game` is zero, and shrinking
it toward 33.7 would hand him half a starting quarterback's volume. Below 100 prior-season
attempts the raw value passes through untouched, and a test pins it.

`yards_per_completion` is an empirical draw, not a scalar, and the simulator bootstraps
the player's own completions on purpose. It is rescaled rather than replaced: every ratio
between samples is preserved, so the spread and the right tail stay his and only the
central tendency regresses.

Receiving and rushing efficiency are almost certainly in the same position — the earlier
audit put their year-over-year persistence at r^2 = 0.012 and 0.021, weaker than any rate
here — but they are not fitted yet and are left alone rather than guessed at.

## A side you cannot buy is not a side

Reported from the board: "Cam Ward UNDER 4 passing TDs isn't even available on Kalshi."
Correct. The exchange lists the market; the no side does not trade:

    KXNFLPASSTDS-26SEP13NYJTEN-TENCWARD1-4    floor 3.5
        yes  0.0000 / 0.2500
        no   0.7500 / 1.0000       <- no ask at any price below a dollar

The board showed it at 76c, which is `1 - yes_ask`, which on this book is **exactly the
no bid** — the price someone would pay you.

This is the same phantom edge fixed once already, and the fix is what re-opened it.
`tradeable()` correctly rejects a $1.00 ask as "a one-sided book reported as a number,
not a price" and returns null — and null was the signal `compute_edge` used to decide it
should INFER the price. **The guard that rejects an untradeable price was feeding the
code that invents one.** Threading the real `no_ask` through, as was done last time, does
nothing when the real value is the one the sanitiser discards.

Both implementations now refuse to infer. A `no_ask` that is null, zero, or a dollar
means the no side is **unavailable**, not unknown, and only the yes side is evaluated.
That is the honest reading of a one-sided book, and it removes the inference that has now
produced two separate top-of-board fabrications.

The golden values in `check:edge` all called `computeEdge(pOver, ask)` with no no-side
price, so every one of them was exercising the inference. They are regenerated from
`signal.py` with explicit two-sided books, plus two one-sided cases that assert the yes
side is chosen and no phantom edge appears.

## Receiving and rushing efficiency regress too, and one of them entirely

Fitted the same way, on consecutive-season pairs with at least 40 touches:

    catch rate       WR n=209 pool 0.6294 r=+0.442 k=0.45  RMSE 0.0717 (raw 0.0819)
                     TE n= 80 pool 0.7225 r=+0.154 k=0.15  RMSE 0.0610 (raw 0.0851)
                     RB n= 52 pool 0.7855 r=-0.090 k=0.00  RMSE 0.0626 (raw 0.0937)
    yards per catch  WR n=209 pool 12.958 r=+0.494 k=0.55  RMSE 2.1670 (raw 2.4152)
                     TE n= 80 pool 10.503 r=+0.400 k=0.45  RMSE 1.6604 (raw 1.8946)
                     RB n= 52 pool  7.479 r=+0.188 k=0.20  RMSE 1.4165 (raw 1.6903)
    yards per carry  RB n=160 pool  4.194 r=+0.102 k=0.10  RMSE 0.6981 (raw 0.9706)
                     QB n= 37 pool  4.821 r=+0.255 k=0.25  RMSE 1.1013 (raw 1.3985)

**A running back's catch rate fits at k = 0.00 and the correlation is negative.** Taken
literally, his own history predicts next season worse than knowing nothing about him.
The sample is 52 pairs and the true value is more likely near zero than below it, but
zero is what minimises held-out error — 0.0626 against 0.0937 — and choosing a friendlier
number would be preferring a prior to a measurement. Yards per carry keeps a tenth.

Efficiency is mostly blocking and luck, and the model was treating it as identity. The
bootstrap arrays are rescaled rather than replaced, so each player's spread and right
tail stay his own and only the central tendency moves; the ratio between any two samples
is unchanged, and a test pins that.

Positions with no fitted pool — a receiving fullback, a wideout taking handoffs — pass
through raw. Borrowing another position's pool would be worse than not shrinking.

## The board would have served every Week 1 pick through its own game

Reported alongside a doubt about ATL/PIT props. Those markets are real — 118 of them,
`active`, two-sided quotes, verified against the live exchange — and a full audit of all
392 board rows against Kalshi found **zero** not listed and **zero** whose recommended
side was untradeable. But checking it surfaced something worse.

`Signal.closeTime` is Kalshi's **settlement** deadline, not kickoff:

    NE at SEA   kickoff       2026-09-10T00:20Z
                close_time    2026-09-12T00:20Z      <- two days later

Every board query filtered `closeTime > now()`. A Wednesday-night game would have stayed
on the board, priced and recommended, until Saturday — through the game itself and for
two days after. Nine queries, all of them.

The board now filters on a new `Signal.kickoff`, taken from the nflverse schedule. A null
kickoff drops out rather than being served: a pick that cannot be aged off the board must
not go on it, and the run warns loudly if any signal lacks one.

### And the kickoff itself was four hours early

nflverse `gametime` is EASTERN. `_venue_index` parsed it and stamped UTC, so every
kickoff in the system was four hours early — aging picks off before the game started and
pulling each weather forecast for the wrong hour.

The tell was the gap to Kalshi's close time: **2 days and 4 hours**. No exchange designs
a settlement window like that. Converted through `America/New_York` it is exactly two
days, and the confirmation is that the gap is now a SINGLE distinct value across all
1,834 signals — Kalshi uses kickoff + 48h uniformly, and our number now agrees with
theirs on every market on the slate.

A naive datetime compared against `now()` in Postgres is a silent four-hour error, so
`tests/test_kickoff.py` pins the zone, the awareness, and the plausible-hours range
rather than any single fixture.

### Still open, and it is not a bug

26% of board rows sit on markets that have never traded, and 32% on books wider than 15c.
Aaron Rodgers 325+ passing yards is quoted 0.05/0.09 on zero volume. Those prices are
real and takeable, so nothing here is fabricated — but an edge measured against an
untested quote is weaker evidence than one against a liquid book, and the board presents
them identically. The treatment is a product decision and is recorded, not chosen.

## A price nobody will trade against is not a market price

Kalshi is an exchange, not a bookmaker: every contract needs someone on the other side.
The board's entire claim is that the model disagrees with the market — and on a book
quoted 0.05 against 0.34 there is no market price to disagree with, only one
participant's resting offer and a 29-cent gap.

Measured across the 2,041 live markets on the Week 1 slate:

    yes-side spread     <=5c   24%
                        6-10c  20%
                        11-15c  9%
                        16-25c 15%
                        >25c   32%        median 13c, p75 32c

    never traded        473 / 2041  (23%)
    volume p25/50/75/90    1 / 18 / 78 / 445

More than half the book is wider than ten cents and a quarter of it has never traded.
Top Picks now holds back anything wider than **15c** and says how many it held back, and
every surviving row carries volume and spread. Zero volume is rendered in the warning
tone rather than hidden: a tight quote nobody has taken is a different claim from one
hundreds of people have, and both are worth seeing.

**The edge is still computed against the ask**, which is what you would actually pay.
This gate is not about the arithmetic being wrong — it is about whether the disagreement
means anything. A null spread is treated as a wide one, because "we could not measure the
book" is not evidence that it is tight.

Spread is measured on the LIVE book when there is one and falls back to the snapshot
otherwise, for the same reason the price does: a stored width is as stale as a stored
price.

`yesBid`, `volume` and `openInterest` have been captured on every archive snapshot since
the archiver was written and had never been read by anything downstream. The board could
not previously tell a market from a single resting offer.

## Pre-launch sweep: three unreachable paths and a contaminated metric

Prompted by the observation that the archiver had been capturing liquidity nothing read.
That turned out to be a pattern rather than an incident.

### The closing line was measured after the game

`grade.py` and `clv.py` both took "the last archived price before the market closed".
Kalshi's `close_time` is a settlement deadline **two days after kickoff**, and these
markets carry `can_close_early` with an `expected_expiration_time` at roughly the final
whistle — they stay open THROUGH the game. So the "closing price" was a quote that had
already watched the outcome happen.

`clv.py`'s own docstring states the property that made the metric worth having: *"CLV is
measured on price movement alone and does not depend on the outcome. That is the point:
it is a far lower-variance signal of edge than win rate."* Under that definition it
depended on the outcome almost entirely, and would have been a slow, noisy restatement of
settlement — while the tier system treated it as independent evidence.

The closing line is now the last snapshot at or before **kickoff**, which is the standard
meaning and is what `Signal.kickoff` was added for. Settlement is read separately, since
it cannot come from a pre-kickoff snapshot.

### It was also grading games that had not been played

The first corrected run graded **5,502 signals for Week 1 fixtures that have not kicked
off**, at a mean CLV of -2.96c. Before kickoff the "last snapshot" is simply the current
price, so CLV is noise around zero — and it would have gone into the tier maths as
evidence the model was losing before a single game was played. Grading now requires
`kickoff < now()`, and those rows were deleted.

### The tier could never promote anything

`compute_edge` derives the tier from `settled_contracts` and `mean_clv_cents`, and
`project.py` called it with neither. `assign_tier` therefore had a constant answer of
UNVALIDATED and `sample_n` was always 0. Grading would have written CLV to SignalResult
every week and **nothing would ever have read it back** — the promotion path was
unreachable, and the tier badge was decoration.

The projection now loads graded CLV per market family once per run and passes it through.
`tests/test_tier_promotion.py` pins both directions: volume with negative CLV is
disproven rather than validated, and good CLV on a thin sample stays unvalidated.

### Orderbook depth is captured and never read

The archiver fetches an orderbook per market — an extra rate-limited call, capped at 400
per run — and stores the JSON. Nothing parses it. `cadence.py` records the cost at
3.91 GB/season. `kalshi_backfill.py`'s docstring still claims orderbook depth is "what
this job uniquely captures", which is true and unused. Left in place rather than removed
two days before launch: it is waste, not a correctness fault, and removing a capture is
irreversible in a way that adding a consumer later is not.

## Backtesting 2025: what could be tested, and what it said

Asked for a backtest against last season. **D1 still holds**: Kalshi retains no settled
prop markets from 2025, so there are no historical lines and no way to reconstruct what
the model *would have bet*. What can be tested is the thing that decides whether any bet
is profitable — an edge is `p_model - price`, and if the probabilities are wrong then
every edge on the board is noise however good the price looks. Calibration needs no
prices at all.

`scripts/backtest_2025.py` replays weeks 8-18 leak-free (`through_week=N`, which filters
`week < N`), scoring 33,029 predictions across five markets against a Kalshi-shaped
strike ladder.

### The first result was wrong, and the harness was at fault

The first run scored only weeks in which a player had a real role (>= 3 targets), and
reported the model badly UNDER-confident — actual over-rates 5 to 9 points above
predicted in every bucket. That is selecting on the outcome: it keeps the games where a
receiver saw eight targets and drops the ones where he saw none, while the projection
averages over both.

Scoring every week the player **took a snap** — knowable before kickoff, and the
condition under which a market is listed — reverses the sign of the finding.

### The model has real skill

    Brier (lower is better)      model 0.1470
                             box score 0.1854      +20.7%
                              always 50% 0.2500
                               base rate 0.2191

    by market   pass_tds   +26.1%      rec_yds     +21.2%
                pass_yds   +18.2%      receptions  +20.2%
                rush_yds   +20.6%

The baseline is the honest one: how often the player has already cleared that line, which
the model's own rationale panel calls "already in the price". Beating a coin flip is not
the bar; beating the box score is, and it does, consistently across every market.

### It is over-confident at the high end, and that replicates

Held out on weeks 14-18, fitted on nothing:

    predicted 0.75  ->  actual 0.693      -0.056
    predicted 0.85  ->  actual 0.785      -0.061
    predicted 0.95  ->  actual 0.907      -0.041
    predicted 0.04  ->  actual 0.049      +0.011

A stated 75-85% is really 69-79%. The low end is if anything slightly UNDER-confident,
which matters because it rules out the obvious fix: a symmetric temperature on the
log-odds, fitted on weeks 8-13, made held-out Brier **worse** (0.1448 -> 0.1453). It
repaired the top and broke the middle.

A ONE-SIDED correction above 50% does survive: temperature 0.79, held-out Brier
0.1448 -> 0.1442 overall and 0.1996 -> 0.1976 on the rows it touches (+1.02%, n=4,402).

**Not applied.** The replay drives the simulator from WITHIN-SEASON inputs, while
production anchors on the prior season with the shrinkage fitted above and layers
adjustments on top. Those are different estimators, and a correction measured on one is
not evidence about the other. The finding is recorded and the harness is committed so it
can be re-run against the production configuration once 2026 provides the weeks.

**What it means for the board today:** high-confidence picks are likely overstated by
roughly five points. A row claiming 78% is nearer 73%, which turns a +26c edge into about
+21c — still positive, but a pick sitting just above the fee bar at high confidence may
not really clear it.

## The payout multiple, stated the way the exchange states it

Kalshi shows a return multiple — "1.21x" — which is easier to read than a cents-per-
contract margin. It is simply `1 / price`: a contract bought at 82.6c returns a dollar,
so 1.211x. Verified against the API, which exposes no such field; the exchange computes
it in its own UI, GROSS of fees. Ours is stated gross for the same reason, so the number
on the board is the number the reader will see when they go to trade.

**It is shown NEXT TO the edge, not instead of it.** The multiple is a restatement of the
price and carries no opinion at all — it is knowable without any model, and a long shot
always shows a big one. A 20x contract is not a good bet because it is 20x. The edge
beside it is the model's actual claim and is net of the exact taker fee.

The two answer different questions, so the board asks both: *what does a dollar come back
as*, and *is the price worth paying*. Replacing the second with the first would have left
the board restating Kalshi's own screen.

## "No separable effect" was being said when nothing had been measured

Asked why Henderson's likely absence is not mentioned on Stevenson's card. It was not,
and the reason was a conflation worth fixing.

`PlayerSplit` holds the pair — `nWith = 14, nWithout = 0, suppressed = true`. Henderson
never missed a game, so there was never anything to compare, and the row is correctly
suppressed. `getPlayerSplits` filters on `significant and not suppressed`, so it never
reached the UI, and the panel fell through to its empty state:

> *"No current teammate's absence has a separable effect on this player's role."*

That sentence means "we compared and found little". The truth was "we could not compare
at all" — for the one teammate on this week's injury report, and the exact reason the
model declines to price Stevenson.

The panel now names them: *"Not measurable: TreVeyon Henderson (14 together, none
apart)…"*, and says plainly that the absence of a comparison is not evidence of no
effect, and that the model refuses rather than guesses.

**Ranking by shared games was wrong and shipped once.** The first version listed Austin
Hooper, Drake Maye, Hunter Henry and Jack Westover — a quarterback, two tight ends and a
fullback, all tied at 14 games — and omitted Henderson entirely. Same-position teammates
now sort first: a tight end sitting does not redistribute carries, and the whole point of
the panel is the teammate whose absence would move this player's role.

**Still missing, and it needs a decision.** The card cannot say Henderson is 34% likely to
sit, because the injury report exists only in Parquet and is read by the pipeline; there
is no injuries table in Postgres. The model knows the number — it is what triggers the
refusal — and the UI has no way to reach it. Surfacing it, and surfacing WHY a player is
absent from the board at all, needs a table, a sync job and a query. Recorded rather than
built two days before launch.

## The model's reasons now reach the reader

Two things the model knew and no page could state. Both were the same shape as the
archiver capturing liquidity nothing read: the data existed, and the consumer did not.

**The injury report existed only as Parquet.** `features/availability.py` measures that a
listed player who did not practise takes no offensive snap **34.3%** of the time, and
that number is what makes the projection refuse to price his teammate — but it lived
inside the pipeline. A card could say a split was "not measurable" and could not say the
teammate may well not play. `Injury` now carries the week's report with the measured
probability attached, synced by `ingest/sync_injuries.py`. The RATE comes from a
completed season and the STATUS from this week, the same separation the projection uses.

**A refused player simply vanished.** The projection declines in several situations and
every one was silent: no signal, no explanation, a card whose markets list read like a
data failure. `ProjectionRefusal` is written by the run that made the decision — not
re-derived in the web layer, so the rule keeps one home — and replaced wholesale each
run, since a player refused an hour ago and priced now must stop showing a stale reason.

Rhamondre Stevenson's card now opens with:

> **Not priced this week.** TreVeyon Henderson in the same RB room is 34% likely not to
> play, and no with/without history exists to price the share that would move.
>
> TreVeyon Henderson (RB) did not participate in practice — ankle.
> 34% likely to take no offensive snap. His carries or targets would have to go somewhere.

And Henderson's own card states his designation with the same measured rate beside it.

The room is filtered to the SAME POSITION deliberately. A tight end sitting does not
redistribute carries, and listing him would bury the back who does — the same mistake
that put a quarterback and two tight ends at the top of the "not measurable" list before
it was ranked by position.

The sync runs in `ingest-nflverse`, deriving the week from the schedule so it advances on
its own. Before the season opens nflverse publishes nothing and the job writes zero rows,
which is the correct output rather than a failure.

## Top Picks can now be asked why

The Why panel is the feature that makes the tool worth using over guessing — every claim
with the number behind it, read from the STORED signal so it shows what the model thought
when the pick fired rather than a fresh recomputation. It was reachable only from the
Prop Board.

Top Picks is the page a reader is most likely to act from, and it had no way to ask. The
reason was structural rather than an oversight: `WhyPanel` needs client state and the
page is a server component, so there was nowhere to hold the selection.

The list is now `components/TopPickList.tsx`, a client component wrapping the same row
markup unchanged. Each row is a button that opens the panel, with a `why →` affordance
matching the board's, a hover and focus state, and an `aria-label` naming the player and
market so the control is not just an unlabelled row to a screen reader.

Moving the markup left eight dead imports behind on the page; lint caught them and they
are gone.

## A workflow that fails to parse leaves no log

Two pushes reported `ingest-nflverse` failing with "this run likely failed because of a
workflow file issue" and **no log at all** — the run never started. The cause was the
week derivation for the injury sync: a nested Python heredoc inside a `run:` block, whose
quoting broke the YAML.

Nothing caught it. `checks` passed both times, because it runs the test suite and the
test suite had no opinion about the workflow files. The failure was visible only as a red
mark on a job whose output could not be read.

The derivation moved into `sync_injuries.current_week`, where it belongs — logic needing
that much quoting care does not belong in a shell step — and `--week` is now optional.

`tests/test_workflows.py` asserts every workflow parses and that every
`python -m pipeline.x` it invokes points at a module that exists. The second half is
worth as much as the first: a scheduled job calling a module that was renamed fails at
runtime, weekly, where nobody is looking.

## The spread gate was not filtering a single under

Spotted on the live site: the top two picks read `0 traded · 0c spread`, and a
zero-wide book is not a thing.

`storedSpreadCents` reconstructed the missing yes quote from the price of the side
taken. On Kalshi `no_ask = 1 - yes_bid`, so for a "no" pick `1 - marketProb` **is**
`yes_bid`, and the subtraction returned exactly zero every time. Zero passes any
threshold, so the gate shipped filtering nothing on the under side — which is most of
the board.

    stored   side=no  no_ask=0.42  yesBid=0.58   ->  computed 0.0c
    live     yes 0.58/0.69  no 0.31/0.42         ->  true width 11.0c

A binary book has ONE width: `yes_ask - yes_bid` equals `no_ask - no_bid`. Measuring it
needs both yes quotes, so `Signal.yesAsk` is now stored alongside `yesBid` and the width
is computed from those regardless of the recommended side. The live path was already
correct — it reads both quotes from the book — so only stored-fallback rows were wrong,
which is why this survived the local check and appeared in production.

`check:edge` now pins the arithmetic, including the collapse-to-zero that caused it.

Effect: of 509 rows clearing the fee bar, 395 pass the width gate and **114 are held
back** that previously were not.

## The variance fix was measured and rejected

Drake Maye, UNDER 174.5 passing yards, +10.4c — flagged as looking wrong, and it was.
The model put P(under) at 31% against a market at 19% and an empirical record of ONE
game under that line in seventeen. Correcting the spread alone erased the edge entirely
(-2.4c), so the whole pick came from the width of the distribution.

The mechanism looked clear. The simulator draws volume and per-unit efficiency
independently and multiplies, and Maye's attempts and yards-per-attempt correlate at
**r = -0.73**: independence implies sd 91.6 where his games showed 48.1, a 1.90x
inflation matching the projection's 87.5 almost exactly.

**The obvious fix is not supported by the backtest.** Targeting the simulated spread at
a shrunk coefficient of variation — pool CV 0.301/0.674/0.640 with k of 0.20/0.30/0.45,
fitted on season pairs — made every band WORSE, at 3,000 and again at 12,000 iterations:

    band              before    after
    within 0.5 sd     0.2346   0.2354
    0.5-1.0 sd        0.1817   0.1865
    1.0-1.5 sd        0.1088   0.1127
    beyond 1.5 sd     0.0499   0.0535     <- the band it was built for

In the far tail the model is already slightly UNDER-confident (says 8.4%, happens 9.8%),
so narrowing the distribution moved it away from the truth rather than toward it. The
change is reverted; `features/spread.py` is deleted rather than left dormant, because
unused paths in this codebase have repeatedly come back as bugs.

**What the diagnosis got wrong.** The 1.90x compared the model's 2026 projection against
Maye's 2025 *realised* spread — one sample, and a coefficient of variation that barely
persists (r = +0.168 for passing). His 0.186 is not a forecast of 2026; the pool 0.301 is
closer, and against that the model's implied 0.399 is 33% wide, not 90%.

So the pick is probably still wrong and the reason is narrower than "the simulator is
miscalibrated": Maye is an unusually consistent quarterback and the model has no way to
know it, because consistency does not carry across seasons well enough to trust.

The backtest keeps the band-by-band tail diagnostic this produced. Overall Brier hides
exactly this: the bulk of predictions dominate it, while every bet on the board lives out
where model and market disagree.
