import os, sys, json, math, hashlib, time, sqlite3, warnings
from datetime import datetime, timezone
import numpy as np
import fade_calib2 as fc

HERE = os.path.dirname(os.path.abspath(__file__))
DBP, LOG = os.path.join(HERE, "fade.db"), os.path.join(HERE, "experiments.json")
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
fc.QLO = 0.0025                                   # 99.5% two-sided (1% family budget / 2 tests)
HOUR, DAYMS = 3600000, 86400000
DFIRST, BOOT, SEEDS, PRIMARY = 31, 10000, (101, 102), 1
STRESS = 0.003

SPEC = {
    "version": "v3-real-1",
    "decision": "00:00 UTC daily per coin; uses candles closing at or before that time",
    "signal": "sign of previous 24h log return; zero return = no signal",
    "rung1": "unfiltered momentum (baseline, descriptive only)",
    "rung2": "rung1 and vol_ratio>=%s (stdev 24h returns / stdev 720h returns)" % fc.VR_MIN,
    "rung3": "rung2 and agreement>=%s among coins with finite nonzero 24h return (target included), >=%d such coins" % (fc.AGREE_MIN, fc.MIN_VALID),
    "trade": "entry next candle open, exit close 24 candles later, 1x, no stops, equal size",
    "cost_round_trip": fc.COST, "stress_cost": STRESS,
    "funding": "NOT INCLUDED in this run (rung 4 and funding deferred; logged limitation)",
    "market_adjustment": "net return minus signal sign x equal-weight mean gross return of coins with data over the same hold",
    "bootstrap": "fixed non-overlapping 7-day blocks of days from day %d, %d resamples, 99.5%% two-sided, seeds %s" % (DFIRST, BOOT, list(SEEDS)),
    "primary_gate": "market-adjusted mean(rung3)-mean(rung2): 99.5% lower bound > 0 at seed 101; seed 102 must agree else UNSTABLE",
    "reported_not_gating": ["raw", "raw ex-10 illiquid", "adjusted ex-10 illiquid", "halves", "rung2 vs rung1 point estimate"],
    "illiquid": "10 lowest mean quote volume (close x base volume) over the dataset",
    "family": "2 hypotheses (rung2 vs 1 descriptive, rung3 vs 2 gated), Bonferroni 1%",
    "mechanisms": {"rung2": "momentum continues when volatility is expanding",
                   "rung3": "momentum is more reliable when other coins confirm it"},
}


def sha(b): return hashlib.sha256(b).hexdigest()


def fsha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def trimmed(x, p=0.1):
    x = np.sort(x)
    if len(x) == 0:
        return float("nan")
    k = int(len(x) * p)
    return float(x[k:len(x) - k].mean()) if len(x) > 2 * k else float(x.mean())


