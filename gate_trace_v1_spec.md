# gate_trace_v1 spec (shadow, log only, no code yet)

Version 1. Frozen at its git commit time (errata 91). Any change needs a new version.

## 1. Purpose
Show where each decision dies (which gate held it) and test ONE alternative
agreement cutoff (50 instead of 60) on forward data. Nothing here changes any
decision, any gate, any cutoff (60/80), the window (4) or the weights.

## 2. Hard limits
- Log only. The logger never changes a decision, never blocks, never raises
  (wrapped in try/except; on failure it writes nothing and the run continues).
- No AI call, no API quota. It uses values the pipeline already computed.
- Writes only to a NEW table shadow_gate_trace in shadow.db. No other table,
  no *.db hand edit, no change to harness.db.
- It gives no role, vote or decision input to anything.
- Hex command "why" is NOT part of v1 (a read-only report in the log script is).

## 3. Unit and eligibility
- Unit: one decision from sp, pw or predict, logged at the moment the final
  action is known.
- Eligible: only rows logged after the commit of the logger code (FIRST_DAY =
  the UTC date of that commit). Earlier decisions never count.
- If one symbol is decided more than once in the same UTC day, only the FIRST
  row of that coin-day counts for the primary test (duplicates are logged
  and marked DUP).

## 4. Fields logged (NULL if the pipeline does not expose it; never invented)
id, utc time, symbol, source (sp|pw|predict), engine signal, Stage 1 status,
Groq direction, Gemini direction, consensus status, whether the OpenRouter
fallback was used, agreement score, score parts (direction match, outcome
match, full agreement, trend adjustment, base score), window used, cutoffs
used (60/80), risk status, final action, stage_held, price at decision and
its source.

stage_held (exactly one value):
- STAGE1_BLOCKED  Stage 1 did not approve
- PROVIDER_INVALID  consensus status INVALID (a provider failed with no rescue)
- CONFLICT  Groq and Gemini direction differ
- AGREEMENT_LOW  agreed direction, agreement score under 60
- OTHER_GUARD  held by another guard (for example Adaptive Memory Safety)
- NONE_HELD  decision not held by any gate

If the hook cannot read the score or the stage without changing existing code
behaviour, the implementation stops and a new spec version is written.
## 5. Primary group M (the only tested group)
A row is in M if ALL hold:
- stage_held = AGREEMENT_LOW
- consensus status AGREEMENT on BUY or SELL (agreed direction D)
- Stage 1 approved
- agreement score s with 50 <= s < 60
- first row of its coin-day (not DUP)
M means: "would have passed a cutoff of 50 but was held at 60".
This is the ONE alternative tested. Cutoffs other than 50 are descriptive only.

## 6. Grading (self-contained, 24h)
- Entry price: price at decision (section 4). Exit: close of the 1h candle
  nearest to decision time + 24h, Binance futures public klines.
- Signed return = +ret for BUY, -ret for SELL. Hit if signed return > 0.
  Exactly 0 is VOID. No data after 24h + 6h = UNAVAILABLE (counted, not hit).
- Fees and slippage are not modelled; this tests direction only.

## 7. Baseline
For each M row, baseline probability = share of ALL logged coins of the same
UTC day (any stage_held, first rows only) whose price moved in direction D
over their own 24h window. Expected hits = sum of these probabilities.

## 8. Primary test and reading rule (registered before any row exists)
- Statistic: (observed hits - expected hits) over graded M rows.
- Test: bootstrap over UTC days (resample days with replacement, 10000 draws,
  fixed seed 1), one-sided, p < 0.05. One test, no correction needed.
- Read only when graded M rows >= 30 AND days with at least one M row >= 20.
  Not read earlier, not peeked at.
- Below 30: "no effect larger than about 15 percentage points detectable"
  (estimate, one sd of a hit rate at n=30 is about 9 points).

## 9. What a result means
- Pass: allowed only to write a SEPARATE frozen spec proposing a guard change,
  plus a new forward test. The guard is never changed from this table alone.
- Fail or too small: nothing changes. "No effect detected" is not proof of none.
- The score measures wording agreement between Groq and Gemini, not accuracy.

## 10. Descriptive only (no tests, no selection)
Counts per stage_held; hit rate vs baseline for score bands under 50, 50-59,
60-79, 80+; share of decisions held per stage per week.

## 11. Honest expectation
Chance level is expected: held calls so far were right 17 of 44 (38.6%) vs a
48.8% baseline (about 7.5 points per sd), from rows that did not store the
score. A null is the likely result.

## 12. Files (after a separate go)
gate_trace_log.py with selftest | check | run | report. Kept in git. First
step after a go: read-only look at apply_adaptive_confidence_guard and the
sp/pw/predict end points to find an anchor. Code in parts of 100 lines or less.
