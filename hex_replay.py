"""hex_replay.py - does Hex's own EMA/RSI signal predict the next 24h?
Usage: python hex_replay.py [COIN ...]
"""
import datetime
import statistics
import sys

import rating_backtest as rb
import sentinel_stage1 as s1

STEP = 6


def collect(coin):
    prepared = s1.prepare_indicators(rb.fetch(coin))
    out = []
    n = len(prepared)
    for i in range(0, n - rb.HORIZON, STEP):
        row = prepared[i]
        sig = s1.generate_signal(row)
        fwd = (prepared[i + rb.HORIZON]["close"] / row["close"] - 1) * 100
        day = datetime.datetime.fromtimestamp(row["t"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
        out.append((sig, coin, day, fwd, i < n // 2))
    return out


def line(label, v, base, sign):
    if not v:
        print(f"{label:<5} n=0")
        return
    f = sorted((x[3] for x in v), key=lambda r: -sign * r) if sign else [x[3] for x in v]
    mean = sum(f) / len(f)
    trim = f[3:] if sign and len(f) > 6 else f
    up = 100 * sum(x > 0 for x in f) / len(f)
    days = len({x[2] for x in v})
    halves = []
    for h in (True, False):
        sub = [x[3] for x in v if x[4] == h]
        allh = [x[3] for x in ALL if x[4] == h]
        halves.append(f"{sum(sub) / len(sub) - sum(allh) / len(allh):+.2f}%" if sub else "n/a")
    print(f"{label:<5} n={len(v):<5} days={days:<4} mean={mean:+.2f}% median={statistics.median(f):+.2f}% "
          f"up={up:.0f}%  vs base {mean - base:+.2f}%")
    print(f"      mean w/o 3 best-for-signal: {sum(trim) / len(trim):+.2f}%   halves vs base: 1st {halves[0]} | 2nd {halves[1]}")


def main(coins):
    global ALL
    ALL = []
    for c in coins:
        try:
            r = collect(c)
            ALL += r
            print(f"{c}: {len(r)} samples")
        except Exception as e:
            print(f"{c}: skipped ({e})")
    if not ALL:
        return
    base = sum(x[3] for x in ALL) / len(ALL)
    print(f"\nBaseline 24h: mean {base:+.2f}% median {statistics.median(x[3] for x in ALL):+.2f}% over {len(ALL)} samples\n")
    for sig, sign in (("BUY", 1), ("SELL", -1), ("HOLD", 0)):
        line(sig, [x for x in ALL if x[0] == sig], base, sign)
    print("\nBUY should beat the baseline and SELL should fall below it, in both halves.")


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]] or rb.COINS)
