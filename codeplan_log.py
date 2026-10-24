#!/usr/bin/env python3
"""codeplan_log.py - codeplan_v1 (frozen spec: codeplan_v1_spec.md). Shadow only.
Writes ONLY shadow_codeplan and shadow_codeplan_grade in shadow.db (on `run`).
No AI calls. Never touches decisions, plans, the guard, the AIs or the live path.
Reuses levels_log (levels_v1 method) and market_ctx_log (rules S,V,T,R) unchanged.
Usage: python3 codeplan_log.py selftest | check | run | report"""
import sys
import time
import json
import sqlite3
import datetime

import levels_log as L
import market_ctx_log as M

DB = "shadow.db"
H = 3600000
MAX_ROWS = 40
MARGIN_H = 1
SCHEMA = [
    "create table if not exists shadow_codeplan(id integer primary key autoincrement, "
    "created_utc text, ctx_id integer unique, day_utc text, symbol text, direction text, "
    "call_s integer, call_v integer, call_t integer, call_r integer, n_up integer, "
    "n_down integer, entry real, snap_ms integer, status text)",
    "create table if not exists shadow_codeplan_grade(id integer primary key autoincrement, "
    "graded_utc text, ctx_id integer unique, symbol text, direction text, entry real, "
    "u_pct real, stop real, tp1 real, tp2 real, tp3 real, outcome text, r_result real, "
    "dir_ret_pct real, candles_used integer, source text, status text, reason text)",
]


def utcnow_s():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_schema(con):
    for s in SCHEMA:
        con.execute(s)
    con.commit()


def decide(nums):
    cl = M.calls(nums)
    v = [cl.get(k) for k in "SVTR"]
    up = sum(1 for x in v if x == 1)
    dn = sum(1 for x in v if x == -1)
    d = "BUY" if up >= 3 else ("SELL" if dn >= 3 else "WAIT")
    return d, cl, up, dn


def due_ms(snap_ms):
    return (snap_ms // H) * H + H + (24 + MARGIN_H) * H


def create_plans(con):
    rows = con.execute(
        "select c.id, c.day_utc, c.snap_ms, c.symbol, c.last_close, c.status, c.numbers_json "
        "from shadow_market_ctx c left join shadow_codeplan p on p.ctx_id = c.id "
        "where p.id is null and c.status in ('OK','PARTIAL') order by c.id").fetchall()
    counts = {"BUY": 0, "SELL": 0, "WAIT": 0}
    now = utcnow_s()
    for cid, day, snap, sym, lc, st, nj in rows:
        try:
            nums = json.loads(nj) if nj else None
            lc = float(lc)
        except Exception:
            continue
        if not nums or lc <= 0:
            continue
        d, cl, up, dn = decide(nums)
        con.execute(
            "insert or ignore into shadow_codeplan(created_utc, ctx_id, day_utc, symbol, direction, "
            "call_s, call_v, call_t, call_r, n_up, n_down, entry, snap_ms, status) "
            "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, cid, day, sym, d, cl.get("S"), cl.get("V"), cl.get("T"), cl.get("R"),
             up, dn, lc, snap, st))
        counts[d] += 1
    con.commit()
    return counts


def due_plans(con, now_ms):
    rows = con.execute(
        "select p.id, p.ctx_id, p.symbol, p.direction, p.entry, p.snap_ms from shadow_codeplan p "
        "left join shadow_codeplan_grade g on g.ctx_id = p.ctx_id "
        "where g.id is null and p.direction in ('BUY','SELL') order by p.id").fetchall()
    due = [r for r in rows if now_ms >= due_ms(r[5])]
    return due, len(rows) - len(due)


def grade_one(entry, direction, snap_ms, cs):
    res = L.grade_row(entry, direction, snap_ms, cs)
    dret = None
    if res["status"] == "OK":
        f0 = (snap_ms // H) * H + H
        post = sorted([c for c in cs if c[0] >= f0], key=lambda x: x[0])[:L.POST_N]
        if len(post) == L.POST_N:
            e = float(entry)
            sgn = 1.0 if direction == "BUY" else -1.0
            dret = (post[-1][4] - e) / e * 100.0 * sgn
    res["dret"] = dret
    return res


def write_grade(con, ctx_id, sym, direction, entry, name, res):
    t = res["tps"]
    con.execute(
        "insert or ignore into shadow_codeplan_grade(graded_utc, ctx_id, symbol, direction, entry, "
        "u_pct, stop, tp1, tp2, tp3, outcome, r_result, dir_ret_pct, candles_used, source, status, "
        "reason) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (utcnow_s(), ctx_id, sym, direction, entry,
         None if res["u"] is None else res["u"] * 100.0, res["stop"], t[0], t[1], t[2],
         res["outcome"], res["r"], res.get("dret"), res["used"], name, res["status"], res["reason"]))
    con.commit()


