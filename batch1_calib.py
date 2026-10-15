import sys, os, json, time, math
import numpy as np
import batch1_engine as E

SHAPE = 'panel_shape.json'
RESULT = 'batch1_calib_result_v3.json'
CKPT = 'batch1_calib_checkpoint_v3.json'
CALIB_SPEC_HASH = '27d0842649a8256ed75c3415c29dfa53fe6a230b92ddfa5a13e76a205dd718d8'
BATCH1_SPEC_HASH = '7fc3c8c279814d4d72c144a27d9998a489b9fe05a41cb633cd60f1be4d934b10'
TYPES = {'A': (20, 0.0), 'B': (60, 0.0), 'C': (20, 0.6), 'D': (60, 0.6)}
TI = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
HYP = E.HYP
BLOCKS = [7, 14, 28]
NB = 10000
ALPHA = 0.005
STAGES = [(986, 11, 18), (1972, 22, 36), (3944, 44, 72)]
SEEDS = [1, 2]
PLANTS = [0.0003, 0.0006, 0.0012]
SQ2 = math.sqrt(2.0)
MAXR = {}
LN2 = math.log(2.0)

def load_shape():
    s = json.load(open(SHAPE))
    names = sorted(s['coins'])
    for c in names:
        if s['coins'][c]['invalid_days']:
            raise SystemExit('invalid days present, generator does not model them: ' + c)
    f = np.array([s['coins'][c]['first_valid_day'] for c in names])
    d0 = int(f.min())
    return dict(N=len(names), T=int(s['end_day_exclusive']) - d0, first=f - d0, day0=d0)

def logvol(rng, n, T, hl, s):
    phi = 0.5 ** (1.0 / hl)
    h = np.empty((n, T))
    h[:, 0] = rng.normal(0, s, n)
    e = rng.normal(0, s * math.sqrt(1 - phi * phi), (n, T))
    for t in range(1, T):
        h[:, t] = phi * h[:, t - 1] + e[:, t]
    np.exp(h, out=h)
    return h

def make_world(sh, seed, tn, w):
    N, T = sh['N'], sh['T']
    hl, dr = TYPES[tn]
    rng = np.random.default_rng([seed, TI[tn], w])
    beta = rng.uniform(0.6, 1.4, N)
    F = 0.02 * logvol(rng, 1, T, hl, 0.25)[0] * rng.standard_t(4, T) / SQ2
    eps = 0.025 * logvol(rng, N, T, hl, 0.30) * rng.standard_t(4, (N, T)) / SQ2
    r = np.ascontiguousarray((beta[:, None] * F[None, :] + eps).T)
    if dr:
        r = r + math.log1p(dr) / 365.0
    for i in range(N):
        r[:sh['first'][i], i] = 0.0
    nclip = int((np.abs(r) > LN2).sum())
    r = np.clip(r, -LN2, LN2)
    lp = np.cumsum(r, 0)
    clipped = nclip
    C = 100.0 * np.exp(np.clip(lp, -600, 600))
    O = np.vstack([C[:1], C[:-1]])
    for i in range(N):
        f = int(sh['first'][i])
        C[:f, i] = np.nan
        O[:f, i] = np.nan
        O[f, i] = C[f, i]
    return O, C, r, clipped

def actives(O, C, day0):
    out = {}
    for h in HYP:
        o = E.run(h, O, C, day0, 0.0)
        out[h] = o['active'][o['start']:]
    return out

def one_world(sh, seed, tn, w):
    O, C, r, clip = make_world(sh, seed, tn, w)
    mx = float(np.expm1(r.max())) if np.isfinite(r).all() else float('inf')
    MAXR[tn] = max(MAXR.get(tn, 0.0), mx)
    if not math.isfinite(mx):
        print('STATUS WORLD INVALID type', tn, 'world', w, 'max daily simple ret', mx)
        raise SystemExit('STOP: WORLD INVALID')
    act = actives(O, C, sh['day0'])
    rb = np.random.default_rng([seed, TI[tn], w, 99])
    pos, ma, nf = {}, {}, 0
    for h in HYP:
        a = act[h]
        if not np.isfinite(a).all():
            nf += 1
            a = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
        ma[h] = float(a.mean())
        for b in BLOCKS:
            pos[h + '|' + str(b)] = int(E.boot_lower(a, b, NB, ALPHA, rb) > 0)
    return pos, ma, clip, nf

def acf(x, k):
    return float((x[:, :-k] * x[:, k:]).mean() / (x * x).mean())

def acf_abs(x, k):
    a = np.abs(x); m = a.mean(); v = ((a - m) ** 2).mean()
    return float(((a[:, :-k] - m) * (a[:, k:] - m)).mean() / v)

def theory(hl, s):
    phi = 0.5 ** (1.0 / hl); v = s * s; r = phi ** 30
    return 0.5 * (math.exp(v * (1 + r)) - math.exp(v)) / (math.exp(2 * v) - 0.5 * math.exp(v))

