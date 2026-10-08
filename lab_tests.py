import os, sys, math, random, shutil, tempfile, dataclasses
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_engine as E
from lab_data import connect, HOUR_MS

G, R, C, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[2m", "\033[0m"
T0 = (1_700_000_000_000 // HOUR_MS) * HOUR_MS
SYMS = [f"C{i:02d}USDT" for i in range(20)]
TMP = tempfile.mkdtemp(prefix="labtest_")
RAW, BUILT = os.path.join(TMP, "raw.db"), os.path.join(TMP, "built.db")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print((G + "PASS " if cond else R + "FAIL ") + name + X + (f"  {D}{detail}{X}" if detail else ""))


def gen_rows(rng, n, t0, price=100.0, sd=0.01, drift=0.0):
    rows, p = [], price
    for i in range(n):
        o = p
        p = o * math.exp(rng.gauss(drift, sd))
        hi = max(o, p) * (1 + abs(rng.gauss(0, sd / 3)))
        lo = min(o, p) * (1 - abs(rng.gauss(0, sd / 3)))
        rows.append((t0 + i * HOUR_MS, o, hi, lo, p, rng.uniform(50, 150)))
    return rows


def make_dbs():
    rng = random.Random(5)
    conn = connect(RAW)
    for i, sym in enumerate(SYMS):
        rows = gen_rows(rng, 6000, T0, sd=0.007 + 0.0003 * i)
        conn.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)", [(sym, "spot") + r for r in rows])
    conn.commit()
    conn.close()
    shutil.copy(RAW, BUILT)
    c = connect(BUILT)
    E.build_set(c, "t", 60, 7)
    c.close()


def copy_of(path):
    p = os.path.join(TMP, f"w{random.random()}.db")
    shutil.copy(path, p)
    return connect(p)


def rids_of(conn, name="t"):
    return [r for (r,) in conn.execute("SELECT round_id FROM rounds WHERE set_name=? ORDER BY ord", (name,))]


def t_future_scramble():
    conn, rng = copy_of(BUILT), random.Random(1)
    rids = rids_of(conn)
    views0 = {r: E.get_view(conn, "t", r) for r in rids}
    preds0 = {r: [fn(views0[r]) for fn in E.OPPONENTS.values()] for r in rids}
    ret0 = {r: E._outcome(conn, "t", r).ret for r in rids}
    for r in rids:
        sym, st = conn.execute("SELECT symbol,start_time FROM rounds WHERE round_id=?", (r,)).fetchone()
        f = rng.uniform(1.3, 2.5)
        t1, t2 = st + E.VISIBLE * HOUR_MS, st + E.SPAN * HOUR_MS
        conn.execute("UPDATE candles SET o=o*?,h=h*?,l=l*?,c=c*?,v=v*? WHERE symbol=? AND open_time>=? AND open_time<?",
                     (f, f, f, f, f, sym, t1, t2))
    conn.commit()
    same_v = all(E.get_view(conn, "t", r) == views0[r] for r in rids)
    same_p = all([fn(E.get_view(conn, "t", r)) for fn in E.OPPONENTS.values()] == preds0[r] for r in rids)
    changed = all(abs(E._outcome(conn, "t", r).ret - ret0[r]) > 1e-6 for r in rids)
    check("scrambled future: views identical", same_v)
    check("scrambled future: every opponent prediction identical", same_p)
    check("scrambled future: outcomes DID change (scramble was effective)", changed)


def t_truncation():
    conn = copy_of(BUILT)
    ok = True
    for r in rids_of(conn):
        sym, st = conn.execute("SELECT symbol,start_time FROM rounds WHERE round_id=?", (r,)).fetchone()
        t_dec = st + E.VISIBLE * HOUR_MS
        rows = conn.execute("SELECT open_time,o,h,l,c,v FROM candles WHERE symbol=? AND open_time<? "
                            "ORDER BY open_time DESC LIMIT ?", (sym, t_dec, E.VISIBLE)).fetchall()[::-1]
        ok &= (E.make_view(r, rows) == E.get_view(conn, "t", r))
    check("series cut at decision time gives the same view", ok)


def t_cheater():
    conn = copy_of(BUILT)
    for r in rids_of(conn):
        o = E._outcome(conn, "t", r)
        E.lock_prediction(conn, "t", r, "cheater", o.direction if o.direction != "FLAT" else "UP", 100)
    s = E.score_player(conn, "t", "cheater")
    check("cheater control scores 100%: scorer can detect leakage", s["n"] > 0 and s["correct"] == s["n"],
          f"{s['correct']}/{s['n']}")
    E.run_opponents(conn, "t")
    honest = [E.score_player(conn, "t", p) for p in E.OPPONENTS]
    check("honest opponents are NOT at 100%", all(h["correct"] < h["n"] for h in honest))


def _world(planted, seed, rounds=2500):
    rng, stats = random.Random(seed), {}
    mom = lambda v: ("UP" if v.candles[-1][3] > v.candles[-21][3] else "DOWN", 70)
    players = dict(E.OPPONENTS, momentum=mom)
    for i in range(rounds):
        vis = gen_rows(rng, E.VISIBLE, T0, sd=0.01)
        drift = 0.0
        if planted:
            drift = 0.004 if vis[-1][4] > vis[-21][4] else -0.004
        ah = gen_rows(rng, E.AHEAD, T0 + E.VISIBLE * HOUR_MS, price=vis[-1][4], sd=0.01, drift=drift)
        rid = f"N{seed}_{i}"
        view, o = E.make_view(rid, vis), E.make_outcome(rid, vis, ah)
        if o.direction == "FLAT":
            continue
        for name, fn in players.items():
            k = stats.setdefault(name, [0, 0])
            k[1] += 1
            k[0] += (fn(view)[0] == o.direction)
    return stats


def t_null_world():
    stats = _world(False, 11)
    ok = True
    detail = []
    for name, (k, n) in stats.items():
        acc = k / n
        ok &= abs(acc - 0.5) < 4 * math.sqrt(0.25 / n)
        detail.append(f"{name} {acc * 100:.1f}%")
    check("independent-returns world: every opponent ~50%", ok, ", ".join(detail))


def t_planted():
    stats = _world(True, 12)
    k, n = stats["momentum"]
    ku, nu = stats["always_up"]
    check("planted momentum effect is detected (>80%)", k / n > 0.8, f"momentum {k / n * 100:.1f}% on {n} rounds")
    check("planted effect: always_up still ~50%", abs(ku / nu - 0.5) < 4 * math.sqrt(0.25 / nu), f"{ku / nu * 100:.1f}%")


def t_structure():
    conn = copy_of(BUILT)
    rows = conn.execute("SELECT round_id,symbol,start_time,stratum FROM rounds WHERE set_name='t'").fetchall()
    check("set has 60 unique rounds", len(rows) == 60 and len({r[0] for r in rows}) == 60)
    by = {}
    for _, s, st, _ in rows:
        by.setdefault(s, []).append(st)
    gap_ok = all(b - a >= E.SPAN * HOUR_MS for v in by.values() for a, b in zip(sorted(v), sorted(v)[1:]))
    check("no overlapping rounds on any coin", gap_ok)
    days = {}
    for _, _, st, _ in rows:
        d = (st + E.VISIBLE * HOUR_MS) // E.DAY_MS
        days[d] = days.get(d, 0) + 1
    check("per-day cap respected", max(days.values()) <= E.MAX_PER_DAY, f"max {max(days.values())}")
    tmax = conn.execute("SELECT MAX(open_time) FROM candles").fetchone()[0]
    cutoff = tmax - E.EXCLUDE_LATEST_DAYS * E.DAY_MS
    check("newest period excluded", all(st + E.SPAN * HOUR_MS <= cutoff for _, _, st, _ in rows))
    cnt = {}
    for r in rows:
        cnt[r[3]] = cnt.get(r[3], 0) + 1
    check("9 strata, quota 6-7 each", len(cnt) == 9 and all(6 <= v <= 7 for v in cnt.values()), str(sorted(cnt.values())))
    check("frozen hash verifies", E.verify(conn, "t"))
    sym, st = rows[0][1], rows[0][2]
    conn.execute("UPDATE candles SET c=c*1.0001 WHERE symbol=? AND open_time=?", (sym, st + 5 * HOUR_MS))
    conn.commit()
    check("tampering with a candle breaks the hash", not E.verify(conn, "t"))


def t_holdout_and_determinism():
    c = copy_of(BUILT)
    E.build_set(c, "h", 30, 8)
    a = {(r[0], r[1]) for r in c.execute("SELECT symbol,start_time FROM rounds WHERE set_name='t'")}
    b = {(r[0], r[1]) for r in c.execute("SELECT symbol,start_time FROM rounds WHERE set_name='h'")}
    check("holdout shares no window with the benchmark", len(b) == 30 and not (a & b))
    c1, c2, c3 = copy_of(RAW), copy_of(RAW), copy_of(RAW)
    E.build_set(c1, "a", 40, 3)
    E.build_set(c2, "b", 40, 3)
    E.build_set(c3, "c", 40, 4)
    q = "SELECT symbol,start_time,stratum FROM rounds ORDER BY ord"
    check("same seed gives the same selection", c1.execute(q).fetchall() == c2.execute(q).fetchall())
    check("different seed gives a different selection", c1.execute(q).fetchall() != c3.execute(q).fetchall())


def t_full_size():
    c = copy_of(RAW)
    E.build_set(c, "big", 300, 1)
    rows = c.execute("SELECT symbol,start_time FROM rounds WHERE set_name='big'").fetchall()
    check("a full 300-round set can actually be built", len(rows) == 300, f"{len(rows)} rounds")
    check("full set uses at least 18 coins", len({r[0] for r in rows}) >= 18)
    days = {}
    for _, st in rows:
        d = (st + E.VISIBLE * HOUR_MS) // E.DAY_MS
        days[d] = days.get(d, 0) + 1
    check("full set respects per-day cap", max(days.values()) <= E.MAX_PER_DAY, f"max {max(days.values())}")
    E.build_set(c, "big2", 100, 2)
    r2 = c.execute("SELECT symbol,start_time FROM rounds WHERE set_name='big2'").fetchall()
    span = E.SPAN * HOUR_MS
    clash = any(s == s2 and abs(t - t2) < span for s, t in rows for s2, t2 in r2)
    check("second set overlaps no window of the first (even partially)", len(r2) == 100 and not clash, f"{len(r2)} rounds")


def t_lock_reveal():
    conn = copy_of(BUILT)
    r = rids_of(conn)[0]
    try:
        E.reveal(conn, "t", r, "human")
        check("reveal before lock is refused", False)
    except E.LockedError:
        check("reveal before lock is refused", True)
    E.lock_prediction(conn, "t", r, "human", "UP", 70)
    o, p = E.reveal(conn, "t", r, "human")
    check("reveal after lock works", o.direction in ("UP", "DOWN", "FLAT") and p == ("UP", 70))
    try:
        E.lock_prediction(conn, "t", r, "human", "DOWN", 50)
        check("a locked prediction cannot be changed", False)
    except E.LockedError:
        check("a locked prediction cannot be changed", True)
    bad = 0
    for d, cf in (("SIDEWAYS", 50), ("UP", 55), ("UP", 40)):
        try:
            E.lock_prediction(conn, "t", r, "x", d, cf)
        except ValueError:
            bad += 1
    check("invalid direction/confidence rejected", bad == 3)


def t_blindness():
    conn = copy_of(BUILT)
    syms = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM candles")}
    ok_f = {f.name for f in dataclasses.fields(E.RoundView)} == {"round_id", "candles"}
    check("RoundView carries only round_id and candles", ok_f)
    ok = True
    for r in rids_of(conn):
        v = E.get_view(conn, "t", r)
        ok &= len(v.candles) == E.VISIBLE and all(len(c) == 5 for c in v.candles)
        ok &= abs(v.candles[-1][3] - 100.0) < 1e-9
        ok &= max(x for c in v.candles for x in c) < 1e5          # no timestamps hiding in values
        ok &= not any(s in v.round_id or s in repr(v) for s in syms)
    check("views are anonymous: no symbol, no time, price-normalised", ok)


if __name__ == "__main__":
    print(f"{C}building synthetic data in {TMP} ...{X}")
    make_dbs()
    for t in (t_future_scramble, t_truncation, t_cheater, t_null_world, t_planted,
              t_structure, t_holdout_and_determinism, t_full_size, t_lock_reveal, t_blindness):
        print(f"{C}-- {t.__name__}{X}")
        try:
            t()
        except Exception as e:
            check(t.__name__ + " ran without an exception", False, repr(e))
    shutil.rmtree(TMP, ignore_errors=True)
    bad = RESULTS.count(False)
    print((G + f"ALL {len(RESULTS)} CHECKS PASSED" if not bad else R + f"{bad} OF {len(RESULTS)} CHECKS FAILED") + X)
    sys.exit(1 if bad else 0)
