"""rating_backtest.py - replay composite_rating on past Binance candles.
Usage: python rating_backtest.py [COIN COIN ...]
"""
import sys
import time

import requests

from composite_rating import composite_rating

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "NEARUSDT"]
WINDOW, STEP, HORIZON, PAGES = 300, 24, 24, 5
BUCKETS = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]


def fetch(symbol):
    rows, end = [], None
    for _ in range(PAGES):
        p = {"symbol": symbol, "interval": "1h", "limit": 1000}
        if end:
            p["endTime"] = end
        r = requests.get("https://api.binance.com/api/v3/klines", params=p, timeout=15)
        r.raise_for_status()
        k = r.json()
        if not k:
            break
        rows = [{"t": x[0], "high": float(x[2]), "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])} for x in k] + rows
        end = k[0][0] - 1
        time.sleep(0.3)
    return rows


def replay(rows):
    out = []
    for i in range(WINDOW, len(rows) - HORIZON, STEP):
        res = composite_rating(rows[i - WINDOW + 1:i + 1])
        fwd = (rows[i + HORIZON]["close"] / rows[i]["close"] - 1) * 100
        out.append((res["rating"], fwd))
    return out


def main(coins):
    allr = []
    for c in coins:
        try:
            rows = fetch(c)
            res = replay(rows)
            allr += res
            print(f"{c}: {len(rows)} candles, {len(res)} samples")
        except Exception as e:
            print(f"{c}: skipped ({e})")
    if not allr:
        return
    base = sum(f for _, f in allr) / len(allr)
    base_up = 100 * sum(f > 0 for _, f in allr) / len(allr)
    print(f"\n{HORIZON}h forward return, {len(allr)} samples")
    print(f"{'ALL (baseline)':<13} n={len(allr):<5} avg={base:+.3f}%  up={base_up:.1f}%\n")
    for b in BUCKETS:
        v = [f for r, f in allr if r == b]
        if not v:
            print(f"{b:<13} n=0")
            continue
        avg = sum(v) / len(v)
        up = 100 * sum(x > 0 for x in v) / len(v)
        print(f"{b:<13} n={len(v):<5} avg={avg:+.3f}%  up={up:.1f}%  vs base {avg - base:+.3f}%")
    print("\nA useful rating shows BUY rows above baseline and SELL rows below it.")


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]] or COINS)
