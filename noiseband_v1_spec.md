# noiseband_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed (the git commit time is the freeze time). Any change needs noiseband_v2. Errata 70.

## Purpose
Log hypothetical entries and exits of a simple noise-band breakout rule on crypto, per coin and per UTC day, and report them descriptively. This is a crypto adaptation with my own simplifications. It does not test the claims of any video or paper. Shadow only, no AI. Nothing reads it: not the guard, plans, prompts, decisions or the live path. Live execution stays BLOCKED.

## Universe and data
- The 40 shadow coins (COIN + USDT as in market_ctx_log.py). Public 30-minute klines, Spot first then Futures (market_facts.URLS), one request per coin per run, limit 1000 (about 20.8 days), 0.3 s pause, no AI quota.
- A day is processed only after it is complete. Candle k = 0..47 of UTC day D is the 30-minute candle opening at D 00:00 + 30 min x k.

## Forward only
- FIRST_DAY = the first UTC day that begins after the commit time of this spec. The code hard-codes it and errata records it. Days before FIRST_DAY are never computed, graded or counted. Earlier price data may be used only as the lookback for bands.

## Band (fixed now, not tuned)
- For day D and candle k: m_j(k) = |close of candle k of day j - open of candle 0 of day j| for each of the 14 consecutive UTC days before D. Noise(k) = mean of m_j(k) over those 14 days. Upper(k) = open of candle 0 of D + Noise(k). Lower(k) = same open - Noise(k).
- A coin-day needs day D and all 14 prior days complete with 48 gap-free candles each, else the row is UNAVAILABLE.

## Entry and exit
- Entry: the first candle k <= 46 of day D whose close is above Upper(k) (long) or below Lower(k) (short). At most one entry per coin per day. Entry price = that candle's close. No entry = NO_ENTRY.
- Exit: the close of the first later candle whose close is back inside the band (Lower(k') <= close <= Upper(k')), else the close of candle 47. My own rule, not the video's or the paper's. No VWAP, no volatility sizing, no stop other than this.
- Result per entry: gross = directional return in percent from entry to exit; net = gross - 0.10 (percentage points, a placeholder round-trip cost, not Binance's exact fee schedule).

## Storage
- shadow_noiseband in shadow.db, insert-only, unique (day_utc, symbol): status (ENTRY, NO_ENTRY, UNAVAILABLE), direction, entry and exit candle index and prices, gross, net, raw move, source. A standalone noiseband_log.py (selftest | check | run | report), run once a day, added to daily.sh after levelcmp_log. No other table is written.
- A run stores every complete eligible day not yet stored that is still inside the downloaded candles. A missed run loses days that have left the 1000-candle window and these are never filled.

## Evaluation (registered before any data)
- Units are ENTRY rows. A hit = gross > 0; exact 0 is excluded and counted. Report: n, hit rate, always-up rate (share of entries whose raw move was positive), base rate (hit rate expected if direction were unrelated to outcome, given the same long share and up-move frequency), mean gross, mean net, and a per-day mean beside the pooled figure, for longs, shorts and all.
- The report refuses below 30 ENTRY rows and below 20 distinct days. No pass bar, no causal claim. Null means: no effect larger than the detectable size for this sample.

## Never
- No AI calls. Results never change a prompt, the guard, a plan or any decision. Using the rule anywhere would need its own frozen spec and forward evidence.

## Known limits
- The UTC anchor, the 30-minute buckets, the 14-day lookback and the 0.10% cost are untested choices, not tuned on data.
- Crypto has no session open or close. Entries cluster across coins on the same days. About 3 to 5 weeks are needed before a read.
- Spread, slippage and funding are not modeled. Not a profit claim.
