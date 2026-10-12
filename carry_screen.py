import os, sys, json, math, hashlib, sqlite3
from datetime import datetime, timezone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST_FILE, FWD_FILE = os.path.join(HERE, "carry_spec_v2_3.json"), os.path.join(HERE, "carry_forward_spec_v1.json")
LOG = os.path.join(HERE, "experiments.json")
KDB, FDB, XDB = (os.path.join(HERE, n) for n in ("carry_klines.db", "funding.db", "fade.db"))
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
HOUR, DAY, T0 = 3600000, 86400000, 1640995200000          # T0 = 2022-01-01 00:00 UTC
WORDING = "This describes what happened historically on seen data. It is not evidence of a long-term edge. No statistical significance is claimed."
SPOT_FEE, PERP_FEE, SLIP, STRESS_SLIP, H_ANNUAL = 0.0010, 0.0005, 0.0005, 0.0015, 0.04


def params(m=0.025, slip=SLIP):
    return dict(cs=SPOT_FEE + slip, cp=PERP_FEE + slip, m=m, pen=0.01, wait=168)


def sha(b): return hashlib.sha256(b).hexdigest()
def fsha(p): return sha(open(p, "rb").read())
def fd(h): return datetime.fromtimestamp((T0 + h * HOUR) / 1000, timezone.utc).strftime("%Y-%m-%d")
def yr(day): return datetime.fromtimestamp(int(day) * DAY / 1000, timezone.utc).year


