import os, sys, json, sqlite3, hashlib, tempfile
from datetime import datetime, timezone
import numpy as np
import carry_screen as S

HERE = os.path.dirname(os.path.abspath(__file__))
FDB, COINS, HARNESS = (os.path.join(HERE, n) for n in ("carry_forward.db", "carry_forward_coins.json", "harness.db"))
G, R, Y, C, D, X = S.G, S.R, S.Y, S.C, S.D, S.X
HOUR, DAY, ORIG_PREP = S.HOUR, S.DAY, S.prep
SERIES = (("sp", "sp_o", "sp_c", 1, 3), ("pp", "pp_o", "pp_c", 1, 3), ("mk", "mk_o", "mk_h", 1, 2))


def ro(path): return sqlite3.connect("file:%s?mode=ro" % path, uri=True)
def fsha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
def fd(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def common_end(conn, coins):
    ends = []
    for t in ("sp", "pp", "mk"):
        for s in coins:
            r = conn.execute("SELECT MAX(t) FROM %s WHERE sym=?" % t, (s,)).fetchone()[0]
            if r is not None:
                ends.append((r + HOUR, s))
    return min(ends) if ends else (None, None)


def build_world(conn, coins, start_ms, t_end):
    H = int((t_end - S.T0) // HOUR)
    out, absent = {}, []
    for s in coins:
        d, good = {}, True
        for tbl, ka, kb, ia, ib in SERIES:
            rows = np.array(conn.execute("SELECT t,o,h,c FROM %s WHERE sym=? AND t>=? AND t<?" % tbl, (s, start_ms, t_end)).fetchall(), float)
            if len(rows) == 0:
                good = False
                break
            idx = ((rows[:, 0] - S.T0) // HOUR).astype(int)
            for key, col in ((ka, ia), (kb, ib)):
                a = np.full(H, np.nan); a[idx] = rows[:, col]; d[key] = a
        if not good:
            absent.append(s)
            continue
        fr = conn.execute("SELECT t,rate FROM f WHERE sym=? AND t>=? AND t<? ORDER BY t", (s, start_ms, t_end)).fetchall()
        d["fund"] = [(int(round((t - S.T0) / HOUR)), float(r)) for t, r in fr]
        out[s] = d
    return dict(H=H, coins=out), absent


def prep_fwd(c, H, h0):
    ok = ~(np.isnan(c["sp_o"]) | np.isnan(c["pp_o"]) | np.isnan(c["mk_o"]) | np.isnan(c["mk_h"]))
    if not ok[h0]:
        return None
    end = int(np.where(ok)[0][-1]) + 1
    bsp = np.full(H + 1, np.nan); bsp[:H] = c["sp_o"]; bsp[end:] = c["sp_c"][end - 1]
    bpp = np.full(H + 1, np.nan); bpp[:H] = c["pp_o"]; bpp[end:] = c["pp_c"][end - 1]
    pairs = sorted((h, r) for h, r in c["fund"] if h0 <= h < min(end, H))
    return dict(start=h0, end=end, bsp=S.ffill(bsp), bpp=S.ffill(bpp), mko=S.ffill(c["mk_o"]), mkh=S.ffill(c["mk_h"]),
                fh=np.array([h for h, _ in pairs], int), fr=np.array([r for _, r in pairs], float), nmiss=int((~ok[h0:end]).sum()))


def compute(conn, coins, start_ms):
    t_end, limiting = common_end(conn, coins)
    if t_end is None or t_end <= start_ms:
        return dict(status="no forward candles yet")
    world, absent = build_world(conn, coins, start_ms, t_end)
    if not world["coins"]:
        return dict(status="no coin has data at the forward start")
    H, h0 = world["H"], int((start_ms - S.T0) // HOUR)
    rebs = [h0] + [r for r in S.rebalance_hours(H) if r > h0]
    S.prep = lambda c, HH: prep_fwd(c, HH, h0)
    try:
        res = S.simulate(world, S.params(), rebs=rebs)
    finally:
        S.prep = ORIG_PREP
    hi, Dq, Cq, Aq = S.daily(res)
    obs, stub = [], None
    if len(hi):
        stub = float(Dq[0] / 100.0 - 1)
        obs = [(int((S.T0 + int(hi[i - 1]) * HOUR) // DAY), float(Dq[i] / Dq[i - 1] - 1)) for i in range(1, len(hi))]
    return dict(status="ok" if len(hi) else "no complete UTC midnight yet", res=res, obs=obs, stub=stub, Dq=Dq, hi=hi, rebs=rebs, h0=h0, H=H,
                t_end=t_end, limiting=limiting, absent=absent, waiting=[s for s in world["coins"] if s not in res["st"]],
                eq_now=float(res["E"][H]), idle=float(np.nanmean(res["C"][h0:H] / res["E"][h0:H])))


def report(comp, start_ms):
    print(f"{C}FORWARD, PAPER-ONLY observation of a frozen specification on data collected after the freeze. No orders are placed. No profitability claim is made, and no significance is claimed. A short forward period cannot support either.{X}")
    if comp["status"] not in ("ok", "no complete UTC midnight yet"):
        print(Y + comp["status"] + X); return
    r = comp["res"]
    wk = (comp["t_end"] - start_ms) / (7 * DAY)
    print(f"forward start {fd(start_ms)} UTC; data through {fd(comp['t_end'])} UTC (set by {comp['limiting']}); {wk:.2f} weeks elapsed (minimum review at 26)")
    print(f"coins in portfolio {r['nuniv']}   waiting for next rebalance {comp['waiting'] or 'none'}   no data at all {comp['absent'] or 'none'}")
    print(f"equity now {comp['eq_now']:.4f} (start 100)   since start {(comp['eq_now'] / 100 - 1) * 100:+.4f}%   average idle share {comp['idle'] * 100:.2f}%")
    miss = {s: v["nmiss"] for s, v in r["info"].items() if v["nmiss"]}
    print(f"missing candle hours carried forward: {miss or 'none'}   liquidation events: {len(r['events'])}")
    for e in r["events"][:10]: print(f"  liquidation {e[0]} {S.fd(e[1])}")
    if comp["status"] != "ok":
        print(Y + "less than one UTC midnight of data: no daily values yet" + X); return
    print(f"first partial day (entry to first 00:00 UTC, includes entry costs): {comp['stub'] * 100:+.4f}%")
    print(f"daily values (UTC day start -> next 00:00), {len(comp['obs'])} complete days; last 14:")
    for d, v in comp["obs"][-14:]:
        print(f"  {datetime.fromtimestamp(d * DAY / 1000, timezone.utc):%Y-%m-%d}  {v * 100:+.4f}%")
    print(f"{D}Not annualized and not compared with H: a short forward period cannot support either. Nothing was written.{X}")


# ----------------------------------------------------------------------------- synthetic self-tests
def mkdb(coins, h0, nh, price=None, fund=None, drop=None, start_at=None):
    c = sqlite3.connect(":memory:")
    for t in ("sp", "pp", "mk"):
        c.execute("CREATE TABLE %s(sym TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,PRIMARY KEY(sym,t))" % t)
    c.execute("CREATE TABLE f(sym TEXT,t INTEGER,rate REAL,mark REAL,PRIMARY KEY(sym,t))")
    for s in coins:
        for k in range((start_at or {}).get(s, 0), nh):
            sp, pp = (100.0, 100.0) if price is None else price(s, k)
            t = S.T0 + (h0 + k) * HOUR
            if not (drop and (s, k) in drop):
                c.execute("INSERT INTO sp VALUES(?,?,?,?,?,?)", (s, t, sp, sp, sp, sp))
            c.execute("INSERT INTO pp VALUES(?,?,?,?,?,?)", (s, t, pp, pp, pp, pp))
            c.execute("INSERT INTO mk VALUES(?,?,?,?,?,?)", (s, t, pp, pp, pp, pp))
        for k, r in (fund or {}).get(s, []):
            c.execute("INSERT INTO f VALUES(?,?,?,?)", (s, S.T0 + (h0 + k) * HOUR, r, 100.0))
    return c


def selftest():
    out = []
    def chk(n, v, d=""):
        out.append(bool(v)); print((G + "PASS " if v else R + "FAIL ") + n + X + (D + "  " + str(d) + X if d else ""))
    hr = lambda y, m, d, h: int((datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000 - S.T0) // HOUR)
    sm = lambda h0: S.T0 + h0 * HOUR
    h0 = hr(2026, 10, 11, 13)
    A, B2 = ["A"], ["A", "B"]
    c = compute(mkdb(B2, h0, 60), B2, sm(h0))
    E = c["res"]["E"]
    chk("flat, two coins: entry costs 0.125 in total, equity 99.875 from the forward start (13:00, not midnight)", abs(E[h0] - 99.875) < 1e-9 and abs(E[h0 + 59] - 99.875) < 1e-9, f"{E[h0]:.6f}")
    chk("first complete day starts at the first 00:00 UTC; stub is the entry cost", c["hi"][0] == h0 + 11 and abs(c["stub"] + 0.00125) < 1e-12)
    chk("flat prices: every complete daily value is zero", all(abs(v) < 1e-12 for _, v in c["obs"]) and len(c["obs"]) == 2, len(c["obs"]))
    N = (100 - 0.125) / 2; F = 0.0001 * N
    c = compute(mkdb(A, h0, 60, fund={"A": [(0, 0.01), (3, 0.0001), (11, 0.0001), (19, 0.0001)]}), A, sm(h0))
    E = c["res"]["E"]
    chk("a funding record at the entry hour is not paid", abs(E[h0] - 99.875) < 1e-9)
    chk("funding strictly after entry is paid at its own hour: 3 payments", abs(E[h0 + 2] - 99.875) < 1e-9 and abs(E[h0 + 3] - (99.875 + F)) < 1e-9 and abs(E[h0 + 59] - (99.875 + 3 * F)) < 1e-9,
        f"{E[h0 + 59] - 99.875:.8f} vs {3 * F:.8f}")
    rng = np.random.default_rng(5); nh = 60
    walk = {s: 100 * np.exp(np.cumsum(rng.normal(0, 0.003, nh))) for s in B2}
    basis = {s: 1 + 0.002 * rng.normal(size=nh) for s in B2}
    p1 = lambda s, k: (walk[s][k], walk[s][k] * basis[s][k])
    p2 = lambda s, k: ((walk[s][k] * 1.3, walk[s][k] * 1.3 * basis[s][k] * 1.01) if k >= 33 else p1(s, k))
    fu = {s: [(3, 0.0001), (11, 0.0002), (19, 0.0001), (27, 0.0003), (35, 0.0001)] for s in B2}
    fu2 = {s: [(3, 0.0001), (11, 0.0002), (19, 0.0001), (27, 0.0003), (35, 0.05)] for s in B2}
    c1, c2 = compute(mkdb(B2, h0, nh, p1, fu), B2, sm(h0)), compute(mkdb(B2, h0, nh, p2, fu2), B2, sm(h0))
    chk("no lookahead: changing prices from hour 33 and funding from hour 35 leaves equity before hour 33 unchanged", np.allclose(c1["res"]["E"][h0:h0 + 33], c2["res"]["E"][h0:h0 + 33], atol=1e-12)
        and not np.allclose(c1["res"]["E"][h0 + 40:h0 + 59], c2["res"]["E"][h0 + 40:h0 + 59]))
    chk("deterministic: the same data gives identical equity", np.allclose(c1["res"]["E"], compute(mkdb(B2, h0, nh, p1, fu), B2, sm(h0))["res"]["E"], equal_nan=True))
    prod = (1 + c1["stub"]) * np.prod([1 + v for _, v in c1["obs"]])
    chk("stub and daily values compound exactly to the last midnight equity", abs(prod - c1["Dq"][-1] / 100) < 1e-12)
    chk("the swapped-in prep is always restored", S.prep is ORIG_PREP)
    c = compute(mkdb(B2, h0, 60, drop={("A", 20)}), B2, sm(h0))
    chk("a missing spot candle is counted, carried forward, and equity stays finite", c["res"]["info"]["A"]["nmiss"] == 1 and np.isfinite(c["res"]["E"][h0:c["H"]]).all(), c["res"]["info"]["A"]["nmiss"])
    c = compute(mkdb(B2, h0, 60, start_at={"B": 5}), B2, sm(h0))
    chk("a coin with no candle at the forward start is not entered and is reported as waiting", c["waiting"] == ["B"] and "B" not in c["res"]["st"] and abs(c["res"]["E"][h0] - 99.875) < 1e-9)
    c = compute(mkdb(["A", "B"], h0, 60, drop=None), ["A", "B", "Z"], sm(h0))
    chk("a coin with no rows at all is reported as absent", c["absent"] == ["Z"])
    hb = hr(2026, 10, 30, 13)
    c = compute(mkdb(A, hb, 70), A, sm(hb))
    nov1 = hr(2026, 11, 1, 0)
    chk("monthly rebalance is scheduled at 00:00 on the 1st; a balanced book pays no extra cost", nov1 in c["rebs"] and abs(c["res"]["E"][nov1] - 99.875) < 1e-9 and abs(c["res"]["E"][hb + 69] - 99.875) < 1e-9)
    c = compute(mkdb(A, h0, 5), A, sm(h0))
    chk("less than one midnight of data: no daily values and no crash", c["status"] == "no complete UTC midnight yet" and c["obs"] == [])
    chk("no candles after the start: reported, not a crash", compute(mkdb(A, h0, 0), A, sm(h0))["status"] == "no forward candles yet")
    p = os.path.join(tempfile.mkdtemp(), "t.db"); w = sqlite3.connect(p); w.execute("CREATE TABLE x(a)"); w.commit(); w.close()
    try:
        ro(p).execute("INSERT INTO x VALUES(1)"); wr = False
    except sqlite3.DatabaseError:
        wr = True
    chk("the read-only connection refuses writes", wr)
    called = []
    st = gate(lambda: (False, "synthetic failure"), lambda: called.append(1))
    chk("a failed spec verification stops the run before any computation", st == 1 and not called)
    bad = bad_constants({"fees": {"spot_per_side": 0.002, "perp_taker_per_side": 0.0005, "slippage_per_leg_per_side": 0.0005, "stress_slippage": 0.0015},
                         "liquidation": {"maintenance_rate": 0.025, "penalty_of_notional": 0.01}, "H_annual": 0.04})
    chk("constants that differ from the frozen spec are caught", bad)
    n = out.count(False)
    print((G + "ALL %d FORWARD-OBSERVATION SELF-CHECKS PASSED" % len(out) if not n else R + "%d OF %d FAILED" % (n, len(out))) + X)
    return n == 0


def bad_constants(spec):
    return not all([spec["fees"]["spot_per_side"] == S.SPOT_FEE, spec["fees"]["perp_taker_per_side"] == S.PERP_FEE, spec["fees"]["slippage_per_leg_per_side"] == S.SLIP,
                    spec["fees"]["stress_slippage"] == S.STRESS_SLIP, spec["liquidation"]["maintenance_rate"] == 0.025,
                    spec["liquidation"]["penalty_of_notional"] == 0.01, spec["H_annual"] == S.H_ANNUAL])


def gate(verify, go):
    ok, msg = verify()
    if not ok:
        print(R + "REFUSED: " + msg + X); return 1
    go(); return 0


def run():
    import carry_verify
    def go():
        h = json.load(open(S.HIST_FILE))["spec"]; f = json.load(open(S.FWD_FILE))["spec"]
        if bad_constants(h) or not str(f["mode"]).startswith("PAPER ONLY"):
            sys.exit(R + "script constants or mode do not match the frozen specs: stop" + X)
        if not os.path.exists(FDB) or not os.path.exists(COINS):
            sys.exit(R + "carry_forward.db or the coin list is missing: run the collector first" + X)
        ms = int(datetime.fromisoformat(f["forward_start_utc"]).timestamp() * 1000); ms = -(-ms // HOUR) * HOUR
        coins = json.load(open(COINS))["coins"]
        before = fsha(HARNESS)
        comp = compute(ro(FDB), coins, ms)
        report(comp, ms)
        print((G + "harness.db unchanged (sha256 %s)" % (before or "none")[:16] if fsha(HARNESS) == before else R + "HARNESS.DB CHANGED: investigate") + X)
    return gate(carry_verify.verify, go)


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if m == "run":
        if not selftest():
            sys.exit(R + "self-checks failed: real data not read" + X)
        sys.exit(run())
    sys.exit(0 if selftest() else 1)
