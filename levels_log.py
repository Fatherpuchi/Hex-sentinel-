#!/usr/bin/env python3
"""levels_log.py - levels_v1 (frozen spec: levels_v1_spec.md). Shadow only.
Writes ONLY the table shadow_levels in shadow.db (on `run`). Never touches
decisions, plans, the guard, the AIs or the live path.
Usage: python3 levels_log.py selftest | check | run | report"""
import sys
import time
import sqlite3
import datetime

DB = "shadow.db"
H = 3600000
MULT = {"stop": 0.5, "tp1": 0.5, "tp2": 1.0, "tp3": 1.5}
NEED_PRE = 168
POST_N = 24
DUE_H = 25
MAX_ROWS = 40
SCHEMA = (
    "create table if not exists shadow_levels("
    "id integer primary key autoincrement, created_utc text, cf_id integer unique, "
    "symbol text, direction text, entry real, u_pct real, stop real, tp1 real, tp2 real, "
    "tp3 real, outcome text, r_result real, candles_used integer, source text, "
    "status text, reason text)"
)


def contiguous_suffix(cs):
    if not cs:
        return []
    i = len(cs) - 1
    while i > 0 and cs[i][0] - cs[i - 1][0] == H:
        i -= 1
    return cs[i:]


def unit_u(run):
    if len(run) < NEED_PRE:
        return None
    last = run[-NEED_PRE:]
    lc = last[-1][4]
    if lc <= 0:
        return None
    rs = []
    for i in range(7):
        blk = last[24 * i:24 * i + 24]
        hi = max(x[2] for x in blk)
        lo = min(x[3] for x in blk)
        rs.append((hi - lo) / lc)
    rs.sort()
    return rs[3]


def make_levels(entry, direction, u):
    sgn = 1.0 if direction == "BUY" else -1.0
    sd = MULT["stop"] * u * entry
    stop = entry - sgn * sd
    tps = [entry + sgn * MULT[k] * u * entry for k in ("tp1", "tp2", "tp3")]
    return stop, tps, sd


def grade_path(entry, direction, stop, tps, post, sd):
    buy = direction == "BUY"
    best = 0
    for c in post:
        hi, lo = c[2], c[3]
        stop_hit = (lo <= stop) if buy else (hi >= stop)
        top = 0
        for n, t in enumerate(tps, 1):
            if (hi >= t) if buy else (lo <= t):
                top = n
        if stop_hit:
            if top > best:
                return "AMBIGUOUS", None
            if best > 0:
                return "TP%d" % best, float(best)
            return "STOP", -1.0
        if top > best:
            best = top
        if best == 3:
            return "TP3", 3.0
    if best > 0:
        return "TP%d" % best, float(best)
    close = post[-1][4]
    ret = (close - entry) / entry if buy else (entry - close) / entry
    return "EXPIRED", ret / (sd / entry)


def _na(reason):
    return {"status": "UNAVAILABLE", "reason": reason, "u": None, "stop": None,
            "tps": [None, None, None], "outcome": "UNAVAILABLE", "r": None, "used": 0}


