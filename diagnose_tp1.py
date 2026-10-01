"""
Diagnose the "TP1 never hit" pattern: for every resolved real trade,
pull the actual Binance candles between when it opened and when it
resolved, and see how close price actually got to TP1 before the
trade closed -- as a % of the distance from entry to TP1.

  100%+  -> price reached/passed TP1 (shouldn't happen if TP1=0 hits,
            but would flag a bug in how TP1 hits are recorded)
   70-99%-> got close, TP1 may just be a bit too far out
   <30%  -> barely moved toward TP1 at all -- direction call itself
            was likely the problem, not the target distance
   negative -> price never even moved favorably, went the wrong way
               almost immediately

Run from the same folder as sentinel.db (or a horizon profile's db,
e.g. sentinel_48h.db -- pass it as the one argument if so).
"""
import sqlite3
import sys
import requests
from datetime import datetime, timezone

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "sentinel.db"


def to_ms(iso_str):
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_klines(symbol, start_ms, end_ms):
    resp = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": "1h",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 1000,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT symbol, direction, entry_price, stop_loss, tp1,
               created_at, expires_at, resolved_at, outcome
        FROM paper_trade_plans
        WHERE status = 'RESOLVED'
        ORDER BY created_at
        """
    ).fetchall()
    conn.close()

    if not rows:
        print("No resolved trades found in this database.")
        return

    header = f"{'Symbol':<12}{'Dir':<5}{'Entry':<14}{'Stop':<14}{'TP1':<14}{'Extreme hit':<14}{'% of way to TP1':<18}{'Outcome'}"
    print(header)
    print("-" * len(header))

    for r in rows:
        symbol, direction = r["symbol"], r["direction"]
        entry, stop, tp1 = r["entry_price"], r["stop_loss"], r["tp1"]
        outcome = r["outcome"] or ""

        start_iso = r["created_at"]
        end_iso = r["resolved_at"] or r["expires_at"]
        note = "" if r["resolved_at"] else "  (no resolved_at -- used expiry, window may run past actual close)"

        if not start_iso or not end_iso or not tp1:
            print(f"{symbol:<12}{direction:<5}-- skipped (missing entry/tp1/timestamp data)")
            continue

        try:
            candles = fetch_klines(symbol, to_ms(start_iso), to_ms(end_iso))
        except Exception as e:
            print(f"{symbol:<12}{direction:<5}-- fetch error: {e}")
            continue

        if not candles:
            print(f"{symbol:<12}{direction:<5}-- no candle data returned for this window")
            continue

        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]

        if direction == "BUY":
            extreme = max(highs)
            pct = (extreme - entry) / (tp1 - entry) * 100 if tp1 != entry else 0.0
        else:
            extreme = min(lows)
            pct = (entry - extreme) / (entry - tp1) * 100 if tp1 != entry else 0.0

        print(
            f"{symbol:<12}{direction:<5}{entry:<14.6g}{stop:<14.6g}"
            f"{tp1:<14.6g}{extreme:<14.6g}{pct:<18.1f}{outcome}{note}"
        )


if __name__ == "__main__":
    main()
