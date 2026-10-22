# market_ctx_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed. Any change needs market_ctx_v2.
Date: 2026-10-20. Errata 60.

## Purpose
Log descriptive market-context numbers per coin and per day, and later test them descriptively against the next 24h return. Nothing reads these numbers: not the guard, decisions, plans, the AIs, facts_v1 or the live path. Live execution stays BLOCKED.

## Collection
- Standalone market_ctx_log.py (selftest | check | run | report), run once a day before `sp`. Does not modify run_sp, run_pw or any hook.
- One 1h klines request per coin for the 40 shadow coins, via market_facts.fetch_klines (limit 1000, Spot first then futures). The source is stored per row. Request weight is not verified.
- market_facts.parse_klines drops the taker-buy fields, so this module parses the raw rows itself (index 9 = taker buy base volume; confirmed in Binance's official futures docs, not checked on the official Spot page).
- Symbol = coin + USDT. SHIB has no confirmed mapping and may be UNAVAILABLE. No mapping is guessed.

## Status per coin
- UNAVAILABLE: request fails, fewer than 200 candles, last closed candle older than 62 minutes, or non-numeric prices.
- PARTIAL: any feature is n/a. OK: otherwise.
- Features use the longest gap-free run of closed candles. A feature that needs more is n/a. Never estimated.

## Features (closed hourly candles only)
- UTC day levels: previous-day high, low, close; today's open; last close's % distance to each. Needs 24 gap-free candles for the previous day.
- UTC week levels: previous-week high and low; week open (weeks start Monday 00:00 UTC); % distances. Needs 168 gap-free candles.
- VWAP, approximate: sum((H+L+C)/3 x volume) / sum(volume), anchored to the UTC day (needs at least 3 closed candles that day) and rolling over 24 candles; last close's % distance to each. Approximate because it is built from hourly bars.
- Market structure: UTC-aligned 4h blocks, fractal swing points with n = 2, last 30 days. UP if the last swing high and swing low are both higher than the previous ones, DOWN if both are lower, MIXED otherwise, n/a with fewer than 2 swing highs or 2 swing lows.
- Taker-buy ratio: taker buy base volume / total volume over the last 24 and the last 168 candles.
- Relative strength vs BTC: coin 24h and 168h close-to-close return minus BTC's. n/a for BTC itself or when BTC is UNAVAILABLE.
- Breadth (one row per run, OK coins only): share of coins with a positive 24h return, share with a positive 168h return, share with structure UP, median 24h return, coin count. Written only when all 40 coins have a row for that day. No extra requests.

## Storage
- shadow_market_ctx (one row per coin per run) and shadow_market_breadth (one row per run) in shadow.db, append-only, own tables. No other DB is written.
- A rerun on the same UTC day only fills coins that have no row for that day.
- numbers_json holds the feature values; status and reason are stored per row.

## Forward grading (no extra requests)
- Each run grades earlier snapshots whose next 24 hourly candles are now complete, using the candles already fetched.
- Forward return = close of the 24th candle after the snapshot's last closed candle vs that candle's close.
- Snapshots with status OK or PARTIAL are gradable for a rule whose own feature is available. UNAVAILABLE snapshots are never graded.

## Evaluation (registered before any data): direction agreement with the sign of the forward return
- Rule S (structure): UP = up call, DOWN = down call, MIXED = no call.
- Rule V (VWAP): last close above the UTC-day VWAP = up, below = down.
- Rule T (taker): 24h taker ratio above 0.5 = up, below = down.
- Rule R (relative strength): 24h relative strength above 0 = up, below = down.
- Excluded and counted separately: n/a values, exact ties, forward return of exactly 0.
- Comparators: always-up and the base rate.
- Reading rule: the report refuses below 30 graded rows per rule AND below 20 distinct snapshot days, because the 40 coins of one day move together. It also prints the mean per-day hit rate next to the pooled one.
- No pass bar, no causal claim. Four rules read together raises the chance of a false finding. Parameters (n = 2, 0.5, 62 minutes, windows) are not tuned on seen data.
- Null means: no effect larger than the detectable size for this sample.

## Never
- These numbers must not trigger BUY/SELL, change a decision, plan, stop, TP or the agreement guard, and are not sent to the AIs in v1. Feeding them to an AI needs its own decision and version.

## Known limits
- UTC day and week are conventions. VWAP is approximate. Swing parameters are arbitrary starting values.
- Rows are correlated across coins and days. Spot and futures sources can mix across coins.
- About 20 distinct days are needed before the report can read, so about three weeks of daily runs.
