# levelcmp_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed (the git commit time is the freeze time). Any change needs levelcmp_v2. Errata 68.

## Purpose
Compare the entry, stop and TP levels each AI printed for guard-held AGREEMENT calls (shadow_held_plans) with the volatility-based levels of levels_v1 (shadow_levels) on the same calls, descriptively. Shadow only. Nothing reads the result: not the AI plans, prompts, the guard, levels_v1, held_plan_grade or the live path. Live execution stays BLOCKED.

## Basis (counts only, observed before this spec; no outcome was read)
- A read-only pairing query on shadow.db found 27 pairs for gemini and 27 for groq, time gaps 0.0 to 0.2 minutes, 5 distinct days, 0 held rows matching more than one counterfactual row. shadow_held_plans had 54 rows, all graded, from 27 distinct audit_ids.

## Pairs
- A held row (one per AI) with graded_utc set and outcome not in UNPARSED, DIRECTION_MISMATCH, INVALID_LEVELS, paired with the shadow_counterfactual row of the same symbol and the same direction with the smallest |created_ms difference| of at most 30 minutes, not excluded, where that counterfactual row has a shadow_levels row with status OK. One-to-one per held row; if two candidates tie, the lower counterfactual id wins.
- Both AIs share the same calls, so AI results are not independent samples.

## Grading (identical for both sides, per pair)
- One path: 1-minute candles, 1440 of them from the first full minute after the audit time (the held row's created_ms), public klines (Spot first, then Futures, limit 1000, two requests with startTime), at least 1380 candles or the pair stays pending and is retried. Failed requests (network, 429, 5xx) are deferred.
- Touch rules as in errata 48: SELL: TP when candle low <= level, stop when candle high >= stop. BUY: TP when high >= level, stop when low <= stop. A TP counts only if first touched in an earlier candle than the stop; a TP and the stop in the same candle with no earlier TP is AMBIGUOUS, never a win. Outcome = highest TP counted, else STOP, else NONE.
- AI side: stop_loss, tp1, tp2, tp3 of the held row; entry reference = midpoint of entry_low and entry_high. Calculated side: stop, tp1, tp2, tp3 of the shadow_levels row; entry reference = its entry (the counterfactual price). Entry fills are not modelled on either side.
- R_own per side: STOP = -1. TPk = |tpk - entry_ref| / |entry_ref - stop|. NONE = (close of the last candle - entry_ref) / entry_ref in the call direction, divided by |entry_ref - stop| / entry_ref. A side with a non-positive stop distance is UNAVAILABLE.

## Measures
- Primary, per AI: mean over pairs of R_own(AI) minus R_own(calculated). Pairs where either side is AMBIGUOUS or UNAVAILABLE are left out of the mean and counted.
- Descriptive, per AI and for the calculated side: outcome counts (STOP, TP1, TP2, TP3, NONE, AMBIGUOUS), stop distance as a percent of the entry reference, and the share of pairs where the AI stop is closer than the calculated stop.
- Consistency check: the re-graded AI outcome is compared with the stored held-plan outcome. Mismatches are counted and reported, never edited.

## Storage and collection
- shadow_levelcmp in shadow.db, insert-only, unique per held row (held_id). Standalone levelcmp_log.py (selftest | check | run | report), added to daily.sh after webdir_log. Reads shadow.db only plus public candles. No AI quota. No other table is written.

## Evaluation (registered before any outcome is read)
- The report refuses below 30 pairs per AI and below 10 distinct days (UTC day of the audit time). No pass bar, no causal claim. Null means: no difference larger than the detectable size for this sample.

## Never
- Results never change an AI plan, a prompt, the guard, levels_v1 or held_plan_grade. Using calculated levels anywhere would need its own frozen spec and forward evidence.

## Known limits
- The calculated multipliers (levels_v1) are arbitrary starting values, so a result says "this setting against the AI's", not "calculated against AI levels" in general.
- levels_v1 graded on 1-hour candles from the next whole hour, so its stored outcomes can differ from this comparison's re-grade of the same levels; this comparison uses the 1-minute path for both sides.
- Small sample, same-day clustering, both AIs share the same calls, guard-held AGREEMENT calls only, a market that mostly fell. Fees and slippage not modelled. Not a profit claim.
