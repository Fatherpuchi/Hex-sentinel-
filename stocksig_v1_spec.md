# stocksig_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed (the git commit time is the freeze time). Any change needs stocksig_v2. Errata 83.

## 1. Purpose
Grade, forward only, the existing stock rule of stocks.py on every trading Binance TradFi perpetual, automatically and not hand-picked, against its own always-up and always-down baselines. No AI, no keys, no credits. Shadow only. stocks.py, stock_paper.db and the stocks menu are not read or changed. Nothing reads the result. Live stays BLOCKED.

## 2. Basis (the code as pasted; no outcome was read)
signal(closes): ema(v, n) seeded with the first value, k = 2/(n+1); rsi(c, 14) Wilder. UP if EMA20 > EMA50 and 50 <= RSI14 <= 70; DOWN if EMA20 < EMA50 (no RSI test); otherwise NO CALL. thr = 0.25 x sd x sqrt(24), sd = sample standard deviation of the hourly log returns of the closes used. Result: VOID if |ln(exit/entry)| < thr, HIT if the sign matches the call, else MISS. stock_paper.db has 1 prediction; the existing log is hand-picked.

## 3. Universe and data
- Public Binance USD-M futures endpoints only: exchangeInfo (symbols with contractType TRADIFI_PERPETUAL and status TRADING at run time; the set can change) and 1h klines. No filter on volume or age; kind (underlyingType), listing age and 24h quote volume are stored as descriptive fields.

## 4. Snapshot (once per UTC day)
- T = the start of the current UTC hour at run time. The first run of each UTC day defines the units of that day (unique per symbol and UTC day of T); a later run that day only adds missing symbols.
- Closes: the closed hourly candles ending at T (the last opens at T-1h), at most 100, taken as the longest contiguous suffix; fewer than 60 means UNAVAILABLE. Signal, thr and the 100-or-fewer closes are computed exactly as in section 2. Entry = the close of the candle opening at T-1h. NO CALL and UNAVAILABLE rows are stored and never graded.

## 5. Grading
- A unit is gradable once now >= T + 24h + 5 minutes. Exit = the close of the 1h candle opening at T+23h (one request per unit: klines startTime = T+23h, limit 1; the returned open time must equal T+23h, else retry on a later run; a unit still without that candle 72 hours after T becomes UNAVAILABLE). ret = ln(exit/entry); VOID, HIT and MISS as in section 2. Also stored: gross directional percent and net = gross - 0.14 (a placeholder round-trip cost; the true fee for these contracts is unknown).
- Failed requests (network, 429, 5xx) are deferred. At most 60 grading requests per run, 0.25 s pause.

## 6. Forward only
- FIRST_DAY = the first UTC day that begins after this spec's commit time (hard-coded in the code and recorded in errata). Runs earlier than that request nothing and store nothing.

## 7. Storage
- shadow_stocksig in shadow.db, insert-only, unique (symbol, day_utc): T_ms, kind, age_days, vol24, entry, direction (UP, DOWN, NO_CALL, UNAVAILABLE), e20, e50, rsi, thr_pct, exit, ret, result, market_open_guess, source, status, reason. Standalone stocksig_log.py (selftest | check | run | report), run once a day, added to daily.sh. No other table or file is written.

## 8. Evaluation (registered before any data)
- Counted units = HIT or MISS (VOID are reported as a share and excluded, as in stocks.py). For UP, DOWN and all: n, distinct UTC days, hit rate, always-up rate (share of counted units with ret > 0), base rate (hit rate expected if calls were unrelated to outcomes, given the same UP share and up-move frequency), per-day mean hit rate, mean gross and net directional return, void share, share of counted units from the five most frequent symbols.
- Descriptive splits: by kind; by market_open_guess at T (the stocks.py window: weekdays 13:30-21:00 UTC, holidays ignored, EQUITY and ETF only).
- Primary row: all counted units pooled; read only with at least 30 counted units over at least 20 distinct UTC days. Every other row needs 30 units over 10 days. Below that, counts only. No pass bar, no causal claim. A null means: no effect larger than the detectable size for this sample.

## 9. Never
- No AI. Results never change stocks.py, its menu, a decision or any plan. Using the rule for anything beyond paper research needs its own frozen spec and forward evidence.

## 10. Known limits
- Perpetual contracts are not the shares; outside US hours their price is set by Binance's own market; holidays are ignored. Stocks move together, so rows cluster by day and the effective sample is much smaller than n. Hourly candles are exchange-defined; fees for these contracts are unknown. The universe changes over time. Not a profit claim.