# ---------------------------------------------------------------- calibrated logic, NaN-aware
def build(Cm, Om):
    N, T = Cm.shape
    with np.errstate(all="ignore"):
        r = np.full((N, T), np.nan)
        r[:, 1:] = np.log(Cm[:, 1:] / Cm[:, :-1])
    bad = ~np.isfinite(r)
    r0 = np.where(bad, 0.0, r)
    z = np.zeros((N, 1))
    cs = np.concatenate([z, np.cumsum(r0, axis=1)], axis=1)
    c2 = np.concatenate([z, np.cumsum(r0 * r0, axis=1)], axis=1)
    cn = np.concatenate([z, np.cumsum(bad, axis=1).astype(float)], axis=1)
    d = np.arange(DFIRST, (T - 24) // 24 + 1)
    i = 24 * d - 1

    def win(w):
        S = cs[:, i + 1] - cs[:, i + 1 - w]
        S2 = c2[:, i + 1] - c2[:, i + 1 - w]
        ok = (cn[:, i + 1] - cn[:, i + 1 - w]) == 0
        sd = np.sqrt(np.maximum((S2 - S * S / w) / (w - 1), 0))
        return S, sd, ok

    S24, sd24, ok24 = win(24)
    _, sd720, ok720 = win(720)
    with np.errstate(all="ignore"):
        ret24 = np.where(ok24, S24, np.nan).T
        vr = np.where(ok24 & ok720 & (sd720 > 0), sd24 / sd720, np.nan).T
        gross = (Cm[:, i + 24] / Om[:, i + 1] - 1).T
    return d, ret24, vr, gross


def trades_real(ret24, vr, gross):
    sign = np.where(np.isfinite(ret24), np.sign(ret24), 0.0)
    valid = sign != 0
    nvalid = valid.sum(1)
    same = np.where(sign > 0, (sign > 0).sum(1)[:, None], (sign < 0).sum(1)[:, None])
    agree = same / np.maximum(nvalid, 1)[:, None]
    fg, fv = np.isfinite(gross), np.isfinite(vr)
    m1 = valid & fg
    m2 = m1 & fv & (np.where(fv, vr, 0) >= fc.VR_MIN)
    m3 = m2 & (agree >= fc.AGREE_MIN) & (nvalid >= fc.MIN_VALID)[:, None]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bench = np.nanmean(gross, axis=1)
    gz = np.where(fg, gross, 0.0)
    net = sign * gz - fc.COST
    adj = net - sign * bench[:, None]
    return sign, agree, m1, m2, m3, net, adj, bench, nvalid


def boot(net, adj, m2, m3, keep, d, rng, Bn):
    blk = np.broadcast_to(((d - DFIRST) // 7)[:, None], net.shape).ravel()
    nb = int(blk.max()) + 1
    lm = np.broadcast_to(keep[None, :], net.shape)
    cols = []
    for val, l in ((net, None), (adj, None), (net, lm), (adj, lm)):
        a2 = m2 if l is None else (m2 & l)
        a3 = m3 if l is None else (m3 & l)
        for w in (np.where(a2, val, 0.0), a2.astype(float), np.where(a3, val, 0.0), a3.astype(float)):
            cols.append(np.bincount(blk, weights=w.ravel(), minlength=nb))
    M = np.stack(cols, axis=1)
    W = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=Bn).astype(float)
    Rm = W @ M
    out = []
    with np.errstate(all="ignore"):
        for v in range(4):
            dd = Rm[:, 4 * v + 2] / Rm[:, 4 * v + 3] - Rm[:, 4 * v] / Rm[:, 4 * v + 1]
            dd = dd[np.isfinite(dd)]
            q = np.quantile(dd, [fc.QLO, 1 - fc.QLO, 0.025, 0.975])
            pt = M[:, 4 * v + 2].sum() / M[:, 4 * v + 3].sum() - M[:, 4 * v].sum() / M[:, 4 * v + 1].sum()
            out.append((float(pt), q))
    return out, nb


# ---------------------------------------------------------------- self-checks
def selfcheck():
    ok = True

    def rep(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print((G + "PASS " if cond else R + "FAIL ") + name + X)

    rng = np.random.default_rng([5, 5])
    r = fc.make_world(rng)
    N = r.shape[0]
    Cx = np.concatenate([np.ones((N, 24)), np.exp(np.cumsum(r, axis=1))], axis=1)
    Ox = np.concatenate([np.full((N, 1), np.nan), Cx[:, :-1]], axis=1)
    d, ret24, vr, gross = build(Cx, Ox)
    sel = d <= fc.DAYS - 1
    fd, fret, fvr, fgross = fc.features(r)
    rep("days line up with the calibrated code", np.array_equal(d[sel] - 1, fd))
    rep("features (24h return, vol ratio, gross) equal the calibrated code",
        np.allclose(ret24[sel], fret, atol=1e-9) and np.allclose(vr[sel], fvr, atol=1e-9) and np.allclose(gross[sel], fgross, atol=1e-9))
    sign, agree, m1, m2, m3, net, adj, bench, nv = trades_real(ret24[sel], vr[sel], gross[sel])
    fs_, fa, fm2, fm3, fnet, fadj = fc.trades(fret, fvr, fgross)
    rep("rung 2 / rung 3 trade sets identical to the calibrated code", np.array_equal(m2, fm2) and np.array_equal(m3, fm3))
    rep("net and market-adjusted returns identical", np.allclose(net, fnet, atol=1e-12) and np.allclose(adj, fadj, atol=1e-12))
    rep("rung 3 is a subset of rung 2", bool((m3 <= m2).all()))
    keep = np.arange(N) >= 0
    keep = np.arange(N) < fc.LIQ_KEEP
    q_fc = fc.run_world(np.random.default_rng([5, 5]), 2000)[0]
    rng2 = np.random.default_rng([5, 5])
    fc.make_world(rng2)
    out, _ = boot(net, adj, m2, m3, keep, d[sel], rng2, 2000)
    rep("bootstrap quantiles identical to the calibrated code (same random stream)",
        np.allclose(np.array([o[1] for o in out]), q_fc, atol=1e-9))
    # NaN holes: nothing selected may be NaN, nothing may crash
    Ch = Cx.copy()
    Ch[3, 5000:5400] = np.nan
    Ch[:, 9000:9003] = np.nan
    Oh = np.concatenate([np.full((N, 1), np.nan), Ch[:, :-1]], axis=1)
    d2, a2, b2, g2 = build(Ch, Oh)
    s2, ag2, n1, n2, n3, nt2, ad2, bn2, nv2 = trades_real(a2, b2, g2)
    rep("with missing candles: every selected trade has finite returns",
        bool(np.isfinite(nt2[n3]).all() and np.isfinite(ad2[n3]).all() and np.isfinite(ad2[n2 & ~np.isnan(bn2)[:, None]]).all()))
    # no lookahead: scaling everything after day-500's decision must not change its signals
    d0 = 500
    Cf = Cx.copy()
    Cf[:, 24 * d0:] *= 3.0
    Of = np.concatenate([np.full((N, 1), np.nan), Cf[:, :-1]], axis=1)
    Of[:, 24 * d0] = Cx[:, 24 * d0 - 1]
    d3, a3, b3, g3 = build(Cf, Of)
    k = int(np.where(d3 == d0)[0][0])
    rep("signals on a day do not change when later prices are altered",
        np.allclose(a3[k], ret24[k], atol=1e-12) and np.allclose(b3[k], vr[k], atol=1e-12))
    print((G + "selfcheck PASS" if ok else R + "selfcheck FAIL") + X)
    return ok


# ---------------------------------------------------------------- data
def load():
    conn = sqlite3.connect(DBP)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT sym FROM k ORDER BY sym")]
    tmin, tmax = conn.execute("SELECT MIN(t),MAX(t) FROM k").fetchone()
    T0 = -(-tmin // DAYMS) * DAYMS
    T = int((tmax - T0) // HOUR + 1)
    Cm, Om = np.full((len(syms), T), np.nan), np.full((len(syms), T), np.nan)
    info = {}
    for j, s in enumerate(syms):
        rows = np.array(conn.execute("SELECT t,o,c,v FROM k WHERE sym=? AND t>=? ORDER BY t", (s, T0)).fetchall(), dtype=float)
        if not len(rows):
            continue
        idx = ((rows[:, 0] - T0) // HOUR).astype(int)
        good = (rows[:, 1] > 0) & (rows[:, 2] > 0)
        Om[j, idx[good]] = rows[good, 1]
        Cm[j, idx[good]] = rows[good, 2]
        info[s] = dict(n=int(good.sum()), first=int(rows[0, 0]), last=int(rows[-1, 0]),
                       qvol=float((rows[:, 2] * rows[:, 3]).mean()), gaps=int(idx[-1] - idx[0] + 1 - len(idx)),
                       bad=int((~good).sum()))
    return syms, Cm, Om, info, T0


def fday(ms): return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def fade24_entry():
    return {"id": "E001", "timestamp": "2026-10-09", "type": "closed", "name": "fade24", "result": "FAILED",
            "rule": "fade a 24h move of >=1.5 sigma (z of 24h return vs 100h vol), 60% confidence, hold 24h",
            "data": "fade.db, 40 coins, 9,739 scored events over 1,036 days, cost 0.20% round trip, no funding",
            "observation": "net return per trade negative: day-cluster 95% CI [-0.701%, -0.069%], trimmed mean -0.113%, "
                           "halves -0.438% / -0.317%, 10% of coins positive. Paired and shuffle tests passed (p=0.0094, 0.0005).",
            "interpretation": "Not supported as a profitable rule. The paired and shuffle tests were later shown to be "
                              "anti-conservative with correlated coins (audit section 4) and were not relied on."}


def append_log(entry):
    log = json.load(open(LOG)) if os.path.exists(LOG) else [fade24_entry()]
    entry["prev_hash"] = sha(json.dumps(log, sort_keys=True).encode())
    entry["id"] = "E%03d" % (len(log) + 1)
    log.append(entry)
    tmp = LOG + ".tmp"
    json.dump(log, open(tmp, "w"), indent=1)
    os.replace(tmp, LOG)
    return entry["id"]


# ---------------------------------------------------------------- main
def main(mode):
    spec_hash = sha(json.dumps(SPEC, sort_keys=True).encode())
    code_hash = {f: fsha(os.path.join(HERE, f))[:16] for f in ("fade_experiment.py", "fade_calib2.py")}
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    print(f"{C}spec hash {spec_hash[:16]}   code {code_hash}{X}")
    if mode == "run" and any(e.get("spec_hash") == spec_hash for e in log):
        raise SystemExit(R + "this spec was already run and logged. It runs once. Stop." + X)
    if not selfcheck():
        raise SystemExit(R + "selfcheck failed: stop and investigate" + X)
    if not os.path.exists(DBP):
        raise SystemExit(R + "fade.db missing" + X)
    syms, Cm, Om, info, T0 = load()
    N = len(syms)
    d, ret24, vr, gross = build(Cm, Om)
    sign, agree, m1, m2, m3, net, adj, bench, nvalid = trades_real(ret24, vr, gross)
    qv = np.array([info.get(s, {}).get("qvol", -1.0) for s in syms])
    least = np.argsort(qv)[:10]
    keep = np.ones(N, bool)
    keep[least] = False
    ndays = len(d)
    print(f"\n{C}== data inventory (no return statistics) =={X}")
    print(f"coins {N}, decision days {ndays} ({fday(T0 + int(d[0]) * DAYMS)} -> {fday(T0 + int(d[-1]) * DAYMS)})")
    late = sorted(((s, i['first']) for s, i in info.items() if i['first'] - T0 > 30 * DAYMS), key=lambda x: x[1])
    print(f"coins with history starting after the first 30 days: {', '.join(s + ' ' + fday(t) for s, t in late) or 'none'}")
    print(f"missing hourly candles (gaps) total {sum(i['gaps'] for i in info.values())}, non-positive prices dropped {sum(i['bad'] for i in info.values())}")
    print(f"10 least liquid (excluded in ex-10 variants): {', '.join(syms[j] for j in least)}")
    print(f"days with fewer than {fc.MIN_VALID} valid coins (no rung-3 trades): {int((nvalid < fc.MIN_VALID).sum())} of {ndays}")
    cnt = [int(m.sum()) for m in (m1, m2, m3)]
    print(f"trades: rung1 {cnt[0]}   rung2 {cnt[1]}   rung3 {cnt[2]}   (calibrated worlds: rung2 ~5872, rung3 ~3071)")
    if cnt[2] < 0.5 * 3071 or cnt[1] < 0.5 * 5872:
        print(Y + "FEWER trades than calibrated: real power is LOWER than the +0.20% minimum detectable effect." + X)
    if mode == "check":
        print(f"{D}check mode: nothing logged, no returns examined. Next: python3 fade_experiment.py run{X}")
        return
    # ------------------------------------------------ the single run
    res = {}
    for s in SEEDS:
        res[s], nb = boot(net, adj, m2, m3, keep, d, np.random.default_rng(s), BOOT)
    g1, g2 = res[SEEDS[0]][PRIMARY][1][0] > 0, res[SEEDS[1]][PRIMARY][1][0] > 0
    status = "PASS" if (g1 and g2) else ("UNSTABLE" if g1 != g2 else "FAIL")
    try:
        mde = json.load(open(os.path.join(HERE, "calib3_result.json")))["mde"]
    except Exception:
        mde = 0.002
    levels = {}
    for nm, m in (("rung1", m1), ("rung2", m2), ("rung3", m3)):
        levels[nm] = dict(n=int(m.sum()), coins=int(m.any(0).sum()), raw20=float(net[m].mean()), raw30=float(net[m].mean() - (STRESS - fc.COST)),
                          adj20=float(adj[m].mean()), adj_trim=trimmed(adj[m]))
    half = d < np.median(d)
    hv = {}
    for nm, h in (("first half", half), ("second half", ~half)):
        a, b = (m3 & h[:, None]), (m2 & h[:, None])
        hv[nm] = float(adj[a].mean() - adj[b].mean()) if a.any() and b.any() else None
    r21 = float(adj[m2].mean() - adj[m1].mean())
    pt, q = res[SEEDS[0]][PRIMARY]
    obs = (f"market-adjusted rung3 minus rung2 = {pt * 100:+.3f}% per trade, 99.5% interval [{q[0] * 100:+.3f}%, {q[1] * 100:+.3f}%] "
           f"(seed {SEEDS[1]}: lower {res[SEEDS[1]][PRIMARY][1][0] * 100:+.3f}%); {levels['rung3']['n']} rung-3 and {levels['rung2']['n']} rung-2 trades, {nb} weekly blocks")
    if status == "PASS":
        interp = ("Primary gate met on both seeds. This is a historical screen on data that has been looked at, with funding, real slippage "
                  "and delisted coins unmodelled. A candidate for forward confirmation only, not evidence that it makes money.")
    elif status == "UNSTABLE":
        interp = "Seeds disagree on the gate, so the result is unstable and not counted as a pass."
    else:
        interp = (f"The proposed mechanism (confirmation helps) was not supported at this sensitivity. Effects smaller than about +{mde * 100:.2f}% per trade "
                  "could not have been detected, so this is not a disproof.")
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": "experiment", "name": "momentum ladder rungs 1-3", "spec": SPEC,
             "spec_hash": spec_hash, "code_hash": code_hash, "dataset": {"db_sha256": fsha(DBP), "coins": syms, "first_day": fday(T0 + int(d[0]) * DAYMS),
                                                                         "last_day": fday(T0 + int(d[-1]) * DAYMS)},
             "trades": cnt, "levels": levels, "diff_variants": {fc.VARIANTS[v]: {"point": res[SEEDS[0]][v][0], "lo": float(res[SEEDS[0]][v][1][0]),
                                                                               "hi": float(res[SEEDS[0]][v][1][1])} for v in range(4)},
             "halves_adjusted_diff": hv, "rung2_vs_rung1_adjusted_point": r21, "minimum_detectable_effect": mde, "status": status,
             "observation": obs, "interpretation": interp,
             "limitations": ["historical screen on seen data", "survivorship: today's 40 coins", "slippage unmeasured, flat 0.20%", "funding not included",
                             "calibration used synthetic worlds with no persistent drift", "rung 2 vs 1 not calibrated, descriptive only"]}
    eid = append_log(entry)
    print(f"\n{C}== results (logged as {eid}) =={X}")
    print(f"{'rung':7s} {'trades':>7s} {'coins':>6s} {'raw@0.20':>9s} {'raw@0.30':>9s} {'adj@0.20':>9s} {'adj trim':>9s}")
    for nm in ("rung1", "rung2", "rung3"):
        L = levels[nm]
        print(f"{nm:7s} {L['n']:7d} {L['coins']:6d} {L['raw20'] * 100:+8.3f}% {L['raw30'] * 100:+8.3f}% {L['adj20'] * 100:+8.3f}% {L['adj_trim'] * 100:+8.3f}%")
    print(f"\n{C}rung 3 minus rung 2, per trade (cost cancels in the difference){X}")
    for v in range(4):
        p, qq = res[SEEDS[0]][v]
        tag = (G if qq[0] > 0 else R) if v == PRIMARY else D
        print(f"{tag}{'GATE ' if v == PRIMARY else '     '}{fc.VARIANTS[v]:26s} {p * 100:+7.3f}%  99.5% [{qq[0] * 100:+.3f}, {qq[1] * 100:+.3f}]  95% [{qq[2] * 100:+.3f}, {qq[3] * 100:+.3f}]{X}")
    print(f"{D}halves (adjusted diff): {hv}   rung2 minus rung1 (adjusted, descriptive): {r21 * 100:+.3f}%{X}")
    print(f"\n{(G if status == 'PASS' else (Y if status == 'UNSTABLE' else R))}PRIMARY GATE: {status}{X}")
    print("Observation:    " + obs)
    print("Interpretation: " + interp)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "check")
