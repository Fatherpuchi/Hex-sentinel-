# levels_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed. Any change needs levels_v2.
Date: 2026-10-20. Errata 56.

## Purpose
Compute stop, invalidation and TP1-TP3 levels in code from realized volatility, and grade them by candle path on the same calls shadow_counterfactual logs. Descriptive only. Nothing reads these levels: not the guard, plans, decisions, the AIs, or the live path. Live execution stays BLOCKED. Multipliers are arbitrary starting values fixed before any data, not tuned.

## Population
- Rows of shadow_counterfactual with coalesce(excluded,0)=0 and direction BUY or SELL, not yet in shadow_levels.
- A row is graded once now >= created_utc + 25 hours.

## Data
- One public klines request per row at grading time: 1h interval, startTime = call time - 170 h, limit 200, same source rule as facts_v1 (market_facts.fetch_klines; the source is stored per row).
- Candle prices for levels use only candles CLOSED before the call (open_time + 1 h <= call time). Candles after the call are used only for the path walk.
- If the symbol has no candle source (for example SHIB if the Spot symbol is unconfirmed) the row is UNAVAILABLE, never guessed.

## Volatility unit U
- U = median over the last 7 non-overlapping 24-candle blocks (ending at the last closed candle before the call) of (block high - block low) / last close before the call.
- Needs 168 gap-free closed candles, else U is n/a and the row is UNAVAILABLE.

## Levels (fixed multipliers, entry = counterfactual row price, direction = row direction)
- Stop distance = 0.5 x U of entry price. TP1 = 0.5 x U, TP2 = 1.0 x U, TP3 = 1.5 x U (that is 1R, 2R, 3R). Stop and invalidation are the same level in v1.
- BUY: stop below entry, TPs above. SELL: stop above entry, TPs below.

## Path grading
- Walk the 24 candles whose open_time >= the first whole hour after the call. First touch decides, using candle high and low.
- Outcomes: STOP, TP1, TP2, TP3 (highest TP reached before any stop), EXPIRED (nothing touched; return = close of the 24th candle vs entry in the call direction), AMBIGUOUS (stop and a TP inside the same candle; counted separately, never assigned), UNAVAILABLE.
- R result: STOP = -1, TPn = +n, EXPIRED = return / stop distance, AMBIGUOUS excluded from averages.
- Fees, slippage, funding are not modeled. Not a profit claim.

## Storage
Table shadow_levels in shadow.db, append-only: id, created_utc, cf_id, symbol, direction, entry, u_pct, stop, tp1, tp2, tp3, outcome, r_result, candles_used, source, status, reason. No other DB is written.

## Reporting
- levels_log.py report prints counts and shares per outcome and the mean R over non-ambiguous rows. It refuses below 30 graded rows.
- No pass bar, no tuning of multipliers on seen data, no causal claim. Null means no effect larger than the detectable size at this n.
- Where an AI-proposed stop and TPs exist (AGREEMENT trades only), show them beside this table as a read-only comparison. Directional rows have levels 0.0 and no comparator.

## Known limits
- Same-hour grading uses 1h candles, so order within a candle is unknown (AMBIGUOUS handles this).
- Window is 24 full candles after the call, so exit differs slightly from counterfactual_grade.py (due at +24 h exactly).
- Counterfactual rows are calls the guard held; this does not show how levels behave on other calls.
- Same-day rows are correlated; 30 rows cannot detect small effects.
- ATR14 on 1h (facts_v1 atr_pct) is not used; U is a 24h range measure to match the 24H horizon.
