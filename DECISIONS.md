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