def grade_row(entry, direction, call_ms, cs):
    try:
        entry = float(entry)
    except Exception:
        entry = 0.0
    if entry <= 0 or direction not in ("BUY", "SELL"):
        return _na("bad entry or direction")
    cs = sorted(cs, key=lambda x: x[0])
    pre = [c for c in cs if c[0] + H <= call_ms]
    f0 = (call_ms // H) * H + H
    post = [c for c in cs if c[0] >= f0][:POST_N]
    run = contiguous_suffix(pre)
    last_open = ((call_ms - H) // H) * H
    if not run or run[-1][0] != last_open:
        return _na("no closed candle just before the call")
    u = unit_u(run)
    if u is None:
        return _na("fewer than 168 gap-free closed candles")
    if u <= 0:
        return _na("zero volatility unit")
    ok = (len(post) == POST_N and post[0][0] == f0 and
          all(post[i][0] - post[i - 1][0] == H for i in range(1, POST_N)))
    if not ok:
        return _na("short or gapped path")
    stop, tps, sd = make_levels(entry, direction, u)
    outcome, r = grade_path(entry, direction, stop, tps, post, sd)
    return {"status": "OK", "reason": "", "u": u, "stop": stop, "tps": tps,
            "outcome": outcome, "r": r, "used": len(run) + len(post)}


def fetch_1h(symbol, start_ms, timeout=15):
    """Returns (source, candles, why). why: None | 'deferred' | 'nosource'."""
    import requests
    import market_facts as mf
    transient = False
    for name in ("spot", "futures"):
        try:
            r = requests.get(mf.URLS[name], params={
                "symbol": symbol, "interval": "1h",
                "startTime": int(start_ms), "limit": 200}, timeout=timeout)
        except Exception:
            transient = True
            continue
        if r.status_code in (418, 429) or r.status_code >= 500:
            transient = True
            continue
        if r.status_code != 200:
            continue
        try:
            d = r.json()
        except Exception:
            transient = True
            continue
        if isinstance(d, list) and d:
            return name, mf.parse_klines(d), None
    return None, [], ("deferred" if transient else "nosource")


def to_ms(cms, cutc):
    if cms is not None:
        try:
            return int(cms)
        except Exception:
            pass
    try:
        dt = datetime.datetime.strptime(str(cutc), "%Y-%m-%dT%H:%M:%SZ")
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _has_table(con):
    return con.execute("select count(*) from sqlite_master where type='table' "
                       "and name='shadow_levels'").fetchone()[0] == 1


def due_rows(con, now_ms):
    rows = con.execute(
        "select id, symbol, direction, price, created_ms, created_utc "
        "from shadow_counterfactual where coalesce(excluded,0)=0 "
        "and upper(direction) in ('BUY','SELL') order by id").fetchall()
    done = set()
    if _has_table(con):
        done = set(r[0] for r in con.execute("select cf_id from shadow_levels"))
    due, notdue = [], 0
    for cid, sym, d, px, cms, cutc in rows:
        if cid in done:
            continue
        ms = to_ms(cms, cutc)
        if ms is None or now_ms < ms + DUE_H * H:
            notdue += 1
            continue
        due.append((cid, sym, str(d).upper(), px, ms))
    return due, notdue, len(done)


def cmd_check():
    con = sqlite3.connect(DB, timeout=30)
    due, notdue, ndone = due_rows(con, int(time.time() * 1000))
    print("counterfactual rows: %d due, %d not due yet, %d already in shadow_levels"
          % (len(due), notdue, ndone))
    print("table shadow_levels exists: %s" % _has_table(con))


def cmd_run():
    con = sqlite3.connect(DB, timeout=30)
    con.execute(SCHEMA)
    con.commit()
    due, notdue, ndone = due_rows(con, int(time.time() * 1000))
    graded = deferred = 0
    for cid, sym, d, px, ms in due[:MAX_ROWS]:
        name, cs, why = fetch_1h(sym, ms - 170 * H)
        if name is None and why == "deferred":
            print("DEFER #%d %s: request failed, retry next run" % (cid, sym))
            deferred += 1
            time.sleep(0.3)
            continue
        if name is None:
            res = _na("no candle source")
        else:
            res = grade_row(px, d, ms, cs)
        t = res["tps"]
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        con.execute(
            "insert or ignore into shadow_levels(created_utc, cf_id, symbol, direction, entry, "
            "u_pct, stop, tp1, tp2, tp3, outcome, r_result, candles_used, source, status, reason) "
            "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, cid, sym, d, px, None if res["u"] is None else res["u"] * 100.0,
             res["stop"], t[0], t[1], t[2], res["outcome"], res["r"], res["used"],
             name, res["status"], res["reason"]))
        con.commit()
        graded += 1
        print("#%d %s %s %s R=%s %s" % (cid, sym, d, res["outcome"],
              "n/a" if res["r"] is None else "%+.2f" % res["r"], res["reason"]))
        time.sleep(0.3)
    left = max(0, len(due) - MAX_ROWS)
    print("run: %d logged, %d deferred, %d over run limit, %d not due yet"
          % (graded, deferred, left, notdue))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    if not _has_table(con):
        print("no shadow_levels table yet")
        return
    rows = con.execute("select outcome, status, r_result from shadow_levels").fetchall()
    ok = [r for r in rows if r[1] == "OK"]
    print("%d logged, %d graded (status OK; AMBIGUOUS counts as graded but is excluded "
          "from mean R), %d unavailable. Rule: read nothing before 30 graded rows."
          % (len(rows), len(ok), len(rows) - len(ok)))
    if len(ok) < 30:
        print("NOT READ: too few rows. No conclusions.")
        return
    for o in ("STOP", "TP1", "TP2", "TP3", "EXPIRED", "AMBIGUOUS"):
        n = sum(1 for r in ok if r[0] == o)
        print("%-9s %3d  %5.1f%%" % (o, n, 100.0 * n / len(ok)))
    rs = [r[2] for r in ok if r[0] != "AMBIGUOUS" and r[2] is not None]
    if rs:
        print("mean R over %d rows: %+.3f" % (len(rs), sum(rs) / len(rs)))
    print("Not a profit claim. Fees and slippage not modeled. Same-day rows are correlated.")
    print("AI-level comparison: not implemented in this version.")


def selftest():
    B = 489000 * H
    call = B + 27 * 60000

    def synth():
        last_open = ((call - H) // H) * H
        pre = [(last_open - (168 - k) * H, 100.0, 101.0, 99.0, 100.0, 1.0) for k in range(169)]
        f0 = (call // H) * H + H
        post = [(f0 + k * H, 100.0, 100.5, 99.5, 100.0, 1.0) for k in range(24)]
        return pre, post

    def setc(post, i, hi=None, lo=None, cl=None):
        o, op, h, l, c, v = post[i]
        post[i] = (o, op, h if hi is None else hi, l if lo is None else lo,
                   c if cl is None else cl, v)

    def case(direction, mod):
        pre, post = synth()
        mod(pre, post)
        return grade_row(100.0, direction, call, pre + post)

    r = case("BUY", lambda pre, post: None)
    assert r["status"] == "OK" and r["outcome"] == "EXPIRED" and abs(r["r"]) < 1e-9, r
    assert abs(r["u"] - 0.02) < 1e-9 and abs(r["stop"] - 99.0) < 1e-9, r
    assert [round(x, 6) for x in r["tps"]] == [101.0, 102.0, 103.0], r
    assert r["used"] == 169 + 24, r
    r = case("BUY", lambda pre, post: setc(post, 23, hi=100.9, lo=99.6, cl=100.5))
    assert r["outcome"] == "EXPIRED" and abs(r["r"] - 0.5) < 1e-9, r
    r = case("BUY", lambda pre, post: setc(post, 3, hi=101.2))
    assert r["outcome"] == "TP1" and r["r"] == 1.0, r
    r = case("BUY", lambda pre, post: setc(post, 2, hi=102.5))
    assert r["outcome"] == "TP2" and r["r"] == 2.0, r
    r = case("BUY", lambda pre, post: setc(post, 1, hi=103.5))
    assert r["outcome"] == "TP3" and r["r"] == 3.0, r
    r = case("BUY", lambda pre, post: setc(post, 4, lo=98.9))
    assert r["outcome"] == "STOP" and r["r"] == -1.0, r
    r = case("BUY", lambda pre, post: (setc(post, 1, hi=101.5), setc(post, 5, lo=98.9)))
    assert r["outcome"] == "TP1", r
    r = case("BUY", lambda pre, post: setc(post, 2, hi=101.5, lo=98.9))
    assert r["outcome"] == "AMBIGUOUS" and r["r"] is None, r
    r = case("BUY", lambda pre, post: (setc(post, 1, hi=101.5), setc(post, 3, hi=101.5, lo=98.9)))
    assert r["outcome"] == "TP1", r
    r = case("SELL", lambda pre, post: setc(post, 2, lo=97.5))
    assert r["outcome"] == "TP2" and abs(r["stop"] - 101.0) < 1e-9, r
    r = case("SELL", lambda pre, post: setc(post, 2, hi=101.2))
    assert r["outcome"] == "STOP", r
    # candles after the 24 are ignored
    r = case("BUY", lambda pre, post: post.append((post[-1][0] + H, 100.0, 999.0, 1.0, 100.0, 1.0)))
    assert r["outcome"] == "EXPIRED", r
    # the candle that is still open at call time is ignored
    r = case("BUY", lambda pre, post: pre.append((B, 100.0, 999.0, 1.0, 100.0, 1.0)))
    assert r["status"] == "OK" and abs(r["u"] - 0.02) < 1e-9, r
    # unavailable cases
    r = case("BUY", lambda pre, post: pre.__delitem__(10))
    assert r["status"] == "UNAVAILABLE" and "168" in r["reason"], r
    r = case("BUY", lambda pre, post: pre.pop())
    assert r["status"] == "UNAVAILABLE" and "just before" in r["reason"], r
    r = case("BUY", lambda pre, post: pre.__delitem__(slice(0, 2)))
    assert r["status"] == "UNAVAILABLE", r
    r = case("BUY", lambda pre, post: pre.__delitem__(0))
    assert r["status"] == "OK", r
    r = case("BUY", lambda pre, post: post.pop())
    assert r["status"] == "UNAVAILABLE" and "path" in r["reason"], r
    assert grade_row(0, "BUY", call, []) ["status"] == "UNAVAILABLE"
    # unit U is the median of 7 block ranges; the extra first candle is ignored
    pre, post = synth()
    pre[0] = (pre[0][0], 100.0, 500.0, 1.0, 100.0, 1.0)
    for i in range(7):
        k = 1 + 24 * i
        pre[k] = (pre[k][0], 100.0, 100.0 + (i + 1), 100.0 - (i + 1), 100.0, 1.0)
    assert abs(unit_u(contiguous_suffix(pre)) - 0.08) < 1e-9
    stop, tps, sd = make_levels(200.0, "BUY", 0.02)
    assert abs(stop - 198.0) < 1e-9 and abs(tps[0] - 202.0) < 1e-9 and abs(tps[2] - 206.0) < 1e-9
    print("SELFTEST OK")


def usage():
    print(__doc__)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"selftest": selftest, "check": cmd_check, "run": cmd_run, "report": cmd_report}.get(cmd, usage)()
