#!/usr/bin/env python3
"""breakout19_log.py - breakout19_v1 (frozen spec: breakout19_v1_spec.md). Shadow only.
Public 1h klines (1d klines only for the logged M context). Writes ONLY shadow_breakout19 in
shadow.db (on `run`). No orders, no AI calls. Never touches prompts, the guard, plans,
decisions or the live path. Forward only: no bar closing before FIRST_BAR_CLOSE_MS is used.
Usage: python3 breakout19_log.py selftest | check | run | report"""
import sys
import time
import sqlite3
import datetime

import market_ctx_log as M

DB = "shadow.db"
H1 = 3600000
H4 = 4 * H1
DAY = 24 * H1
HH_BARS = 24
TR_MULT = 1.5
STOP_PCT = 2.0
HOLD_H = 24
FEE_PCT = 0.05
SLIP_PCT = 0.02
COST_PP = 2.0 * (FEE_PCT + SLIP_PCT)
LIMIT = 1000
NEED_H = 200
MIN_TRADES = 30
MIN_DAYS = 20
STEP = {"1h": H1, "1d": DAY}
FIRST_BAR_CLOSE_MS = int(datetime.datetime(2026, 11, 4, 8, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
COLS = ("created_utc, symbol, signal_close_ms, signal_utc, day_utc, direction, status, reason, entry, stop, "
        "exit_ms, exit_px, exit_type, gross_pct, net_pct, r_net, mirror_net_pct, hh, ll, m19, tr19, prev19, "
        "s_pos, m_pos, source")
SCHEMA = (
    "create table if not exists shadow_breakout19(id integer primary key autoincrement, created_utc text, "
    "symbol text, signal_close_ms integer, signal_utc text, day_utc text, direction text, status text, "
    "reason text, entry real, stop real, exit_ms integer, exit_px real, exit_type text, gross_pct real, "
    "net_pct real, r_net real, mirror_net_pct real, hh real, ll real, m19 real, tr19 real, prev19 real, "
    "s_pos real, m_pos real, source text, unique(symbol, signal_close_ms))")


def utcnow_s():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def day_of(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")


def parse_raw(raw, step):
    out = {}
    for k in raw:
        try:
            t, o, h, l, c = int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])
        except Exception:
            continue
        if t % step != 0:
            continue
        vals = (o, h, l, c)
        if any(v != v or abs(v) == float("inf") or v <= 0 for v in vals):
            continue
        if h < max(o, l, c) or l > min(o, h, c):
            continue
        out[t] = vals
    return out


def fetch_klines(symbol, interval, limit, need, timeout=15):
    """Returns (source, {open_ms: (o, h, l, c)}, why). why: None | 'deferred' | 'nosource'."""
    import requests
    import market_facts as mf
    best_name, best = None, {}
    transient = False
    for name in ("spot", "futures"):
        try:
            r = requests.get(mf.URLS[name], params={"symbol": symbol, "interval": interval,
                                                    "limit": limit}, timeout=timeout)
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
        if not isinstance(d, list) or not d:
            continue
        cm = parse_raw(d, STEP[interval])
        if len(cm) >= need:
            return name, cm, None
        if len(cm) > len(best):
            best_name, best = name, cm
    if transient and len(best) < need:
        return None, {}, "deferred"
    if best:
        return best_name, best, None
    return None, {}, "nosource"


def closed_only(cm, now_ms):
    return dict((t, v) for t, v in cm.items() if t + H1 <= now_ms)


def bar_ok(cm, t0):
    return all((t0 + i * H1) in cm for i in range(4))


def true_range(cm, o):
    h, l = cm[o][1], cm[o][2]
    pc = cm[o - H1][3]
    return max(h - l, abs(h - pc), abs(l - pc))


def eval_bar(cm, t0):
    T = t0 + H4
    res = {"status": "UNAVAILABLE", "reason": "", "T": T}
    if not bar_ok(cm, t0):
        res["reason"] = "signal bar incomplete"
        return res
    prior = [t0 - j * H4 for j in range(1, HH_BARS + 1)]
    if not all(bar_ok(cm, p) for p in prior):
        res["reason"] = "fewer than 24 complete 4H bars before"
        return res
    if not all((T - k * H1) in cm for k in range(1, 40)):
        res["reason"] = "fewer than 39 consecutive hourly candles"
        return res
    hh = max(cm[p + i * H1][1] for p in prior for i in range(4))
    ll = min(cm[p + i * H1][2] for p in prior for i in range(4))
    close = cm[T - H1][3]
    m19 = close - cm[T - 20 * H1][3]
    tr19 = sum(true_range(cm, T - k * H1) for k in range(1, 20))
    prev19 = sum(true_range(cm, T - k * H1) for k in range(20, 39))
    expansion = tr19 >= TR_MULT * prev19
    direction = None
    if expansion and close > hh and m19 > 0:
        direction = "LONG"
    elif expansion and close < ll and m19 < 0:
        direction = "SHORT"
    res.update(status="SIGNAL" if direction else "NO_SIGNAL", direction=direction, close=close, hh=hh, ll=ll,
               m19=m19, tr19=tr19, prev19=prev19, s_pos=((close - ll) / (hh - ll)) if hh > ll else None)
    return res


def opposite(d):
    return "SHORT" if d == "LONG" else "LONG"


def ret_pct(direction, entry, px):
    if direction == "LONG":
        return (px - entry) / entry * 100.0
    return (entry - px) / entry * 100.0


def simulate(cm, direction, T, entry):
    """Returns None unless all 24 path candles exist. Gap exits at the candle open."""
    path = [cm.get(T + i * H1) for i in range(HOLD_H)]
    if any(c is None for c in path):
        return None
    long_ = direction == "LONG"
    stop = entry * (1.0 - STOP_PCT / 100.0) if long_ else entry * (1.0 + STOP_PCT / 100.0)
    exit_type, px, ex_ms = "TIME", path[-1][3], T + HOLD_H * H1
    for i, (o, h, l, c) in enumerate(path):
        gap = (o <= stop) if long_ else (o >= stop)
        touch = (l <= stop) if long_ else (h >= stop)
        if gap:
            exit_type, px, ex_ms = "STOP", o, T + i * H1
            break
        if touch:
            exit_type, px, ex_ms = "STOP", stop, T + (i + 1) * H1
            break
    gross = ret_pct(direction, entry, px)
    net = gross - COST_PP
    return {"stop": stop, "exit_type": exit_type, "exit_px": px, "exit_ms": ex_ms,
            "gross": gross, "net": net, "r": net / STOP_PCT}


def m_pos_for(daily, T, close_k):
    d0 = ((T - H1) // DAY) * DAY
    days = [d0 - j * DAY for j in range(1, 121)]
    if any(d not in daily for d in days):
        return None
    hi = max(daily[d][1] for d in days)
    lo = min(daily[d][2] for d in days)
    if hi <= lo:
        return None
    return (close_k - lo) / (hi - lo)


def process_coin(cm, now_ms, first_close_ms, stored):
    rows, pending, blocked = [], False, 0
    if not cm:
        return rows, pending, blocked
    cm_min = min(cm)
    busy = None
    t0 = first_close_ms - H4
    while t0 + H4 <= now_ms:
        T = t0 + H4
        if T in stored:
            ex = stored[T]
            if ex is not None and (busy is None or ex > busy):
                busy = ex
            t0 += H4
            continue
        if t0 - HH_BARS * H4 < cm_min:
            t0 += H4
            continue
        ev = eval_bar(cm, t0)
        if busy is not None and T < busy:
            if ev["status"] == "SIGNAL":
                blocked += 1
            t0 += H4
            continue
        if ev["status"] == "UNAVAILABLE":
            rows.append({"T": T, "kind": "UNAVAILABLE", "reason": ev["reason"]})
        elif ev["status"] == "SIGNAL":
            d, entry = ev["direction"], ev["close"]
            sim = simulate(cm, d, T, entry)
            ctx = {"hh": ev["hh"], "ll": ev["ll"], "m19": ev["m19"], "tr19": ev["tr19"],
                   "prev19": ev["prev19"], "s_pos": ev["s_pos"]}
            if sim is None:
                if now_ms < T + HOLD_H * H1:
                    pending = True
                    break
                row = {"T": T, "kind": "UNAVAILABLE", "reason": "path candles missing", "direction": d,
                       "entry": entry, "exit_ms": T + HOLD_H * H1}
                row.update(ctx)
                rows.append(row)
                busy = T + HOLD_H * H1
            else:
                mir = simulate(cm, opposite(d), T, entry)
                row = {"T": T, "kind": "OK", "direction": d, "entry": entry, "stop": sim["stop"],
                       "exit_ms": sim["exit_ms"], "exit_px": sim["exit_px"], "exit_type": sim["exit_type"],
                       "gross": sim["gross"], "net": sim["net"], "r": sim["r"], "mirror": mir["net"]}
                row.update(ctx)
                rows.append(row)
                busy = sim["exit_ms"]
        t0 += H4
    return rows, pending, blocked


def store_rows(con, sym, source, rows, daily):
    now = utcnow_s()
    n = 0
    for r in rows:
        T = r["T"]
        ok = r["kind"] == "OK"
        m_pos = m_pos_for(daily, T, r["entry"]) if (ok and daily) else None
        vals = (now, sym, T, fmt_ms(T), day_of(T), r.get("direction"), "OK" if ok else "UNAVAILABLE",
                r.get("reason", ""), r.get("entry"), r.get("stop"), r.get("exit_ms"), r.get("exit_px"),
                r.get("exit_type"), r.get("gross"), r.get("net"), r.get("r"), r.get("mirror"), r.get("hh"),
                r.get("ll"), r.get("m19"), r.get("tr19"), r.get("prev19"), r.get("s_pos"), m_pos, source)
        cur = con.execute("insert or ignore into shadow_breakout19(%s) values(%s)" % (COLS, ",".join(["?"] * 25)), vals)
        n += 1 if cur.rowcount > 0 else 0
    con.commit()
    return n


def stored_map(con, sym):
    return dict(con.execute("select signal_close_ms, exit_ms from shadow_breakout19 where symbol=?",
                            (sym,)).fetchall())


def count_overlaps(items):
    n = 0
    for i, (s, t, e) in enumerate(items):
        for j, (s2, t2, e2) in enumerate(items):
            if i != j and s2 != s and t2 < e and t < e2:
                n += 1
                break
    return n


def days_over(ts, limit):
    c = {}
    for t in ts:
        c[day_of(t)] = c.get(day_of(t), 0) + 1
    return sum(1 for v in c.values() if v > limit)


def summarize(rows):
    """rows: (symbol, T, status, direction, exit_ms, exit_type, net, r, mirror)."""
    ok = [r for r in rows if r[2] == "OK" and r[6] is not None and r[7] is not None]
    st = {"n": len(ok), "unavailable": sum(1 for r in rows if r[2] != "OK")}
    if not ok:
        return st
    byd = {}
    for r in ok:
        byd.setdefault(day_of(r[1]), []).append((r[6], r[7]))
    n = len(ok)
    mir = [r[8] for r in ok if r[8] is not None]
    st.update(
        longs=sum(1 for r in ok if r[3] == "LONG"), shorts=sum(1 for r in ok if r[3] == "SHORT"),
        days=len(byd), stopped=sum(1 for r in ok if r[5] == "STOP") / float(n),
        hit=sum(1 for r in ok if r[6] > 0) / float(n),
        net=sum(r[6] for r in ok) / float(n), r=sum(r[7] for r in ok) / float(n),
        pd_net=sum(sum(a for a, _ in v) / len(v) for v in byd.values()) / len(byd),
        pd_r=sum(sum(b for _, b in v) / len(v) for v in byd.values()) / len(byd),
        mirror=(sum(mir) / len(mir)) if mir else None,
        overlaps=count_overlaps([(r[0], r[1], r[4]) for r in ok]),
        over5=days_over([r[1] for r in ok], 5))
    return st


def build_report(con):
    if not con.execute("select count(*) from sqlite_master where name='shadow_breakout19'").fetchone()[0]:
        return ["no shadow_breakout19 table yet"]
    rows = con.execute("select symbol, signal_close_ms, status, direction, exit_ms, exit_type, net_pct, r_net, "
                       "mirror_net_pct from shadow_breakout19").fetchall()
    s = summarize(rows)
    if not s["n"]:
        return ["0 trades graded; UNAVAILABLE rows %d. Rule: read nothing before %d trades and %d distinct "
                "days." % (s["unavailable"], MIN_TRADES, MIN_DAYS), "NOT READ: too few trades or days. No conclusions."]
    out = ["%d trades graded (long %d, short %d) over %d distinct UTC signal days; UNAVAILABLE rows %d. "
           "Rule: read nothing before %d trades and %d distinct days."
           % (s["n"], s["longs"], s["shorts"], s["days"], s["unavailable"], MIN_TRADES, MIN_DAYS)]
    if s["n"] < MIN_TRADES or s["days"] < MIN_DAYS:
        out.append("NOT READ: too few trades or days. No conclusions.")
        return out
    out.append("stopped out %.1f%% | net hit rate %.1f%% | mean net %+.3f%% (per-day mean %+.3f%%) | "
               "mean R %+.2f (per-day mean %+.2f)"
               % (100 * s["stopped"], 100 * s["hit"], s["net"], s["pd_net"], s["r"], s["pd_r"]))
    out.append("mirror (opposite direction, same stop and exit rules) mean net %s"
               % ("n/a" if s["mirror"] is None else "%+.3f%%" % s["mirror"]))
    out.append("overlapping trades across coins: %d of %d | UTC days above 5 signals: %d"
               % (s["overlaps"], s["n"], s["over5"]))
    out.append("No pass bar, no causal claim. Costs are placeholders (%.2f pp round trip). Signals cluster "
               "across coins and days. S and M context fields are stored only." % COST_PP)
    return out


def cmd_check():
    now_ms = int(time.time() * 1000)
    nbars = max(0, (now_ms - FIRST_BAR_CLOSE_MS) // H4 + 1) if now_ms >= FIRST_BAR_CLOSE_MS else 0
    print("first bar closes %s UTC (forward only) | now %s UTC | completed 4H bars since then: %d"
          % (fmt_ms(FIRST_BAR_CLOSE_MS), fmt_ms(now_ms), nbars))
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_breakout19'").fetchone()[0]:
        print("table shadow_breakout19 does not exist yet; `run` would create it. "
              "Nothing was requested or written.")
        return
    by = dict(con.execute("select status, count(*) from shadow_breakout19 group by 1").fetchall())
    last = con.execute("select max(signal_utc) from shadow_breakout19").fetchone()[0]
    print("stored rows by status %s | last stored signal bar %s" % (by, last))


def cmd_run():
    now_ms = int(time.time() * 1000)
    if now_ms < FIRST_BAR_CLOSE_MS:
        print("run: no eligible bar yet (the first bar closes at %s UTC). Nothing requested, nothing written."
              % fmt_ms(FIRST_BAR_CLOSE_MS))
        return
    con = sqlite3.connect(DB, timeout=30)
    con.execute(SCHEMA)
    con.commit()
    tot = {"trades": 0, "unav": 0, "pending": 0, "blocked": 0, "deferred": 0, "nosource": 0, "coins": 0}
    for sym in M.SYMS:
        name, cm, why = fetch_klines(sym, "1h", LIMIT, NEED_H)
        if why == "deferred":
            print("DEFER %s: request failed, retry next run" % sym)
            tot["deferred"] += 1
            time.sleep(0.3)
            continue
        if why == "nosource":
            print("NOSOURCE %s: no candle source, nothing stored" % sym)
            tot["nosource"] += 1
            time.sleep(0.3)
            continue
        tot["coins"] += 1
        rows, pending, blocked = process_coin(closed_only(cm, now_ms), now_ms, FIRST_BAR_CLOSE_MS,
                                              stored_map(con, sym))
        daily = None
        if any(r["kind"] == "OK" for r in rows):
            dn, dcm, dwhy = fetch_klines(sym, "1d", 130, 130)
            daily = dcm if dn else None
        store_rows(con, sym, name, rows, daily)
        tot["pending"] += 1 if pending else 0
        tot["blocked"] += blocked
        for r in rows:
            if r["kind"] == "OK":
                tot["trades"] += 1
                print("%s %s signal %s UTC entry %.6g -> %s net %+.2f%%"
                      % (sym, r["direction"], fmt_ms(r["T"]), r["entry"], r["exit_type"], r["net"]))
            else:
                tot["unav"] += 1
        time.sleep(0.3)
    print("run: %d coins processed | new graded trades %d, UNAVAILABLE rows %d | coins with a trade pending %d | "
          "signals suppressed by an open trade %d | deferred %d, no source %d"
          % (tot["coins"], tot["trades"], tot["unav"], tot["pending"], tot["blocked"], tot["deferred"],
             tot["nosource"]))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    for line in build_report(con):
        print(line)


def selftest():
    utc = datetime.timezone.utc

    def close(a, b, e=1e-9):
        return a is not None and abs(a - b) < e

    # 1 constants and forward-only start
    assert H4 == 14400000 and DAY == 86400000 and abs(COST_PP - 0.14) < 1e-12
    commit_ms = int(datetime.datetime(2026, 11, 4, 7, 51, 47, tzinfo=utc).timestamp() * 1000)
    assert FIRST_BAR_CLOSE_MS % H4 == 0 and fmt_ms(FIRST_BAR_CLOSE_MS) == "2026-11-04 08:00"
    assert FIRST_BAR_CLOSE_MS > commit_ms >= FIRST_BAR_CLOSE_MS - H4
    assert day_of(20000 * DAY) == "2024-10-04" and fmt_ms(0) == "1970-01-01 00:00"
    assert len(M.SYMS) == 40

    # 2 candle parsing
    got = parse_raw([[H1 * 5, "100", "101", "99", "100"], [H1 * 5 + 1, "1", "2", "1", "1"], ["bad"],
                     [H1 * 6, "nan", "1", "1", "1"], [H1 * 7, "100", "99", "98", "100"],
                     [H1 * 8, "100", "101", "99", "-1"], [H1 * 9, "100", "101", "99", "100.5"]], H1)
    assert got == {H1 * 5: (100.0, 101.0, 99.0, 100.0), H1 * 9: (100.0, 101.0, 99.0, 100.5)}, got

    # 3 signal detection on synthetic hourly candles
    FLAT = (100.0, 100.5, 99.5, 100.0)
    T = 20003 * DAY

    def base():
        return dict((t, FLAT) for t in range(T - 200 * H1, T + 100 * H1, H1))

    def sig(last):
        cm = base()
        for k in range(2, 20):
            cm[T - k * H1] = (100.0, 101.0, 99.0, 100.0)
        cm[T - H1] = last
        return cm
    LONG_LAST = (100.0, 102.5, 100.0, 102.0)
    ev = eval_bar(sig(LONG_LAST), T - H4)
    assert ev["status"] == "SIGNAL" and ev["direction"] == "LONG" and ev["T"] == T, ev
    assert close(ev["hh"], 101.0) and close(ev["ll"], 99.0) and close(ev["close"], 102.0), ev
    assert close(ev["m19"], 2.0) and close(ev["tr19"], 38.5) and close(ev["prev19"], 19.0), ev
    assert close(ev["s_pos"], 1.5), ev
    ev = eval_bar(sig((100.0, 100.0, 97.5, 98.0)), T - H4)
    assert ev["direction"] == "SHORT" and close(ev["m19"], -2.0) and close(ev["s_pos"], -0.5), ev
    assert eval_bar(sig((100.0, 102.5, 100.0, 100.8)), T - H4)["status"] == "NO_SIGNAL"
    cm = base()
    cm[T - H1] = LONG_LAST
    ev = eval_bar(cm, T - H4)
    assert ev["status"] == "NO_SIGNAL" and close(ev["tr19"], 20.5) and close(ev["prev19"], 19.0), ev
    cm[T - H1] = (100.0, 110.5, 100.0, 110.0)
    assert eval_bar(cm, T - H4)["status"] == "SIGNAL"
    cm[T - H1] = (100.0, 110.4, 100.0, 110.0)
    assert eval_bar(cm, T - H4)["status"] == "NO_SIGNAL"
    cm = sig(LONG_LAST)
    del cm[T - 50 * H1]
    ev = eval_bar(cm, T - H4)
    assert ev["status"] == "UNAVAILABLE" and "24 complete 4H bars" in ev["reason"], ev
    cm = sig(LONG_LAST)
    del cm[T - 2 * H1]
    assert eval_bar(cm, T - H4)["reason"] == "signal bar incomplete"
    cm = dict((t, v) for t, v in sig(LONG_LAST).items() if t >= T - 90 * H1)
    assert "24 complete 4H bars" in eval_bar(cm, T - H4)["reason"]

    # 4 trade simulation, stops, gaps, mirror
    def pathcm(px, mods=None):
        cm = dict((T + i * H1, (px, px + 0.5, px - 0.5, px)) for i in range(24))
        for i, v in (mods or {}).items():
            cm[T + i * H1] = v
        return cm
    LASTC = {23: (102.0, 103.5, 101.5, 103.0)}
    cmA = pathcm(102.0, LASTC)
    r = simulate(cmA, "LONG", T, 102.0)
    assert r["exit_type"] == "TIME" and r["exit_px"] == 103.0 and r["exit_ms"] == T + 24 * H1, r
    assert close(r["gross"], 1.0 / 102.0 * 100.0) and close(r["net"], r["gross"] - 0.14), r
    assert close(r["r"], r["net"] / 2.0) and close(r["stop"], 99.96), r
    m = simulate(cmA, "SHORT", T, 102.0)
    assert m["exit_type"] == "TIME" and close(m["gross"], -1.0 / 102.0 * 100.0) and close(m["stop"], 104.04), m
    cmB = pathcm(102.0, {**LASTC, 5: (102.0, 102.2, 99.5, 100.0)})
    r = simulate(cmB, "LONG", T, 102.0)
    assert r["exit_type"] == "STOP" and close(r["exit_px"], 99.96) and r["exit_ms"] == T + 6 * H1, r
    assert close(r["gross"], -2.0) and close(r["net"], -2.14) and close(r["r"], -1.07), r
    assert simulate(cmB, "SHORT", T, 102.0)["exit_type"] == "TIME"
    cmC = pathcm(102.0, {**LASTC, 3: (99.0, 99.5, 98.5, 99.2)})
    r = simulate(cmC, "LONG", T, 102.0)
    assert r["exit_type"] == "STOP" and r["exit_px"] == 99.0 and r["exit_ms"] == T + 3 * H1, r
    assert close(r["gross"], -3.0 / 102.0 * 100.0) and close(r["net"], r["gross"] - 0.14), r
    r = simulate(pathcm(98.0, {2: (98.0, 100.5, 97.5, 99.0)}), "SHORT", T, 98.0)
    assert r["exit_type"] == "STOP" and close(r["exit_px"], 99.96) and r["exit_ms"] == T + 3 * H1, r
    assert close(r["gross"], -2.0) and close(r["net"], -2.14), r
    cmM = dict(cmA)
    del cmM[T + 10 * H1]
    assert simulate(cmM, "LONG", T, 102.0) is None

    # 5 context M position
    d0 = ((T - H1) // DAY) * DAY
    daily = dict((d0 - j * DAY, (100.0, 110.0, 90.0, 100.0)) for j in range(1, 131))
    assert close(m_pos_for(daily, T, 102.0), 0.6)
    gap = dict(daily)
    del gap[d0 - 50 * DAY]
    assert m_pos_for(gap, T, 102.0) is None
    assert m_pos_for(dict((d0 - j * DAY, (100.0, 100.0, 100.0, 100.0)) for j in range(1, 131)), T, 100.0) is None

    # 6 per-coin sequencing with a fake signal source (patched eval_bar)
    cmF = base()
    T1, U0, T2, T3 = T, T - 4 * H1, T + 8 * H1, T + 28 * H1
    first = T1 - 8 * H1
    sigmap = {U0: "UNAV", T1: "LONG", T2: "LONG", T3: "LONG"}

    def fake(cm, t0):
        Tb = t0 + H4
        v = sigmap.get(Tb)
        if v == "UNAV":
            return {"status": "UNAVAILABLE", "reason": "fake", "T": Tb}
        if v:
            return {"status": "SIGNAL", "direction": v, "close": 100.0, "hh": 100.5, "ll": 99.5, "m19": 0.5,
                    "tr19": 20.0, "prev19": 10.0, "s_pos": 0.5, "T": Tb}
        return {"status": "NO_SIGNAL", "T": Tb}
    g = globals()
    real_eval = g["eval_bar"]
    g["eval_bar"] = fake
    try:
        now = T1 + 60 * H1
        rows1, pend, blk = process_coin(closed_only(cmF, now), now, first, {})
        assert [(r["T"], r["kind"]) for r in rows1] == [(U0, "UNAVAILABLE"), (T1, "OK"), (T3, "OK")], rows1
        assert not pend and blk == 1, (pend, blk)
        t1 = rows1[1]
        assert t1["direction"] == "LONG" and close(t1["entry"], 100.0) and close(t1["stop"], 98.0), t1
        assert t1["exit_type"] == "TIME" and t1["exit_ms"] == T1 + 24 * H1, t1
        assert close(t1["gross"], 0.0) and close(t1["net"], -0.14) and close(t1["r"], -0.07), t1
        assert close(t1["mirror"], -0.14) and close(t1["s_pos"], 0.5), t1
        now = T1 + 30 * H1
        rows, pend, blk = process_coin(closed_only(cmF, now), now, first, {})
        assert [(r["T"], r["kind"]) for r in rows] == [(U0, "UNAVAILABLE"), (T1, "OK")] and pend and blk == 1
        now = T1 + 10 * H1
        rows, pend, blk = process_coin(closed_only(cmF, now), now, first, {})
        assert [(r["T"], r["kind"]) for r in rows] == [(U0, "UNAVAILABLE")] and pend and blk == 0
        now = T1 + 60 * H1
        rows, pend, blk = process_coin(closed_only(cmF, now), now, first, {U0: None, T1: T1 + 24 * H1})
        assert [(r["T"], r["kind"]) for r in rows] == [(T3, "OK")] and not pend and blk == 1, rows
        cmG = dict(cmF)
        del cmG[T1 + 5 * H1]
        rows, pend, blk = process_coin(closed_only(cmG, now), now, first, {})
        assert [(r["T"], r["kind"]) for r in rows] == [(U0, "UNAVAILABLE"), (T1, "UNAVAILABLE"), (T3, "OK")], rows
        assert rows[1]["reason"] == "path candles missing" and rows[1]["exit_ms"] == T1 + 24 * H1, rows[1]
        assert rows[1]["direction"] == "LONG" and blk == 1
        short = dict((t, v) for t, v in cmF.items() if t >= T1 - 10 * H1)
        assert process_coin(closed_only(short, now), now, first, {}) == ([], False, 0)
        assert process_coin({}, now, first, {}) == ([], False, 0)
    finally:
        g["eval_bar"] = real_eval
    assert g["eval_bar"] is real_eval

    # 7 storage and stored map (in memory)
    con = sqlite3.connect(":memory:")
    con.execute(SCHEMA)
    assert store_rows(con, "XUSDT", "spot", rows1, None) == 3
    assert store_rows(con, "XUSDT", "spot", rows1, None) == 0
    assert stored_map(con, "XUSDT") == {U0: None, T1: T1 + 24 * H1, T3: T3 + 24 * H1}
    row = con.execute("select direction, status, entry, stop, exit_type, net_pct, r_net, mirror_net_pct, s_pos, "
                      "m_pos, signal_utc, day_utc, source from shadow_breakout19 where signal_close_ms=?",
                      (T1,)).fetchone()
    assert row[:2] == ("LONG", "OK") and row[4] == "TIME" and row[9] is None, row
    assert close(row[2], 100.0) and close(row[3], 98.0) and close(row[5], -0.14) and close(row[6], -0.07), row
    assert close(row[7], -0.14) and close(row[8], 0.5), row
    assert row[10:] == (fmt_ms(T1), day_of(T1), "spot"), row
    row = con.execute("select status, reason, direction from shadow_breakout19 where signal_close_ms=?",
                      (U0,)).fetchone()
    assert row == ("UNAVAILABLE", "fake", None), row
    con2 = sqlite3.connect(":memory:")
    con2.execute(SCHEMA)
    store_rows(con2, "YUSDT", "futures", [rows1[1]], daily)
    assert close(con2.execute("select m_pos from shadow_breakout19").fetchone()[0], 0.5)
    assert closed_only({T: FLAT, T + H1: FLAT}, T + H1) == {T: FLAT}

    # 8 statistics and report
    assert count_overlaps([("X", 0, 10), ("Y", 5, 15), ("Z", 20, 30), ("X", 6, 8)]) == 3
    assert days_over([T + i * 1000 for i in range(7)] + [T + DAY, T + DAY + 1], 5) == 1

    def table(n, mod_days=20, unav=3):
        c = sqlite3.connect(":memory:")
        c.execute(SCHEMA)
        for i in range(n):
            t = 20010 * DAY + (i % mod_days) * DAY + (8 if i < 20 else 12) * H1
            stop = i % 4 == 0
            c.execute("insert into shadow_breakout19(symbol, signal_close_ms, status, direction, exit_ms, "
                      "exit_type, net_pct, r_net, mirror_net_pct) values(?,?,?,?,?,?,?,?,?)",
                      ("S%d" % i, t, "OK", "LONG" if i < 30 else "SHORT", t + 24 * H1,
                       "STOP" if stop else "TIME", -2.14 if stop else 1.0, -1.07 if stop else 0.5, 0.5))
        for i in range(unav):
            c.execute("insert into shadow_breakout19(symbol, signal_close_ms, status) values(?,?,?)",
                      ("U%d" % i, 20010 * DAY + i, "UNAVAILABLE"))
        return c
    c = table(40)
    s = summarize(c.execute("select symbol, signal_close_ms, status, direction, exit_ms, exit_type, net_pct, "
                            "r_net, mirror_net_pct from shadow_breakout19").fetchall())
    assert (s["n"], s["longs"], s["shorts"], s["days"], s["unavailable"]) == (40, 30, 10, 20, 3), s
    assert close(s["stopped"], 0.25) and close(s["hit"], 0.75) and close(s["net"], 0.215), s
    assert close(s["pd_net"], 0.215) and close(s["r"], 0.1075) and close(s["pd_r"], 0.1075), s
    assert close(s["mirror"], 0.5) and s["overlaps"] == 40 and s["over5"] == 0, s
    lines = build_report(c)
    assert lines[0] == ("40 trades graded (long 30, short 10) over 20 distinct UTC signal days; UNAVAILABLE rows 3. "
                        "Rule: read nothing before 30 trades and 20 distinct days."), lines[0]
    text = "\n".join(lines)
    assert "stopped out 25.0% | net hit rate 75.0% | mean net +0.215% (per-day mean +0.215%)" in text, text
    assert "mean R +0.11 (per-day mean +0.11)" in text and "mean net +0.500%" in text, text
    assert "overlapping trades across coins: 40 of 40 | UTC days above 5 signals: 0" in text, text
    assert "NOT READ" not in text
    assert "NOT READ" in "\n".join(build_report(table(29)))
    assert "NOT READ" in "\n".join(build_report(table(40, mod_days=10)))
    assert build_report(sqlite3.connect(":memory:")) == ["no shadow_breakout19 table yet"]
    assert "NOT READ" in "\n".join(build_report(table(0)))

    # 9 candle fetch with a fake requests.get (no network)
    import requests
    import market_facts as mf
    real = requests.get
    calls = []

    class Resp:
        def __init__(self, code, data=None):
            self.status_code, self._d = code, data

        def json(self):
            return self._d

    def kl(n, step=H1, t0=1000 * H1):
        return [[t0 + i * step, "100", "100.5", "99.5", "100", "1"] for i in range(n)]
    script = []

    def fakeget(url, params=None, timeout=None):
        calls.append((url, dict(params)))
        x = script.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    requests.get = fakeget
    try:
        script[:] = [Resp(200, kl(250))]
        name, cm, why = fetch_klines("XUSDT", "1h", LIMIT, NEED_H)
        assert name == "spot" and len(cm) == 250 and why is None, (name, len(cm), why)
        assert calls[0] == (mf.URLS["spot"], {"symbol": "XUSDT", "interval": "1h", "limit": 1000}), calls[0]
        script[:] = [Resp(400, {}), Resp(200, kl(250))]
        name, cm, why = fetch_klines("XUSDT", "1h", LIMIT, NEED_H)
        assert name == "futures" and len(cm) == 250 and why is None, (name, len(cm), why)
        script[:] = [Resp(200, kl(100)), Resp(429, {})]
        assert fetch_klines("XUSDT", "1h", LIMIT, NEED_H) == (None, {}, "deferred")
        script[:] = [Resp(200, kl(100)), Resp(400, {})]
        name, cm, why = fetch_klines("XUSDT", "1h", LIMIT, NEED_H)
        assert name == "spot" and len(cm) == 100 and why is None, (name, len(cm), why)
        script[:] = [Resp(400, {}), Resp(400, {})]
        assert fetch_klines("XUSDT", "1h", LIMIT, NEED_H) == (None, {}, "nosource")
        script[:] = [Resp(200, []), Resp(200, [])]
        assert fetch_klines("XUSDT", "1h", LIMIT, NEED_H) == (None, {}, "nosource")
        script[:] = [RuntimeError("boom"), RuntimeError("boom")]
        assert fetch_klines("XUSDT", "1h", LIMIT, NEED_H) == (None, {}, "deferred")
        calls[:] = []
        script[:] = [Resp(200, kl(130, step=DAY, t0=1000 * DAY))]
        name, cm, why = fetch_klines("XUSDT", "1d", 130, 130)
        assert name == "spot" and len(cm) == 130 and calls[0][1]["interval"] == "1d" and calls[0][1]["limit"] == 130
    finally:
        requests.get = real
    assert mf.URLS.get("spot") and mf.URLS.get("futures")
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"selftest": selftest, "check": cmd_check, "run": cmd_run, "report": cmd_report}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