def dir_stats(rows):
    use = [(d, dr, x) for d, dr, x in rows if x is not None and x != 0]
    n = len(use)
    if n == 0:
        return {"n": 0, "excluded": len(rows)}
    hit = sum(1 for _, _, x in use if x > 0)
    raw_up = sum(1 for _, dr, x in use if (x if dr == "BUY" else -x) > 0)
    buys = sum(1 for _, dr, _ in use if dr == "BUY")
    pf = raw_up / float(n)
    pc = buys / float(n)
    byd = {}
    for day, _, x in use:
        byd.setdefault(day, []).append(1.0 if x > 0 else 0.0)
    return {"n": n, "excluded": len(rows) - n, "hit": hit / float(n), "always_up": pf,
            "base": pc * pf + (1 - pc) * (1 - pf), "days": len(byd),
            "per_day": sum(sum(v) / len(v) for v in byd.values()) / len(byd)}


def mean_r(rows):
    use = [(d, r) for d, o, r in rows if o != "AMBIGUOUS" and r is not None]
    if not use:
        return None, None, 0
    pooled = sum(r for _, r in use) / float(len(use))
    byd = {}
    for d, r in use:
        byd.setdefault(d, []).append(r)
    per_day = sum(sum(v) / len(v) for v in byd.values()) / len(byd)
    return pooled, per_day, len(use)


def cmd_check():
    con = sqlite3.connect(DB, timeout=30)
    names = set(r[0] for r in con.execute("select name from sqlite_master where type='table'"))
    if "shadow_market_ctx" not in names:
        print("no shadow_market_ctx table yet; run market_ctx_log.py first. Nothing was written.")
        return
    elig = con.execute("select count(*) from shadow_market_ctx where status in ('OK','PARTIAL')").fetchone()[0]
    if "shadow_codeplan" not in names:
        print("tables do not exist yet; %d eligible ctx rows; `run` would create them. "
              "Nothing was requested or written." % elig)
        return
    plans = dict(con.execute("select direction, count(*) from shadow_codeplan group by 1").fetchall())
    new = con.execute("select count(*) from shadow_market_ctx c left join shadow_codeplan p on p.ctx_id=c.id "
                      "where p.id is null and c.status in ('OK','PARTIAL')").fetchone()[0]
    due, notdue = due_plans(con, int(time.time() * 1000))
    print("plans %s | %d ctx rows without a plan | %d due for grading, %d not due yet"
          % (plans, new, len(due), notdue))


