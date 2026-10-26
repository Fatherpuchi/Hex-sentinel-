#!/usr/bin/env python3
"""levelcmp_log.py - levelcmp_v1 (frozen spec: levelcmp_v1_spec.md). Shadow only.
Reads shadow.db (shadow_held_plans, shadow_counterfactual, shadow_levels) and public
1-minute candles. Writes ONLY shadow_levelcmp in shadow.db (on `run`). No AI calls.
Never touches AI plans, prompts, levels_v1, held_plan_grade, the guard or the live path.
Usage: python3 levelcmp_log.py selftest | check | run | report"""
import sys
import time
import sqlite3
import datetime

DB = "shadow.db"
M = 60000
WIN = 1440
NEED = 1380
PAIR_MS = 1800000
DUE_EXTRA_MIN = 5
MAX_GROUPS = 40
MIN_PAIRS = 30
MIN_DAYS = 10
SCHEMA = (
    "create table if not exists shadow_levelcmp(id integer primary key autoincrement, "
    "created_utc text, held_id integer unique, cf_id integer, levels_id integer, ai text, "
    "symbol text, direction text, audit_ms integer, day_utc text, ai_entry real, ai_stop real, "
    "ai_tp1 real, ai_tp2 real, ai_tp3 real, calc_entry real, calc_stop real, calc_tp1 real, "
    "calc_tp2 real, calc_tp3 real, ai_outcome text, calc_outcome text, ai_r real, calc_r real, "
    "ai_stop_pct real, calc_stop_pct real, stored_ai_outcome text, consistent integer, "
    "candles_used integer, source text, status text, reason text)")
CAND_SQL = (
    "select h.id, h.ai, h.symbol, h.direction, h.created_ms, h.entry_low, h.entry_high, "
    "h.stop_loss, h.tp1, h.tp2, h.tp3, h.outcome, c.id, c.created_ms, l.id, l.entry, l.stop, "
    "l.tp1, l.tp2, l.tp3 from shadow_held_plans h join shadow_counterfactual c "
    "on c.symbol = h.symbol and upper(c.direction) = upper(h.direction) "
    "and abs(c.created_ms - h.created_ms) <= 1800000 and coalesce(c.excluded, 0) = 0 "
    "join shadow_levels l on l.cf_id = c.id and l.status = 'OK' "
    "where h.graded_utc is not null "
    "and h.outcome not in ('UNPARSED','DIRECTION_MISMATCH','INVALID_LEVELS')")


