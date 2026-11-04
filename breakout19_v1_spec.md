# breakout19_v1 spec (shadow only, DRAFT, text only, no code)

Status: DRAFT. NOT frozen. It freezes only when the operator says "freeze breakout19_v1" and a later commit records it. Errata 77.

## 1. Origin
- The design came from a chat with Binance AI Pro (untrusted text), locked by the operator's four answers, which the assistant has not seen. This spec is the assistant's interpretation of the pasted summary. Where the summary is ambiguous the choice is stated below. S and M (computed and logged by the AI Pro design, gating nothing) are not defined for the assistant and are NOT implemented.
- Shadow only. No orders, no AI calls, nothing reads the results (not the guard, prompts, decisions or execution). It tests the RULE, not Binance AI Pro's execution. Live stays BLOCKED.

## 2. Data
- The 40 shadow coins (COIN + USDT as in market_ctx_log.SYMS). Public 1h klines, Spot first then Futures (market_facts.URLS, source stored), limit 1000. Closed candles only. 4H bars are UTC-aligned blocks of four consecutive 1h candles (opens 00, 04, 08, 12, 16, 20 UTC); a 4H bar needs all four candles.

## 3. Signal at the completed 4H bar k, closing at time T
- HH = highest high and LL = lowest low of the 24 completed 4H bars before bar k (not including k). Long breakout: close(k) > HH. Short breakout: close(k) < LL (close beyond only; a wick beyond does not count).
- Direction agreement: M19 = close of the 1h candle ending at T minus close of the 1h candle ending at T-19h. Long needs M19 > 0, short needs M19 < 0 (zero is no signal).
- Range expansion: TR19 = sum of the true ranges of the 19 hourly candles ending at T; PREV19 = the same sum for the 19 candles before them (ending at T-19h). True range = max(high-low, |high-previous close|, |low-previous close|). Condition TR19 >= 1.5 x PREV19. This needs 39 consecutive hourly candles. The summary does not say sum or mean; with equal counts the ratio is the same.
- A signal needs the breakout, the agreement and the expansion. Missing data (a gap, fewer than 25 4H bars or 39 hourly candles) means no signal and the bar is counted UNAVAILABLE.

## 4. Trade
- Entry price = close(k) at T (idealised; a real fill can differ). Stop = entry x (1 - 0.02) for longs and x (1 + 0.02) for shorts. No take-profit. Exit at the first of: the stop touched, or the close of the 24th hourly candle after T (entry + 24 h).
- Stop touched in an hourly candle: long when low <= stop, short when high >= stop. Exit price = the stop, or the candle's open if the candle opens beyond the stop (a gap). Hourly resolution: the order inside a candle is unknown and no take-profit exists, so no ambiguity class is needed.
- Costs (placeholders, not verified for any account): taker fee 0.05% per side and slippage 0.02% per side, both applied at entry and exit, so 0.14 percentage points round trip. net_pct = directional return in percent - 0.14. R = net_pct / 2.0 (the stop distance).

## 5. Constraints in v1
- Per coin: no second signal while the coin's previous trade is open (a new signal needs T >= the previous exit time). Bars are processed in order per coin; a bar after an unfinished trade waits (PENDING) and is processed on a later run.
- NOT enforced in v1: 1 open position across coins, at most 5 entries per UTC day, 10x isolated margin, the 1.50 USDT risk cap and symbol minimum sizes. Every signal is graded independently, so v1 measures the rule and not the portfolio rules. The report prints how often signals overlap across coins and how many UTC days exceed 5 signals. Minimum order size is an execution issue (exec_v1).

## 6. Forward only
- FIRST_BAR = the first 4H bar whose close is after this spec's commit time (git time; hard-coded in the code, recorded in errata). Earlier bars are never signalled, graded or counted. Earlier candles may be used only as lookback.

## 7. Grading and storage
- A trade is graded once 24 complete hourly candles exist after T. Public candles only, no AI quota. Failed requests (network, 429, 5xx) are deferred and retried.
- shadow_breakout19 in shadow.db, insert-only, unique (symbol, signal_close_ms): direction, entry, stop, exit time, exit price, exit type (STOP or TIME), gross_pct, net_pct, r_net, mirror_net_pct, status, source. Standalone breakout19_log.py (selftest | check | run | report), run once a day, added to daily.sh after noiseband_log.
- Mirror comparator: for each trade, the opposite-direction trade at the same entry with the same stop and exit rules and the same costs; mirror_net_pct is stored.

## 8. Evaluation (registered before any data)
- Units are graded trades. Report: n, long and short counts, share stopped out, mean net_pct and mean R (pooled and per-day mean), net hit rate (net_pct > 0), mean mirror net_pct, signals overlapping across coins, days above 5 signals, UNAVAILABLE count.
- The report refuses below 30 trades and below 20 distinct UTC signal days. No pass bar, no causal claim. If a strategy comparison (strategylib) is later written, its false-positive correction counts this candidate too.

## 9. Never
- No orders, no AI use. Results never change a prompt, the guard, a plan or any decision. Using the rule anywhere needs its own frozen spec and forward evidence.

## 10. Known limits
- The interpretation of an unseen design; S and M missing. Entry at the 4H close and the 0.05% and 0.02% costs are optimistic or unverified. Hourly candles for stops and 1h sampling of the 19h windows. Signals cluster across coins and days. Min-size and portfolio constraints not modelled. A null means no effect larger than the detectable size. Not a profit claim.
