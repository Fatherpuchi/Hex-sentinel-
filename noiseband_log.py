#!/usr/bin/env python3
"""noiseband_log.py - noiseband_v1 (frozen spec: noiseband_v1_spec.md). Shadow only.
Public 30-minute klines only. Writes ONLY shadow_noiseband in shadow.db (on `run`).
No AI calls. Never touches prompts, the guard, plans, decisions or the live path.
Forward only: nothing before FIRST_DAY is computed, graded or counted.
Usage: python3 noiseband_log.py selftest | check | run | report"""
import sys
import time
import sqlite3
import datetime

import codeplan_log as C
import market_ctx_log as M

DB = "shadow.db"
H30 = 1800000
DAY = 86400000
NCAND = 48
LOOKBACK = 14
LIMIT = 1000
NEED_CANDLES = (LOOKBACK + 1) * NCAND
COST_PP = 0.10
MIN_ENTRIES = 30
MIN_DAYS = 20
FIRST_DAY_MS = int(datetime.datetime(2026, 10, 27, tzinfo=datetime.timezone.utc).timestamp() * 1000)
SCHEMA = (
    "create table if not exists shadow_noiseband(id integer primary key autoincrement, "
    "created_utc text, day_utc text, symbol text, status text, reason text, direction text, "
    "entry_idx integer, exit_idx integer, entry_px real, exit_px real, gross_pct real, "
    "net_pct real, raw_pct real, source text, unique(day_utc, symbol))")