def cmd_run():
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_market_ctx'").fetchone()[0]:
        print("no shadow_market_ctx table yet; run market_ctx_log.py first")
        return
    ensure_schema(con)
    counts = create_plans(con)
    due, notdue = due_plans(con, int(time.time() * 1000))
    graded = deferred = 0
    for pid, cid, sym, d, entry, snap in due[:MAX_ROWS]:
        name, cs, why = L.fetch_1h(sym, snap - 170 * H)
        if name is None and why == "deferred":
            print("DEFER #%d %s: request failed, retry next run" % (cid, sym))
            deferred += 1
            time.sleep(0.3)
            continue
        res = L._na("no candle source") if name is None else grade_one(entry, d, snap, cs)
        if name is None:
            res["dret"] = None
        write_grade(con, cid, sym, d, entry, name, res)
        graded += 1
        print("#%d %s %s %s R=%s ret=%s %s" % (
            cid, sym, d, res["outcome"],
            "n/a" if res["r"] is None else "%+.2f" % res["r"],
            "n/a" if res.get("dret") is None else "%+.2f%%" % res["dret"], res["reason"]))
        time.sleep(0.3)
    print("run: new plans BUY %d SELL %d WAIT %d | %d graded, %d deferred, %d over run limit, %d not due yet"
          % (counts["BUY"], counts["SELL"], counts["WAIT"], graded, deferred,
             max(0, len(due) - MAX_ROWS), notdue))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    names = set(r[0] for r in con.execute("select name from sqlite_master where type='table'"))
    if "shadow_codeplan_grade" not in names:
        print("no codeplan tables yet")
        return
    plans = dict(con.execute("select direction, count(*) from shadow_codeplan group by 1").fetchall())
    tot = sum(plans.values())
    wait = plans.get("WAIT", 0)
    rows = con.execute(
        "select p.day_utc, p.direction, g.outcome, g.r_result, g.dir_ret_pct, g.status "
        "from shadow_codeplan p join shadow_codeplan_grade g on g.ctx_id = p.ctx_id").fetchall()
    ok = [r for r in rows if r[5] == "OK"]
    days = len(set(r[0] for r in ok))
    print("%d plans (BUY %d, SELL %d, WAIT %d = %.1f%%); %d graded OK over %d distinct days, %d unavailable. "
          "Rule: read nothing before 30 graded non-WAIT rows and 20 distinct days."
          % (tot, plans.get("BUY", 0), plans.get("SELL", 0), wait,
             100.0 * wait / tot if tot else 0.0, len(ok), days, len(rows) - len(ok)))
    if len(ok) < 30 or days < 20:
        print("NOT READ: too few rows or days. No conclusions.")
        return
    for o in ("STOP", "TP1", "TP2", "TP3", "EXPIRED", "AMBIGUOUS"):
        n = sum(1 for r in ok if r[2] == o)
        print("%-9s %3d  %5.1f%%" % (o, n, 100.0 * n / len(ok)))
    pooled, per_day, nr = mean_r([(r[0], r[2], r[3]) for r in ok])
    if nr:
        print("mean R over %d rows: pooled %+.3f | per-day mean %+.3f" % (nr, pooled, per_day))
    ds = dir_stats([(r[0], r[1], r[4]) for r in ok])
    if ds["n"]:
        print("direction hit %.1f%% over %d rows (%d excluded, exact 0) | always-up %.1f%% | base %.1f%% "
              "| per-day mean hit %.1f%% over %d days"
              % (100 * ds["hit"], ds["n"], ds["excluded"], 100 * ds["always_up"], 100 * ds["base"],
                 100 * ds["per_day"], ds["days"]))
    print("No pass bar, no causal claim. Fees and slippage not modeled. Rows correlate across coins and days.")


