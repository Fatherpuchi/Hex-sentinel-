"""rating_compare.py - backtest OUR rating vs the full TradingView-rules rating."""
import sys

import rating_backtest as rb
from composite_rating import composite_rating
from tv_rating import tv_rating

BUCKETS = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]


def replay2(rows):
    out, idx = [], list(range(rb.WINDOW, len(rows) - rb.HORIZON, rb.STEP))
    for j, i in enumerate(idx):
        w = rows[i - rb.WINDOW + 1:i + 1]
        fwd = (rows[i + rb.HORIZON]["close"] / rows[i]["close"] - 1) * 100
        out.append((composite_rating(w)["rating"], tv_rating(w)["rating"], fwd, j < len(idx) // 2))
    return out


def report(name, pairs, base):
    print(f"\n=== {name} ===")
    for b in BUCKETS:
        v = [f for r, f, _ in pairs if r == b]
        if v:
            avg = sum(v) / len(v)
            print(f"{b:<12} n={len(v):<5} avg={avg:+.3f}%  up={100 * sum(x > 0 for x in v) / len(v):.1f}%  vs base {avg - base:+.3f}%")
        else:
            print(f"{b:<12} n=0")
    for half, lab in ((True, "1st half"), (False, "2nd half")):
        sub = [(r, f) for r, f, h in pairs if h == half]
        hb = sum(f for _, f in sub) / len(sub)
        side = lambda names: [f for r, f in sub if r in names]
        bu, se = side(("BUY", "STRONG BUY")), side(("SELL", "STRONG SELL"))
        bt = f"{sum(bu) / len(bu) - hb:+.3f}%" if bu else "n/a"
        st = f"{sum(se) / len(se) - hb:+.3f}%" if se else "n/a"
        print(f"  {lab}: buy-side vs base {bt} (n={len(bu)}) | sell-side vs base {st} (n={len(se)})")


def main(coins):
    rows_all = []
    for c in coins:
        try:
            rows = rb.fetch(c)
            res = replay2(rows)
            rows_all += res
            print(f"{c}: {len(rows)} candles, {len(res)} samples")
        except Exception as e:
            print(f"{c}: skipped ({e})")
    if not rows_all:
        return
    base = sum(x[2] for x in rows_all) / len(rows_all)
    print(f"\nbaseline 24h avg {base:+.3f}% over {len(rows_all)} samples")
    report("OUR rating (6 EMAs + 6 osc, deadband)", [(a, f, h) for a, _, f, h in rows_all], base)
    report("TRADINGVIEW rules (15 MAs + 11 osc)", [(b, f, h) for _, b, f, h in rows_all], base)
    print("\nGood = buy-side positive and sell-side negative in BOTH halves.")


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]] or rb.COINS)
