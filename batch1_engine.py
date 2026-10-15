import numpy as np, hashlib, time
NEED = {'ema50_200': 200, 'breakout20': 21, 'weekly_mom_b1': 8, 'meanrev_short_b1': 63}
HYP = ['ema50_200', 'breakout20', 'weekly_mom_b1', 'meanrev_short_b1']

def engine_hash():
    return hashlib.sha256(open(__file__, 'rb').read()).hexdigest()

def prep(O, C):
    T, N = C.shape
    ok = ~np.isnan(C) & ~np.isnan(O)
    first = np.full(N, T)
    for i in range(N):
        w = np.flatnonzero(ok[:, i])
        if len(w):
            first[i] = w[0]
            if not ok[w[0]:, i].all():
                raise ValueError('interior invalid bar, coin %d' % i)
    return ok, first

def bench(O, C):
    ok = ~np.isnan(C) & ~np.isnan(O)
    R = np.where(ok, C / O - 1, 0.0)
    return (R * ok).sum(1) / np.maximum(ok.sum(1), 1)

def sig_ema(C, ok, first):
    T, N = C.shape
    L = np.zeros((T, N), bool)
    e50 = np.full(N, np.nan)
    e200 = np.full(N, np.nan)
    for t in range(T):
        v = ok[t]
        seed = v & np.isnan(e50)
        upd = v & ~np.isnan(e50)
        c = C[t]
        e50[upd] += (2 / 51) * (c[upd] - e50[upd])
        e200[upd] += (2 / 201) * (c[upd] - e200[upd])
        e50[seed] = c[seed]
        e200[seed] = c[seed]
        L[t] = v & (t - first + 1 >= 200) & (e50 > e200)
    return L

def sig_breakout(C, ok, first):
    T, N = C.shape
    L = np.zeros((T, N), bool)
    st = np.zeros(N, bool)
    with np.errstate(all='ignore'):
        for t in range(20, T):
            cap = ok[t] & (t - first + 1 >= 21)
            hi = C[t - 20:t].max(0)
            lo = C[t - 10:t].min(0)
            st = np.where(cap & (C[t] > hi), True, np.where(cap & (C[t] < lo), False, st))
            st = st & cap
            L[t] = st
    return L

def sig_meanrev(C, ok, first):
    T, N = C.shape
    L = np.zeros((T, N), bool)
    with np.errstate(all='ignore'):
        for t in range(62, T):
            cap = ok[t] & (t - first + 1 >= 63)
            r3 = C[t] / C[t - 3] - 1
            rets = C[t - 60:t] / C[t - 61:t - 1] - 1
            s = rets.std(0, ddof=1)
            z = r3 / (s * np.sqrt(3))
            L[t] = cap & (z <= -1.5)
    return L

def weights_long(L, ok):
    T, N = L.shape
    W = np.zeros((T, N))
    nact = ok.sum(1)
    for t in range(1, T):
        if nact[t] > 0:
            W[t] = (L[t - 1] & ok[t]) / nact[t]
    return W

def weights_weekly(C, ok, first, day0):
    T, N = C.shape
    W = np.zeros((T, N))
    for t in range(7, T - 1):
        if (day0 + t + 4) % 7 != 0:
            continue
        el = ok[t] & (t - first + 1 >= 8)
        n = int(el.sum())
        if n < 20:
            continue
        k = n // 5
        idx = np.flatnonzero(el)
        r = C[t, idx] / C[t - 7, idx] - 1
        order = np.argsort(r, kind='stable')
        row = np.zeros(N)
        row[idx[order[-k:]]] = 0.5 / k
        row[idx[order[:k]]] = -0.5 / k
        W[t + 1:t + 8] = row
    return W

def account(W, R, cost):
    T, N = W.shape
    gross = (W * R).sum(1)
    prev = np.zeros(N)
    turn = np.zeros(T)
    for t in range(T):
        turn[t] = np.abs(W[t] - prev).sum()
        prev = W[t] * (1 + R[t]) / (1 + gross[t])
    return gross, gross - cost * turn, turn

def run(name, O, C, day0, cost):
    ok, first = prep(O, C)
    if name == 'weekly_mom_b1':
        W = weights_weekly(C, ok, first, day0)
        nz = np.flatnonzero(np.abs(W).sum(1) > 0)
        start = int(nz[0]) if len(nz) else C.shape[0]
    else:
        f = {'ema50_200': sig_ema, 'breakout20': sig_breakout, 'meanrev_short_b1': sig_meanrev}[name]
        W = weights_long(f(C, ok, first), ok)
        start = int(first.min()) + NEED[name]
    R = np.where(ok, C / O - 1, 0.0)
    rbh = bench(O, C)
    gross, net, turn = account(W, R, cost)
    E = W.sum(1)
    return dict(W=W, gross=gross, net=net, turn=turn, E=E, rbh=rbh, active=net - E * rbh, start=start)

def boot_lower(a, b, B, alpha, rng, chunk=2000):
    n = len(a)
    m = -(-n // b)
    cs = np.concatenate([[0.0], np.cumsum(np.concatenate([a, a[:b]]))])
    means = np.empty(B)
    d = 0
    while d < B:
        k = min(chunk, B - d)
        s = rng.integers(0, n, size=(k, m))
        means[d:d + k] = (cs[s + b] - cs[s]).sum(1) / (m * b)
        d += k
    return float(np.quantile(means, alpha))

def _panel(rng, T, N, late=()):
    C = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, (T, N)), 0))
    O = np.vstack([C[:1], C[:-1]])
    for i, s in late:
        C[:s, i] = np.nan
        O[:s, i] = np.nan
        O[s, i] = C[s, i]
    return O, C