def selftest():
    assert L.MULT == {"stop": 0.5, "tp1": 0.5, "tp2": 1.0, "tp3": 1.5}, "levels_v1 constants changed"
    assert L.POST_N == 24 and L.NEED_PRE == 168
    B = 489000 * H
    snap = B + 27 * 60000

    def close(a, b, e=1e-9):
        return a is not None and abs(a - b) < e

    def synth():
        last_open = ((snap - H) // H) * H
        pre = [(last_open - (168 - k) * H, 100.0, 101.0, 99.0, 100.0, 1.0) for k in range(169)]
        f0 = (snap // H) * H + H
        post = [(f0 + k * H, 100.0, 100.5, 99.5, 100.0, 1.0) for k in range(24)]
        return pre, post

    # 1 direction rule: 3 of 4 calls, else WAIT
    def d_of(s, v, t, r):
        return decide({"structure": s, "vwap_day_dist": v, "taker24": t, "rs24": r})
    d = d_of("UP", 1.0, 0.6, 2.0)
    assert d[0] == "BUY" and d[2] == 4 and d[3] == 0, d
    assert d_of("UP", 1.0, 0.6, -2.0)[0] == "BUY"
    assert d_of("DOWN", -1.0, 0.4, None)[0] == "SELL"
    assert d_of("DOWN", -0.2873, 0.5264, None)[0] == "WAIT"
    assert d_of("UP", 1.0, 0.4, -1.0)[0] == "WAIT"
    assert d_of(None, None, None, None)[0] == "WAIT"
    assert d_of("MIXED", 0.0, 0.5, 0.0)[0] == "WAIT"
    assert due_ms(snap) == B + 26 * H

    # 2 grading and direction return
    pre, post = synth()
    r = grade_one(100.0, "BUY", snap, pre + post)
    assert r["status"] == "OK" and r["outcome"] == "EXPIRED" and close(r["dret"], 0.0), r
    pre, post = synth()
    post[23] = (post[23][0], 100.0, 100.5, 99.5, 100.5, 1.0)
    r = grade_one(100.0, "BUY", snap, pre + post)
    assert r["outcome"] == "EXPIRED" and close(r["dret"], 0.5), r
    r = grade_one(100.0, "SELL", snap, pre + post)
    assert r["outcome"] == "EXPIRED" and close(r["dret"], -0.5), r
    pre, post = synth()
    post[3] = (post[3][0], 100.0, 101.2, 99.5, 100.0, 1.0)
    r = grade_one(100.0, "BUY", snap, pre + post)
    assert r["outcome"] == "TP1" and r["r"] == 1.0 and close(r["dret"], 0.0), r
    pre, post = synth()
    post.pop()
    r = grade_one(100.0, "BUY", snap, pre + post)
    assert r["status"] == "UNAVAILABLE" and r["dret"] is None, r

    # 3 plan creation and due logic (in memory)
    con = sqlite3.connect(":memory:")
    M.ensure_schema(con)
    ensure_schema(con)

    def sd(st, nums):
        return {"status": st, "reason": "", "numbers": nums, "last_open": B - H, "last_close": 100.0,
                "age": 27.0, "candles": 1000, "cm": None}
    M.store(con, "2026-10-21", snap, "AAAUSDT", "spot",
            sd("OK", {"structure": "UP", "vwap_day_dist": 1.0, "taker24": 0.6, "rs24": 2.0}))
    M.store(con, "2026-10-21", snap, "BBBUSDT", "spot",
            sd("PARTIAL", {"structure": "UP", "vwap_day_dist": 1.0, "taker24": 0.4, "rs24": -1.0}))
    M.store(con, "2026-10-21", snap, "CCCUSDT", None, M.na("request failed or too few candles"))
    M.store(con, "2026-10-21", snap, "DDDUSDT", "spot",
            sd("OK", {"structure": "DOWN", "vwap_day_dist": -1.0, "taker24": 0.4, "rs24": None}))
    assert create_plans(con) == {"BUY": 1, "SELL": 1, "WAIT": 1}
    assert create_plans(con) == {"BUY": 0, "SELL": 0, "WAIT": 0}
    assert con.execute("select count(*) from shadow_codeplan").fetchone()[0] == 3
    assert con.execute("select count(*) from shadow_codeplan where symbol='CCCUSDT'").fetchone()[0] == 0
    assert con.execute("select entry, snap_ms from shadow_codeplan where symbol='AAAUSDT'").fetchone() == (100.0, snap)
    assert due_plans(con, due_ms(snap) - 1) == ([], 2)
    assert len(due_plans(con, due_ms(snap))[0]) == 2
    aid = con.execute("select ctx_id from shadow_codeplan where symbol='AAAUSDT'").fetchone()[0]
    pre, post = synth()
    res = grade_one(100.0, "BUY", snap, pre + post)
    write_grade(con, aid, "AAAUSDT", "BUY", 100.0, "spot", res)
    write_grade(con, aid, "AAAUSDT", "BUY", 100.0, "spot", res)
    assert con.execute("select count(*) from shadow_codeplan_grade").fetchone()[0] == 1
    assert con.execute("select outcome, status from shadow_codeplan_grade").fetchone() == ("EXPIRED", "OK")
    assert len(due_plans(con, due_ms(snap))[0]) == 1

    # 4 statistics
    rows = [("d1", "BUY", 2.0), ("d1", "BUY", 1.0), ("d2", "SELL", 3.0), ("d2", "BUY", -1.0),
            ("d3", "SELL", -2.0), ("d3", "BUY", 0.0)]
    s = dir_stats(rows)
    assert s["n"] == 5 and s["excluded"] == 1 and s["days"] == 3, s
    assert close(s["hit"], 0.6) and close(s["always_up"], 0.6) and close(s["base"], 0.52), s
    assert close(s["per_day"], 0.5), s
    assert dir_stats([("d1", "BUY", 0.0)]) == {"n": 0, "excluded": 1}
    p, pd, n = mean_r([("d1", "STOP", -1.0), ("d1", "TP2", 2.0), ("d2", "AMBIGUOUS", None), ("d2", "EXPIRED", 0.4)])
    assert n == 3 and close(p, 1.4 / 3.0) and close(pd, 0.45), (p, pd, n)
    assert mean_r([("d1", "AMBIGUOUS", None)]) == (None, None, 0)
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"selftest": selftest, "check": cmd_check, "run": cmd_run, "report": cmd_report}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
