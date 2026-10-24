#!/usr/bin/env python3
"""webdir_log.py - webdir_v1 (frozen spec: webdir_v1_spec.md). Shadow only.
Reads web_intelligence_evidence in sentinel.db READ-ONLY. Writes ONLY shadow_webdir and
shadow_webdir_grade in shadow.db (on `run`). No AI calls. Never touches prompts, evidence
weights, the guard, decisions or the live path.
Usage: python3 webdir_log.py selftest | check | run | report"""
import sys
import time
import sqlite3
import datetime

import codeplan_log as C

SENT_DB = "sentinel.db"
DB = "shadow.db"
H = 3600000
DAY = 24 * H
MAX_SYMS = 40
PAGES = 4
DUE_H = 25
SCHEMA = [
    "create table if not exists shadow_webdir(id integer primary key autoincrement, "
    "created_utc text, unit_key text unique, kind text, symbol text, snap_ms integer, "
    "day_utc text, call_dir integer, n_bull integer, n_bear integer, event_key text, status text)",
    "create table if not exists shadow_webdir_grade(id integer primary key autoincrement, "
    "graded_utc text, unit_id integer unique, entry real, fwd_pct real, status text, "
    "reason text, source text, candles_used integer)",
]


def utcnow_s():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_date(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")


def to_ms(ts):
    try:
        s = str(ts).strip().replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def norm_symbol(s):
    s = str(s or "").strip().upper()
    if not s or s == "NONE":
        return None
    return s if s.endswith("USDT") else s + "USDT"


def read_evidence(sc):
    rows = sc.execute("select symbol, direction, retrieved_at, event_key from web_intelligence_evidence "
                      "where direction in ('BULLISH','BEARISH')").fetchall()
    ev, skipped = [], 0
    for sym, d, ra, ek in rows:
        ms, ns = to_ms(ra), norm_symbol(sym)
        if ms is None or ns is None:
            skipped += 1
            continue
        ev.append((ns, 1 if d == "BULLISH" else -1, ms, ek))
    return ev, skipped


def build_units(ev, now_ms):
    units = {}
    cnt = {}
    for ns, c, ms, ek in ev:
        d0 = (ms // DAY) * DAY
        b = cnt.setdefault((ns, d0), [0, 0])
        b[0 if c > 0 else 1] += 1
    for (ns, d0), (nb, nr) in cnt.items():
        snap = d0 + DAY
        if snap > now_ms:
            continue
        call = (nb > nr) - (nb < nr)
        units["P|%s|%d" % (ns, snap)] = {
            "kind": "P", "symbol": ns, "snap": snap, "day": utc_date(d0), "call": call,
            "nb": nb, "nr": nr, "ek": None, "status": "TIE" if call == 0 else "PENDING"}
    first = {}
    for ns, c, ms, ek in ev:
        if ek is None or str(ek).strip() == "":
            continue
        k = (ns, str(ek))
        if k not in first or ms < first[k][0]:
            first[k] = (ms, c)
    for (ns, ek), (ms, c) in first.items():
        snap = ((ms + H - 1) // H) * H
        if snap > now_ms:
            continue
        units["E|%s|%s" % (ns, ek)] = {
            "kind": "E", "symbol": ns, "snap": snap, "day": utc_date(snap), "call": c,
            "nb": 1 if c > 0 else 0, "nr": 1 if c < 0 else 0, "ek": ek, "status": "PENDING"}
    return units


def ensure_schema(con):
    for s in SCHEMA:
        con.execute(s)
    con.commit()


def store_units(con, units):
    now = utcnow_s()
    n = 0
    for key in sorted(units):
        u = units[key]
        cur = con.execute(
            "insert or ignore into shadow_webdir(created_utc, unit_key, kind, symbol, snap_ms, day_utc, "
            "call_dir, n_bull, n_bear, event_key, status) values(?,?,?,?,?,?,?,?,?,?,?)",
            (now, key, u["kind"], u["symbol"], u["snap"], u["day"], u["call"], u["nb"], u["nr"],
             u["ek"], u["status"]))
        if cur.rowcount > 0:
            n += 1
    con.commit()
    return n


def due_units(con, now_ms):
    rows = con.execute(
        "select u.id, u.symbol, u.snap_ms, u.call_dir, u.kind from shadow_webdir u "
        "left join shadow_webdir_grade g on g.unit_id = u.id "
        "where g.id is null and u.call_dir != 0 order by u.id").fetchall()
    due = [r for r in rows if now_ms >= r[2] + DUE_H * H]
    return due, len(rows) - len(due)


def parse_closes(raw):
    out = {}
    for k in raw:
        try:
            t = int(k[0])
            c = float(k[4])
        except Exception:
            continue
        if c == c and abs(c) != float("inf"):
            out[t] = c
    return out


def fetch_closes(symbol, start_ms, end_ms, timeout=15):
    import requests
    import market_facts as mf
    for name in ("spot", "futures"):
        closes = {}
        start = int(start_ms)
        for _ in range(PAGES):
            try:
                r = requests.get(mf.URLS[name], params={"symbol": symbol, "interval": "1h",
                                 "startTime": start, "limit": 1000}, timeout=timeout)
            except Exception:
                return None, {}, "deferred"
            if r.status_code in (418, 429) or r.status_code >= 500:
                return None, {}, "deferred"
            if r.status_code != 200:
                break
            try:
                d = r.json()
            except Exception:
                return None, {}, "deferred"
            if not isinstance(d, list) or not d:
                break
            page = parse_closes(d)
            if not page:
                break
            closes.update(page)
            last = max(page)
            if len(d) < 1000 or last + H > end_ms:
                break
            start = last + H
        if closes:
            return name, closes, None
    return None, {}, "nosource"


def grade_unit(snap, closes):
    need = [snap - H + i * H for i in range(25)]
    if any(t not in closes for t in need):
        return None, "missing or gapped candles"
    entry = closes[need[0]]
    if entry <= 0:
        return None, "non-positive entry"
    return (entry, (closes[need[24]] - entry) / entry * 100.0), ""


def write_grade(con, uid, entry, fwd, status, reason, source, used):
    con.execute(
        "insert or ignore into shadow_webdir_grade(graded_utc, unit_id, entry, fwd_pct, status, reason, "
        "source, candles_used) values(?,?,?,?,?,?,?,?)",
        (utcnow_s(), uid, entry, fwd, status, reason, source, used))
    con.commit()


def eval_units(rows):
    allr = [(d, "BUY" if c > 0 else "SELL", f * c) for d, c, f in rows if c != 0]
    return {"all": C.dir_stats(allr),
            "bull": C.dir_stats([r for r in allr if r[1] == "BUY"]),
            "bear": C.dir_stats([r for r in allr if r[1] == "SELL"])}


def line(name, s):
    if not s["n"]:
        return "%-6s n=0 (%d excluded)" % (name, s["excluded"])
    return ("%-6s n=%d days=%d hit %.1f%% | always-up %.1f%% | base %.1f%% | per-day mean %.1f%% "
            "| excluded %d" % (name, s["n"], s["days"], 100 * s["hit"], 100 * s["always_up"],
                              100 * s["base"], 100 * s["per_day"], s["excluded"]))


def open_sentinel():
    return sqlite3.connect("file:%s?mode=ro" % SENT_DB, uri=True)


def cmd_check():
    sc = open_sentinel()
    now_ms = int(time.time() * 1000)
    ev, skipped = read_evidence(sc)
    raw = [r[0] for r in sc.execute("select distinct symbol from web_intelligence_evidence")]
    non = [s for s in raw if not str(s).upper().endswith("USDT")]
    print("directional evidence rows used %d (skipped %d: bad time or no symbol)" % (len(ev), skipped))
    print("distinct stored symbols %d, not ending in USDT %d, sample %s" % (len(raw), len(non), raw[:8]))
    units = build_units(ev, now_ms)
    kinds = {"P": 0, "E": 0}
    ties = 0
    for u in units.values():
        kinds[u["kind"]] += 1
        ties += 1 if u["call"] == 0 and u["kind"] == "P" else 0
    print("units that would exist now: %d primary (%d ties), %d event" % (kinds["P"], ties, kinds["E"]))
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_webdir'").fetchone()[0]:
        print("tables do not exist yet; `run` would create them. Nothing was requested or written.")
        return
    due, notdue = due_units(con, now_ms)
    stored = con.execute("select count(*) from shadow_webdir").fetchone()[0]
    print("stored units %d | %d due for grading, %d not due yet" % (stored, len(due), notdue))


def cmd_run():
    sc = open_sentinel()
    con = sqlite3.connect(DB, timeout=30)
    ensure_schema(con)
    now_ms = int(time.time() * 1000)
    ev, skipped = read_evidence(sc)
    new = store_units(con, build_units(ev, now_ms))
    due, notdue = due_units(con, now_ms)
    by = {}
    for uid, sym, snap, call, kind in due:
        by.setdefault(sym, []).append((uid, snap))
    syms = sorted(by)
    ok = bad = deferred = 0
    for sym in syms[:MAX_SYMS]:
        us = by[sym]
        name, closes, why = fetch_closes(sym, min(u[1] for u in us) - H, max(u[1] for u in us) + 24 * H)
        if name is None and why == "deferred":
            print("DEFER %s: request failed, retry next run" % sym)
            deferred += 1
            time.sleep(0.3)
            continue
        for uid, snap in us:
            if name is None:
                write_grade(con, uid, None, None, "UNAVAILABLE", "no candle source", None, 0)
                bad += 1
                continue
            res, reason = grade_unit(snap, closes)
            if res is None:
                write_grade(con, uid, None, None, "UNAVAILABLE", reason, name, 0)
                bad += 1
            else:
                write_grade(con, uid, res[0], res[1], "OK", "", name, 25)
                ok += 1
        if name is None:
            print("UNAVAILABLE %s: no candle source (%d units)" % (sym, len(us)))
        time.sleep(0.3)
    print("run: %d new units, %d graded OK, %d UNAVAILABLE, %d symbols deferred, %d symbols over run limit, "
          "%d units not due yet" % (new, ok, bad, deferred, max(0, len(syms) - MAX_SYMS), notdue))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_webdir_grade'").fetchone()[0]:
        print("no webdir tables yet")
        return
    tot = dict(con.execute("select kind, count(*) from shadow_webdir group by 1").fetchall())
    ties = con.execute("select count(*) from shadow_webdir where call_dir = 0").fetchone()[0]
    rows = con.execute(
        "select u.kind, u.day_utc, u.call_dir, g.fwd_pct, g.status from shadow_webdir u "
        "join shadow_webdir_grade g on g.unit_id = u.id where u.call_dir != 0").fetchall()
    ok = [r for r in rows if r[4] == "OK"]
    pri = [(r[1], r[2], r[3]) for r in ok if r[0] == "P"]
    evn = [(r[1], r[2], r[3]) for r in ok if r[0] == "E"]
    days = len(set(r[0] for r in pri))
    print("units: primary %d (ties %d), event %d | graded OK: primary %d over %d days, event %d | "
          "unavailable %d. Rule: read nothing before 30 graded primary units and 20 distinct days."
          % (tot.get("P", 0), ties, tot.get("E", 0), len(pri), days, len(evn), len(rows) - len(ok)))
    if len(pri) < 30 or days < 20:
        print("NOT READ: too few units or days. No conclusions.")
        return
    res = eval_units(pri)
    print("PRIMARY (symbol-day)")
    for k in ("all", "bull", "bear"):
        print(line(k, res[k]))
    if len(evn) < 30:
        print("EVENT: NOT READ (%d graded, minimum 30)" % len(evn))
    else:
        res = eval_units(evn)
        print("EVENT (symbol-event), not pooled with primary")
        for k in ("all", "bull", "bear"):
            print(line(k, res[k]))
    print("No pass bar, no causal claim. Tests the keyword rule only. Rows cluster by day and symbol.")


def selftest():
    def close(a, b, e=1e-9):
        return a is not None and abs(a - b) < e
    utc = datetime.timezone.utc

    # 1 time parsing and symbols
    d = datetime.date(2026, 10, 23)
    base = ((d - datetime.date(1970, 1, 1)).days * 24 * 3600 + 22 * 3600 + 35 * 60 + 15) * 1000
    assert abs(to_ms("2026-10-23T22:35:15.812612+00:00") - (base + 812)) <= 1
    assert to_ms("2026-10-23T22:35:15Z") == base and to_ms("2026-10-23T22:35:15") == base
    assert to_ms("2026-10-23T23:35:15+01:00") == base and to_ms("not a time") is None and to_ms(None) is None
    assert utc_date(base) == "2026-10-23"
    assert norm_symbol("btc") == "BTCUSDT" and norm_symbol("ETHUSDT") == "ETHUSDT"
    assert norm_symbol("") is None and norm_symbol(None) is None

    # 2 evidence read (in-memory)
    sc = sqlite3.connect(":memory:")
    sc.execute("create table web_intelligence_evidence(symbol, direction, retrieved_at, event_key)")
    sc.executemany("insert into web_intelligence_evidence values(?,?,?,?)", [
        ("a", "BULLISH", "2026-10-23T22:35:15.812612+00:00", "k1"),
        ("AUSDT", "NEUTRAL", "2026-10-23T22:35:15+00:00", "k9"),
        ("B", "BEARISH", "not a time", "k2"),
        (None, "BULLISH", "2026-10-23T22:35:15+00:00", "k3")])
    ev, sk = read_evidence(sc)
    assert len(ev) == 1 and sk == 2 and ev[0][0] == "AUSDT" and ev[0][1] == 1, (ev, sk)

    # 3 unit construction
    D0 = 20000 * DAY
    ev = [("AUSDT", 1, D0 + 3 * H, "e1"), ("AUSDT", 1, D0 + 5 * H, "e1"),
          ("AUSDT", -1, D0 + 7 * H + 30 * 60000, "e2"), ("AUSDT", 1, D0 + DAY + 2 * H, "e3"),
          ("AUSDT", -1, D0 + DAY + 3 * H, "e4"), ("BUSDT", -1, D0 + DAY + 90 * 60000, None),
          ("AUSDT", 1, D0 + 2 * DAY + H, "e5")]
    now = D0 + 2 * DAY + 5 * H
    units = build_units(ev, now)
    assert len(units) == 8 and sum(1 for u in units.values() if u["kind"] == "P") == 3, sorted(units)
    u = units["P|AUSDT|%d" % (D0 + DAY)]
    assert u["call"] == 1 and u["nb"] == 2 and u["nr"] == 1 and u["day"] == utc_date(D0), u
    u = units["P|AUSDT|%d" % (D0 + 2 * DAY)]
    assert u["call"] == 0 and u["status"] == "TIE", u
    assert units["P|BUSDT|%d" % (D0 + 2 * DAY)]["call"] == -1
    assert "P|AUSDT|%d" % (D0 + 3 * DAY) not in units
    assert units["E|AUSDT|e1"]["snap"] == D0 + 3 * H and units["E|AUSDT|e1"]["call"] == 1
    assert units["E|AUSDT|e2"]["snap"] == D0 + 8 * H and units["E|AUSDT|e2"]["call"] == -1
    assert units["E|AUSDT|e5"]["snap"] == D0 + 2 * DAY + H

    # 4 storage, due logic, grade writing (in memory)
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    assert store_units(con, units) == 8 and store_units(con, units) == 0
    due, notdue = due_units(con, now)
    assert len(due) == 5 and notdue == 2, (len(due), notdue)
    uid = [r for r in due if r[1] == "AUSDT" and r[4] == "E"][0][0]
    write_grade(con, uid, 100.0, 1.5, "OK", "", "spot", 25)
    write_grade(con, uid, 100.0, 9.9, "OK", "", "spot", 25)
    assert con.execute("select count(*), max(fwd_pct) from shadow_webdir_grade").fetchone() == (1, 1.5)
    assert len(due_units(con, now)[0]) == 4

    # 5 grading arithmetic
    S = 20000 * DAY + 7 * H
    cl = dict((S - H + i * H, 100.0) for i in range(25))
    cl[S + 23 * H] = 102.0
    res, why = grade_unit(S, cl)
    assert res is not None and close(res[0], 100.0) and close(res[1], 2.0), (res, why)
    cl2 = dict(cl)
    del cl2[S + 5 * H]
    assert grade_unit(S, cl2) == (None, "missing or gapped candles")
    cl3 = dict(cl)
    cl3[S - H] = 0.0
    assert grade_unit(S, cl3) == (None, "non-positive entry")

    # 6 statistics
    rows = [("d1", 1, 2.0), ("d1", 1, 3.0), ("d2", -1, -3.0), ("d2", -1, 1.0),
            ("d3", 1, -2.0), ("d3", 1, 0.0)]
    r = eval_units(rows)
    a = r["all"]
    assert a["n"] == 5 and a["excluded"] == 1 and a["days"] == 3, a
    assert close(a["hit"], 0.6) and close(a["always_up"], 0.6) and close(a["base"], 0.52), a
    assert close(a["per_day"], 0.5), a
    b = r["bull"]
    assert b["n"] == 3 and close(b["hit"], 2 / 3.0) and close(b["base"], 2 / 3.0) and close(b["per_day"], 0.5), b
    e = r["bear"]
    assert e["n"] == 2 and close(e["hit"], 0.5) and close(e["base"], 0.5), e

    # 7 klines paging with a fake requests.get (no network)
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
        return [[t0 + i * H, "1", "1", "1", "100.0"] for i in range(n)]
    script = []

    def fake(url, params=None, timeout=None):
        calls.append(params["startTime"])
        x = script.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    requests.get = fake
    try:
        st = 1000 * H
        script[:] = [Resp(400, {}), Resp(200, page(st, 1000)), Resp(200, page(st + 1000 * H, 5))]
        name, closes, why = fetch_closes("XUSDT", st, st + 1004 * H)
        assert name == "futures" and len(closes) == 1005 and why is None, (name, len(closes), why)
        assert calls == [st, st, st + 1000 * H], calls
        script[:] = [Resp(429, {})]
        assert fetch_closes("XUSDT", st, st + H) == (None, {}, "deferred")
        script[:] = [Resp(400, {}), Resp(400, {})]
        assert fetch_closes("XUSDT", st, st + H) == (None, {}, "nosource")
        script[:] = [RuntimeError("boom")]
        assert fetch_closes("XUSDT", st, st + H) == (None, {}, "deferred")
        script[:] = [Resp(200, page(st, 30))]
        name, closes, why = fetch_closes("XUSDT", st, st + 29 * H)
        assert name == "spot" and len(closes) == 30, (name, len(closes))
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
