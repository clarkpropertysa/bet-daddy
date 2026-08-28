# Bet Daddy: Claude Code Build Prompt

Paste everything below the line into Claude Code as the opening message of a fresh session in an empty repo.

---

## 0. Read this before you write a single line

You are building **Bet Daddy**, a personal NFL and NBA player-prop research tool. I am the only user. It is not a product, there is no signup flow, and nobody is being sold anything.

Work in this order and do not skip ahead:

1. **Verify every external API before you depend on it.** Your training data about `nfl_data_py`, `nflreadpy`, `nba_api`, and the Kalshi API is probably stale. Use WebFetch on the current docs and run a real request against each source before you design around it. If a library has been renamed or deprecated, find out now, not in week three.
2. **Build the data spine first, UI last.** No React until real rows are in Postgres and a test asserts real numbers against them.
3. **Never fabricate, mock, or placeholder sports data.** Not in seeds, not in tests, not in a "temporary" fixture. A single fake number that survives into the UI destroys the entire point of this tool. If data is unavailable, the correct behavior is an explicit empty state that says which source failed.
4. **Ask me before adding a paid dependency.** Budget is roughly zero for v1.
5. Commit in small, working increments. Write a `DECISIONS.md` and log every schema and modeling choice with the reasoning.

Read the whole prompt, then give me a plan and your concerns before starting. If you think part of this spec is wrong, say so.

---

## 1. What this is and what it is not

