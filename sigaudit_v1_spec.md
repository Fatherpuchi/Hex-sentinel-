# sigaudit_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed (the git commit time is the freeze time). Any change needs sigaudit_v2. Errata 82.

## 1. Purpose
Grade the deterministic engine's own BUY/SELL signal (market_signal in ai_consensus_audit) against the next 24h price change, by Stage 1 status, so we learn whether the engine's direction has any detectable edge before any AI or guard is involved. It does not grade the AIs, the agreement guard or any plan. Shadow only. Nothing reads the result: not Stage 1, the guard, prompts, decisions or execution. Live stays BLOCKED.

## 2. Basis (counts only, from a read-only query seen before this spec; no outcome was read)
ai_consensus_audit: 489 rows, 144 symbols, 367 distinct symbol-days. REJECTED rows carry market_signal BLOCKED (238, no direction). APPROVED: SELL 128, BUY 41, HOLD 55. WATCH: SELL 6, BUY 4, HOLD 17.

## 3. Units
- Rows of ai_consensus_audit (sentinel.db opened read-only) with strategy_status in (APPROVED, WATCH) and market_signal in (BUY, SELL). Rows with HOLD or BLOCKED are never graded.
- One unit per (symbol, UTC day of timestamp): the first such row of that day. Later directional rows of the same symbol and day are ignored and counted, and a same-day opposite signal is counted separately as a flip.

## 4. Price and return (no AI, public data)
- t = the row timestamp. Entry = the open of the 1-minute candle that starts at floor(t to the minute). Exit = the open of the 1-minute candle that starts 24 hours after that minute. return_pct = (exit - entry) / entry x 100; directional_pct = return_pct for BUY and -return_pct for SELL.
- Each price is one public klines request (interval 1m, startTime = that minute, limit 1), Spot first then Futures (market_facts.URLS; the source is stored). The returned candle's open time must equal the requested minute, else the unit is UNAVAILABLE. Failed requests (network, 429, 5xx) are deferred and retried. Two requests per unit, at most 60 units per run, 0.25 s pause, no AI quota.
- A unit is gradable once now >= t + 24 h + 2 min. hit = directional_pct > 0; exactly 0 is excluded and counted. net_pct = directional_pct - 0.14 (a placeholder round-trip cost).

## 5. Groups (reported separately, never pooled)
- A = timestamp before 2026-10-16T08:24:00Z (the first counterfactual row). A_unseen = A and the audit id is not a consensus_id in paper_trade_plans (read-only join); A_seen = the rest of A (outcomes of those paper trades were seen in aggregate: 4 wins, 8 stops, 2 failures).
- B = from 2026-10-16T08:24:00Z up to the freeze time. Its outcomes were seen in aggregate through the counterfactual report (17 of 44 right).
- C = timestamp at or after the freeze time (the commit time of this spec, written into the code and errata).
- The primary group is APPROVED, A_unseen, all signals. All other groups, and WATCH, are descriptive.

## 6. Storage
shadow_sigaudit in shadow.db, insert-only, unique (symbol, day_utc): audit_id, timestamp, status, signal, grp, seen flag, entry, exit, return_pct, directional_pct, net_pct, source, status, reason; plus a table row count of ignored same-day rows and flips in the run output. Standalone sigaudit_log.py (selftest | check | run | report), added to daily.sh after breakout19_log. No other table is written.

## 7. Evaluation (registered before any outcome is read)
- For each group and signal (BUY, SELL, all): n, distinct UTC days, hit rate, always-up rate (share of units whose raw return was positive), base rate (hit rate expected if the signal were unrelated to the outcome, given the same BUY share and up-move frequency), per-day mean hit rate, mean gross and mean net directional return, and the share of units from the five most frequent coins. Side by side: APPROVED against WATCH hit rates, descriptive only.
- A row of the report is read only with at least 30 units and 10 distinct days; below that it prints counts only. No pass bar, no causal claim. A null means: no effect larger than the detectable size for this sample.

## 8. Never
Results never change Stage 1, the guard, prompts, decisions or any plan. Using the engine's signal for anything needs its own frozen spec and forward evidence.

## 9. Known limits
- The audit timestamp is when the row was written, minutes after the engine computed its signal. Same-day repeats and flips are collapsed. The market mostly fell in September and October and SELL is 76 percent of directional rows; the base-rate column is the control. Rows cluster by day and coin, so noise is larger than the n suggests. Spot and Futures prices can differ. Availability of 1-minute history this far back was not verified. Listings, delistings and renamed symbols can make a unit UNAVAILABLE. Not a profit claim.
