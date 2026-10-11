import math
import numpy as np
import fade_study as fs

G, R, C, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[2m", "\033[0m"
HOUR = 3600000
T0 = (1_600_000_000_000 // HOUR) * HOUR
RES = []
fs.opp_composite = lambda v: ("UP", 50)      # heavy opponents are irrelevant here
fs.E.opp_ema_rsi = lambda v: ("UP", 50)


def check(name, ok, detail=""):
    RES.append(bool(ok))
    print((G + "PASS " if ok else R + "FAIL ") + name + X + (f"  {D}{detail}{X}" if detail else ""))


def coin(rng, common, idio=0.008, plant=0.0):
    """Synthetic coin. plant>0 plants 24h mean reversion, plant<0 plants momentum, 0 = no edge."""
    n = len(common)
    noise = rng.normal(0, idio, n)
    if plant == 0.0:
        r = common + noise
    else:
        r = np.zeros(n)
        for k in range(n):
            r[k] = common[k] + noise[k] - plant * r[max(0, k - 24):k].sum()
    c = 100 * np.exp(np.cumsum(r))
    o = np.concatenate([[100.0], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    return np.column_stack([T0 + np.arange(n) * HOUR, o, h, l, c, rng.uniform(50, 150, n)])


def world(seed, plant=0.0, ncoins=20, n=8000):
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 0.006, n)             # shared market factor: coins move together
    evs = []
    for k in range(ncoins):
        evs += fs.events_for(f"S{k:02d}", coin(rng, common, plant=plant), {})
    evs.sort(key=lambda e: e["t"])
    return evs


def stats(evs):
    days = np.array([e["day"] for e in evs])
    net = fs.net_of(evs, "fade24", 0.0)
    n = len(net)
    t = net.mean() / (net.std(ddof=1) / math.sqrt(n))
    dlo, dhi = fs.cluster_ci(net, days)
    wlo, whi = fs.cluster_ci(net, days // 7)
    ac, sc = fs.acc_of(evs, "fade24")
    up, _ = fs.acc_of(evs, "always_up")
    p_pair = fs.exact_p(int(((ac == 1) & (up == 0)).sum()), int(((ac == 0) & (up == 1)).sum()))
    dirs = np.array([1 if e["d"]["fade24"] == "UP" else -1 for e in sc])
    outs = np.array([1 if e["out"] == "UP" else -1 for e in sc])
    rng, obs = np.random.default_rng(5), (dirs == outs).mean()
    hit = sum((dirs == rng.permutation(outs)).mean() >= obs for _ in range(400))
    return dict(mean=net.mean(), naive=abs(t) > 1.96, day=(dlo > 0 or dhi < 0),
                week=(wlo > 0 or whi < 0), pair=p_pair < 0.05, shuf=(hit + 1) / 401 < 0.05)


def main():
    print(f"{C}-- 1. cost and sign arithmetic{X}")
    ev = lambda d, g: {"d": {"x": d}, "gross": g}
    f = lambda d, g: fs.net_of([ev(d, g)], "x", 0.002)[0]
    check("long, price +2%: net +1.8%", abs(f("UP", .02) - .018) < 1e-12)
    check("short, price -2%: net +1.8%", abs(f("DOWN", -.02) - .018) < 1e-12)
    check("long, price -2%: net -2.2%", abs(f("UP", -.02) + .022) < 1e-12)
    check("short, price +2%: net -2.2%", abs(f("DOWN", .02) + .022) < 1e-12)

    print(f"{C}-- 2. entry, exit, hold, trigger recomputed independently{X}")
    a = coin(np.random.default_rng(3), np.random.default_rng(4).normal(0, 0.006, 8000))
    evs = fs.events_for("T", a, {})
    idx = {int(x): k for k, x in enumerate(a[:, 0])}
    ok = dict(entry=True, hold=True, gross=True, trig=True, label=True)
    for e in evs:
        i = idx[int(e["t"])]
        ok["entry"] &= a[i + 1, 0] == a[i, 0] + HOUR
        ok["hold"] &= (a[i + 24, 0] + HOUR) - a[i + 1, 0] == 24 * HOUR
        ok["gross"] &= abs(e["gross"] - (a[i + 24, 4] / a[i + 1, 1] - 1)) < 1e-12
        sd = np.diff(np.log(a[i - 99:i + 1, 4])).std(ddof=1)
        z = math.log(a[i, 4] / a[i - 24, 4]) / (sd * math.sqrt(24))
        ok["trig"] &= abs(z) >= 1.5 and (e["d"]["fade24"] == "DOWN") == (z > 0)
        ok["label"] &= e["out"] == ("UP" if a[i + 24, 4] > a[i, 4] else "DOWN")
    check(f"{len(evs)} events: entry = open right after the decision candle", ok["entry"])
    check("hold is exactly 24 hours", ok["hold"])
    check("gross return = close[i+24] / open[i+1] - 1", ok["gross"])
    check("trigger and direction match an independent recomputation (fast code = slow code)", ok["trig"])
    check("outcome label matches the price path", ok["label"])
    check("events on one coin never overlap", all(b["t"] - x["t"] >= 24 * HOUR for x, b in zip(evs, evs[1:])))

    print(f"{C}-- 3. no dependence on the future{X}")
    cut = fs.events_for("T", a[:6000], {})
    lim = a[5975, 0]
    check("events identical when everything after the cut is deleted",
          [(e["t"], e["d"]["fade24"]) for e in evs if e["t"] <= lim] == [(e["t"], e["d"]["fade24"]) for e in cut])

    print(f"{C}-- 4. worlds with NO edge and correlated coins (24 runs, takes a minute){X}")
    REPS = 24
    rows = [stats(world(100 + s)) for s in range(REPS)]
    m = np.array([r["mean"] for r in rows])
    z = m.mean() / (m.std(ddof=1) / math.sqrt(REPS))
    check("mean gross return per trade is about 0 when there is no edge", abs(z) < 3,
          f"mean {m.mean() * 100:+.4f}%, z={z:+.2f}")
    print(f"{D}false positives at a nominal 5% (valid test: about {REPS * 0.05:.1f} of {REPS}){X}")
    for key, lab in (("naive", "naive t-test, events independent"), ("day", "day-cluster interval"),
                     ("week", "week-cluster interval"), ("pair", "paired exact test vs always_up"),
                     ("shuf", "shuffle test")):
        print(f"   {lab:36s} {sum(r[key] for r in rows):2d} of {REPS}")
    check("week-cluster interval is not anti-conservative (<=4 of 24)", sum(r["week"] for r in rows) <= 4)

    print(f"{C}-- 5. planted effects must be found{X}")
    for plant, want, nm in ((0.01, 1, "planted mean reversion: fade earns"), (-0.01, -1, "planted momentum: fade loses")):
        e2 = world(7, plant=plant)
        net = fs.net_of(e2, "fade24", 0.0)
        lo, hi = fs.cluster_ci(net, np.array([e["day"] for e in e2]) // 7)
        check(nm, (lo > 0) if want == 1 else (hi < 0), f"mean {net.mean() * 100:+.3f}% [{lo * 100:+.3f}, {hi * 100:+.3f}]")

    bad = RES.count(False)
    print((G + f"ALL {len(RES)} AUDIT CHECKS PASSED" if not bad else R + f"{bad} OF {len(RES)} AUDIT CHECKS FAILED") + X)
    print(f"{D}Logic only, on synthetic data. NOT audited: survivorship bias, real slippage, funding, bad candles in fade.db.{X}")


if __name__ == "__main__":
    main()
