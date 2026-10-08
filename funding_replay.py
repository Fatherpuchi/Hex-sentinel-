"""funding_replay.py - do unusual funding rates predict the next 1h/4h/8h/24h?
Usage: python funding_replay.py [COIN ...]
"""
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

G, R, Y, C, X, B = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m", "\033[1m"
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "NEARUSDT"]
DAYS, WINDOW, HORIZONS = 400, 270, (1, 4, 8, 24)
BUCKETS = ["<5", "5-25", "25-75", "75-95", ">95"]
HOUR = 3600000


def get(url, params):
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5)


def fetch_funding(sym, start):
    out, now = [], int(time.time() * 1000)
    while start < now:
        d = get("https://fapi.binance.com/fapi/v1/fundingRate",
                {"symbol": sym, "startTime": start, "limit": 1000})
        if not d:
            break
        out += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in d]
        start = int(d[-1]["fundingTime"]) + 1
        time.sleep(0.2)
        if len(d) < 1000:
            break
    return out


def fetch_prices(sym, start):
    out, now = {}, int(time.time() * 1000)
    while start < now:
        d = get("https://fapi.binance.com/fapi/v1/klines",
                {"symbol": sym, "interval": "1h", "startTime": start, "limit": 1500})
        if not d:
            break
        for k in d:
            out[int(k[0])] = float(k[1])          # hour open time -> open price
        start = int(d[-1][0]) + HOUR
        time.sleep(0.2)
        if len(d) < 1500:
            break
    return out


def build_events(sym, funding, prices):
    ev = []
    vals = [r for _, r in funding]
    for i in range(WINDOW, len(funding)):
        t, rate = funding[i]
        prev = np.array(vals[i - WINDOW:i])
        pct = ((prev < rate).sum() + 0.5 * (prev == rate).sum()) / WINDOW
        b = 0 if pct < .05 else 1 if pct < .25 else 2 if pct < .75 else 3 if pct < .95 else 4
        t0 = t - t % HOUR
        if t0 not in prices:
            continue
        rets = {}
        for h in HORIZONS:
            p1 = prices.get(t0 + h * HOUR)
            if p1:
                rets[h] = (p1 / prices[t0] - 1) * 100
        if rets:
            ev.append({"coin": sym, "t": t, "rate": rate * 100, "b": b, "rets": rets})
    return ev


def perm_p(a, b, stat, rng, n=2000):
    obs = abs(stat(a) - stat(b))
    pool, k, cnt = np.concatenate([a, b]), len(a), 0
    for _ in range(n):
        p = rng.permutation(pool)
        if abs(stat(p[:k]) - stat(p[k:])) >= obs:
            cnt += 1
    return (cnt + 1) / (n + 1)


def col(v):
    return G if v > 0 else R if v < 0 else Y


def report(ev):
    rng = np.random.default_rng(0)
    tmed = np.median([e["t"] for e in ev])
    coins = sorted({e["coin"] for e in ev})
    print(f"{C}{'=' * 66}\nFUNDING REPLAY - {len(ev)} settlements, {len(coins)} coins\n{'=' * 66}{X}")
    print("Bucket = how high this funding rate is vs the coin's previous ~90 days.\n")
    for h in HORIZONS:
        rows = [e for e in ev if h in e["rets"]]
        base = np.mean([e["rets"][h] for e in rows])
        print(f"{B}{C}+{h}h forward return   (baseline mean {base:+.3f}%){X}")
        for bi, name in enumerate(BUCKETS):
            v = [e for e in rows if e["b"] == bi]
            if not v:
                print(f"  {name:>6}  n=0")
                continue
            r = np.array([e["rets"][h] for e in v])
            print(f"  {name:>6}  n={len(r):<5} avg funding {np.mean([e['rate'] for e in v]):+.4f}%  "
                  f"mean {col(r.mean())}{r.mean():+6.2f}%{X}  median {col(np.median(r))}{np.median(r):+6.2f}%{X}  "
                  f"up {100 * (r > 0).mean():3.0f}%  vs base {col(r.mean() - base)}{r.mean() - base:+.2f}%{X}")
        print()

    print(f"{B}{C}Do the EXTREMES differ from everything else? (shuffle test + stability){X}")
    print("  solid = mean AND median gaps agree, both p<0.05, same sign in both halves, and in most coins")
    print(f"  {Y}24h windows overlap (3 settlements per day), so its p-values are too optimistic.{X}\n")
    any_solid = False
    for bi, name in ((0, "<5 (most negative)"), (4, ">95 (most positive)")):
        for h in HORIZONS:
            rows = [e for e in ev if h in e["rets"]]
            a = np.array([e["rets"][h] for e in rows if e["b"] == bi])
            b = np.array([e["rets"][h] for e in rows if e["b"] != bi])
            if len(a) < 20:
                continue
            dm, dmed = a.mean() - b.mean(), np.median(a) - np.median(b)
            pm, pmed = perm_p(a, b, np.mean, rng), perm_p(a, b, np.median, rng)
            halves = []
            for first in (True, False):
                aa = [e["rets"][h] for e in rows if e["b"] == bi and (e["t"] < tmed) == first]
                bb = [e["rets"][h] for e in rows if e["b"] != bi and (e["t"] < tmed) == first]
                halves.append(np.mean(aa) - np.mean(bb) if len(aa) >= 5 else 0.0)
            agree = 0
            for c in coins:
                aa = [e["rets"][h] for e in rows if e["coin"] == c and e["b"] == bi]
                bb = [e["rets"][h] for e in rows if e["coin"] == c and e["b"] != bi]
                if len(aa) >= 5 and np.sign(np.mean(aa) - np.mean(bb)) == np.sign(dm):
                    agree += 1
            same_half = np.sign(halves[0]) == np.sign(halves[1]) == np.sign(dm)
            solid = pm < .05 and pmed < .05 and dm * dmed > 0 and same_half and agree >= max(3, int(0.67 * len(coins)))
            any_solid |= solid
            tag = f"{G if dm > 0 else R}SOLID{X}" if solid else f"{Y}not solid{X}"
            print(f"  {name:<19} +{h:<2}h mean gap {col(dm)}{dm:+6.2f}%{X} (p={pm:.2f}) median gap {col(dmed)}{dmed:+6.2f}%{X} "
                  f"(p={pmed:.2f}) halves {halves[0]:+.2f}/{halves[1]:+.2f}  coins {agree}/{len(coins)}  n={len(a)}  {tag}")
    print()
    if any_solid:
        print(f"{G}At least one extreme passed every check. Next step: test it on coins/months NOT used here before believing it.{X}")
    else:
        print(f"{Y}No extreme funding bucket passed every check: no demonstrated predictive value at these horizons.{X}")


def main(coins):
    start = int((datetime.now(timezone.utc) - timedelta(days=DAYS)).timestamp() * 1000)
    ev = []
    for c in coins:
        try:
            f, p = fetch_funding(c, start), fetch_prices(c, start)
            e = build_events(c, f, p)
            ev += e
            print(f"{c}: {len(f)} funding settlements, {len(p)} hourly candles, {len(e)} usable events")
        except Exception as ex:
            print(f"{c}: skipped ({ex})")
    if len(ev) < 200:
        print("Not enough data to analyse.")
        return
    print()
    report(ev)


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]] or COINS)
