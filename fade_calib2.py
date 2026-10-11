import sys, time, math, json
import numpy as np

G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"

# ---------------- FROZEN before running ----------------
N, DAYS = 40, 1095
H = DAYS * 24
LIQ_KEEP = 30                       # coins 30..39 = the "10 least liquid"
COST = 0.002
VR_MIN, AGREE_MIN, MIN_VALID = 1.25, 0.60, 30
QLO = 0.001667                      # 99.667% two-sided (Bonferroni 1%/3)
WORLDS, SEEDS, B_FULL = 986, (1, 2), 10000
POWER_WORLDS, POWER_DELTA, POWER_SEED = 100, 0.004, 3
LIM_TWO99 = (8, 14)                 # (per seed, pooled)
LIM_ONE99 = (6, 9)
LIM_TWO95 = 65
VARIANTS = ["raw", "market-adjusted", "raw ex-10 illiquid", "adjusted ex-10 illiquid"]
# -------------------------------------------------------


def ar1(rng, n, phi, sd):
    e = rng.standard_normal((DAYS, n)) * sd * math.sqrt(1 - phi * phi)
    x = np.empty((DAYS, n))
    x[0] = rng.standard_normal(n) * sd
    for t in range(1, DAYS):
        x[t] = phi * x[t - 1] + e[t]
    return x


def make_world(rng):
    cv = ar1(rng, 1, 0.95, 0.25)[:, 0]
    iv = ar1(rng, N, 0.90, 0.30)
    F = rng.standard_normal(H) * np.repeat(0.003 * np.exp(cv), 24)
    beta = rng.uniform(0.6, 1.4, N)
    sig = rng.uniform(0.003, 0.007, N)
    idv = np.repeat(sig[None, :] * np.exp(iv), 24, axis=0).T
    return beta[:, None] * F[None, :] + idv * rng.standard_normal((N, H))


def features(r):
    z = np.zeros((N, 1))
    cs = np.concatenate([z, np.cumsum(r, axis=1)], axis=1)
    c2 = np.concatenate([z, np.cumsum(r * r, axis=1)], axis=1)
    d = np.arange(30, DAYS - 1)
    i = 24 * d - 1

    def sd(w):
        S = cs[:, i + 1] - cs[:, i + 1 - w]
        S2 = c2[:, i + 1] - c2[:, i + 1 - w]
        return np.sqrt(np.maximum((S2 - S * S / w) / (w - 1), 0))

    ret24 = (cs[:, i + 1] - cs[:, i + 1 - 24]).T
    vr = (sd(24) / sd(720)).T
    gross = (np.exp(cs[:, i + 25] - cs[:, i + 1]) - 1).T
    return d, ret24, vr, gross


def trades(ret24, vr, gross):
    sign = np.sign(ret24)
    valid = sign != 0
    nvalid = valid.sum(1)
    same = np.where(sign > 0, (sign > 0).sum(1)[:, None], (sign < 0).sum(1)[:, None])
    agree = same / np.maximum(nvalid, 1)[:, None]
    m2 = valid & (vr >= VR_MIN)
    m3 = m2 & (agree >= AGREE_MIN) & (nvalid >= MIN_VALID)[:, None]
    bench = gross.mean(1)
    net = sign * gross - COST
    adj = net - sign * bench[:, None]
    return sign, agree, m2, m3, net, adj


def selfcheck():
    rng = np.random.default_rng(0)
    r = make_world(rng)
    d, ret24, vr, gross = features(r)
    sign, agree, m2, m3, net, adj = trades(ret24, vr, gross)
    ok = bool((m3 <= m2).all())
    pick = np.random.default_rng(9)
    for _ in range(150):
        k, c = int(pick.integers(len(d))), int(pick.integers(N))
        i = 24 * int(d[k]) - 1
        w24, w720 = r[c, i - 23:i + 1], r[c, i - 719:i + 1]
        v = w24.std(ddof=1) / w720.std(ddof=1)
        rets = r[:, i - 23:i + 1].sum(1)
        s = np.sign(rets)
        nv = int((s != 0).sum())
        ag = int((s == s[c]).sum()) / max(nv, 1)
        g = math.exp(r[c, i + 1:i + 25].sum()) - 1
        ok &= abs(v - vr[k, c]) < 1e-9 and abs(g - gross[k, c]) < 1e-9
        ok &= abs(rets[c] - ret24[k, c]) < 1e-9 and abs(ag - agree[k, c]) < 1e-9
    print((G + "selfcheck PASS" if ok else R + "selfcheck FAIL") + X +
          f"{D}  fast code = slow code on 150 random decisions; rung-3 trades are a subset of rung-2{X}")
    return ok


