import os, sys, math, sqlite3
import numpy as np
import lab_engine as E
from lab_stats import exact_p, opp_composite

HERE = os.path.dirname(os.path.abspath(__file__))
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
HOUR, DAY = 3600000, 86400000
VIS, AHEAD, LOOK, K = 100, 24, 24, 1.5            # FROZEN: the pre-registered rule
COSTS, PRIMARY = (0.0010, 0.0020, 0.0030), 0.0020  # round-trip fees + slippage
NAMES = ["fade24", "momentum", "always_up", "always_down", "ema_rsi", "composite", "random"]


def seen_windows():
    out, tmax = {}, 0
    p = os.path.join(HERE, "lab.db")
    if os.path.exists(p):
        lc = sqlite3.connect(p)
        for s, t in lc.execute("SELECT symbol,start_time FROM rounds"):
            out.setdefault(s, []).append(t)
        tmax = lc.execute("SELECT MAX(open_time) FROM candles").fetchone()[0] or 0
    return out, tmax


def events_for(sym, a, seen):
    t, o, h, l, c, v = a.T
    n = len(t)
    if n < VIS + AHEAD + 1:
        return []
    lr = np.diff(np.log(c))
    cs = np.concatenate([[0.0], np.cumsum(lr)])
    cs2 = np.concatenate([[0.0], np.cumsum(lr * lr)])
    m, out, i = VIS - 1, [], VIS - 1
    while i + AHEAD < n:
        if t[i + AHEAD] - t[i - VIS + 1] != (VIS + AHEAD - 1) * HOUR:
            i += 1
            continue
        S, S2 = cs[i] - cs[i - m], cs2[i] - cs2[i - m]
        var = (S2 - S * S / m) / (m - 1)
        if var <= 0:
            i += 1
            continue
        sd = math.sqrt(var)
        z = math.log(c[i] / c[i - LOOK]) / (sd * math.sqrt(LOOK))
        if abs(z) < K:
            i += 1
            continue
        ev_s, ev_e = t[i - VIS + 1], t[i + AHEAD] + HOUR
        if any(ev_s < s + (VIS + AHEAD) * HOUR and ev_e > s for s in seen.get(sym, [])):
            i += 1
            continue
        ret = math.log(c[i + AHEAD] / c[i])
        thr = E.FLAT_K * sd * math.sqrt(AHEAD)
        flat = ret == 0 or abs(ret) < thr
        rows = [tuple(r) for r in a[i - VIS + 1:i + 1]]
        view = E.make_view(f"{sym}_{int(t[i])}", rows)
        fade = "DOWN" if z > 0 else "UP"
        d = {"fade24": fade, "momentum": "UP" if fade == "DOWN" else "DOWN", "always_up": "UP", "always_down": "DOWN",
             "ema_rsi": E.opp_ema_rsi(view)[0], "composite": opp_composite(view)[0], "random": E.opp_random(view)[0]}
        out.append(dict(sym=sym, t=float(t[i]), day=int(t[i] // DAY), d=d, flat=flat,
                        out="UP" if ret > 0 else "DOWN", gross=float(c[i + AHEAD] / o[i + 1] - 1)))
        i += AHEAD
    return out


def trimmed(x, p=0.1):
    x = np.sort(x)
    k = int(len(x) * p)
    return float(x[k:len(x) - k].mean()) if len(x) > 2 * k else float(x.mean())


def cluster_ci(vals, days, B=2000):
    ud, inv = np.unique(days, return_inverse=True)
    s, n = np.bincount(inv, weights=vals), np.bincount(inv)
    idx = np.random.default_rng(1).integers(0, len(ud), (B, len(ud)))
    mm = s[idx].sum(1) / n[idx].sum(1)
    return float(np.percentile(mm, 2.5)), float(np.percentile(mm, 97.5))


def net_of(evs, name, cost):
    sg = np.array([1.0 if e["d"][name] == "UP" else -1.0 for e in evs])
    return sg * np.array([e["gross"] for e in evs]) - cost


def acc_of(evs, name):
    sc = [e for e in evs if not e["flat"]]
    return np.array([1.0 if e["d"][name] == e["out"] else 0.0 for e in sc]), sc


def main():
    db = os.path.join(HERE, "fade.db")
    if not os.path.exists(db):
        raise SystemExit("run fade_data.py first")
    conn = sqlite3.connect(db)
    seen, tmax = seen_windows()
    evs = []
    for (sym,) in conn.execute("SELECT DISTINCT sym FROM k ORDER BY sym").fetchall():
        a = np.array(conn.execute("SELECT t,o,h,l,c,v FROM k WHERE sym=? ORDER BY t", (sym,)).fetchall(), dtype=float)
        evs += events_for(sym, a, seen)
    if not evs:
        raise SystemExit("no events found")
    evs.sort(key=lambda e: e["t"])
    days = np.array([e["day"] for e in evs])
    scored = [e for e in evs if not e["flat"]]
    coins = {e["sym"] for e in scored}
    print(f"{C}fade24 trigger found {len(evs)} unseen, non-overlapping events ({len(scored)} scored, "
          f"{len(evs) - len(scored)} FLAT) on {len(coins)} coins over {len(set(days))} days{X}")
    print(f"{D}Same events for every strategy. Costs: round trip {', '.join('%.2f%%' % (c * 100) for c in COSTS)}; "
          f"headline {PRIMARY * 100:.2f}%. Events on one day are correlated: the net-return interval resamples days.{X}\n")
    up_c, up_sc = acc_of(evs, "always_up")
    print(f"{C}{'strategy':12s} {'n':>5s} {'acc':>6s} {'95% int':>9s} {'vs up':>7s} {'p(pair)':>8s} "
          f"{'net%@.10':>9s} {'@.20':>7s} {'@.30':>7s} {'median':>7s} {'trim':>7s} {'PF':>5s} {'win%':>5s}{X}")
    for nm in NAMES:
        ac, sc = acc_of(evs, nm)
        lo, hi = E.wilson(int(ac.sum()), len(ac))
        w = int(((ac == 1) & (up_c == 0)).sum())
        lz = int(((ac == 0) & (up_c == 1)).sum())
        nets = [net_of(evs, nm, c) for c in COSTS]
        n2 = nets[1]
        pf = n2[n2 > 0].sum() / max(1e-12, -n2[n2 < 0].sum())
        print(f"{nm:12s} {len(ac):5d} {ac.mean() * 100:5.1f}% {lo * 100:3.0f}-{hi * 100:3.0f}% "
              f"{(ac.mean() - up_c.mean()) * 100:+6.1f} {exact_p(w, lz):8.3f} "
              f"{nets[0].mean() * 100:+8.3f} {n2.mean() * 100:+7.3f} {nets[2].mean() * 100:+7.3f} "
              f"{np.median(n2) * 100:+7.3f} {trimmed(n2) * 100:+7.3f} {pf:5.2f} {(n2 > 0).mean() * 100:4.0f}")
    # ---- fade24 verdict
    ac, sc = acc_of(evs, "fade24")
    sgn = np.where(ac == 1, 1, 0)
    dirs = np.array([1 if e["d"]["fade24"] == "UP" else -1 for e in sc])
    outs = np.array([1 if e["out"] == "UP" else -1 for e in sc])
    rng, obs, hit = np.random.default_rng(2), (dirs == outs).mean(), 0
    for _ in range(2000):
        hit += (dirs == rng.permutation(outs)).mean() >= obs
    p_shuf = (hit + 1) / 2001
    w = int(((ac == 1) & (up_c == 0)).sum())
    lz = int(((ac == 0) & (up_c == 1)).sum())
    p_pair = exact_p(w, lz)
    net = net_of(evs, "fade24", PRIMARY)
    ci = cluster_ci(net, days)
    half = len(evs) // 2
    h1, h2 = net[:half].mean(), net[half:].mean()
    per = {}
    for e, x in zip(evs, net):
        per.setdefault(e["sym"], []).append(x)
    big = {s: np.mean(v) for s, v in per.items() if len(v) >= 10}
    share = (sum(1 for v in big.values() if v > 0) / len(big)) if big else 0.0
    crit = [
        ("size: >=300 scored, >=15 coins, >=100 days", len(sc) >= 300 and len(coins) >= 15 and len(set(days)) >= 100,
         f"{len(sc)} / {len(coins)} / {len(set(days))}"),
        ("beats always_up on same events, paired p<0.01", p_pair < 0.01 and ac.mean() > up_c.mean(), f"p={p_pair:.4f}"),
        ("shuffle test p<0.01", p_shuf < 0.01, f"p={p_shuf:.4f}"),
        ("day-cluster 95% CI of net return excludes 0", ci[0] > 0, f"[{ci[0] * 100:+.3f}%, {ci[1] * 100:+.3f}%]"),
        ("trimmed-mean net return > 0", trimmed(net) > 0, f"{trimmed(net) * 100:+.3f}%"),
        ("both halves of the period net > 0", h1 > 0 and h2 > 0, f"{h1 * 100:+.3f}% / {h2 * 100:+.3f}%"),
        (">=55% of coins (10+ events) net > 0", share >= 0.55, f"{share * 100:.0f}% of {len(big)} coins"),
    ]
    print(f"\n{C}== fade24 verdict against the bar fixed in advance (net at {PRIMARY * 100:.2f}% cost) =={X}")
    for name, ok, d in crit:
        print(f"{(G + 'PASS ') if ok else (R + 'FAIL ')}{name}  {d}{X}")
    allok = all(ok for _, ok, _ in crit)
    print((G + "ALL CRITERIA MET: a candidate only. Next: forward-test on newly collected data, parameters unchanged."
           if allok else R + "NOT MET: fade24 is dropped. Parameters are not to be changed and re-run.") + X)
    rec = [e for e in evs if e["t"] >= tmax - 30 * DAY] if tmax else []
    if rec:
        r = np.array([net_of([e], "fade24", PRIMARY)[0] for e in rec])
        print(f"{D}newest block (inside the Lab's excluded last 30 days): {len(rec)} events, mean net {r.mean() * 100:+.3f}%{X}")
    print(f"{D}The paired and shuffle tests treat events as independent, which is optimistic. "
          f"Only the day-cluster interval accounts for coins moving together.{X}")


if __name__ == "__main__":
    main()