def utcnow_s():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_date(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")


def num(x):
    try:
        v = float(x)
    except Exception:
        return None
    return v if v == v and abs(v) != float("inf") else None


def start_of(ms):
    return (int(ms) // M + 1) * M


def due_ms(ms):
    return start_of(ms) + (WIN + DUE_EXTRA_MIN) * M


def pick_pairs(rows):
    best = {}
    for r in rows:
        gap = abs(r[13] - r[4])
        if gap > PAIR_MS:
            continue
        key = (gap, r[12])
        if r[0] not in best or key < best[r[0]][0]:
            best[r[0]] = (key, r)
    return dict((hid, v[1]) for hid, v in best.items())


def walk(direction, stop, tps, seq):
    buy = direction == "BUY"
    best = 0
    for _t, hi, lo, _c in seq:
        stop_hit = (lo <= stop) if buy else (hi >= stop)
        touched = 0
        for n, tp in enumerate(tps, 1):
            if (hi >= tp) if buy else (lo <= tp):
                touched = n
        if stop_hit:
            if best == 0 and touched > 0:
                return "AMBIGUOUS"
            return "TP%d" % best if best else "STOP"
        if touched > best:
            best = touched
    return "TP%d" % best if best else "NONE"


def side(direction, e, stop, tps, seq):
    res = {"outcome": "UNAVAILABLE", "r": None, "stop_pct": None, "reason": ""}
    vals = [num(e), num(stop)] + [num(x) for x in tps]
    if any(v is None or v <= 0 for v in vals):
        res["reason"] = "missing or non-positive levels"
        return res
    e, stop, t = vals[0], vals[1], vals[2:]
    buy = direction == "BUY"
    if (buy and stop >= e) or ((not buy) and stop <= e):
        res["reason"] = "stop on the wrong side"
        return res
    ok = (e < t[0] <= t[1] <= t[2]) if buy else (e > t[0] >= t[1] >= t[2])
    if not ok:
        res["reason"] = "TPs not monotonic or on the wrong side"
        return res
    sd = abs(e - stop)
    out = walk(direction, stop, t, seq)
    sgn = 1.0 if buy else -1.0
    if out == "STOP":
        r = -1.0
    elif out.startswith("TP"):
        r = abs(t[int(out[2]) - 1] - e) / sd
    elif out == "NONE":
        r = sgn * (seq[-1][3] - e) / sd
    else:
        r = None
    return {"outcome": out, "r": r, "stop_pct": sd / e * 100.0, "reason": ""}


def grade_pair(direction, ai_e, ai_stop, ai_tps, calc_e, calc_stop, calc_tps, seq):
    a = side(direction, ai_e, ai_stop, ai_tps, seq)
    c = side(direction, calc_e, calc_stop, calc_tps, seq)
    bad = [(n, x) for n, x in (("ai", a), ("calc", c)) if x["outcome"] in ("AMBIGUOUS", "UNAVAILABLE")]
    if bad:
        reason = "; ".join("%s %s%s" % (n, x["outcome"], (": " + x["reason"]) if x["reason"] else "")
                           for n, x in bad)
        return {"ai": a, "calc": c, "status": "EXCLUDED", "reason": reason}
    return {"ai": a, "calc": c, "status": "OK", "reason": ""}


def no_source_result():
    na = {"outcome": "UNAVAILABLE", "r": None, "stop_pct": None, "reason": ""}
    return {"ai": na, "calc": dict(na), "status": "UNAVAILABLE", "reason": "no candle source"}


def parse_candles(raw):
    out = {}
    for k in raw:
        try:
            t, hi, lo, cl = int(k[0]), float(k[2]), float(k[3]), float(k[4])
        except Exception:
            continue
        if all(v == v and abs(v) != float("inf") for v in (hi, lo, cl)):
            out[t] = (hi, lo, cl)
    return out


def fetch_1m(symbol, start_ms, timeout=15):
    """Returns (source, {open_ms: (hi, lo, close)}, why). why: None | 'short' | 'deferred' | 'nosource'."""
    import requests
    import market_facts as mf
    end = start_ms + WIN * M
    best = (None, {})
    transient = False
    for name in ("spot", "futures"):
        got = {}
        st = int(start_ms)
        for _ in range(2):
            try:
                r = requests.get(mf.URLS[name], params={"symbol": symbol, "interval": "1m",
                                 "startTime": st, "limit": 1000}, timeout=timeout)
            except Exception:
                transient = True
                break
            if r.status_code in (418, 429) or r.status_code >= 500:
                transient = True
                break
            if r.status_code != 200:
                break
            try:
                d = r.json()
            except Exception:
                transient = True
                break
            if not isinstance(d, list) or not d:
                break
            page = parse_candles(d)
            if not page:
                break
            got.update(page)
            last = max(page)
            if len(d) < 1000 or last + M >= end:
                break
            st = last + M
        win = dict((t, v) for t, v in got.items() if start_ms <= t < end)
        if len(win) >= NEED:
            return name, win, None
        if len(win) > len(best[1]):
            best = (name, win)
    if transient:
        return None, {}, "deferred"
    if best[1]:
        return best[0], best[1], "short"
    return None, {}, "nosource"


def ensure_schema(con):
    con.execute(SCHEMA)
    con.commit()


def store_pair(con, r, g, source, used):
    a, c = g["ai"], g["calc"]
    el, eh = num(r[5]), num(r[6])
    ai_e = (el + eh) / 2.0 if el is not None and eh is not None else None
    cons = None
    if g["status"] in ("OK", "EXCLUDED") and a["outcome"] != "UNAVAILABLE":
        cons = int(a["outcome"] == str(r[11]))
    cols = ("created_utc, held_id, cf_id, levels_id, ai, symbol, direction, audit_ms, day_utc, "
            "ai_entry, ai_stop, ai_tp1, ai_tp2, ai_tp3, calc_entry, calc_stop, calc_tp1, calc_tp2, "
            "calc_tp3, ai_outcome, calc_outcome, ai_r, calc_r, ai_stop_pct, calc_stop_pct, "
            "stored_ai_outcome, consistent, candles_used, source, status, reason")
    vals = (utcnow_s(), r[0], r[12], r[14], r[1], r[2], str(r[3]).upper(), r[4], utc_date(r[4]),
            ai_e, r[7], r[8], r[9], r[10], r[15], r[16], r[17], r[18], r[19],
            a["outcome"], c["outcome"], a["r"], c["r"], a["stop_pct"], c["stop_pct"],
            str(r[11]), cons, used, source, g["status"], g["reason"])
    con.execute("insert or ignore into shadow_levelcmp(%s) values(%s)" % (cols, ",".join(["?"] * 31)), vals)
    con.commit()


def summarize(rows, ai):
    mine = [r for r in rows if r[0] == ai]
    ok = [r for r in mine if r[2] == "OK"]
    ex = [r for r in mine if r[2] == "EXCLUDED"]
    un = [r for r in mine if r[2] == "UNAVAILABLE"]
    out = {"ai": ai, "stored": len(mine), "ok": len(ok), "excluded": len(ex), "unavailable": len(un),
           "days": len(set(r[1] for r in ok))}
    diffs = [(r[1], r[5] - r[6]) for r in ok]
    out["mean_diff"] = sum(d for _, d in diffs) / len(diffs) if diffs else None
    byd = {}
    for day, d in diffs:
        byd.setdefault(day, []).append(d)
    out["per_day_diff"] = sum(sum(v) / len(v) for v in byd.values()) / len(byd) if byd else None
    graded = ok + ex
    ac, cc = {}, {}
    for r in graded:
        ac[r[3]] = ac.get(r[3], 0) + 1
        cc[r[4]] = cc.get(r[4], 0) + 1
    out["ai_counts"], out["calc_counts"] = ac, cc
    both = [r for r in graded if r[7] is not None and r[8] is not None]
    out["both"] = len(both)
    if both:
        out["ai_stop_mean"] = sum(r[7] for r in both) / len(both)
        out["calc_stop_mean"] = sum(r[8] for r in both) / len(both)
        out["closer_share"] = sum(1 for r in both if r[7] < r[8]) / float(len(both))
    out["checked"] = sum(1 for r in graded if r[9] is not None)
    out["mismatch"] = sum(1 for r in graded if r[9] == 0)
    return out


def fmt_counts(d):
    return " ".join("%s %d" % (k, d[k]) for k in sorted(d)) or "none"


def cmd_check():
    con = sqlite3.connect(DB, timeout=30)
    names = set(r[0] for r in con.execute("select name from sqlite_master where type='table'"))
    for t in ("shadow_held_plans", "shadow_counterfactual", "shadow_levels"):
        if t not in names:
            print("missing table %s; nothing was written" % t)
            return
    picks = pick_pairs(con.execute(CAND_SQL).fetchall())
    by = {}
    for r in picks.values():
        by.setdefault(r[1], []).append(r)
    for ai in sorted(by):
        rs = by[ai]
        gaps = [abs(r[13] - r[4]) / 60000.0 for r in rs]
        print("%s: %d pairs over %d days, gap %.1f-%.1f min" % (
            ai, len(rs), len(set(utc_date(r[4]) for r in rs)), min(gaps), max(gaps)))
    if "shadow_levelcmp" not in names:
        print("table shadow_levelcmp does not exist yet; `run` would create it. "
              "Nothing was requested or written.")
        return
    done = set(r[0] for r in con.execute("select held_id from shadow_levelcmp"))
    todo = [r for hid, r in picks.items() if hid not in done]
    now = int(time.time() * 1000)
    due = [r for r in todo if now >= due_ms(r[4])]
    print("stored %d | %d pairs without a row: %d due, %d not due yet" % (
        len(done), len(todo), len(due), len(todo) - len(due)))


def cmd_run():
    con = sqlite3.connect(DB, timeout=30)
    ensure_schema(con)
    now = int(time.time() * 1000)
    picks = pick_pairs(con.execute(CAND_SQL).fetchall())
    done = set(r[0] for r in con.execute("select held_id from shadow_levelcmp"))
    todo = [r for hid, r in sorted(picks.items()) if hid not in done]
    due = [r for r in todo if now >= due_ms(r[4])]
    groups = {}
    for r in due:
        groups.setdefault((r[2], start_of(r[4])), []).append(r)
    keys = sorted(groups)
    logged = pending = deferred = unavail = 0
    for key in keys[:MAX_GROUPS]:
        sym, start = key
        name, win, why = fetch_1m(sym, start)
        if why == "deferred":
            print("DEFER %s: request failed, retry next run" % sym)
            deferred += len(groups[key])
            time.sleep(0.3)
            continue
        if why == "short":
            print("PENDING %s: only %d of %d candles, retry next run" % (sym, len(win), WIN))
            pending += len(groups[key])
            time.sleep(0.3)
            continue
        seq = sorted((t, v[0], v[1], v[2]) for t, v in win.items())
        for r in groups[key]:
            if name is None:
                store_pair(con, r, no_source_result(), None, 0)
                unavail += 1
            else:
                el, eh = num(r[5]), num(r[6])
                ai_e = (el + eh) / 2.0 if el is not None and eh is not None else None
                g = grade_pair(str(r[3]).upper(), ai_e, r[7], r[8:11], r[15], r[16], r[17:20], seq)
                store_pair(con, r, g, name, len(win))
                print("#%d %s %s %s ai=%s calc=%s %s" % (r[0], r[1], sym, str(r[3]).upper(),
                      g["ai"]["outcome"], g["calc"]["outcome"], g["status"]))
            logged += 1
        time.sleep(0.3)
    print("run: %d logged (%d with no candle source), %d pending, %d deferred, %d groups over run limit, "
          "%d pairs not due yet" % (logged, unavail, pending, deferred, max(0, len(keys) - MAX_GROUPS),
                                    len(todo) - len(due)))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_levelcmp'").fetchone()[0]:
        print("no shadow_levelcmp table yet")
        return
    rows = con.execute("select ai, day_utc, status, ai_outcome, calc_outcome, ai_r, calc_r, ai_stop_pct, "
                       "calc_stop_pct, consistent from shadow_levelcmp").fetchall()
    sums = dict((ai, summarize(rows, ai)) for ai in ("groq", "gemini"))
    for ai in ("groq", "gemini"):
        s = sums[ai]
        print("%s: %d stored, %d OK, %d excluded, %d unavailable, %d days. "
              "Rule: read nothing before %d OK pairs per AI and %d distinct days."
              % (ai, s["stored"], s["ok"], s["excluded"], s["unavailable"], s["days"], MIN_PAIRS, MIN_DAYS))
    if any(s["ok"] < MIN_PAIRS or s["days"] < MIN_DAYS for s in sums.values()):
        print("NOT READ: too few pairs or days. No conclusions.")
        return
    for ai in ("groq", "gemini"):
        s = sums[ai]
        print("%s | mean paired R (AI minus calculated) %+.3f over %d pairs | per-day mean %+.3f" % (
            ai, s["mean_diff"], s["ok"], s["per_day_diff"]))
        print("  AI outcomes: %s" % fmt_counts(s["ai_counts"]))
        print("  calc outcomes: %s" % fmt_counts(s["calc_counts"]))
        if s["both"]:
            print("  stop distance %% of entry: AI mean %.2f, calc mean %.2f | AI stop closer in %.1f%% of %d pairs"
                  % (s["ai_stop_mean"], s["calc_stop_mean"], 100 * s["closer_share"], s["both"]))
        print("  consistency with stored held-plan outcome: %d mismatches of %d checked" % (s["mismatch"], s["checked"]))
    print("No pass bar, no causal claim. Both AIs share the same calls. Fees and slippage not modeled.")


def selftest():
    def close(a, b, e=1e-9):
        return a is not None and abs(a - b) < e

    def mk(n, hi=100.4, lo=99.6, cl=100.0):
        return [[i * M, hi, lo, cl] for i in range(n)]

    def seqt(c):
        return [tuple(x) for x in c]

    # 1 walk: BUY
    B = (99.0, [101.0, 102.0, 103.0])

    def wb(mods):
        c = mk(20)
        for i, (h, l) in mods.items():
            c[i][1], c[i][2] = h, l
        return walk("BUY", B[0], B[1], seqt(c))
    assert wb({}) == "NONE"
    assert wb({5: (101.2, 99.5)}) == "TP1"
    assert wb({5: (102.5, 99.5), 9: (100.5, 98.9)}) == "TP2"
    assert wb({5: (101.2, 98.9)}) == "AMBIGUOUS"
    assert wb({2: (101.2, 99.5), 6: (102.5, 98.9)}) == "TP1"
    assert wb({4: (100.5, 98.9)}) == "STOP"
    assert wb({3: (100.5, 98.9), 7: (103.5, 99.5)}) == "STOP"
    assert wb({5: (103.5, 99.5)}) == "TP3"
    # walk: SELL
    c = mk(20)
    c[5][2] = 97.5
    assert walk("SELL", 101.0, [99.0, 98.0, 97.0], seqt(c)) == "TP2"
    c = mk(20)
    c[4][1] = 101.2
    assert walk("SELL", 101.0, [99.0, 98.0, 97.0], seqt(c)) == "STOP"

    # 2 side(): outcome, R, stop %
    c = mk(20)
    c[5][1] = 102.5
    s = side("BUY", 100.0, 99.0, [101.0, 102.0, 103.0], seqt(c))
    assert s["outcome"] == "TP2" and close(s["r"], 2.0) and close(s["stop_pct"], 1.0), s
    c = mk(20, cl=100.5)
    s = side("BUY", 100.0, 99.0, [101.0, 102.0, 103.0], seqt(c))
    assert s["outcome"] == "NONE" and close(s["r"], 0.5), s
    c = mk(20, cl=99.5)
    s = side("SELL", 100.0, 101.0, [99.0, 98.0, 97.0], seqt(c))
    assert s["outcome"] == "NONE" and close(s["r"], 0.5), s
    c = mk(20)
    c[3][2] = 98.9
    s = side("BUY", 100.0, 99.0, [101.0, 102.0, 103.0], seqt(c))
    assert s["outcome"] == "STOP" and close(s["r"], -1.0), s
    for args, why in (
            (("BUY", None, 99.0, [101.0, 102.0, 103.0]), "missing"),
            (("BUY", 100.0, 101.0, [101.0, 102.0, 103.0]), "wrong side"),
            (("BUY", 100.0, 99.0, [101.0, 100.5, 103.0]), "monotonic"),
            (("SELL", 100.0, 99.0, [99.0, 98.0, 97.0]), "wrong side"),
            (("BUY", 100.0, 100.0, [101.0, 102.0, 103.0]), "wrong side")):
        s = side(*args, seq=seqt(mk(5)))
        assert s["outcome"] == "UNAVAILABLE" and why in s["reason"], (args, s)

    # 3 grade_pair
    c = mk(10, hi=100.4, lo=98.9, cl=99.0)
    g = grade_pair("SELL", 100.0, 101.0, [99.0, 98.0, 97.0], 100.0, 100.5, [99.5, 99.0, 98.5], seqt(c))
    assert g["status"] == "OK" and g["ai"]["outcome"] == "TP1" and close(g["ai"]["r"], 1.0), g
    assert g["calc"]["outcome"] == "TP2" and close(g["calc"]["r"], 2.0), g
    c = mk(10)
    c[3][1], c[3][2] = 101.2, 98.9
    g = grade_pair("BUY", 100.0, 99.0, [101.0, 102.0, 103.0], 100.0, 99.5, [100.5, 101.0, 101.5], seqt(c))
    assert g["status"] == "EXCLUDED" and "AMBIGUOUS" in g["reason"], g
    assert no_source_result()["status"] == "UNAVAILABLE"

    # 4 timing helpers
    assert start_of(1000000) == 1020000 and start_of(1020000) == 1080000
    assert due_ms(1000000) == 1020000 + 1445 * M
    assert utc_date(86400000 * 20000) == "2024-10-04"

    # 5 pairing SQL and pick_pairs (in memory)
    db = sqlite3.connect(":memory:")
    db.execute("create table shadow_held_plans(id, ai, symbol, direction, created_ms, entry_low, entry_high, "
               "stop_loss, tp1, tp2, tp3, graded_utc, outcome)")
    db.execute("create table shadow_counterfactual(id, symbol, direction, created_ms, excluded)")
    db.execute("create table shadow_levels(id, cf_id, entry, stop, tp1, tp2, tp3, status)")
    T0 = 1000000
    db.executemany("insert into shadow_held_plans values(?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, "groq", "AUSDT", "SELL", T0, 99.5, 100.5, 101.0, 99.0, 98.0, 97.0, "g", "TP1"),
        (2, "gemini", "AUSDT", "SELL", T0, 99.5, 100.5, 101.0, 99.0, 98.0, 97.0, "g", "TP1"),
        (3, "groq", "BUSDT", "BUY", T0, 99.5, 100.5, 99.0, 101.0, 102.0, 103.0, "g", "UNPARSED"),
        (4, "groq", "AUSDT", "SELL", T0, 99.5, 100.5, 101.0, 99.0, 98.0, 97.0, None, None)])
    db.executemany("insert into shadow_counterfactual values(?,?,?,?,?)", [
        (10, "AUSDT", "SELL", T0 + 60000, 0), (11, "AUSDT", "SELL", T0 + 30000, 0),
        (15, "AUSDT", "SELL", T0 - 30000, 0), (12, "AUSDT", "BUY", T0 + 1000, 0),
        (13, "AUSDT", "SELL", T0 + 2000000, 0), (14, "AUSDT", "SELL", T0 + 1000, 1),
        (16, "BUSDT", "BUY", T0, 0)])
    db.executemany("insert into shadow_levels values(?,?,?,?,?,?,?,?)", [
        (100 + i, cid, 100.0, 100.5, 99.5, 99.0, 98.5, "OK") for i, cid in enumerate((10, 11, 15, 12, 13, 14, 16))])
    rows = db.execute(CAND_SQL).fetchall()
    picks = pick_pairs(rows)
    assert set(picks) == {1, 2}, set(picks)
    assert picks[1][12] == 11 and picks[2][12] == 11 and picks[1][14] == 101, picks[1]

    # 6 storage and consistency (in memory)
    st = sqlite3.connect(":memory:")
    ensure_schema(st)
    r = picks[1]
    seq = seqt(mk(10, hi=100.4, lo=98.9, cl=99.0))
    g = grade_pair("SELL", 100.0, r[7], r[8:11], r[15], r[16], r[17:20], seq)
    store_pair(st, r, g, "spot", 1440)
    store_pair(st, r, g, "spot", 1440)
    assert st.execute("select count(*) from shadow_levelcmp").fetchone()[0] == 1
    row = st.execute("select ai_outcome, calc_outcome, ai_r, calc_r, consistent, status, ai_entry, day_utc "
                     "from shadow_levelcmp").fetchone()
    assert row[0] == "TP1" and row[1] == "TP2" and close(row[2], 1.0) and close(row[3], 2.0), row
    assert row[4] == 1 and row[5] == "OK" and close(row[6], 100.0) and row[7] == "1970-01-01", row
    store_pair(st, picks[2], no_source_result(), None, 0)
    assert st.execute("select status, consistent from shadow_levelcmp where held_id=2").fetchone() == ("UNAVAILABLE", None)

    # 7 summaries
    rows = [("groq", "d1", "OK", "TP1", "STOP", 0.5, -1.0, 2.0, 1.0, 1),
            ("groq", "d1", "OK", "NONE", "TP2", 0.25, 2.0, 2.0, 1.0, 1),
            ("groq", "d2", "OK", "STOP", "STOP", -1.0, -1.0, 1.0, 2.0, 0),
            ("groq", "d2", "EXCLUDED", "AMBIGUOUS", "TP1", None, 1.0, 1.0, 1.0, 1),
            ("groq", "d2", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", None, None, None, None, None),
            ("gemini", "d1", "OK", "TP1", "TP1", 0.5, 0.5, 1.0, 1.0, 1)]
    s = summarize(rows, "groq")
    assert (s["stored"], s["ok"], s["excluded"], s["unavailable"], s["days"]) == (5, 3, 1, 1, 2), s
    assert close(s["mean_diff"], -0.25 / 3.0) and close(s["per_day_diff"], -0.0625), s
    assert s["ai_counts"] == {"TP1": 1, "NONE": 1, "STOP": 1, "AMBIGUOUS": 1}, s["ai_counts"]
    assert s["both"] == 4 and close(s["ai_stop_mean"], 1.5) and close(s["calc_stop_mean"], 1.25), s
    assert close(s["closer_share"], 0.25) and s["checked"] == 4 and s["mismatch"] == 1, s
    assert summarize(rows, "gemini")["ok"] == 1 and summarize([], "groq")["mean_diff"] is None

    # 8 candle fetch with a fake requests.get (no network)
    import requests
    import market_facts as mf
    real = requests.get
    calls = []

    class Resp:
        def __init__(self, code, data):
            self.status_code = code
            self._d = data

        def json(self):
            return self._d

    def page(t0, n):
        return [[t0 + i * M, "1", "101", "99", "100"] for i in range(n)]
    script = []

    def fake(url, params=None, timeout=None):
        calls.append(params["startTime"])
        x = script.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    requests.get = fake
    try:
        s0 = 1000 * M
        script[:] = [Resp(200, page(s0, 1000)), Resp(200, page(s0 + 1000 * M, 500))]
        name, win, why = fetch_1m("XUSDT", s0)
        assert name == "spot" and len(win) == 1440 and why is None, (name, len(win), why)
        assert calls == [s0, s0 + 1000 * M], calls
        assert win[s0] == (101.0, 99.0, 100.0) and max(win) == s0 + 1439 * M
        script[:] = [Resp(200, page(s0, 100)), Resp(200, page(s0, 1000)), Resp(200, page(s0 + 1000 * M, 440))]
        name, win, why = fetch_1m("XUSDT", s0)
        assert name == "futures" and len(win) == 1440 and why is None, (name, len(win), why)
        script[:] = [Resp(200, page(s0, 100)), Resp(200, page(s0, 200))]
        name, win, why = fetch_1m("XUSDT", s0)
        assert name == "futures" and len(win) == 200 and why == "short", (name, len(win), why)
        script[:] = [Resp(429, {}), Resp(429, {})]
        assert fetch_1m("XUSDT", s0) == (None, {}, "deferred")
        script[:] = [Resp(400, {}), Resp(400, {})]
        assert fetch_1m("XUSDT", s0) == (None, {}, "nosource")
        script[:] = [RuntimeError("boom"), RuntimeError("boom")]
        assert fetch_1m("XUSDT", s0) == (None, {}, "deferred")
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