def rebalance_hours(H):
    out = []
    for d in range(H // 24 + 1):
        h = 24 * d
        if h < H and datetime.fromtimestamp((T0 + h * HOUR) / 1000, timezone.utc).day == 1:
            out.append(h)
    return out


def ffill(a):
    a = np.asarray(a, float)
    idx = np.where(np.isnan(a), 0, np.arange(len(a)))
    np.maximum.accumulate(idx, out=idx)
    return a[idx]


def prep(c, H):
    ok = ~(np.isnan(c["sp_o"]) | np.isnan(c["pp_o"]) | np.isnan(c["mk_o"]) | np.isnan(c["mk_h"]))
    if not ok.any():
        return None
    fh0 = [h for h, _ in c["fund"] if 0 <= h < H and ok[h]]
    if not fh0:
        return None
    start, end = int(fh0[0]), int(np.where(ok)[0][-1]) + 1
    bsp = np.full(H + 1, np.nan); bsp[:H] = c["sp_o"]; bsp[end:] = c["sp_c"][end - 1]
    bpp = np.full(H + 1, np.nan); bpp[:H] = c["pp_o"]; bpp[end:] = c["pp_c"][end - 1]
    pairs = sorted((h, r) for h, r in c["fund"] if start <= h < min(end, H))
    return dict(start=start, end=end, bsp=ffill(bsp), bpp=ffill(bpp), mko=ffill(c["mk_o"]), mkh=ffill(c["mk_h"]),
                fh=np.array([h for h, _ in pairs], int), fr=np.array([r for _, r in pairs], float),
                nmiss=int((~ok[start:end]).sum()))


def simulate(world, P, rebs=None, capital=100.0):
    H = world["H"]
    ctx = {s: p for s, c in world["coins"].items() for p in [prep(c, H)] if p}
    syms = sorted(ctx)
    rebs = [r for r in (rebalance_hours(H) if rebs is None else rebs) if r < H]
    st = {s: dict(status="none", sq=0.0, pq=0.0, e=0.0, mb=0.0, cc=0.0, lb=None, last=0.0, pnl=0.0, entry=None, ever=False) for s in syms}
    E, Cc, A = np.full(H + 1, np.nan), np.full(H + 1, np.nan), np.zeros(H + 1, int)
    cash, started, c0, events = capital, False, None, []
    ratio = {s: np.inf for s in syms}
    for kk, h0 in enumerate(rebs):
        h1 = rebs[kk + 1] if kk + 1 < len(rebs) else H
        elig = []
        for s in syms:
            x, c = st[s], ctx[s]
            if x["status"] == "ended" or c["start"] > h0 or c["end"] <= h0:
                continue
            if x["status"] == "waiting" and h0 < x["lb"] + P["wait"]:
                continue
            elig.append(s)

        def val(s):
            x, c = st[s], ctx[s]
            if x["status"] == "held":
                return x["sq"] * c["bsp"][h0] + x["mb"] + x["pq"] * (x["e"] - c["bpp"][h0])
            if x["status"] == "waiting":
                return x["sq"] * c["bsp"][h0] + x["cc"]
            return 0.0
        if elig:
            pool = cash + sum(val(s) for s in elig)
            if not started:
                started, c0 = True, h0
            T = pool / len(elig)
            for s in elig:
                x, c = st[s], ctx[s]
                ps, pp = c["bsp"][h0], c["bpp"][h0]
                cost = P["cs"] * abs(T / 2 - x["sq"] * ps) + P["cp"] * abs(T / 2 - x["pq"] * pp)
                N = (T - cost) / 2
                x.update(status="held", sq=N / ps, pq=N / pp, e=pp, mb=N, cc=0.0, lb=None, last=T, ever=True)
                if x["entry"] is None:
                    x["entry"] = h0
            cash = 0.0
        if not started:
            continue
        L = h1 - h0
        Cs, Ep, Ap = np.zeros(L + 1), np.zeros(L + 1), np.zeros(L + 1, int)
        for s in syms:
            x, c = st[s], ctx[s]
            if x["status"] not in ("held", "waiting"):
                continue
            spx, ppx = c["bsp"][h0:h1 + 1], c["bpp"][h0:h1 + 1]
            je = c["end"] - h0 if (c["end"] <= h1 and c["end"] < H) else None
            jl, was_held = None, x["status"] == "held"
            if was_held:
                F = np.zeros(L + 1)
                sel = (c["fh"] > h0) & (c["fh"] < h1)
                if sel.any():
                    hh = c["fh"][sel]
                    F[hh - h0] += c["fr"][sel] * x["pq"] * c["mko"][hh]
                mbA = x["mb"] + np.cumsum(F)
                eq = x["sq"] * spx + mbA + x["pq"] * (x["e"] - ppx)
                mh = c["mkh"][h0:h1]
                eh, req = mbA[:L] + x["pq"] * (x["e"] - mh), P["m"] * x["pq"] * mh
                lim = L if je is None else min(L, je)
                if lim > 0:
                    ratio[s] = min(ratio[s], float((eh[:lim] / req[:lim]).min()))
                liq = np.where(eh[:lim] < req[:lim])[0]
                if len(liq):
                    kl = int(liq[0]); jl = kl + 1
                    ps_ = (mbA[kl] + x["pq"] * x["e"]) / (x["pq"] * (1 + P["m"]))
                    eqt = mbA[kl] + x["pq"] * (x["e"] - ps_)
                    cashc = max(0.0, eqt - P["pen"] * x["pq"] * ps_)
                    events.append((s, h0 + jl, float(ps_), float(cashc)))
                    eq = eq.copy(); eq[jl:] = x["sq"] * spx[jl:] + cashc
                    x.update(status="waiting", pq=0.0, mb=0.0, e=0.0, cc=cashc, lb=h0 + jl)
                else:
                    x["mb"] = mbA[L]
            else:
                eq = x["sq"] * spx + x["cc"]
            ja = jl if jl is not None else (je if je is not None else L + 1)
            if was_held:
                Ap[:ja] += 1
            if je is not None:
                if was_held and jl is None:
                    sv = x["sq"] * spx[je]
                    pe = mbA[je] + x["pq"] * (x["e"] - ppx[je])
                    proceeds = sv + pe - P["cs"] * sv - P["cp"] * x["pq"] * ppx[je]
                else:
                    proceeds = x["sq"] * spx[je] * (1 - P["cs"]) + x["cc"]
                eq = eq.copy(); eq[je:] = 0.0; Cs[je:] += proceeds
                x["pnl"] += proceeds - x["last"]
                x.update(status="ended", sq=0.0, pq=0.0, mb=0.0, cc=0.0, last=0.0)
            else:
                x["pnl"] += eq[L] - x["last"]; x["last"] = eq[L]
            Ep += eq
        Cp = cash + Cs
        Et = Ep + Cp
        E[h0:h1], Cc[h0:h1], A[h0:h1] = Et[:L], Cp[:L], Ap[:L]
        if h1 == H:
            E[H], Cc[H], A[H] = Et[L], Cp[L], Ap[L]
        cash += Cs[L]
    info = {s: dict(start=ctx[s]["start"], end=ctx[s]["end"], nmiss=ctx[s]["nmiss"]) for s in syms}
    return dict(E=E, C=Cc, A=A, events=events, ratio=ratio, st=st, c0=c0, nuniv=len(syms), info=info, H=H)


def daily(res):
    h = np.arange(res["H"] + 1, dtype=np.int64)
    hi = np.where(((T0 + h * HOUR) % DAY == 0) & ~np.isnan(res["E"]))[0]
    return hi, res["E"][hi], res["C"][hi], res["A"][hi]


def windows(days, Dq):
    pos = {int(d): i for i, d in enumerate(days)}
    counted = positive = excl = 0
    for j, d in enumerate(days):
        if (int(d) + 3) % 7 != 0:
            continue
        s = pos.get(int(d) - 182)
        if s is None:
            excl += 1
            continue
        counted += 1
        positive += int(Dq[j] > Dq[s])
    return counted, positive, excl, int(np.sum(np.diff(days) != 1))


def metrics(hi, Dq, Cq, Aq, nuniv, drop_day=None):
    days = ((T0 + np.asarray(hi, np.int64) * HOUR) // DAY).astype(np.int64)
    Dq = np.asarray(Dq, float).copy(); Aq = np.asarray(Aq); Cq = np.asarray(Cq, float)
    if drop_day is not None:
        r = Dq[1:] / Dq[:-1]
        r[days[:-1] == drop_day] = 1.0
        Dq = np.concatenate([[Dq[0]], Dq[0] * np.cumprod(r)])
    n = len(Dq) - 1
    tr = float(Dq[-1] / Dq[0] - 1)
    ann = float((1 + tr) ** (365.0 / n) - 1) if n > 0 else float("nan")
    peak = np.maximum.accumulate(Dq)
    ys = {}
    for i, d in enumerate(days):
        ys.setdefault(yr(d), []).append(i)
    years = []
    for y in sorted(ys):
        ii = ys[y]; a = ii[0]; b = ii[-1] + 1 if ii[-1] + 1 < len(Dq) else ii[-1]
        frac = float((Aq[ii] / nuniv).min())
        years.append(dict(year=y, ret=float(Dq[b] / Dq[a] - 1), frac=frac, full=frac >= 0.8, points=len(ii)))
    mon = [i for i, d in enumerate(days) if (int(d) + 3) % 7 == 0]
    wk = [Dq[j] / Dq[i] - 1 for i, j in zip(mon, mon[1:]) if days[j] - days[i] == 7]
    ms = [i for i, d in enumerate(days) if datetime.fromtimestamp(int(d) * DAY / 1000, timezone.utc).day == 1]
    mo = [Dq[j] / Dq[i] - 1 for i, j in zip(ms, ms[1:])]
    cnt, pos_, excl, carried = windows(days, Dq)
    return dict(total=tr, ann=ann, n=n, dd_peak=float(((Dq - peak) / peak).min()), dd_cap=float((peak - Dq).max() / Dq[0]),
                years=years, worst_week=float(min(wk)) if wk else None, worst_month=float(min(mo)) if mo else None,
                sd=float(np.std(Dq[1:] / Dq[:-1] - 1, ddof=1)) if n > 1 else float("nan"),
                idle=float(np.mean(Cq / np.asarray(Dq))) if len(Cq) else float("nan"),
                win_counted=cnt, win_pos=pos_, win_excl=excl, win_carried=carried, win_share=(pos_ / cnt if cnt else None))


# ------------------------------------------------------------------ synthetic self-tests (no database access)
def mkcoin(H, start=0, end=None, o=None, mkh=None, fr=0.0001):
    end = H if end is None else end
    o = np.full(H, 100.0) if o is None else np.asarray(o, float).copy()
    c = np.append(o, o[-1])[1:]
    mh = np.maximum(o, c) if mkh is None else np.asarray(mkh, float).copy()

    def cut(a):
        a = a.copy(); a[:start] = np.nan; a[end:] = np.nan
        return a
    return dict(sp_o=cut(o), sp_c=cut(c), pp_o=cut(o), pp_c=cut(c), mk_o=cut(o), mk_h=cut(mh),
                fund=[(h, fr) for h in range(start, min(end, H)) if h % 8 == 0])


def selftest():
    out = []

    def chk(name, cond, detail=""):
        out.append(bool(cond))
        print((G + "PASS " if cond else R + "FAIL ") + name + X + (f"  {D}{detail}{X}" if detail else ""))
    H = 24 * 70                                    # Jan 1 - Mar 12 2022; rebalances at hours 0, 744, 1416
    P0 = params(); P0.update(cs=0.0, cp=0.0)
    P1 = params()
    chk("rebalance hours are the 1st of each month", rebalance_hours(H) == [0, 744, 1416])
    chk("Monday detection matches the calendar", (18995 + 3) % 7 == 0 and datetime.fromtimestamp(18995 * DAY / 1000, timezone.utc).weekday() == 0)
    W = lambda **k: dict(H=H, coins=k)
    ident = lambda r: abs(sum(x["pnl"] for x in r["st"].values()) - (r["E"][H] - 100.0)) < 1e-9

    r = simulate(W(A=mkcoin(H, fr=0.0)), P0)
    chk("flat prices, zero cost, zero funding: equity stays 100", np.allclose(r["E"], 100.0, atol=1e-9))
    r = simulate(W(A=mkcoin(H, fr=0.0)), P1)
    chk("entry cost = spot 0.15% + perp 0.10% of the 50 notional each; no cost at the next rebalance",
        abs(r["E"][0] - 99.875) < 1e-9 and abs(r["E"][744] - 99.875) < 1e-9, f"E0={r['E'][0]:.6f}")
    r = simulate(W(A=mkcoin(H, fr=0.0001)), P0)
    slow = sum(0.0001 * 0.5 * 100.0 for h in range(1, 744) if h % 8 == 0)
    chk("funding: only settlements strictly between entry and exit are paid (92 of them)", abs(r["E"][743] - (100 + slow)) < 1e-9 and abs(slow - 0.46) < 1e-9,
        f"E743={r['E'][743]:.6f} slow={slow:.6f}")
    chk("funding paid at the rebalance hour is not paid twice", abs(r["E"][744] - r["E"][743]) < 1e-9)
    chk("sum of coin P&L equals equity change (funding case)", ident(r))
    o = np.concatenate([np.linspace(100, 130, 744), np.full(H - 744, 130.0)])
    r = simulate(W(A=mkcoin(H, o=o, fr=0.0)), P0)
    chk("delta neutral: a 30% rise leaves equity at 100", np.allclose(r["E"], 100.0, atol=1e-9) and r["ratio"]["A"] > 1 and not r["events"])
    for spike_h, name, back in ((100, "liquidation then rejoin at the next rebalance", 744), (700, "liquidation within 7 days of a rebalance waits for the following one", 1416)):
        o = np.full(H, 100.0); c = np.append(o, o[-1])[1:]; mh = np.maximum(o, c); mh[spike_h] = 300.0
        r = simulate(W(A=mkcoin(H, mkh=mh, fr=0.0)), P0)
        ps = 100 / 0.5125; cashc = 0.5 * ps * 0.015
        ev = r["events"]
        chk(name, len(ev) == 1 and ev[0][1] == spike_h + 1 and abs(ev[0][2] - ps) < 1e-9 and abs(ev[0][3] - cashc) < 1e-9
            and r["st"]["A"]["status"] == "held" and r["ratio"]["A"] < 1, f"p*={ev[0][2]:.4f} cash={ev[0][3]:.6f}" if ev else "no event")
        chk("  equity after liquidation = spot leg + residual cash; position inactive while waiting",
            abs(r["E"][spike_h + 50] - (50 + cashc)) < 1e-9 and r["A"][spike_h + 50] == 0)
        chk("  coin is held again after the wait and P&L identity holds", r["A"][back + 30] == 1 and ident(r))
    r = simulate(W(A=mkcoin(H, fr=0.0), B=mkcoin(H, start=240, fr=0.0)), P0)
    chk("new coin waits for the next rebalance (entry day 31, waited 21 days)", r["st"]["B"]["entry"] == 744 and r["info"]["B"]["start"] == 240
        and (r["st"]["B"]["entry"] - r["info"]["B"]["start"]) / 24 == 21 and r["A"][500] == 1 and r["A"][800] == 2 and np.allclose(r["E"], 100.0, atol=1e-9))
    r = simulate(W(A=mkcoin(H, fr=0.0), B=mkcoin(H, end=960, fr=0.0)), P0)
    chk("coin whose data ends: cash idles at 0, then is redistributed at the next rebalance",
        abs(r["C"][1000] - 50) < 1e-9 and abs(r["E"][1000] - 100) < 1e-9 and abs(r["C"][1416]) < 1e-9 and r["A"][1500] == 1
        and r["st"]["B"]["status"] == "ended" and ident(r))
    r = simulate(W(A=mkcoin(H, end=960, fr=0.0)), P1)
    chk("exit cost at data end equals fees on both legs", abs((r["E"][959] - r["E"][960]) - 0.12484375) < 1e-9, f"drop={r['E'][959] - r['E'][960]:.8f}")
    r = simulate(W(A=mkcoin(H, fr=0.0), B=mkcoin(H, start=240, fr=0.0)), P1)
    chk("rebalance costs apply to traded notional including transfers between coins", abs(r["E"][744] - 99.75015625) < 1e-9 and ident(r),
        f"E744={r['E'][744]:.8f}")
    rng = np.random.default_rng(3)
    o = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, H)))
    o2 = o.copy(); o2[301:] *= 1.37
    r1, r2 = simulate(W(A=mkcoin(H, o=o)), P1), simulate(W(A=mkcoin(H, o=o2)), P1)
    chk("no lookahead: altering prices after hour 300 does not change equity up to hour 300", np.allclose(r1["E"][:301], r2["E"][:301], atol=1e-12))
    chk("deterministic: two runs give identical output", np.allclose(r1["E"], simulate(W(A=mkcoin(H, o=o)), P1)["E"], equal_nan=True))
    rs = simulate(W(A=mkcoin(H, o=o)), params(slip=STRESS_SLIP))
    chk("higher slippage lowers final equity", rs["E"][H] < r1["E"][H])
    d0 = 18995
    days = np.arange(d0, d0 + 400)
    chk("rolling windows: 32 counted, 26 excluded (rising curve: all positive)", windows(days, 100.0 + np.arange(400)) == (32, 32, 26, 0))
    chk("rolling windows: falling curve has none positive; a missing day is counted", windows(days, 500.0 - np.arange(400))[1] == 0
        and windows(np.delete(days, 100), np.delete(100.0 + np.arange(400), 100))[3] == 1)
    hi = np.arange(0, 6 * 24, 24)
    m = metrics(hi, [100, 120, 90, 110, 80, 130], np.zeros(6), np.ones(6, int), 1)
    chk("max drawdown on a known curve (peak basis 33.3%, capital basis 40%)", abs(m["dd_peak"] + 1 / 3) < 1e-9 and abs(m["dd_cap"] - 0.4) < 1e-9)
    m = metrics(hi, [100, 100, 100, 80, 80, 80], np.zeros(6), np.ones(6, int), 1, drop_day=int((T0 + 2 * DAY) // DAY))
    chk("dropping a day removes that day's return", abs(m["total"]) < 1e-12)
    hi = np.arange(0, 24 * 430, 24)
    m = metrics(hi, 100 * 1.001 ** np.arange(430), np.zeros(430), np.where(hi < 24 * 365, 3, 5), 5)
    y = {q["year"]: q for q in m["years"]}
    chk("full-year rule: 2022 at 60% active is partial, 2023 at 100% is full", not y[2022]["full"] and y[2023]["full"] and abs(y[2022]["frac"] - 0.6) < 1e-9)
    bad = out.count(False)
    print((G + f"ALL {len(out)} SCREEN SELF-CHECKS PASSED" if not bad else R + f"{bad} OF {len(out)} SCREEN SELF-CHECKS FAILED") + X)
    return bad == 0


# ------------------------------------------------------------------ real data (run mode only)
def load_world(cutoff_ms):
    H = int((cutoff_ms - T0) // HOUR)
    kc = sqlite3.connect("file:%s?mode=ro" % KDB, uri=True)
    fc = sqlite3.connect("file:%s?mode=ro" % FDB, uri=True)
    coins = {}
    for s in [r[0] for r in fc.execute("SELECT DISTINCT sym FROM f ORDER BY sym")]:
        d, good = {}, True
        for tbl, (ka, ia, kb, ib) in (("sp", ("sp_o", 1, "sp_c", 3)), ("pp", ("pp_o", 1, "pp_c", 3)), ("mk", ("mk_o", 1, "mk_h", 2))):
            rows = np.array(kc.execute("SELECT t,o,h,c FROM %s WHERE sym=? AND t>=? AND t<?" % tbl, (s, T0, cutoff_ms)).fetchall(), float)
            if len(rows) == 0:
                good = False
                break
            idx = ((rows[:, 0] - T0) // HOUR).astype(int)
            for key, col in ((ka, ia), (kb, ib)):
                a = np.full(H, np.nan); a[idx] = rows[:, col]; d[key] = a
        if not good:
            continue
        fr = fc.execute("SELECT t,rate FROM f WHERE sym=? AND t<? ORDER BY t", (s, cutoff_ms)).fetchall()
        d["fund"] = [(int(round((t - T0) / HOUR)), float(r)) for t, r in fr]
        coins[s] = d
    return dict(H=H, coins=coins)


def liquidity_rank(syms):
    xc = sqlite3.connect("file:%s?mode=ro" % XDB, uri=True)
    a = int(datetime(2023, 11, 11, tzinfo=timezone.utc).timestamp() * 1000)
    b = int(datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp() * 1000)
    out = []
    for s in syms:
        dd = {}
        for t, c, v in xc.execute("SELECT t,c,v FROM k WHERE sym=? AND t>=? AND t<?", (s, a, b)):
            dd[t // DAY] = dd.get(t // DAY, 0.0) + c * v
        out.append((float(np.median(list(dd.values()))) if dd else 0.0, s))
    return [s for _, s in sorted(out)]


def funding_stats(w):
    by = {}
    for s, c in w["coins"].items():
        for h, r in c["fund"]:
            by.setdefault(h // 24, {}).setdefault(s, 0.0)
            by[h // 24][s] += r
    x = np.array([np.mean(list(by[d].values())) for d in sorted(by)])
    x0 = x - x.mean()
    ac = lambda k: float((x0[:-k] * x0[k:]).sum() / (x0 * x0).sum())
    return float(x.mean() * 365), ac(1), ac(30)


def screen(m, nev, share):
    full = [y for y in m["years"] if y["full"]]
    return [(3, "net return positive in every full calendar year", (all(y["ret"] > 0 for y in full) if full else None)),
            (4, "zero liquidation events in the base model", nev == 0),
            (5, "max drawdown <= 10% of capital (larger of peak and capital basis)", max(-m["dd_peak"], m["dd_cap"]) <= 0.10),
            (6, ">= 80% of rolling 26-week windows positive", (m["win_share"] >= 0.80) if m["win_counted"] else None),
            (7, ">= 55% of coins with positive net return", share >= 0.55)]


def append_log(entry):
    log = json.load(open(LOG))
    entry["prev_hash"] = sha(json.dumps(log, sort_keys=True).encode())
    entry["id"] = "E%03d" % (len(log) + 1)
    log.append(entry)
    json.dump(log, open(LOG + ".tmp", "w"), indent=1)
    os.replace(LOG + ".tmp", LOG)
    return entry["id"]


def pct(x): return "n/a" if x is None else f"{x * 100:+.2f}%"


def run():
    import carry_verify
    ok, msg = carry_verify.verify()
    if not ok:
        raise SystemExit(R + "REFUSED: " + msg + X)
    spec = json.load(open(HIST_FILE))["spec"]
    chk = [spec["fees"]["spot_per_side"] == SPOT_FEE, spec["fees"]["perp_taker_per_side"] == PERP_FEE, spec["fees"]["slippage_per_leg_per_side"] == SLIP,
           spec["fees"]["stress_slippage"] == STRESS_SLIP, spec["liquidation"]["maintenance_rate"] == 0.025, spec["liquidation"]["penalty_of_notional"] == 0.01,
           spec["H_annual"] == H_ANNUAL]
    if not all(chk):
        raise SystemExit(R + "script constants do not match the frozen spec: stop" + X)
    code_hash = fsha(os.path.abspath(__file__))
    if any(e.get("type") == "historical_screen" and e.get("code_sha256") == code_hash for e in json.load(open(LOG))):
        raise SystemExit(R + "this exact script has already been run and logged. Nothing to do." + X)
    print(f"{C}{WORDING}{X}\n{D}specs verified: {msg}{X}")
    if not selftest():
        raise SystemExit(R + "self-checks failed: real data not read" + X)
    cutoff = spec["global_cutoff"]["window_end_utc_ms"]
    w = load_world(cutoff)
    H = w["H"]
    low5 = liquidity_rank(sorted(w["coins"]))[:5]
    w5 = dict(H=H, coins={s: c for s, c in w["coins"].items() if s not in low5})
    runs = {}

    def go(name, world, P):
        r = simulate(world, P)
        hi, Dq, Cq, Aq = daily(r)
        runs[name] = (r, metrics(hi, Dq, Cq, Aq, r["nuniv"]), (hi, Dq, Cq, Aq))
    go("base", w, params()); go("maint 1%", w, params(m=0.01)); go("maint 5%", w, params(m=0.05))
    go("slippage 0.15%", w, params(slip=STRESS_SLIP)); go("ex 5 least liquid", w5, params())
    rb, mb, (hi, Dq, Cq, Aq) = runs["base"]
    dropday = int(datetime(2023, 3, 24, tzinfo=timezone.utc).timestamp() // 86400)
    md = metrics(hi, Dq, Cq, Aq, rb["nuniv"], drop_day=dropday)
    share = lambda r: (lambda l: (sum(1 for x in l if x > 0) / len(l)) if l else 0.0)([v["pnl"] for v in r["st"].values() if v["ever"]])
    print(f"\n{C}== inputs =={X}\ncutoff (exclusive) {fd(H)}   coins {rb['nuniv']}   curve {fd(hi[0])} -> {fd(hi[-1])}   daily points {len(hi)}")
    print(f"5 least-liquid (excluded only in the robustness run): {', '.join(low5)}")
    print(f"\n{C}== per coin: start, entry (days waited), carried-forward hours, cumulative P&L (units of 100) =={X}")
    for s in sorted(rb["st"]):
        x, i = rb["st"][s], rb["info"][s]
        print(f"{s:10s} start {fd(i['start'])}  entry {fd(x['entry']) if x['entry'] is not None else 'never'}  waited {((x['entry'] - i['start']) / 24 if x['entry'] is not None else 0):4.0f}d  "
              f"holes {i['nmiss']:2d}  end {fd(i['end']) if i['end'] < H else 'cutoff'}  pnl {x['pnl']:+8.3f}")
    print(f"\n{C}== base results (maintenance 2.5%, slippage 0.05%) =={X}")
    print(f"total return {pct(mb['total'])} over {mb['n']} days; annualized {pct(mb['ann'])}; H = {H_ANNUAL * 100:.1f}%: "
          f"{'above H' if mb['ann'] > H_ANNUAL else 'not above H'} (descriptive)")
    for y in mb["years"]:
        print(f"  {y['year']}  return {pct(y['ret'])}  min active fraction {y['frac'] * 100:5.1f}%  {'FULL-YEAR' if y['full'] else 'partial'}  ({y['points']} daily points)")
    print(f"worst calendar week {pct(mb['worst_week'])}   worst calendar month {pct(mb['worst_month'])}")
    print(f"max drawdown: {mb['dd_peak'] * 100:.2f}% of peak; {mb['dd_cap'] * 100:.2f}% of initial capital")
    print(f"average idle share of equity {mb['idle'] * 100:.2f}%   daily return sd {mb['sd'] * 100:.3f}%")
    print(f"rolling 26-week windows: counted {mb['win_counted']}, positive {mb['win_pos']}, excluded as incomplete {mb['win_excl']}, missing days carried {mb['win_carried']}"
          f"  (overlapping, not independent)")
    print(f"coins with positive net return: {share(rb) * 100:.1f}%")
    mean_f, ac1, ac30 = funding_stats(w)
    print(f"{D}for the record: mean funding {mean_f * 100:.2f}%/yr on perp notional, daily mean-funding autocorrelation lag1 {ac1:.2f}, lag30 {ac30:.2f}{X}")
    print(f"\n{C}== liquidation sensitivity =={X}")
    nev = {}
    for name in ("maint 1%", "base", "maint 5%"):
        r = runs[name][0]
        near = min(((v, s) for s, v in r["ratio"].items() if np.isfinite(v)), default=(float("nan"), "-"))
        nev[name] = len(r["events"])
        print(f"{name:10s} events {len(r['events']):3d}  closest approach (margin equity / maintenance) {near[0]:.3f} at {near[1]}"
              + ("  events: " + ", ".join(f"{e[0]} {fd(e[1])}" for e in r["events"][:6]) if r["events"] else ""))
    print(f"\n{C}== other sensitivities =={X}")
    for name in ("slippage 0.15%", "ex 5 least liquid"):
        m = runs[name][1]
        print(f"{name:18s} annualized {pct(m['ann'])}  {'above H' if m['ann'] > H_ANNUAL else 'not above H'}  max drawdown {m['dd_peak'] * 100:.2f}% / {m['dd_cap'] * 100:.2f}%  events {len(runs[name][0]['events'])}")
    print(f"{'without 2023-03-24':18s} annualized {pct(md['ann'])}  max drawdown {md['dd_peak'] * 100:.2f}% / {md['dd_cap'] * 100:.2f}%  (that day's return set to 0 on the curve)")
    print(f"\n{C}== screening thresholds (descriptive screen, not a test) =={X}")
    sb = screen(mb, nev["base"], share(rb))
    r5, m5 = runs["ex 5 least liquid"][0], runs["ex 5 least liquid"][1]
    s5 = screen(m5, len(r5["events"]), share(r5))
    show = lambda v: (Y + "not evaluable" if v is None else (G + "meets" if v else R + "does not meet")) + X
    for (n, label, v), (_, _, v5) in zip(sb, s5):
        print(f"criterion {n}: {label}\n    base: {show(v)}   without the 5 least-liquid (criterion 8): {show(v5)}")
    print(f"\n{Y}{WORDING}{X}")
    entry = dict(timestamp=datetime.now(timezone.utc).isoformat(), type="historical_screen", name="carry v2.3 descriptive historical screen",
                 status="DESCRIPTIVE SCREEN COMPLETED (no significance claimed)", mandatory_wording=WORDING,
                 historical_spec_hash=json.load(open(HIST_FILE))["hash"], forward_spec_hash=json.load(open(FWD_FILE))["hash"], code_sha256=code_hash,
                 dataset_sha256={os.path.basename(p): fsha(p) for p in (KDB, FDB, XDB)}, cutoff=fd(H),
                 headline={"total_return": mb["total"], "annualized": mb["ann"], "max_drawdown_peak": mb["dd_peak"], "max_drawdown_capital": mb["dd_cap"],
                           "liquidation_events": nev, "idle_share": mb["idle"], "coins_positive_share": share(rb)},
                 thresholds={f"{n}": v for n, _, v in sb}, thresholds_ex5={f"{n}": v for n, _, v in s5},
                 observation="Descriptive results of the frozen accounting on seen historical data; see headline and thresholds.",
                 interpretation="Describes what happened historically on seen data. Not evidence of a long-term edge. No statistical significance is claimed.",
                 limitations=["survivorship: today's listed coins", "H, fees, slippage and maintenance are unverified provisional assumptions",
                              "funding was used as a direction signal in an earlier replay on 14 coins", "implementation readings listed in the script header were not in the frozen text"])
    print(f"{D}logged as {append_log(entry)}{X}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if mode == "run":
        run()
    else:
        sys.exit(0 if selftest() else 1)
