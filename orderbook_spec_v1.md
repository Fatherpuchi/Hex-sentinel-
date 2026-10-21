# orderbook_v1 spec (shadow only, text spec, no code yet)

Status: FROZEN once committed. Any change needs orderbook_v2.
Date: 2026-10-20. Errata 53.

## Purpose
Log descriptive Spot order-book liquidity numbers per coin and later test, descriptively, whether they relate to the next 24h return. Nothing reads these numbers: not the guard, decisions, plans, the AIs, or facts_v1. Live execution stays BLOCKED.

## Source
- GET https://api.binance.com/api/v3/depth?symbol=<COIN>USDT&limit=100, public, no key, one request per coin.
- Shape confirmed by a user-pasted request (AAVEUSDT, 2026-10-20): keys lastUpdateId, bids, asks; 100 levels per side; each level [price, qty] as strings; bids high to low, asks low to high.
- Third-party sources (not the official docs page) give weight 5 for limit 1-100. Not verified against response headers.
- Universe: the 40 shadow coins. Spot symbol = coin + USDT. The SHIB spot symbol is unconfirmed: if its request fails the row is UNAVAILABLE. No mapping is guessed.

## Numbers per snapshot
- best_bid, best_ask, mid = (best_bid + best_ask) / 2, spread_pct = (best_ask - best_bid) / mid * 100.
- Bands b in {0.1, 0.25, 0.5} percent of mid. Bid notional B = sum(price*qty) over bids with price >= mid*(1-b/100). Ask notional A = same over asks with price <= mid*(1+b/100).
- A band is covered only if the deepest returned level on EACH side lies at or beyond the band edge. If not covered, that band is n/a for both sides. Never estimated.
- Imbalance per covered band I = (B - A) / (B + A). n/a if B + A == 0.
- Largest wall per side inside the 0.5% band (only if that band is covered, else n/a): price, notional, distance % from mid, share of that side's 0.5% band notional.
- snapshot_utc = local clock when the request was sent; lastUpdateId stored; round trip seconds stored.

## Status
- UNAVAILABLE: request error or timeout (15 s, no retry), non-numeric values, empty side, best_bid >= best_ask, bids or asks not sorted, mid <= 0.
- STALE: round trip > 5 s (numbers kept, excluded from grading).
- PARTIAL: any band n/a (numbers kept for covered bands).
- OK: otherwise.
- No price cross-check against a report price in v1 (no report price exists in a standalone run).

## Storage
Table shadow_orderbook in shadow.db, append-only, own table. Columns at minimum: id, created_utc, symbol, spot_symbol, status, reason, last_update_id, round_trip_s, best_bid, best_ask, mid, spread_pct, per band (0.1, 0.25, 0.5) bid_notional, ask_notional, imbalance, wall fields, numbers_json. The raw book is not stored. No other DB is written.

## Collection
- Standalone script orderbook_log.py (check|run), run once a day right before `sp`. 0.25 s pause between coins. Does not modify run_sp, run_pw, or any hook.
- Never run twice for the same UTC day without a "new" flag (to be defined in the code spec).

## Evaluation (registered before any data)
- Question: does the sign of the 0.25% imbalance agree with the sign of the next-24h return?
- Pairing: a snapshot pairs with a shadow_counterfactual row only if same coin, snapshot_utc <= row created_utc, and no more than 60 minutes earlier. Never use a snapshot taken after the call. Unpaired snapshots are logs only and are never graded.
- Return = move_pct of the paired shadow_counterfactual row (same entry/exit method as counterfactual_grade.py).
- Excluded from grading and counted separately: status not OK or PARTIAL-with-0.25%-covered, STALE, imbalance exactly 0 or n/a, move_pct exactly 0.
- Comparator: always-up baseline. No pass bar. No causal claim.
- The report refuses below 30 graded paired rows. 30 is a minimum for reading, not evidence of reliability.
- Null means: no effect larger than the detectable size for this sample. It does not mean no effect exists.
- Bands, limit and status rules are not tuned on seen data.

## Never
- Order-book numbers must not trigger BUY/SELL, change a decision, plan, stop, TP, or the agreement guard.
- Full books are never sent to the AIs.

## Known limits
- Displayed orders can be cancelled or fake; one exchange only.
- A snapshot is stale within minutes while the main horizon is 24H.
- Hex coins are USDT perps; the Spot book is only a proxy.
- 100 levels may not reach the 0.5% band for liquid coins (BTC, ETH): those rows are PARTIAL.
- Pairing is only with shadow_counterfactual rows, so paired rows accumulate slowly.
- Not in v1: evaluating all snapshots against klines returns (would give more rows; needs v2).