def selfcheck():
    bad = []
    def chk(c, m):
        if not c:
            bad.append(m)
    O = np.full((2, 3), 100.0)
    C = np.array([[110, 100, 100], [90, 100, 100.]])
    chk(np.allclose(bench(O, C), [0.1 / 3, -0.1 / 3]), 'bench mean')
    g, n, tu = account(np.array([[.5, .5], [.5, .5]]), np.array([[.1, -.1], [0, 0.]]), 0.001)
    chk(np.allclose(tu, [1.0, 0.1]), 'turnover hand')
    chk(np.allclose(n, [-0.001, -0.0001]), 'cost hand')
    t = np.arange(260.)
    C = np.stack([100 * 1.01 ** t, 100 * 0.99 ** t], 1)
    O = np.vstack([C[:1], C[:-1]])
    for nm in ['ema50_200', 'breakout20']:
        o = run(nm, O, C, 0, 0.0)
        chk(abs(o['W'][255, 0] - 0.5) < 1e-12 and o['W'][255, 1] == 0, nm + ' up/down coin')
    o = run('ema50_200', O, C, 0, 0.0)
    chk(o['W'][150].sum() == 0 and o['start'] == 200, 'ema warmup/start')
    cl = np.array([100.] * 20 + list(range(101, 112)) + [90., 90.]).reshape(-1, 1)
    o = run('breakout20', np.vstack([cl[:1], cl[:-1]]), cl, 0, 0.0)['W'][:, 0]
    chk(o[20] == 0 and (o[21:32] == 1).all() and o[32] == 0, 'breakout hand entry/exit')
    rng = np.random.default_rng(3)
    c0 = np.concatenate([100 * np.exp(np.cumsum(rng.normal(0, 0.01, 80))), [0] * 3])
    c0[80:] = c0[79] * 0.95 ** np.arange(1, 4)
    c1 = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 83)))
    C = np.stack([c0, c1], 1)
    O = np.vstack([C[:1], C[:-1]])
    o = run('meanrev_short_b1', O, C, 0, 0.0)
    chk(np.abs(o['W'][:63]).sum() == 0, 'meanrev warmup flat')
    cu = np.stack([C[:, 0].copy(), C[:, 1]], 1)
    cu[80:, 0] = cu[79, 0] * 1.05 ** np.arange(1, 4)
    ou = run('meanrev_short_b1', np.vstack([cu[:1], cu[:-1]]), cu, 0, 0.0)
    chk(np.abs(ou['W'][81:83, 0]).sum() == 0, 'meanrev no long after rise')
    # planted drop at day 82: decision at close of 82 would need day 83; extend one day
    C = np.vstack([C, C[-1] * 1.0])
    O = np.vstack([C[:1], C[:-1]])
    o = run('meanrev_short_b1', O, C, 0, 0.0)
    chk(abs(o['W'][83, 0] - 0.5) < 1e-12, 'meanrev planted drop long next day')
    rng = np.random.default_rng(7)
    O, C = _panel(rng, 120, 40)
    o = run('weekly_mom_b1', O, C, 19000, 0.0)
    W = o['W']
    m = np.abs(W).sum(1) > 0
    chk(m.any(), 'weekly no positions')
    if m.any():
        chk(((W > 0).sum(1)[m] == 8).all() and ((W < 0).sum(1)[m] == 8).all(), 'weekly 8/8')
        chk((np.abs(W.sum(1)) < 1e-12).all() and (abs(np.abs(W).sum(1)[m] - 1) < 1e-12).all(), 'weekly neutral gross1')
        chk((19000 + int(np.flatnonzero(m)[0]) - 1 + 4) % 7 == 0, 'weekly first decision is Sunday')
    chk(np.abs(o['E']).max() < 1e-12, 'weekly E=0')
    O, C = _panel(rng, 120, 19)
    chk(np.abs(run('weekly_mom_b1', O, C, 19000, 0.0)['W']).sum() == 0, 'weekly N<20 flat')
    T, N, D0 = 330, 40, 250
    O, C = _panel(rng, T, N, late=[(0, 10), (1, 10), (2, 40)])
    f = rng.uniform(0.6, 1.6, (T - D0, N))
    C2 = C.copy(); O2 = O.copy()
    C2[D0:] *= f; O2[D0:] *= f
    for nm in HYP:
        a = run(nm, O, C, 19000, 0.001)['W']
        b = run(nm, O2, C2, 19000, 0.001)['W']
        chk(np.array_equal(a[:D0 + 1], b[:D0 + 1]), nm + ' lookahead')
    a = np.random.default_rng(5).normal(0, 0.01, 1000)
    l0 = boot_lower(a, 7, 2000, 0.005, np.random.default_rng(1))
    l1 = boot_lower(a + 0.005, 7, 2000, 0.005, np.random.default_rng(1))
    chk(l0 < a.mean() and l1 > 0 and l1 < a.mean() + 0.005, 'bootstrap bounds')
    chk(l0 == boot_lower(a, 7, 2000, 0.005, np.random.default_rng(1)), 'bootstrap reproducible')
    return bad

if __name__ == '__main__':
    t0 = time.time()
    bad = selfcheck()
    for b in bad:
        print('FAIL', b)
    print('ENGINE SELFCHECK:', len(bad), 'FAIL', round(time.time() - t0, 1), 's', engine_hash()[:16])
