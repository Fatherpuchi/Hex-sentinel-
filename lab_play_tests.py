import os, sys, io, re, random, shutil, tempfile, contextlib, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_engine as E
import lab_play as P
from lab_data import connect, HOUR_MS

G, R, C, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[2m", "\033[0m"
T0 = (1_700_000_000_000 // HOUR_MS) * HOUR_MS
TMP = tempfile.mkdtemp(prefix="labplay_")
RAW = os.path.join(TMP, "raw.db")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print((G + "PASS " if cond else R + "FAIL ") + name + X + (f"  {D}{detail}{X}" if detail else ""))


def gen_rows(rng, n, t0, price=100.0, sd=0.01):
    rows, p = [], price
    for i in range(n):
        o = p
        p = o * math.exp(rng.gauss(0, sd))
        hi = max(o, p) * (1 + abs(rng.gauss(0, sd / 3)))
        lo = min(o, p) * (1 - abs(rng.gauss(0, sd / 3)))
        rows.append((t0 + i * HOUR_MS, o, hi, lo, p, rng.uniform(50, 150)))
    return rows


def make_db():
    rng = random.Random(5)
    conn = connect(RAW)
    for i in range(20):
        rows = gen_rows(rng, 6000, T0, sd=0.007 + 0.0003 * i)
        conn.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)", [(f"C{i:02d}USDT", "spot") + r for r in rows])
    conn.commit()
    E.build_set(conn, "t", 40, 7)
    conn.close()


def copy_of():
    p = os.path.join(TMP, f"w{random.random()}.db")
    shutil.copy(RAW, p)
    c = connect(p)
    P.ensure(c)
    return c


def first_view(conn):
    rid = [r for (r,) in conn.execute("SELECT round_id FROM rounds WHERE set_name='t' ORDER BY ord")][0]
    return rid, E.get_view(conn, "t", rid)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}" + (" WHERE player='human'" if table == "predictions" else "")).fetchone()[0]


def t_chart():
    conn = copy_of()
    rid, v = first_view(conn)
    a, b = P.render_chart(v.candles, 22, 78), P.render_chart(v.candles, 0, 78)
    plain = [P.ANSI.sub("", ln) for ln in a[:-1]]
    check("chart has 26 price rows + 3 volume rows + footer", len(a) == 30)
    check("every chart row is 8 axis + 78 candle columns", all(len(p) == 86 for p in plain))
    check("price axis labels stay fixed while panning",
          [P.ANSI.sub("", x)[:8] for x in a[:-1]] == [P.ANSI.sub("", x)[:8] for x in b[:-1]])
    check("panning changes the picture", a != b)
    check("footer fits an 88-column screen", len(P.ANSI.sub("", a[-1])) <= 88)
    syms = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM candles")}
    check("chart text names no coin", not any(s in "".join(a) for s in syms))
    cs = [(100, 101, 99, 100, 1)] * 100
    cs[50] = (100, 110, 99, 108, 5)
    cs[51] = (108, 109, 95, 96, 5)
    pg, vg, hi, lo = P.build_grid(cs, 0, 100)
    check("rising candle is a green body", any(pg[r][50] == ("█", P.G) for r in range(26)))
    check("falling candle is a red body", any(pg[r][51] == ("█", P.R) for r in range(26)))


def t_html():
    conn = copy_of()
    rid, v = first_view(conn)
    html0 = open(P.html_chart(v, TMP)).read()
    check("HTML chart draws exactly 100 candles", html0.count('class="c"') == 100)
    syms = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM candles")}
    check("HTML names no coin", not any(s in html0 for s in syms))
    sym, st = conn.execute("SELECT symbol,start_time FROM rounds WHERE round_id=?", (rid,)).fetchone()
    t1, t2 = st + E.VISIBLE * HOUR_MS, st + E.SPAN * HOUR_MS
    conn.execute("UPDATE candles SET o=o*2,h=h*2,l=l*2,c=c*2,v=v*2 WHERE symbol=? AND open_time>=? AND open_time<?", (sym, t1, t2))
    conn.commit()
    html1 = open(P.html_chart(E.get_view(conn, "t", rid), TMP)).read()
    check("scrambling the future leaves the HTML identical", html0 == html1)


def t_flow():
    keep = (P.getkey, P.ask, P.BLOCK)

    def fake_ask(prompt):
        p = prompt.lower()
        if "your call" in p:
            return "u"
        if "confidence" in p:
            return "70"
        if p.startswith("lock"):
            return "y"
        return ""

    P.ask = fake_ask
    P.getkey = lambda: "p"
    P.BLOCK = 3
    check("reveal rule: block waits for 3", not P.should_reveal(2, 10, "block") and P.should_reveal(3, 10, "block"))
    check("reveal rule: last rounds of a set are revealed", P.should_reveal(1, 0, "block"))
    check("reveal rule: each mode reveals immediately", P.should_reveal(1, 10, "each") and not P.should_reveal(0, 10, "each"))
    conn = copy_of()
    o1 = io.StringIO()
    with contextlib.redirect_stdout(o1):
        P.play(conn, "t", "block", limit=3)
    check("3 calls locked as 'human'", count(conn, "predictions") == 3)
    check("block of 3 was revealed", count(conn, "reveals") == 3 and "result" in o1.getvalue())
    o2 = io.StringIO()
    with contextlib.redirect_stdout(o2):
        P.play(conn, "t", "block", limit=2)
    check("2 more locked, nothing revealed early", count(conn, "predictions") == 5 and count(conn, "reveals") == 3
          and "result" not in o2.getvalue())
    s = P.session_stats(conn, "t")
    check("record counts only revealed rounds", s["n"] + s["void"] == 3, str(s))
    o3 = io.StringIO()
    with contextlib.redirect_stdout(o3):
        P.play(conn, "t", "each", limit=1)
    check("each mode reveals the very next call (and flushes the waiting 2)", count(conn, "reveals") == 6 and "result" in o3.getvalue())
    try:
        E.lock_prediction(conn, "t", P.played(conn, "t")[0], "human", "DOWN", 50)
        check("a played round cannot be re-locked", False)
    except E.LockedError:
        check("a played round cannot be re-locked", True)
    c2 = copy_of()
    P.getkey = lambda: "q"
    with contextlib.redirect_stdout(io.StringIO()):
        P.play(c2, "t", "block", limit=5)
    check("quitting at the chart locks nothing", count(c2, "predictions") == 0)
    P.getkey, P.ask, P.BLOCK = keep


if __name__ == "__main__":
    print(f"{C}building synthetic data in {TMP} ...{X}")
    make_db()
    for t in (t_chart, t_html, t_flow):
        print(f"{C}-- {t.__name__}{X}")
        try:
            t()
        except Exception as e:
            check(t.__name__ + " ran without an exception", False, repr(e))
    shutil.rmtree(TMP, ignore_errors=True)
    bad = RESULTS.count(False)
    print((G + f"ALL {len(RESULTS)} CHECKS PASSED" if not bad else R + f"{bad} OF {len(RESULTS)} CHECKS FAILED") + X)
    sys.exit(1 if bad else 0)