The inspiration is [propswire.com](https://propswire.com), which does MLB prop research: matchup, pitcher, park and trend data plus stated reasoning behind every signal. I want the same interaction model for NFL and NBA.

**Be clear-eyed that this is not a port.** MLB props are structurally easy: discrete plate appearances, a nearly closed pitcher-vs-batter system, stable park factors, weather. NFL and NBA have none of that. The drivers are opportunity (snaps, routes, targets, minutes, usage rate), game script, rest, and injury-driven usage redistribution. The whole analytics layer has to be built from scratch on different primitives. Do not try to map MLB concepts across.

**Non-goals. Do not build these:**

- Any sportsbook account connection, bet placement, or bankroll sync
- Any social feature: no feeds, follows, tailing, user leaderboards, comments, sharing
- MLB, NHL, NCAA, soccer, or any sport other than NFL and NBA
- Subscription tiers, payments, marketing pages
- Push notifications in v1

---

## 2. The thing that will make or break this

Almost every prop tool on the market sells backward-looking hit rates. "He has gone over in 8 of his last 10." That number is nearly worthless on its own, because the line has already moved to absorb it. A tool built on hit rates with a confident UI is a machine for producing losing bets that feel researched.

So the **backtesting and calibration harness is Phase 1, not Phase 4.** Every signal this app emits must be born with a track record attached. The rule:

> A signal does not appear in the UI as actionable until it has been backtested against historical Kalshi prices across at least 200 settled contracts and shows positive expected value after fees.

Signals below that bar can still display, but must render in a visually distinct "unvalidated" state with the sample size shown. There is a permanent Track Record page (Section 11.8) that logs every signal the app has ever emitted, settled or not. It is not optional and it does not get hidden when results are bad.

---

## 3. Stack

Match my standard stack:

- **Web**: Next.js (App Router), TypeScript, Tailwind, shadcn/ui
- **DB**: PostgreSQL on Neon, Prisma as the app-side ORM
- **Hosting**: Vercel
- **Data and modeling**: Python 3.11+, run in **GitHub Actions on a cron schedule**, writing directly to Neon. Do not try to run pandas or the modeling code inside Vercel functions.
- **Heavy local compute**: DuckDB over Parquet. See Section 6 for why.
- **Charts**: Recharts, dark theme, muted palette

Repo layout:

```
/web            Next.js app
/pipeline       Python: ingestion, features, model, backtest
  /ingest       one module per source
  /features     feature engineering
  /model        projection + simulation
  /backtest     harness, calibration, reports
/prisma         schema + migrations
/.github/workflows   cron jobs
DECISIONS.md
```

---

## 4. Data sources

### 4.1 NFL (free, reliable, no rate limits)

**nflverse** is the backbone. The data ships as Parquet files attached to GitHub releases on the `nflverse/nflverse-data` repo, so it is fast, static, and will not block you.

- **Use `nflreadpy`, not `nfl_data_py`.** As of late 2025 `nfl_data_py` is archived and unmaintained. `nflreadpy` is the nflverse-maintained Python port of `nflreadr` and is the current client. Confirm this is still true when you start. You can also read the nflverse-data release Parquet URLs directly, which is the most robust path and a good fallback if the client lags a schema change.
- What you need from it:
  - **Play-by-play** (nflfastR): every play back to 1999 with EPA, WPA, air yards, yards after catch, personnel, situation. This is the source for almost every derived feature.
  - **Weekly player stats**: the actual prop outcomes you are predicting
  - **Snap counts**: the single best NFL opportunity signal
  - **Depth charts** and **rosters**
  - **Injuries**: official weekly injury report designations
  - **Schedules**: dates, kickoff times, rest days, venue, roof, surface
  - **Next Gen Stats**: separation, cushion, average depth of target, time to throw, rush yards over expected
  - **FTN charting data**: play action, motion, blitzers, personnel groupings
  - **PFR advanced stats**: includes some coverage and pressure data

### 4.2 NBA

**`nba_api`** (https://github.com/swar/nba_api) wraps stats.nba.com. It is free and by far the richest NBA source. Endpoints that matter here:

- `leaguegamelog`, `playergamelog` for outcomes
- `boxscoreadvancedv3`, `boxscoreusagev3`, `boxscorescoringv3`, `boxscoreplayertrackv3` for usage, pace, touches, distance
- **`boxscorematchupsv3`** for possession-level defender-vs-offensive-player data. This is the endpoint that answers "how does this player do against this specific defender."
- `leaguedashptdefend` for defensive impact by shot type and distance
- `leaguedashteamstats` and `leaguedashplayerstats` with measure types (Advanced, Four Factors, Opponent, Defense)
- `leaguedashlineups` for on/off and lineup effects
- `hustlestatsboxscore`
- `scoreboardv2` and the schedule endpoints for rest and back-to-backs

**Known risk you must handle up front:** stats.nba.com aggressively rate-limits and frequently blocks datacenter IP ranges, which includes GitHub Actions runners. Before building the NBA pipeline, run a probe from an Actions runner and confirm you can get data. Mitigations in order of preference:

1. Slow, patient ingestion with realistic headers and 1 to 2 second sleeps, run overnight
2. Ingest from my machine on a schedule instead of CI, writing to the same Neon DB
3. A free-tier fallback source such as balldontlie for basic box scores, with `nba_api` only for the advanced endpoints

Report back with what actually works. Do not architect around an endpoint you have not successfully called.

### 4.3 Markets: Kalshi is primary

**Kalshi is the venue I actually trade, so Kalshi prices are the target of every edge calculation.** Sportsbook lines are reference only.

- Base URL: `https://external-api.kalshi.com/trade-api/v2` (demo: `https://external-api.demo.kalshi.co/trade-api/v2`)
- Auth: three headers, `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (ms), `KALSHI-ACCESS-SIGNATURE`. The signature is an RSA-PSS SHA256 signature over the string `timestamp + METHOD + path`, path excluding query params, salt length equal to digest length, base64 encoded. There are official Python and TypeScript SDKs; check whether using the SDK is cleaner than hand-rolling.
- Endpoints to use: `GetSeriesList` and `GetEvents` (discovery), `GetMarkets`, `GetMarket`, `GetMarketOrderbook`, `GetMarketCandlesticks`, `GetHistoricalMarketCandlesticks`, `GetTrades`, `GetSettlements`, `GetGameStats`, `GetLiveData`. There is also a WebSocket feed with orderbook, ticker, and public trade channels.
- **Do not hardcode series tickers.** Discover the NFL and NBA player prop series programmatically via the series list and sports tag search, and store the discovered tickers in the DB with a refresh job. Kalshi's ticker taxonomy changes.
- Read the **Rate Limits and Tiers** page and the **Fee Rounding** page in the docs. Kalshi's trading fee scales with contract price and is large enough at mid-range prices to erase a thin edge. **Implement the fee formula exactly as documented, do not approximate it**, and net it out of every edge and backtest number in the app.
- Historical candlesticks plus settlements are what make the backtest possible. Start archiving them on day one, including for markets you are not trading, because you cannot go back and get depth you did not record.

### 4.4 Sportsbook reference (free tier only)

The Odds API free tier is 500 credits per month. Player prop requests are metered per market per bookmaker per event, so this budget vanishes instantly if you poll. Use it deliberately:

- One snapshot per slate, a few hours before lock, for a handful of major books
- Purpose is a sanity check on Kalshi pricing and a consensus reference, not a live feed
- Track credit consumption in the DB and hard-stop at 400 credits per month
- If it proves too thin to be useful, drop it. It is a nice-to-have.

---

## 5. What "insight" actually means here

These are the feature families that drive prop outcomes. Build them in this priority order.

### 5.1 Opportunity and usage (highest value, build first)

Volume predicts props far better than efficiency does.

- **NFL**: snap share, route participation rate, target share, air yards share, WOPR, red zone touch share, carry share, pass rate over expectation for the offense, first-read share. Track 3-game and 5-game rolling values plus trend direction, not just season averages.
- **NBA**: projected minutes, usage rate, shot attempts per 36, FTA rate, 3PA rate, touches, time of possession, assist rate, rebound chance rate. Minutes projection is the highest-leverage number in the whole system, treat it as a first-class model output.

### 5.2 Injury cascade and with/without splits

The single most exploitable signal in props. When a teammate is out, usage redistributes unevenly, and markets are slow to price the second-order beneficiaries.

- Compute per-player performance splits **with and without** each significant teammate, from play-by-play, with sample sizes attached.
- Model usage redistribution: when player X is out, player Y's target share historically goes from A to B.
- Join to the current injury report and surface "usage vacancy" as a ranked daily list.
- Be rigorous about sample size. Most with/without splits are noise. Show n and a confidence interval, and suppress anything under a threshold you pick and document.

### 5.3 Rest, schedule, and travel (you asked for this specifically)

Build a full schedule-context module:

- **NBA back-to-backs**: this is the flagship. Compute team and player splits for 0 days rest (second night of a B2B), 1 day, 2 days, 3+ days. Break out further by whether it is the road end of a B2B, and by 3-games-in-4-nights and 4-in-6 density.
- Minutes suppression and rest-day DNPs for veterans on the second night. Model DNP probability explicitly, because a DNP is the worst outcome for an over.
- Travel: miles traveled, time zone changes, altitude games (Denver, Utah), and East-to-West coast body clock effects.
- Post-blowout effects: minutes and usage after a game with a large fourth quarter margin.
- **NFL**: rest differential (Thursday games, post-bye, short week, post-international game), and travel/timezone for early kickoffs by West Coast teams.

### 5.4 Matchup, including player vs player (you asked for this too)

- **NBA**: use `boxscorematchupsv3` to build a real defender-vs-offense possession table. Then answer: how does this player score against this specific defender, over how many possessions, and how does that compare to his baseline. Layer team-level defensive context: opponent defensive rating, rim protection, perimeter defense, defensive rebounding rate, how they defend pick and roll.
- **NFL**: true shadow-coverage data is not free. Do the honest version: infer WR alignment and likely coverage from play-by-play and NGS, and grade opponent pass defense by position and by target depth band (short, intermediate, deep) using EPA and success rate allowed. Grade run defense by gap and by expected yards allowed. Label these as inferred, not charted, in the UI.
- Produce a single **matchup grade** per player-market, but always expose the components behind it.

### 5.5 Game environment and script

- Projected game total and spread drive prop volume more than anything except injuries.
- **NFL**: trailing teams pass more. Model the pass/run mix conditional on projected game script. Weather matters for passing and kicking props (wind above roughly 15 mph is the real threshold, not temperature); pull it only for outdoor stadiums.
- **NBA**: projected possessions from both teams' pace, adjusted for opponent. Blowout risk suppresses minutes for starters and inflates them for bench.

### 5.6 The signal itself

The bet signal is never a hit rate. It is: **model probability distribution vs Kalshi price, net of fees**, expressed as expected value in cents per contract, with a confidence tier based on model calibration in that market bucket.

---

## 6. Data architecture

Neon's free tier is small (roughly 0.5 GB). Twenty-five seasons of NFL play-by-play plus NBA box scores will not fit comfortably alongside everything else. So:

- **Raw layer**: keep raw play-by-play and raw box scores as **Parquet** files, in the repo's cache directory in CI and optionally in cheap object storage. Query them with **DuckDB**, which reads Parquet directly and is dramatically faster than Postgres for this workload.
- **Feature layer**: the pipeline computes features in DuckDB/pandas and writes **only the engineered outputs** to Neon.
- **Postgres holds**: players, teams, games, schedule context, player-game features, splits, matchup aggregates, market snapshots, projections, signals, and settlement results.

This keeps Neon small, makes backfills cheap, and means the web app only ever does simple indexed reads.

### 6.1 Schema sketch

Design properly, this is directional:

```
sports              nfl | nba
teams               id, sport, abbrev, name, conference, division, venue, timezone, altitude
players             id, sport, external_ids (jsonb: nflverse gsis, nba person_id, kalshi name key), name, position, team_id
games               id, sport, season, week_or_date, home_team, away_team, kickoff_utc, venue,
                    roof, surface, is_neutral
game_context        game_id, team_id, days_rest, is_b2b, b2b_leg, games_in_last_4, games_in_last_6,
                    travel_miles, tz_shift, is_post_bye, is_short_week, altitude, wind_mph, temp_f,
                    precip, projected_total, projected_spread, projected_possessions
player_game_stats   player_id, game_id, minutes_or_snaps, and every stat that backs a prop market
player_game_usage   player_id, game_id, snap_share, route_pct, target_share, air_yards_share,
                    rz_share, usage_rate, touches, poss_time, shot_attempts_per36, ...
player_splits       player_id, split_type (rest_0, rest_1, home, away, vs_top10_def, without_<pid>, ...),
                    market, n, mean, stdev, p25, p50, p75, updated_at
matchup_possessions player_id, defender_id, game_id, partial_poss, pts, fga, tov   -- NBA
defense_grades      team_id, sport, split (position, depth_band, shot_zone), metric, value, rank, window
injuries            player_id, game_id, report_status, practice_status, final_status, source_ts

kalshi_series       ticker, sport, market_family, title, discovered_at
kalshi_markets      ticker, series_ticker, event_ticker, player_id, game_id, market_type,
                    strike, open_ts, close_ts, status
market_snapshots    market_ticker, ts, yes_bid, yes_ask, last_price, volume, open_interest,
                    orderbook_depth (jsonb)
market_settlements  market_ticker, settled_ts, result, settlement_value

projections         player_id, game_id, market_type, model_version, run_ts,
                    mean, stdev, distribution (jsonb: percentiles), p_over_by_strike (jsonb)
signals             id, projection_id, market_ticker, run_ts, model_prob, market_prob,
                    edge_cents_net_of_fees, kelly_fraction, confidence_tier, reason (jsonb),
                    validated boolean
signal_results      signal_id, closing_price, settled_result, clv_cents, pnl_if_bet, graded_ts
odds_api_usage      month, credits_used
pipeline_runs       job, started, finished, status, rows_written, error
```

Every table gets a source and ingested_at column. Every pipeline job writes a `pipeline_runs` record. If a job fails, the UI must show that the data is stale rather than silently serving yesterday's numbers.

---

## 7. Projection model

**Do not produce point estimates.** A prop is a question about a distribution's tail, so simulate the distribution.

Approach for v1, deliberately simple and honest:

1. **Project the volume driver first** (NFL: snaps, routes, targets, carries. NBA: minutes, then usage rate). Include a discrete probability of DNP or inactive.
2. **Simulate.** Monte Carlo, 20,000+ iterations per player-market:
   - NFL receptions: targets from a negative binomial fit to the player's recent rate adjusted for matchup, then catches from a binomial on catch probability
   - NFL receiving yards: catches, then yards per catch drawn from the player's empirical distribution (right-skewed, do not assume normal)
   - NFL rush yards: attempts, then yards per carry from an empirical distribution with the fat right tail preserved
   - NBA points: minutes, then possessions used, then shot mix and efficiency, then FTs
   - NBA rebounds and assists: per-minute rates with negative binomial dispersion, scaled by simulated minutes and pace
3. **Adjust** the simulation inputs by the matchup, rest, and game-script features from Section 5. Every adjustment must be a named, logged multiplier so the "why" panel can show it.
4. **Calibrate.** Fit isotonic regression on historical predicted-vs-actual by market type and by probability bucket. Report a calibration curve. An uncalibrated model that is right on average and wrong in the tails is a losing model, and props live in the tails.
5. **Compare** the simulated P(over strike) to the Kalshi implied probability, net of fees, and emit a signal.

Prefer an empirical, distribution-first baseline over a fancy model. Get a boring model calibrated and validated before considering gradient boosting or anything else. Version every model run so backtests are reproducible.

---

## 8. Backtest harness

Build this in Phase 1, alongside the data spine.

- Replay historical Kalshi candlestick prices and settlements. Reconstruct what the model would have said at a fixed point before close (for example T-60 minutes), using **only data available at that time**. Point-in-time correctness is mandatory. Any leakage of post-game information invalidates everything, so write explicit tests for it.
- Metrics reported per market type, per sport, per confidence tier:
  - **Closing line value** in cents (the single most predictive metric of long-run edge)
  - ROI and total P&L, net of Kalshi fees
  - Brier score and a calibration plot
  - Hit rate vs expected hit rate, with a confidence interval
  - Maximum drawdown and longest losing streak
- Sample size gates. Report n everywhere. Refuse to render a confidence tier with insufficient n.
- Walk-forward validation only. No in-sample tuning that gets reported as performance.

---

## 9. UI surfaces

Dark, dense, fast. Information-first, no hype language, no "lock" or "smash" framing. Every number is clickable through to its inputs.

1. **Slate** (home). Today's games with rest state and B2B flags, projected totals and pace, the top validated edges, injury news that changed usage today, and biggest Kalshi price moves. This is the PropsWire-style at-a-glance dashboard.
2. **Prop Board.** The workhorse. Sortable, filterable table of every available Kalshi player prop: player, market, strike, Kalshi yes price, model probability, net edge in cents, confidence tier, matchup grade, rest state, recent volume trend. Filters for sport, market type, team, edge threshold, confidence, rest state.
3. **Player page.** Game log, rolling usage charts, split tables (home/away, rest state, opponent defense tier, with/without each key teammate), the simulated outcome distribution drawn against the current strike, and market price history.
4. **Matchup page.** NBA: player vs defender possession history and per-possession results. NFL: player vs opponent defense by position and target depth band, clearly labeled as inferred.
5. **Rest and Schedule.** B2B tracker for the next two weeks, 3-in-4 and 4-in-6 density, travel and timezone flags, historical team and player performance in each rest state.
6. **Market Movers.** Kalshi price movement over the last 24 hours with volume, and divergence between Kalshi implied probability and the sportsbook reference consensus when available.
7. **Injury Impact.** Today's injury report joined to usage-vacancy projections: who absorbs the freed-up usage and by how much, with sample sizes.
8. **Track Record.** Every signal ever emitted, with closing line value, settlement, and running ROI. Filterable by market, sport, confidence tier, and date range. Includes the calibration plot. **This page never gets hidden or softened.**
9. **Why panel.** A slide-over available from any signal that shows the full chain: baseline rate, each named adjustment and its multiplier, the simulated distribution, the market price, the fee, and the net edge. This is the feature that makes the tool worth using over guessing.

Auth: single user. NextAuth with one allowlisted email, or a simple middleware password. Do not build a user system.

---

## 10. Phase plan

The 2026 NFL season opens **Wednesday, September 9, 2026**. NBA opens late October. Today is August 28, 2026. That is 12 days. NFL ships first; design the schema to be sport-agnostic from the start but do not build NBA-specific features yet.

**Phase 0, days 1 to 3: prove the data.**
Verify each source with a real request. Get NFL play-by-play, weekly stats, snap counts, injuries, and schedules loading into Parquet and queryable in DuckDB. Get Kalshi auth working and discover the NFL prop series tickers. Start the market snapshot archiver immediately, running every 15 minutes, because historical price data cannot be recovered later. Set up Neon, Prisma schema, and the GitHub Actions cron scaffolding.

**Phase 1, days 4 to 8: features and harness.**
NFL usage features, rest and schedule context, defense grades, and with/without splits. The Monte Carlo projection model for the core NFL markets (receptions, receiving yards, rushing yards, passing yards, passing TDs, anytime TD). The backtest harness with point-in-time correctness tests. Run the backtest on whatever historical Kalshi data exists and report honestly, including if the answer is "the model has no edge."

**Phase 2, days 9 to 12: NFL UI.**
Slate, Prop Board, Player page, Why panel, Track Record. Ship before Week 1 kickoff. It is fine if signals render unvalidated in Week 1 with sample size shown.

**Phase 3, weeks 3 to 8: NFL depth and honesty.**
Matchup pages, Injury Impact, Market Movers, calibration refinement. Accumulate live results in the Track Record page. Kill any signal family that shows negative CLV.

**Phase 4, October: NBA.**
Resolve the stats.nba.com access question first. Then NBA usage and minutes projection, the back-to-back module, defender-vs-player matchups, and NBA markets on the Prop Board.

---

## 11. Acceptance criteria

Phase 0 is done when a single command loads real NFL data and a test asserts specific known-correct values (for example, a named quarterback's actual passing yards in a specific 2025 game) against the loaded rows.

Phase 1 is done when the backtest produces a calibration plot and a CLV number from real historical Kalshi prices, and a point-in-time leakage test passes.

Phase 2 is done when I can open the Prop Board on a live NFL slate, click any row, and see the full reasoning chain in the Why panel with every input traceable to a source.

Overall, the tool has succeeded if after eight weeks the Track Record page shows positive closing line value on validated signals. If it shows negative CLV, it has told me the truth, which is the second-best outcome and much better than a pretty dashboard that lies.

---

## 12. Things that will go wrong, handle them explicitly

- **Player identity resolution across sources.** nflverse GSIS IDs, NBA person IDs, and Kalshi's player naming will not match. Build a proper crosswalk table with fuzzy matching plus a manual override table, and log every unmatched name loudly. This will consume more time than you expect. Do not paper over it with string matching that silently mismatches similar names.
- **stats.nba.com blocking CI runners.** Probe early, per Section 4.2.
- **Kalshi ticker taxonomy changes.** Discovery job, not hardcoded strings.
- **Kalshi fees eating thin edges.** Exact formula from the docs, applied everywhere.
- **Survivorship and point-in-time bias in the backtest.** Test for it explicitly.
- **Small samples masquerading as insight.** Every split shows n. Suppress below threshold.
- **Neon free tier limits.** Monitor size, keep raw data in Parquet.
- **Stale pipeline runs.** Surface staleness in the UI, never serve stale data silently.

---

## 13. First response

Do not start coding. Reply with:

1. Your read on the plan and where you disagree with it
2. What you verified about each data source, with the actual results of your test requests
3. The proposed Prisma schema
4. Anything in Section 5 you think is not achievable with free data, and what you would substitute
5. Your honest estimate of whether Phase 2 lands before September 9