def utcnow_s():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_str(d0):
    return datetime.datetime.fromtimestamp(d0 / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")


def day_ms(s):
    dt = datetime.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def fmt_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def parse_raw(raw):
    out = {}
    for k in raw:
        try:
            t, o, c = int(k[0]), float(k[1]), float(k[4])
        except Exception:
            continue
        if t % H30 != 0 or not (o == o and c == c) or abs(o) == float("inf") or abs(c) == float("inf"):
            continue
        if o <= 0 or c <= 0:
            continue
        out[t] = (o, c)
    return out


def fetch_30m(symbol, timeout=15):
    """Returns (source, {open_ms: (open, close)}, why). why: None | 'deferred' | 'nosource'."""
    import requests
    import market_facts as mf
    best_name, best = None, {}
    transient = False
    for name in ("spot", "futures"):
        try:
            r = requests.get(mf.URLS[name], params={"symbol": symbol, "interval": "30m",
                             "limit": LIMIT}, timeout=timeout)
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
        cm = parse_raw(d)
        if len(cm) >= NEED_CANDLES:
            return name, cm, None
        if len(cm) > len(best):
            best_name, best = name, cm
    if transient and len(best) < NEED_CANDLES:
        return None, {}, "deferred"
    if best:
        return best_name, best, None
    return None, {}, "nosource"


def day_complete(cm, d0):
    return all((d0 + k * H30) in cm for k in range(NCAND))


def eval_day(closed, d0):
    res = {"day": day_str(d0), "status": "UNAVAILABLE", "reason": "", "dir": None, "ke": None,
           "kx": None, "pe": None, "px": None, "gross": None, "net": None, "raw": None}
    if not day_complete(closed, d0):
        res["reason"] = "day incomplete"
        return res
    prior = [d0 - j * DAY for j in range(1, LOOKBACK + 1)]
    if not all(day_complete(closed, p) for p in prior):
        res["reason"] = "lookback incomplete"
        return res
    open0 = closed[d0][0]
    upper, lower = [], []
    for k in range(NCAND):
        m = sum(abs(closed[p + k * H30][1] - closed[p][0]) for p in prior) / float(LOOKBACK)
        upper.append(open0 + m)
        lower.append(open0 - m)
    ke, direction = None, None
    for k in range(NCAND - 1):
        c = closed[d0 + k * H30][1]
        if c > upper[k]:
            ke, direction = k, "LONG"
            break
        if c < lower[k]:
            ke, direction = k, "SHORT"
            break
    if ke is None:
        res["status"] = "NO_ENTRY"
        return res
    kx = NCAND - 1
    for k in range(ke + 1, NCAND):
        c = closed[d0 + k * H30][1]
        if lower[k] <= c <= upper[k]:
            kx = k
            break
    pe = closed[d0 + ke * H30][1]
    px = closed[d0 + kx * H30][1]
    raw = (px - pe) / pe * 100.0
    gross = raw if direction == "LONG" else -raw
    res.update(status="ENTRY", dir=direction, ke=ke, kx=kx, pe=pe, px=px, gross=gross,
               net=gross - COST_PP, raw=raw)
    return res


def process_days(cm, now_ms, first_ms, stored):
    closed = dict((t, v) for t, v in cm.items() if t + H30 <= now_ms)
    if not closed:
        return []
    wstart = min(closed)
    last0 = (now_ms // DAY - 1) * DAY
    rows = []
    d0 = first_ms
    while d0 <= last0:
        if day_str(d0) not in stored and wstart <= d0:
            rows.append(eval_day(closed, d0))
        d0 += DAY
    return rows


def store_rows(con, sym, name, rows):
    now = utcnow_s()
    n = 0
    for r in rows:
        cur = con.execute(
            "insert or ignore into shadow_noiseband(created_utc, day_utc, symbol, status, reason, "
            "direction, entry_idx, exit_idx, entry_px, exit_px, gross_pct, net_pct, raw_pct, source) "
            "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, r["day"], sym, r["status"], r["reason"], r["dir"], r["ke"], r["kx"], r["pe"],
             r["px"], r["gross"], r["net"], r["raw"], name))
        n += 1 if cur.rowcount > 0 else 0
    con.commit()
    return n


def group_lines(name, grp):
    if not grp:
        return ["%-5s no ENTRY rows" % name]
    s = C.dir_stats([(r[0], "BUY" if r[2] == "LONG" else "SELL", r[3]) for r in grp])
    byd = {}
    for r in grp:
        byd.setdefault(r[0], []).append((r[3], r[4]))
    n = len(grp)
    mg = sum(r[3] for r in grp) / float(n)
    mn = sum(r[4] for r in grp) / float(n)
    pdg = sum(sum(g for g, _ in v) / len(v) for v in byd.values()) / len(byd)
    pdn = sum(sum(x for _, x in v) / len(v) for v in byd.values()) / len(byd)
    if s["n"]:
        first = ("%-5s n=%d days=%d hit %.1f%% | always-up %.1f%% | base %.1f%% | per-day mean hit %.1f%% "
                 "| excluded %d" % (name, s["n"], s["days"], 100 * s["hit"], 100 * s["always_up"],
                                    100 * s["base"], 100 * s["per_day"], s["excluded"]))
    else:
        first = "%-5s every entry had a gross result of exactly 0 (%d excluded)" % (name, s["excluded"])
    second = ("      mean gross %+.3f%% net %+.3f%% over %d entries | per-day mean gross %+.3f%% net %+.3f%%"
              % (mg, mn, n, pdg, pdn))
    return [first, second]


def build_report(con):
    if not con.execute("select count(*) from sqlite_master where name='shadow_noiseband'").fetchone()[0]:
        return ["no shadow_noiseband table yet"]
    rows = con.execute("select day_utc, status, direction, gross_pct, net_pct from shadow_noiseband").fetchall()
    ent = [r for r in rows if r[1] == "ENTRY" and r[3] is not None and r[4] is not None]
    noe = sum(1 for r in rows if r[1] == "NO_ENTRY")
    una = sum(1 for r in rows if r[1] == "UNAVAILABLE")
    days = len(set(r[0] for r in ent))
    nl = sum(1 for r in ent if r[2] == "LONG")
    out = ["%d ENTRY rows over %d distinct days (long %d, short %d); NO_ENTRY %d; UNAVAILABLE %d. "
           "Rule: read nothing before %d ENTRY rows and %d distinct days."
           % (len(ent), days, nl, len(ent) - nl, noe, una, MIN_ENTRIES, MIN_DAYS)]
    if len(ent) < MIN_ENTRIES or days < MIN_DAYS:
        out.append("NOT READ: too few entries or days. No conclusions.")
        return out
    out.extend(group_lines("all", ent))
    out.extend(group_lines("long", [r for r in ent if r[2] == "LONG"]))
    out.extend(group_lines("short", [r for r in ent if r[2] == "SHORT"]))
    out.append("No pass bar, no causal claim. Net uses a placeholder 0.10 pp round-trip cost; spread, "
               "slippage and funding are not modeled. Entries cluster across coins on the same days.")
    return out


def cmd_check():
    now_ms = int(time.time() * 1000)
    last0 = (now_ms // DAY - 1) * DAY
    n_elig = 0 if last0 < FIRST_DAY_MS else (last0 - FIRST_DAY_MS) // DAY + 1
    print("first day %s (forward only) | now %s UTC | last complete day %s | eligible days so far %d"
          % (day_str(FIRST_DAY_MS), fmt_ms(now_ms), day_str(last0), n_elig))
    if n_elig == 0:
        print("no eligible day yet: %s completes at %s UTC" % (day_str(FIRST_DAY_MS), fmt_ms(FIRST_DAY_MS + DAY)))
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_noiseband'").fetchone()[0]:
        print("table shadow_noiseband does not exist yet; `run` would create it. "
              "Nothing was requested or written.")
        return
    by = dict(con.execute("select status, count(*) from shadow_noiseband group by 1").fetchall())
    last = con.execute("select max(day_utc) from shadow_noiseband").fetchone()[0]
    print("stored rows by status %s | last stored day %s" % (by, last))


def cmd_run():
    con = sqlite3.connect(DB, timeout=30)
    con.execute(SCHEMA)
    con.commit()
    now_ms = int(time.time() * 1000)
    last0 = (now_ms // DAY - 1) * DAY
    if last0 < FIRST_DAY_MS:
        print("run: no eligible day yet (%s completes at %s UTC). Nothing requested, nothing written."
              % (day_str(FIRST_DAY_MS), fmt_ms(FIRST_DAY_MS + DAY)))
        return
    stored = {}
    for d, s in con.execute("select day_utc, symbol from shadow_noiseband"):
        stored.setdefault(s, set()).add(d)
    cnt = {"ENTRY": 0, "NO_ENTRY": 0, "UNAVAILABLE": 0}
    deferred = nosrc = 0
    for sym in M.SYMS:
        name, cm, why = fetch_30m(sym)
        if why == "deferred":
            print("DEFER %s: request failed, retry next run" % sym)
            deferred += 1
            time.sleep(0.3)
            continue
        if why == "nosource":
            print("NOSOURCE %s: no candle source, nothing stored" % sym)
            nosrc += 1
            time.sleep(0.3)
            continue
        rows = process_days(cm, now_ms, FIRST_DAY_MS, stored.get(sym, set()))
        store_rows(con, sym, name, rows)
        for r in rows:
            cnt[r["status"]] += 1
            if r["status"] == "UNAVAILABLE":
                print("UNAVAILABLE %s %s: %s" % (sym, r["day"], r["reason"]))
        time.sleep(0.3)
    print("run: %d new rows (ENTRY %d, NO_ENTRY %d, UNAVAILABLE %d), %d symbols deferred, %d without a source"
          % (sum(cnt.values()), cnt["ENTRY"], cnt["NO_ENTRY"], cnt["UNAVAILABLE"], deferred, nosrc))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    for line in build_report(con):
        print(line)


def selftest():
    utc = datetime.timezone.utc

    def close(a, b, e=1e-9):
        return a is not None and abs(a - b) < e

    # 1 constants, forward-only start, reused helpers
    assert FIRST_DAY_MS % DAY == 0 and day_str(FIRST_DAY_MS) == "2026-10-27"
    commit_ms = int(datetime.datetime(2026, 10, 26, 7, 4, 39, tzinfo=utc).timestamp() * 1000)
    assert FIRST_DAY_MS > commit_ms and FIRST_DAY_MS - DAY <= commit_ms
    assert day_ms("2026-10-27") == FIRST_DAY_MS
    assert len(M.SYMS) == 40 and NEED_CANDLES == 720
    s = C.dir_stats([("d1", "BUY", 2.0), ("d1", "SELL", -1.0), ("d2", "BUY", 0.0)])
    assert s["n"] == 2 and s["excluded"] == 1 and close(s["hit"], 0.5) and close(s["always_up"], 1.0), s
    assert close(s["base"], 0.5) and close(s["per_day"], 0.5) and s["days"] == 1, s

    # 2 candle parsing
    ok = parse_raw([[H30 * 5, "100", "0", "0", "101"], [H30 * 5 + 1, "1", "0", "0", "1"], ["bad"],
                    [H30 * 6, "nan", "0", "0", "1"], [H30 * 7, "100", "0", "0", "-1"]])
    assert ok == {H30 * 5: (100.0, 101.0)}, ok

    # 3 synthetic days: prior closes = 100 + 0.25 x (k+1), so Noise(k) = 0.25 x (k+1) exactly
    D0 = 20014 * DAY
    NOW = D0 + DAY + 3600000

    def make(fn, n_prior=14, drop=(), start_k=0):
        cm = {}
        for j in range(n_prior, 0, -1):
            p = D0 - j * DAY
            for k in range(NCAND):
                cm[p + k * H30] = (100.0, 100.0 + 0.25 * (k + 1))
        for k in range(start_k, NCAND):
            cm[D0 + k * H30] = (100.0, fn(k))
        for t in drop:
            cm.pop(t, None)
        return cm

    def one(cm, now=NOW, first=D0, stored=frozenset()):
        return process_days(cm, now, first, set(stored))

    r = one(make(lambda k: 100.0))
    assert len(r) == 1 and r[0]["status"] == "NO_ENTRY" and r[0]["day"] == day_str(D0), r
    r = one(make(lambda k: {5: 102.0, 6: 100.5}.get(k, 100.0)))[0]
    assert r["status"] == "ENTRY" and r["dir"] == "LONG" and r["ke"] == 5 and r["kx"] == 6, r
    raw = (100.5 - 102.0) / 102.0 * 100.0
    assert close(r["gross"], raw) and close(r["raw"], raw) and close(r["net"], raw - 0.10), r
    assert r["pe"] == 102.0 and r["px"] == 100.5, r
    r = one(make(lambda k: 98.0 if k == 3 else (90.2 if k > 3 else 100.0)))[0]
    assert r["dir"] == "SHORT" and r["ke"] == 3 and r["kx"] == 39 and r["px"] == 90.2, r
    raw = (90.2 - 98.0) / 98.0 * 100.0
    assert close(r["raw"], raw) and close(r["gross"], -raw) and close(r["net"], -raw - 0.10), r
    r = one(make(lambda k: 105.0 if k == 2 else (120.0 if k > 2 else 100.0)))[0]
    assert r["dir"] == "LONG" and r["ke"] == 2 and r["kx"] == 47 and r["px"] == 120.0, r
    assert close(r["gross"], (120.0 - 105.0) / 105.0 * 100.0), r
    r = one(make(lambda k: 103.0 if k == 4 else (90.2 if k > 4 else 100.0)))[0]
    assert r["dir"] == "LONG" and r["ke"] == 4 and r["kx"] == 39 and r["px"] == 90.2, r
    assert close(r["gross"], (90.2 - 103.0) / 103.0 * 100.0), r
    r = one(make(lambda k: 120.0 if k == 46 else 100.0))[0]
    assert r["status"] == "ENTRY" and r["ke"] == 46 and r["kx"] == 47 and r["px"] == 100.0, r
    r = one(make(lambda k: 150.0 if k == 47 else 100.0))[0]
    assert r["status"] == "NO_ENTRY", r

    # 4 unavailable days and skipped days
    r = one(make(lambda k: 100.0, drop=(D0 + 10 * H30,)))[0]
    assert r["status"] == "UNAVAILABLE" and r["reason"] == "day incomplete", r
    r = one(make(lambda k: 100.0, drop=(D0 - 5 * DAY + 3 * H30,)))[0]
    assert r["status"] == "UNAVAILABLE" and r["reason"] == "lookback incomplete", r
    r = one(make(lambda k: 100.0, n_prior=10))[0]
    assert r["status"] == "UNAVAILABLE" and r["reason"] == "lookback incomplete", r
    assert one(make(lambda k: 100.0, n_prior=0, start_k=10)) == []
    cm = make(lambda k: 100.0)
    assert one(cm, first=D0 + DAY) == []
    assert one(cm, stored={day_str(D0)}) == []
    assert one(cm, now=D0 + DAY - 1) == []
    assert one({}) == []
    rows = one(make(lambda k: 100.0, n_prior=15), first=D0 - DAY)
    assert [x["day"] for x in rows] == [day_str(D0 - DAY), day_str(D0)], rows
    assert [x["status"] for x in rows] == ["NO_ENTRY", "NO_ENTRY"], rows
    assert len(one(make(lambda k: 100.0, n_prior=15), first=D0 - DAY, stored={day_str(D0 - DAY)})) == 1

    # 5 storage (in memory)
    sc = sqlite3.connect(":memory:")
    sc.execute(SCHEMA)
    rows = one(make(lambda k: {5: 102.0, 6: 100.5}.get(k, 100.0)))
    assert store_rows(sc, "XUSDT", "spot", rows) == 1 and store_rows(sc, "XUSDT", "spot", rows) == 0
    row = sc.execute("select day_utc, symbol, status, direction, entry_idx, exit_idx, entry_px, exit_px, source "
                     "from shadow_noiseband").fetchone()
    assert row == (day_str(D0), "XUSDT", "ENTRY", "LONG", 5, 6, 102.0, 100.5, "spot"), row

    # 6 report
    def fresh(spec):
        c2 = sqlite3.connect(":memory:")
        c2.execute(SCHEMA)
        for i, (day, st, d, g, n) in enumerate(spec):
            c2.execute("insert into shadow_noiseband(created_utc, day_utc, symbol, status, direction, "
                       "gross_pct, net_pct) values(?,?,?,?,?,?,?)", ("t", day, "S%d" % i, st, d, g, n))
        return c2
    spec = []
    for i in range(25):
        day = "2026-11-%02d" % (i + 1)
        spec.append((day, "ENTRY", "LONG", 1.0, 0.9))
        spec.append((day, "ENTRY", "SHORT", -0.5, -0.6))
    spec.append(("2026-11-01", "NO_ENTRY", None, None, None))
    spec.append(("2026-11-01", "UNAVAILABLE", None, None, None))
    t = "\n".join(build_report(fresh(spec)))
    assert "50 ENTRY rows over 25 distinct days (long 25, short 25); NO_ENTRY 1; UNAVAILABLE 1" in t, t
    assert "n=50 days=25 hit 50.0% | always-up 100.0% | base 50.0% | per-day mean hit 50.0% | excluded 0" in t, t
    assert "mean gross +0.250% net +0.150% over 50 entries | per-day mean gross +0.250% net +0.150%" in t, t
    assert "n=25 days=25 hit 100.0% | always-up 100.0% | base 100.0%" in t, t
    assert "n=25 days=25 hit 0.0% | always-up 100.0% | base 0.0%" in t, t
    assert "mean gross +1.000% net +0.900% over 25 entries" in t and "mean gross -0.500% net -0.600% over 25 entries" in t, t
    t = "\n".join(build_report(fresh([("2026-11-%02d" % (i // 3 + 1), "ENTRY", "LONG", 1.0, 0.9) for i in range(30)])))
    assert "NOT READ" in t and "30 ENTRY rows over 10 distinct days" in t, t
    t = "\n".join(build_report(fresh([("2026-11-%02d" % (i + 1), "ENTRY", "LONG", 1.0, 0.9) for i in range(20)])))
    assert "NOT READ" in t, t
    assert build_report(sqlite3.connect(":memory:")) == ["no shadow_noiseband table yet"]

    # 7 candle fetch with a fake requests.get (no network)
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

    def page(n):
        return [[20000 * DAY + i * H30, "100", "0", "0", "100.5"] for i in range(n)]
    script = []

    def fake(url, params=None, timeout=None):
        calls.append((url, dict(params)))
        x = script.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    requests.get = fake
    try:
        script[:] = [Resp(200, page(800))]
        name, cm, why = fetch_30m("XUSDT")
        assert name == "spot" and len(cm) == 800 and why is None, (name, len(cm), why)
        assert calls[0] == (mf.URLS["spot"], {"symbol": "XUSDT", "interval": "30m", "limit": 1000}), calls[0]
        script[:] = [Resp(400, {}), Resp(200, page(800))]
        name, cm, why = fetch_30m("XUSDT")
        assert name == "futures" and len(cm) == 800 and why is None, (name, len(cm), why)
        script[:] = [Resp(200, page(100)), Resp(200, page(900))]
        name, cm, why = fetch_30m("XUSDT")
        assert name == "futures" and len(cm) == 900 and why is None, (name, len(cm), why)
        script[:] = [Resp(200, page(100)), Resp(400, {})]
        name, cm, why = fetch_30m("XUSDT")
        assert name == "spot" and len(cm) == 100 and why is None, (name, len(cm), why)
        script[:] = [Resp(200, page(100)), Resp(429, {})]
        assert fetch_30m("XUSDT") == (None, {}, "deferred")
        script[:] = [Resp(400, {}), Resp(400, {})]
        assert fetch_30m("XUSDT") == (None, {}, "nosource")
        script[:] = [Resp(200, []), Resp(200, [])]
        assert fetch_30m("XUSDT") == (None, {}, "nosource")
        script[:] = [RuntimeError("boom"), RuntimeError("boom")]
        assert fetch_30m("XUSDT") == (None, {}, "deferred")
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