def run_world(rng, B, delta=0.0):
    r = make_world(rng)
    d, ret24, vr, gross = features(r)
    sign, agree, m2, m3, net, adj = trades(ret24, vr, gross)
    blk = np.broadcast_to(((d - 30) // 7)[:, None], net.shape).ravel()
    nb = int(blk.max()) + 1
    liq = np.broadcast_to(np.arange(N)[None, :] < LIQ_KEEP, net.shape)
    cols = []
    for val, lm in ((net, None), (adj, None), (net, liq), (adj, liq)):
        a2 = m2 if lm is None else (m2 & lm)
        a3 = m3 if lm is None else (m3 & lm)
        for w in (np.where(a2, val, 0.0), a2.astype(float), np.where(a3, val + delta, 0.0), a3.astype(float)):
            cols.append(np.bincount(blk, weights=w.ravel(), minlength=nb))
    M = np.stack(cols, axis=1)
    W = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=B).astype(float)
    Rm = W @ M
    qs = []
    with np.errstate(all="ignore"):
        for v in range(4):
            dd = Rm[:, 4 * v + 2] / Rm[:, 4 * v + 3] - Rm[:, 4 * v] / Rm[:, 4 * v + 1]
            dd = dd[np.isfinite(dd)]
            qs.append(np.quantile(dd, [QLO, 1 - QLO, 0.025, 0.975]))
    return np.array(qs), int(m2.sum()), int(m3.sum())


def batch(seed, n, B, delta=0.0, label=""):
    t0 = time.time()
    two99, one99, two95, comb, n2s, n3s = [], [], [], [], [], []
    for w in range(n):
        q, n2, n3 = run_world(np.random.default_rng([seed, w]), B, delta)
        two99.append((q[:, 0] > 0) | (q[:, 1] < 0))
        one99.append(q[:, 0] > 0)
        two95.append((q[:, 2] > 0) | (q[:, 3] < 0))
        comb.append(bool((q[:, 0] > 0).all()))
        n2s.append(n2)
        n3s.append(n3)
        if (w + 1) % max(1, n // 10) == 0:
            el = time.time() - t0
            print(f"{D}{label} {w + 1}/{n} worlds  {el / 60:.1f} min elapsed, ~{el / (w + 1) * (n - w - 1) / 60:.1f} min left{X}", flush=True)
    return dict(two99=np.array(two99), one99=np.array(one99), two95=np.array(two95),
                comb=np.array(comb), n2=np.array(n2s), n3=np.array(n3s))


def lg(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def cdf(k, n, p):
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(1.0, sum(math.exp(lg(n, i) + i * lp + (n - i) * lq) for i in range(k + 1)))


def cp(k, n, a=0.05):
    lo = hi = None
    if k == 0:
        lo = 0.0
    else:
        x, y = 0.0, 1.0
        for _ in range(50):
            m = (x + y) / 2
            x, y = (m, y) if 1 - cdf(k - 1, n, m) < a / 2 else (x, m)
        lo = (x + y) / 2
    if k >= n:
        hi = 1.0
    else:
        x, y = 0.0, 1.0
        for _ in range(50):
            m = (x + y) / 2
            x, y = (m, y) if cdf(k, n, m) > a / 2 else (x, m)
        hi = (x + y) / 2
    return lo, hi


def line(name, k, n, nominal, lim):
    lo, hi = cp(k, n)
    ok = k <= lim
    print(f"{(G + 'PASS ') if ok else (R + 'FAIL ')}{name:26s} {k:3d}/{n}  {k / n * 100:5.2f}%  "
          f"95% CI [{lo * 100:.2f}, {hi * 100:.2f}]%  nominal {nominal * 100:.3f}%  limit <= {lim}{X}")
    return ok


def main(mode):
    if not selfcheck():
        raise SystemExit(R + "slow and fast code disagree: stop and fix before calibrating" + X)
    if mode == "quick":
        t0 = time.time()
        res = batch(1, 30, 2000, label="quick")
        print(f"{C}30 worlds in {(time.time() - t0) / 60:.1f} min -> full run (1,972 null + {POWER_WORLDS} power worlds, B=10000) "
              f"takes roughly {(time.time() - t0) / 30 * 2072 * 3.5 / 3600:.1f} h if bootstrap cost scales; read the ETA lines of the full run{X}")
        print(f"{D}mean trades per world: rung 2 = {res['n2'].mean():.0f}, rung 3 = {res['n3'].mean():.0f}; "
              f"false positives in these 30 (two-sided 99.667%, per variant): {res['two99'].sum(0).tolist()}{X}")
        return
    runs = {s: batch(s, WORLDS, B_FULL, label=f"seed {s}") for s in SEEDS}
    allok = True
    print(f"\n{C}== false positives in no-edge worlds; rung 3 minus rung 2 =={X}")
    for v, nm in enumerate(VARIANTS):
        print(f"{C}-- {nm}{X}")
        t = [int(runs[s]["two99"][:, v].sum()) for s in SEEDS]
        o = [int(runs[s]["one99"][:, v].sum()) for s in SEEDS]
        f = [int(runs[s]["two95"][:, v].sum()) for s in SEEDS]
        for j, s in enumerate(SEEDS):
            allok &= line(f"seed {s} two-sided 99.667%", t[j], WORLDS, 0.00333, LIM_TWO99[0])
        allok &= line("pooled two-sided 99.667%", sum(t), WORLDS * 2, 0.00333, LIM_TWO99[1])
        for j, s in enumerate(SEEDS):
            allok &= line(f"seed {s} one-sided lower>0", o[j], WORLDS, 0.00167, LIM_ONE99[0])
        allok &= line("pooled one-sided lower>0", sum(o), WORLDS * 2, 0.00167, LIM_ONE99[1])
        for j, s in enumerate(SEEDS):
            allok &= line(f"seed {s} two-sided 95%", f[j], WORLDS, 0.05, LIM_TWO95)
    cb = [int(runs[s]["comb"].sum()) for s in SEEDS]
    print(f"{D}combined real pass rule (all four variants lower>0): seed counts {cb}, pooled {sum(cb)}/{WORLDS * 2}{X}")
    print(f"{D}mean trades per world: rung 2 = {np.mean([runs[s]['n2'].mean() for s in SEEDS]):.0f}, "
          f"rung 3 = {np.mean([runs[s]['n3'].mean() for s in SEEDS]):.0f}{X}")
    pw = batch(POWER_SEED, POWER_WORLDS, B_FULL, delta=POWER_DELTA, label="power")
    print(f"\n{C}== power check: +{POWER_DELTA * 100:.1f}% planted on every rung-3 trade ({POWER_WORLDS} worlds) =={X}")
    for v, nm in enumerate(VARIANTS):
        rate = pw["one99"][:, v].mean()
        print(f"{(G + 'ok   ') if rate >= 0.8 else (Y + 'WEAK ')}{nm:26s} detected in {rate * 100:.0f}%{X}")
    print(f"{D}combined rule detected in {pw['comb'].mean() * 100:.0f}%{X}")
    print("\n" + (G + "CALIBRATION PASSED: the paired block-bootstrap procedure may be used in the frozen experiment."
                  if allok else R + "CALIBRATION FAILED: stop. Investigate the testing method; do not change limits or run the real data.") + X)
    json.dump({"seeds": list(SEEDS), "worlds": WORLDS, "passed": bool(allok),
               "two99": {str(s): runs[s]["two99"].sum(0).tolist() for s in SEEDS},
               "one99": {str(s): runs[s]["one99"].sum(0).tolist() for s in SEEDS},
               "two95": {str(s): runs[s]["two95"].sum(0).tolist() for s in SEEDS},
               "power_one99": pw["one99"].mean(0).tolist()}, open("calib2_result.json", "w"))
    print(f"{D}saved calib2_result.json{X}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "quick")
