"""rating_strong.py - are the STRONG signals one lucky rally, or spread out?"""
import datetime
import statistics
import sys
from collections import Counter

import rating_backtest as rb
from composite_rating import composite_rating


def main(coins):
    S = []
    for c in coins:
        try:
            rows = rb.fetch(c)
        except Exception as e:
            print(f"{c}: skipped ({e})")
            continue
        n0 = len(S)
        for i in range(rb.WINDOW, len(rows) - rb.HORIZON, rb.STEP):
            res = composite_rating(rows[i - rb.WINDOW + 1:i + 1])
            if res["rating"] in ("STRONG BUY", "STRONG SELL"):
                fwd = (rows[i + rb.HORIZON]["close"] / rows[i]["close"] - 1) * 100
                day = datetime.datetime.fromtimestamp(rows[i]["t"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
                S.append((res["rating"], c, day, fwd))
        print(f"{c}: {len(S) - n0} strong samples")
    for lab, sign in (("STRONG BUY", 1), ("STRONG SELL", -1)):
        v = [x for x in S if x[0] == lab]
        if not v:
            continue
        f = sorted((x[3] for x in v), key=lambda r: -sign * r)
        days = Counter(x[2] for x in v)
        mean = sum(f) / len(f)
        trimmed = f[3:]
        print(f"\n{lab}: n={len(v)} on {len(days)} distinct days")
        print(f"  mean {mean:+.2f}%   median {statistics.median(f):+.2f}%")
        if trimmed:
            print(f"  mean without the 3 best-for-signal samples: {sum(trimmed) / len(trimmed):+.2f}%")
        print(f"  busiest days: {days.most_common(4)}")
        print(f"  by coin: {dict(Counter(x[1] for x in v))}")
    print("\nIf the median is near 0 or the mean collapses without 3 samples, a few big moves drive it.")


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]] or rb.COINS)
