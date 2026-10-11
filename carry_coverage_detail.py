import os, time, sqlite3, calendar
from collections import Counter
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
KDB, FDB = os.path.join(HERE, "carry_klines.db"), os.path.join(HERE, "funding.db")
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
HOUR, DAYMS, SER = 3600000, 86400000, ("sp", "pp", "mk")
MK_CUT = calendar.timegm((2023, 10, 31, 0, 0, 0)) * 1000
MIN_MONTHS = 12


def d(ms): return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000))


def main():
    fc, kc = sqlite3.connect(FDB), sqlite3.connect(KDB)
    syms = [r[0] for r in fc.execute("SELECT DISTINCT sym FROM f ORDER BY sym")]
    holes = {t: Counter() for t in SER}
    mkstart = Counter()
    grid = {"before 2023-10-31": [0, 0, set()], "after": [0, 0, set()]}
    print(f"{C}{'coin':10s} {'missSp':>6s} {'missPp':>6s} {'missMk':>6s} {'lead':>5s} {'trail':>5s} {'mid':>4s}  {'first miss':16s} {'window start':16s} {'months':>6s}  RuleB{X}")
    okB, bad_coins = [], []
    for s in syms:
        recs = fc.execute("SELECT t, mark FROM f WHERE sym=? ORDER BY t", (s,)).fetchall()  # times and mark price only; no funding rate
        ts = np.array([r[0] for r in recs], dtype=np.int64)
        hrs = np.round(ts / HOUR).astype(np.int64) * HOUR
        pos = [i for i, r in enumerate(recs) if r[1] > 0]
        mkstart[d(int(ts[pos[0]]))[:10] if pos else "none"] += 1
        sets = {t: {r[0] for r in kc.execute(f"SELECT t FROM {t} WHERE sym=?", (s,))} for t in SER}
        for t in SER:
            a = sorted(sets[t])
            if a:
                for h in set(range(a[0], a[-1] + 1, HOUR)) - sets[t]:
                    holes[t][h] += 1
        miss = {t: sum(int(h) not in sets[t] for h in hrs) for t in SER}
        ok = np.array([all(int(h) in sets[t] for t in SER) for h in hrs])
        n = len(ok)
        bad = np.where(~ok)[0]
        pre = 0
        while pre < n and not ok[pre]: pre += 1
        post = 0
        while post < n - pre and not ok[n - 1 - post]: post += 1
        bad_in = [int(i) for i in bad if i < n - post]
        mid = len(bad_in) - pre
        L = max(bad_in) if bad_in else -1
        start, end = int(hrs[L + 1]), int(hrs[n - 1 - post])
        months = (end - start) / (30.44 * DAYMS)
        good = mid == 0 and months >= MIN_MONTHS
        (okB if good else bad_coins).append(s)
        col = G if not len(bad) else (Y if good else R)
        fm = d(int(hrs[bad[0]])) if len(bad) else "-"
        print(f"{col}{s:10s} {miss['sp']:6d} {miss['pp']:6d} {miss['mk']:6d} {pre:5d} {post:5d} {mid:4d}  {fm:16s} {d(start):16s} {months:6.1f}  {'ok' if good else 'NO'}{X}")
        dh = np.round(np.diff(ts) / HOUR).astype(int)
        for i in np.where(dh == 8)[0] + 1:
            g = grid["before 2023-10-31" if ts[i] < MK_CUT else "after"]
            g[0] += 1
            if (int(hrs[i]) // HOUR) % 8 != 0:
                g[1] += 1
                g[2].add(s)
    print(f"\n{C}== Rule B: eligible {len(okB)} of {len(syms)} =={X}")
    for s in bad_coins:
        print(f"{Y}  not eligible: {s}{X}")
    print(f"\n{C}== where the mark price first appears on funding records (date: coins) =={X}")
    print(dict(mkstart))
    print(f"\n{C}== 8h-spaced settlements on the 00:00/08:00/16:00 UTC grid (tests early records without mark price) =={X}")
    for k, (tot, off, cs) in grid.items():
        print(f"{k:20s} 8h-spaced records {tot:6d}   off-grid {off:5d}   coins {sorted(cs) if cs else '-'}")
    print(f"\n{C}== internal candle holes (hour: number of coins affected) =={X}")
    for t in SER:
        items = sorted(holes[t].items())
        print(f"{t}: " + (", ".join(f"{d(h)} x{c}" for h, c in items[:10]) + (" ..." if len(items) > 10 else "") if items else "none"))
    print(f"\n{D}Only timestamps, counts and the mark-price start date were read. No funding rate, basis, price level or return.{X}")


if __name__ == "__main__":
    main()
