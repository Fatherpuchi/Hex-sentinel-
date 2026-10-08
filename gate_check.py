"""gate_check.py - does Hex's gate (BLOCKED vs not) predict what price did next?
Usage (run from ~/binance-sentinel): python gate_check.py [SL_PCT TP_PCT]
"""
import glob
import os
import re
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from math import sqrt

import requests

G, R, Y, C, X, B = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m", "\033[1m"
HORIZONS = (1, 4, 8, 24)
DEDUPE_HOURS = 6
SL = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0   # Hex's STOP_LOSS_PERCENT = 2%
TP = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0   # assumed 2:1 take-profit
GROUPS = ("BLOCKED", "HOLD", "BUY", "SELL")


def load():
    rows = []
    for path in sorted(glob.glob("sentinel*.db")):
        if not re.fullmatch(r"sentinel(?:_\d+h)?\.db", os.path.basename(path)):
            continue
        conn = sqlite3.connect(path)
        try:
            rows += conn.execute("SELECT symbol, signal, price, created_at FROM paper_signals").fetchall()
        except sqlite3.OperationalError:
            pass
        conn.close()
    out, last = [], {}
    for sym, sig, price, ts in sorted(rows, key=lambda r: r[3]):
        t = datetime.fromisoformat(ts)
        if not price or sig not in GROUPS:
            continue
        if sym in last and (t - last[sym]) < timedelta(hours=DEDUPE_HOURS):
            continue
        last[sym] = t
        out.append((sym, sig, float(price), t))
    return out


def candles(symbol, t):
    """15m candles starting at the first boundary at/after t (up to 100)."""
    step = 15 * 60
    start = int(-(-t.timestamp() // step) * step * 1000)
    params = {"symbol": symbol, "interval": "15m", "startTime": start, "limit": 100}
    last = None
    for url in ("https://api.binance.com/api/v3/klines", "https://fapi.binance.com/fapi/v1/klines"):
        try:
            r = requests.get(url, params=params, timeout=12)
            r.raise_for_status()
            d = r.json()
            if d:
                return [(float(k[1]), float(k[2]), float(k[3])) for k in d]  # open, high, low
        except Exception as e:
            last = e
    if last:
        raise last
    return []


def measure(entry, cs):
    res = {}
    for h in HORIZONS:
        n = h * 4
        if len(cs) <= n:
            continue
        win = cs[:n]
        res[h] = {
            "ret": (cs[n][0] / entry - 1) * 100,
            "mfe": (max(c[1] for c in win) / entry - 1) * 100,
            "mae": (min(c[2] for c in win) / entry - 1) * 100,
        }
    if 24 in res:                       # stop/target race over 24h, long side
        out = None
        for _, hi, lo in cs[:96]:
            hit_sl, hit_tp = (lo / entry - 1) * 100 <= -SL, (hi / entry - 1) * 100 >= TP
            if hit_sl:                  # both in one candle -> assume stop first
                out = -SL
                break
            if hit_tp:
                out = TP
                break
        res["race"] = out if out is not None else res[24]["ret"]
        res["race_kind"] = "SL" if out == -SL else "TP" if out == TP else "neither"
    return res


def col(v):
    return G if v > 0 else R if v < 0 else Y


def main():
    dec = load()
    print(f"{C}{'=' * 64}\nGATE CHECK - what did price do after each Stage 1 decision?\n{'=' * 64}{X}")
    print(f"{len(dec)} decisions after de-duplicating same-coin runs within {DEDUPE_HOURS}h")
    print(f"Hypothetical long trade: stop-loss {SL}% / take-profit {TP}%  (24h race)\n")
    now = datetime.now(timezone.utc)
    data = []
    for i, (sym, sig, price, t) in enumerate(dec):
        if now - t < timedelta(hours=1, minutes=15):
            continue
        try:
            m = measure(price, candles(sym, t))
        except Exception:
            continue
        if m:
            data.append((sig, sym, t, m))
        time.sleep(0.15)
    print(f"measured {len(data)} of {len(dec)} decisions (others too recent or no candle data)\n")
    if not data:
        return

    by = {g: [d for d in data if d[0] == g] for g in GROUPS}
    open_ = [d for d in data if d[0] != "BLOCKED"]
    sets = [("BLOCKED", by["BLOCKED"]), ("NOT BLOCKED", open_)] + [(g, by[g]) for g in ("HOLD", "BUY", "SELL")]
    sets.append(("ALL (baseline)", data))

    for h in HORIZONS:
        print(f"{B}{C}+{h}h after decision (long-side){X}")
        for name, grp in sets:
            v = [d[3][h] for d in grp if h in d[3]]
            if not v:
                print(f"  {name:<15} n=0")
                continue
            r = [x["ret"] for x in v]
            mean, med = sum(r) / len(r), statistics.median(r)
            win = 100 * sum(x > 0 for x in r) / len(r)
            mfe = sum(x["mfe"] for x in v) / len(v)
            mae = sum(x["mae"] for x in v) / len(v)
            print(f"  {name:<15} n={len(r):<4} mean {col(mean)}{mean:+6.2f}%{X} median {col(med)}{med:+6.2f}%{X} "
                  f"win {win:4.0f}%  MFE {mfe:+5.2f}%  MAE {mae:+6.2f}%")
        print()

    print(f"{B}{C}Stop/target race over 24h (long, SL {SL}% / TP {TP}%){X}")
    for name, grp in sets:
        v = [d[3] for d in grp if "race" in d[3]]
        if not v:
            print(f"  {name:<15} n=0")
            continue
        kinds = [x["race_kind"] for x in v]
        exp = sum(x["race"] for x in v) / len(v)
        print(f"  {name:<15} n={len(v):<4} TP first {100 * kinds.count('TP') / len(v):3.0f}%  "
              f"SL first {100 * kinds.count('SL') / len(v):3.0f}%  neither {100 * kinds.count('neither') / len(v):3.0f}%  "
              f"avg {col(exp)}{exp:+.2f}%{X}")

    print(f"\n{B}{C}The key comparison: BLOCKED minus NOT BLOCKED, every horizon{X}")
    print("  (p = chance of a gap this big if the labels meant nothing; tested by shuffling labels)")
    import random

    def perm_p(x, y, stat, n=3000):
        obs, pool, cnt = abs(stat(x) - stat(y)), x + y, 0
        for _ in range(n):
            random.shuffle(pool)
            if abs(stat(pool[:len(x)]) - stat(pool[len(x):])) >= obs:
                cnt += 1
        return (cnt + 1) / (n + 1)

    mean = lambda v: sum(v) / len(v)
    verdicts = []
    for h in HORIZONS:
        a = [d[3][h]["ret"] for d in by["BLOCKED"] if h in d[3]]
        b = [d[3][h]["ret"] for d in open_ if h in d[3]]
        if len(a) < 5 or len(b) < 5:
            print(f"  +{h:<2}h  not enough decisions yet")
            continue
        dm, dmed = mean(a) - mean(b), statistics.median(a) - statistics.median(b)
        pm, pmed = perm_p(a, b, mean), perm_p(a, b, statistics.median)
        solid = pm < 0.05 and pmed < 0.05 and dm * dmed > 0
        verdicts.append((h, solid, dm))
        tag = (f"{G if dm > 0 else R}consistent gap{X}" if solid else f"{Y}not solid{X}")
        print(f"  +{h:<2}h  mean gap {col(dm)}{dm:+6.2f}%{X} (p={pm:.2f})   median gap {col(dmed)}{dmed:+6.2f}%{X} (p={pmed:.2f})   {tag}   n={len(a)}/{len(b)}")
    solid_h = [h for h, ok, _ in verdicts if ok]
    if not solid_h:
        print(f"  => no horizon shows a gap on BOTH mean and median: no demonstrated difference")
    else:
        signs = {dm > 0 for h, ok, dm in verdicts if ok}
        print(f"  => solid gap at +{solid_h}h; direction {'consistent' if len(signs) == 1 else 'MIXED'} across them")
    print(f"\n{Y}Notes: decisions from one batch share the same market moment, so the real sample is smaller than n.")
    print(f"BLOCKED/HOLD have no direction, so they're measured as if long. BUY/SELL lines are NOT direction-adjusted;")
    print(f"for SELL read a negative return as a correct call.{X}")


if __name__ == "__main__":
    main()