def model_selfcheck(sh):
    bad = []
    worst = 0.0
    T = sh['T']
    for t, (hl, dr) in TYPES.items():
        rng = np.random.default_rng([0, TI[t], 123])
        F = 0.02 * logvol(rng, 1000, T, hl, 0.25) * rng.standard_t(4, (1000, T)) / SQ2
        e = 0.025 * logvol(rng, 2000, T, hl, 0.30) * rng.standard_t(4, (2000, T)) / SQ2
        for lab, x, s in (('F', F, 0.25), ('e', e, 0.30)):
            a1, a30, ab, th = acf(x, 1), acf(x, 30), acf_abs(x, 30), theory(hl, s)
            worst = max(worst, abs(a1) / 0.03, abs(a30) / 0.03, abs(ab - th) / 0.05)
            if abs(a1) > 0.03: bad.append('%s %s lag1 %.3f' % (t, lab, a1))
            if abs(a30) > 0.03: bad.append('%s %s lag30 %.3f' % (t, lab, a30))
            if abs(ab - th) > 0.05: bad.append('%s %s abs lag30 %.3f theory %.3f' % (t, lab, ab, th))
        m = F.mean(1); se = m.std(ddof=1) / math.sqrt(len(m))
        worst = max(worst, abs(m.mean()) / (4 * se))
        if abs(m.mean()) > 4 * se: bad.append('%s F mean %.5g se %.5g' % (t, m.mean(), se))
    O, C, r, cl = make_world(sh, 0, 'A', 0)
    if int(np.isnan(C).sum()) != int(sh['first'].sum()) or not np.isfinite(C[~np.isnan(C)]).all():
        bad.append('panel nan pattern/finite')
    a = actives(O, C, sh['day0'])['ema50_200']
    l0 = E.boot_lower(a, 7, 2000, ALPHA, np.random.default_rng(1))
    l1 = E.boot_lower(a + 0.0005, 7, 2000, ALPHA, np.random.default_rng(1))
    if abs((l1 - l0) - 0.0005) > 0.00005: bad.append('planted effect not recovered')
    print('worst margin (1.0 = at tolerance): %.2f' % worst)
    return bad

def binom_cdf(x, n, p):
    lp = math.log(p); lq = math.log1p(-p); tot = 0.0
    for k in range(x + 1):
        tot += math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq)
    return tot

def cp_upper(x, n):
    if x >= n: return 1.0
    lo, hi = (x / n if x > 0 else 0.0), 1.0
    for _ in range(60):
        p = (lo + hi) / 2
        if binom_cdf(x, n, p) > 0.025: lo = p
        else: hi = p
    return hi

def key(t, s): return t + '|' + str(s)

def save(st):
    json.dump(st, open(CKPT + '.tmp', 'w'))
    os.replace(CKPT + '.tmp', CKPT)

def new_state(eh):
    return dict(engine_hash=eh, counts={}, ndone={}, diag={}, flags={'clipped': 0, 'nonfinite': 0},
                final={}, needs_more=[], active=list(TYPES), stage=0, power={'ndone': {}, 'det': {}})

def run_to(st, sh, t, target):
    for s in SEEDS:
        k = key(t, s)
        nd = st['ndone'].get(k, 0)
        cnt = st['counts'].setdefault(k, {h + '|' + str(b): 0 for h in HYP for b in BLOCKS})
        dg = st['diag'].setdefault(k, {h: [0.0, 0.0, 0] for h in HYP})
        t0 = time.time()
        for w in range(nd, target):
            pos, ma, cl, nf = one_world(sh, s, t, w)
            for q, v in pos.items(): cnt[q] += v
            for h in HYP:
                dg[h][0] += ma[h]; dg[h][1] += ma[h] ** 2; dg[h][2] += 1
            st['flags']['clipped'] += int(cl); st['flags']['nonfinite'] += nf
            mr = st['flags'].setdefault('maxret', {}); mr[t] = max(mr.get(t, 0.0), MAXR.get(t, 0.0))
            st['ndone'][k] = w + 1
            if (w + 1) % 25 == 0 or w + 1 == target:
                save(st)
                el = time.time() - t0
                print('%s %d/%d  %.0fs  eta %.0fs' % (k, w + 1, target, el, el / (w + 1 - nd) * (target - w - 1)), flush=True)

def cell(st, t, ls, lp, h, b):
    c = [st['counts'][key(t, s)][h + '|' + str(b)] for s in SEEDS]
    return (all(x <= ls for x in c) and sum(c) <= lp), c

def power_phase(st, sh, blk):
    n = STAGES[0][0]
    for t in ('A', 'B'):
        nd = st['power']['ndone'].get(t, 0)
        det = st['power']['det'].setdefault(t, {h: [0] * len(PLANTS) for h in HYP})
        t0 = time.time()
        for w in range(nd, n):
            O, C, r, cl = make_world(sh, 1, t, w)
            act = actives(O, C, sh['day0'])
            for hi, h in enumerate(HYP):
                a = np.nan_to_num(act[h])
                for pi, p in enumerate(PLANTS):
                    rb = np.random.default_rng([1, TI[t], w, 55, hi, pi])
                    det[h][pi] += int(E.boot_lower(a + p, blk, NB, ALPHA, rb) > 0)
            st['power']['ndone'][t] = w + 1
            if (w + 1) % 25 == 0 or w + 1 == n:
                save(st)
                print('power %s %d/%d %.0fs' % (t, w + 1, n, time.time() - t0), flush=True)

