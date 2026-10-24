# webdir_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed (the git commit time is the freeze time). Any change needs webdir_v2. Errata 65.

## Purpose
Grade the stored `direction` of the existing web evidence against the next 24h return, descriptively. This tests only the keyword direction rule (_web_classify_direction in sentinel_ai.py: substring counts of fixed bullish and bearish words, ties NEUTRAL), not what the AIs make of the evidence text. Nothing reads these results: not the prompts, evidence weights, the guard, decisions or the live path. Live execution stays BLOCKED.

## Source
- Read-only access to web_intelligence_evidence in sentinel.db (opened with mode=ro). Rows with direction BULLISH or BEARISH. NEUTRAL rows are ignored.
- Time of availability = retrieved_at (ISO with offset, converted to UTC). published_at is never used for timing. Evidence retrieved after a snapshot is never used for that snapshot.

## Primary unit: symbol-day
- For symbol S and UTC day D, use only rows with retrieved_at inside D. Sign = count(BULLISH) - count(BEARISH). Zero = excluded and counted separately.
- Snapshot time = start of D+1 (00:00 UTC). Entry = close of the 1h candle that opened at snapshot - 1 h. The path is the 24 consecutive 1h candles opening at snapshot ... snapshot + 23 h. Forward return = close of the 24th path candle vs entry, in percent. Exact 0 is excluded and counted.
- A unit is gradable once now >= snapshot + 25 h.

## Secondary unit: symbol-event
- For symbol S and event_key K, keep the earliest-retrieved row; its direction is the call. Snapshot time = the first whole hour at or after that retrieved_at. Entry and path as above relative to that snapshot. Reported next to the primary, never pooled with it.

## Symbols and data
- Stored symbol used as is if it ends in USDT, otherwise USDT is appended (the stored format is unseen; the first `check` run shows it). No other mapping is guessed. A symbol with no candle source, or with a gap in the needed candles, is UNAVAILABLE.
- Candles: public 1h klines via market_facts.URLS (Spot first, then futures; source stored per unit), limit 1000 per request, startTime-based pages covering [first snapshot - 1 h, last snapshot + 24 h] per symbol. At most 40 symbols per run, 0.3 s pause, no AI quota. Failed requests (network, 429, 5xx) are deferred and retried next run.
- Existing rows since the first stored evidence are included. Nobody has looked at their outcomes. Known limit: the stored direction was assigned by whichever rule was live when stored.

## Storage
- shadow_webdir (units: kind, symbol, snapshot, call, counts, event_key) and shadow_webdir_grade (grades: entry, forward return, status, reason, source) in shadow.db, insert-only, unique per unit. A standalone webdir_log.py (selftest | check | run | report). No other DB is written. It is added to daily.sh after codeplan_log.

## Evaluation (registered before any data)
- Direction hit rate for BULLISH calls, for BEARISH calls and pooled, against always-up and the base rate (hit rate expected if calls were unrelated to outcomes, given the same call and up-move frequencies), plus a per-day mean beside the pooled figure.
- The report refuses below 30 graded primary units and below 20 distinct days. No pass bar, no causal claim. Null means: no effect larger than the detectable size for this sample.

## Never
- Results never change prompts, evidence weights, the keyword lists, the guard or any decision. What to do with a positive read would need its own frozen spec and forward evidence.

## Known limits
- The keyword rule is crude: substring matches, and terms that describe moves already made (surge, drop, fall, gains), so a hit may only reflect follow-through after a price move that preceded the article.
- 54.8% of rows have source type "unknown" and 75.6% are NEUTRAL. BULLISH outnumbers BEARISH about two to one.
- Rows cluster by day and symbol, and 10.5% of symbol-event pairs repeat across rows. Fees and slippage are not modeled. Not a profit claim.
