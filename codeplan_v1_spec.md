# codeplan_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed. Any change needs codeplan_v2.
Date: 2026-10-20. Errata 62.

## Purpose
Once a day, log one code-made plan per coin with no AI call, and grade it by candle path. Shadow only. Nothing reads it: not plans, the guard, decisions, the AIs or the live path. Live execution stays BLOCKED. It tests whether a code-only plan does better than chance, not whether it makes money.

## Inputs
- shadow_market_ctx rows (market_ctx_v1) with status OK or PARTIAL. Rows with status UNAVAILABLE get no plan row.
- Plan time needs no request. Only grading makes klines requests.

## Direction (fixed now, not tuned)
- Calls are the four market_ctx_v1 rules S (structure), V (UTC-day VWAP), T (taker ratio 24h vs 0.5) and R (relative strength 24h vs 0), each up, down or no call, exactly as defined in market_ctx_v1_spec.md and market_ctx_log.py `calls()`.
- BUY if at least 3 calls are up. SELL if at least 3 calls are down. Otherwise WAIT (including ties, no calls and n/a values).

## Entry and levels
- Entry = last_close of the ctx row.
- Levels use the levels_v1 method unchanged (U = median of seven 24h ranges, stop 0.5 x U, TP1 0.5 x U, TP2 1.0 x U, TP3 1.5 x U, entry-based). They are computed at grading time from candles closed before the snapshot, so there is no look-ahead.
- Snapshot time = the ctx row's snap_ms. The path starts at the first whole hour after snap_ms (as levels_v1 does), so the entry can be up to an hour stale. Recorded as a known limit.

## Grading
- A row is graded once now >= first whole hour after snap_ms + 24 h + 1 h margin (24 complete path candles).
- Same path walk and outcome classes as levels_v1: STOP, TP1, TP2, TP3, EXPIRED, AMBIGUOUS, UNAVAILABLE. R result as in levels_v1.
- Direction return = close of the 24th path candle vs entry, in the plan direction (positive = correct). Exact 0 is excluded and counted separately.
- WAIT rows are logged and never graded.
- One klines request per graded row (limit 200, startTime = snap_ms - 170 h), at most 40 rows per run, 0.3 s pause. Failed requests (network, 429, 5xx) are deferred and retried on the next run.

## Storage
- shadow_codeplan (plan log) and shadow_codeplan_grade (grades), both in shadow.db, insert-only, unique per ctx_id. The plan table holds ctx_id, day, symbol, direction, the four calls, entry, snap_ms and status. The grade table holds levels, outcome, R, direction return, status and reason. No other DB is written.

## Collection
- Standalone codeplan_log.py (selftest | check | run | report), run once a day after `market_ctx_log.py run` and before `sp`. Does not modify run_sp, run_pw or any hook.

## Evaluation (registered before any data)
- The report refuses below 30 graded non-WAIT rows and below 20 distinct days.
- It reports: outcome shares, mean R over non-ambiguous rows, direction hit rate vs always-up and vs the base rate (same definition as market_ctx_v1), the WAIT share, and per-day means beside the pooled figures.
- No pass bar, no causal claim. Null means: no effect larger than the detectable size for this sample.
- A comparison with the AI plans (AGREEMENT trades only, which are the rows with real stops and TPs) is a later separate patch.

## Never
- Code plans never change a decision, plan, stop, TP, the guard or execution, and are never sent to the AIs. Replacing any AI plan with a code plan needs its own frozen spec and forward evidence.

## Known limits
- The direction rule rests on market_ctx rules with no evidence yet. If those are null, this is null too.
- Direction and levels are tested together, so a null cannot say which part failed. The rules S and V both come from price, so they are not independent.
- Entry can be up to an hour stale. Fees, slippage and funding are not modeled.
- Rows correlate across coins and days. About 3 weeks of daily data are needed before a read.
- Not a profit claim.