def full(sh):
    if os.path.exists(RESULT):
        raise SystemExit('result exists, not overwriting')
    bad = model_selfcheck(sh)
    for b in bad: print('FAIL', b)
    if bad:
        raise SystemExit('STOP: model self-check failed; nothing loosened')
    eh = E.engine_hash()
    st = json.load(open(CKPT)) if os.path.exists(CKPT) else new_state(eh)
    if st['engine_hash'] != eh:
        raise SystemExit('engine hash changed since checkpoint')
    while st['active'] and st['stage'] < len(STAGES):
        si = st['stage']; n, ls, lp = STAGES[si]
        for t in st['active']: run_to(st, sh, t, n)
        flagged = []
        for t in st['active']:
            fl = False
            for h in HYP:
                for b in BLOCKS:
                    ok, c = cell(st, t, ls, lp, h, b)
                    if ok and cp_upper(sum(c), 2 * n) > 0.02: fl = True
            if fl and si < len(STAGES) - 1:
                flagged.append(t)
            else:
                st['final'][t] = si
                if fl: st['needs_more'].append(t)
        st['active'] = flagged; st['stage'] = si + 1; save(st)
    cells = []; fails = {b: 0 for b in BLOCKS}
    for t in TYPES:
        n, ls, lp = STAGES[st['final'][t]]
        for h in HYP:
            for b in BLOCKS:
                ok, c = cell(st, t, ls, lp, h, b)
                if not ok: fails[b] += 1
                cells.append(dict(type=t, hyp=h, block=b, seed1=c[0], seed2=c[1], pooled=sum(c), ok=ok, worlds_per_seed=n))
    sel = None; mde = {}; pw = {}
    if st['needs_more']:
        status = 'NEEDS MORE WORLDS'
    else:
        q = [b for b in BLOCKS if fails[b] == 0]
        if not q:
            status = 'NO BLOCK QUALIFIES'
        else:
            sel = q[0]; status = 'CALIBRATED'
            power_phase(st, sh, sel)
            n = STAGES[0][0]
            for h in HYP:
                rates = [[st['power']['det'][t][h][pi] / n for pi in range(len(PLANTS))] for t in ('A', 'B')]
                pooled = [(rates[0][pi] + rates[1][pi]) / 2 for pi in range(len(PLANTS))]
                pw[h] = dict(typeA=rates[0], typeB=rates[1], pooled=pooled)
                mde[h] = next((PLANTS[pi] for pi in range(len(PLANTS)) if pooled[pi] >= 0.8), None)
    res = dict(version='batch1-calibration-v3', calib_spec_hash=CALIB_SPEC_HASH, batch1_spec_hash=BATCH1_SPEC_HASH,
               engine_hash=eh, status=status, selected_block=sel, fails_per_block=fails, stage_of_type=st['final'],
               cells=cells, power=pw, mde=mde, diag_mean_gross_active=st['diag'], flags=st['flags'],
               finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(res, open(RESULT, 'x'), indent=1)
    print('STATUS', status, 'block', sel, 'fails/block', fails, 'MDE', mde, 'flags', st['flags'])

def quick(sh):
    bad = model_selfcheck(sh)
    for b in bad: print('FAIL', b)
    print('MODEL SELFCHECK:', len(bad), 'FAIL')
    tw = []; agg = {}
    for t in TYPES:
        for w in range(5):
            t0 = time.time()
            pos, ma, cl, nf = one_world(sh, 1, t, w)
            tw.append(time.time() - t0)
            for h in HYP: agg.setdefault((t, h), []).append(ma[h])
        O, C, r, cl = make_world(sh, 1, t, 0)
        x = np.sort((r * r).ravel())[::-1]
        with np.errstate(all='ignore'):
            mv = float(np.nanmax(np.abs(C / O - 1)))
        print(t, 'top1%% days share of variance %.2f' % (x[:len(x) // 100].sum() / x.sum()), 'max daily simple ret %.3g' % mv, 'clipped', cl)
    for (t, h), v in agg.items():
        print(t, h, 'mean gross active %.4f%%/day  se %.4f%%' % (100 * np.mean(v), 100 * np.std(v, ddof=1) / math.sqrt(len(v))))
    m = sum(tw) / len(tw)
    print('per world %.2fs; projected stage1 %.1f h, worst case (stage3) %.1f h, plus power ~%.1f h' % (m, m * 986 * 8 / 3600, m * 3944 * 8 / 3600, m * 1.5 * 1972 / 3600))

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    sh = load_shape()
    if mode == 'quick': quick(sh)
    elif mode == 'full': full(sh)
    else: print('usage: quick | full')
