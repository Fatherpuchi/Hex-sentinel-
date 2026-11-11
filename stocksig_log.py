#!/usr/bin/env python3
"""stocksig_log.py - stocksig_v1 (frozen spec: stocksig_v1_spec.md). Shadow only.
Runs the stocks.py rule (EMA20/EMA50 + RSI14 on 1h closes) on every trading Binance TradFi
perpetual once a day and grades it forward. Public Binance USD-M futures endpoints only; no AI,
no keys. stocks.py and stock_paper.db are neither imported nor touched (rule functions copied).
Writes ONLY shadow_stocksig and shadow_stocksig_grade in shadow.db (on `run`).
Forward only: nothing before FIRST_DAY_MS is requested or stored.
Usage: python3 stocksig_log.py selftest | check | run | report"""
import sys
import time
import math
import sqlite3
import datetime

DB = "shadow.db"
FAPI = "https://fapi.binance.com"
H1 = 3600000
DAY = 24 * H1
MAX_GRADE = 60
PAUSE = 0.25
COST_PP = 0.14
MIN_BARS = 60
MAX_BARS = 100
FETCH_LIMIT = 120
FIRST_DAY_MS = int(datetime.datetime(2026, 11, 11, tzinfo=datetime.timezone.utc).timestamp() * 1000)
SCHEMA = [
    "create table if not exists shadow_stocksig(id integer primary key autoincrement, created_utc text, "
    "symbol text, day_utc text, t_ms integer, kind text, age_days real, vol24 real, entry real, "
    "direction text, e20 real, e50 real, rsi real, thr_pct real, market_open integer, source text, "
    "status text, reason text, unique(symbol, day_utc))",
    "create table if not exists shadow_stocksig_grade(id integer primary key autoincrement, "
    "unit_id integer unique, graded_utc text, exit_px real, ret real, result text, gross_pct real, "
    "net_pct real, status text, reason text)",
]


def utcnow_s():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_str(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")


def fmt_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def is_transient(code, data):
    return code in (0, 418, 429) or code >= 500 or (code == 200 and data is None)


def http_get(path, params=None, timeout=20):
    import requests
    try:
        r = requests.get(FAPI + path, params=params, timeout=timeout, headers={"User-Agent": "hex-stocksig/1"})
    except Exception:
        return 0, None
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


# ---- the stocks.py rule, copied (not imported) ----
def ema(v, n):
    k, e = 2.0 / (n + 1), v[0]
    for x in v[1:]:
        e = x * k + e * (1 - k)
    return e


def rsi(c, n=14):
    ch = [c[i] - c[i - 1] for i in range(1, len(c))]
    ag, al = sum(max(x, 0) for x in ch[:n]) / n, sum(max(-x, 0) for x in ch[:n]) / n
    for x in ch[n:]:
        ag, al = (ag * (n - 1) + max(x, 0)) / n, (al * (n - 1) + max(-x, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def signal(closes):
    e20, e50, r = ema(closes, 20), ema(closes, 50), rsi(closes)
    if e20 > e50 and 50 <= r <= 70:
        return "UP", e20, e50, r
    if e20 < e50:
        return "DOWN", e20, e50, r
    return "NO_CALL", e20, e50, r


def thr_of(cl):
    lr = [math.log(cl[i] / cl[i - 1]) for i in range(1, len(cl))]
    m = sum(lr) / len(lr)
    sd = math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1))
    return 0.25 * sd * math.sqrt(24)
# --- end part 1 ---


def market_open_guess(kind, dt):
    if kind not in ("EQUITY", "ETF"):
        return None
    return dt.weekday() < 5 and (13 * 60 + 30) <= dt.hour * 60 + dt.minute < 21 * 60


def classify(direction, ret, thr):
    if abs(ret) < thr:
        return "VOID"
    return "HIT" if (ret > 0) == (direction == "UP") else "MISS"


def closed_suffix(raw, t_ms):
    cs = {}
    for k in raw:
        try:
            o, c = int(k[0]), float(k[4])
        except Exception:
            continue
        if o % H1 != 0 or c != c or c <= 0 or abs(c) == float("inf"):
            continue
        if o + H1 <= t_ms:
            cs[o] = c
    if not cs:
        return []
    opens = []
    o = max(cs)
    while o in cs:
        opens.append(o)
        o -= H1
    opens.reverse()
    return [(x, cs[x]) for x in opens]


def build_unit(raw, t_ms):
    suf = closed_suffix(raw, t_ms)
    if not suf or suf[-1][0] != t_ms - H1:
        return {"direction": "UNAVAILABLE", "reason": "no closed candle just before T"}
    cl = [c for _, c in suf][-MAX_BARS:]
    if len(cl) < MIN_BARS:
        return {"direction": "UNAVAILABLE", "reason": "fewer than 60 contiguous closed hourly candles"}
    d, e20, e50, rs = signal(cl)
    return {"direction": d, "entry": cl[-1], "e20": e20, "e50": e50, "rsi": rs, "thr": thr_of(cl), "reason": ""}


def ensure_schema(con):
    for s in SCHEMA:
        con.execute(s)
    con.commit()


def insert_unit(con, sym, day, t_ms, kind, age, vol, mo, u):
    d = u["direction"]
    status = "PENDING" if d in ("UP", "DOWN") else d
    thr = u.get("thr")
    con.execute(
        "insert or ignore into shadow_stocksig(created_utc, symbol, day_utc, t_ms, kind, age_days, vol24, entry, "
        "direction, e20, e50, rsi, thr_pct, market_open, source, status, reason) "
        "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (utcnow_s(), sym, day, t_ms, kind, age, vol, u.get("entry"), d, u.get("e20"), u.get("e50"), u.get("rsi"),
         None if thr is None else thr * 100.0, mo, "futures", status, u.get("reason", "")))


def insert_grade(con, uid, exit_px, ret, result, gross, net, status, reason):
    con.execute(
        "insert or ignore into shadow_stocksig_grade(unit_id, graded_utc, exit_px, ret, result, gross_pct, "
        "net_pct, status, reason) values(?,?,?,?,?,?,?,?,?)",
        (uid, utcnow_s(), exit_px, ret, result, gross, net, status, reason))


def run_snapshot(con, now_ms, getter, sleep):
    t_ms = (now_ms // H1) * H1
    day = day_str(t_ms)
    out = {"universe": 0, "new": {"UP": 0, "DOWN": 0, "NO_CALL": 0, "UNAVAILABLE": 0}, "deferred": 0, "error": ""}
    code, info = getter("/fapi/v1/exchangeInfo", None)
    if code != 200 or not isinstance(info, dict) or not isinstance(info.get("symbols"), list):
        out["error"] = "exchangeInfo failed (HTTP %s)" % code
        return out
    meta = {}
    for s in info["symbols"]:
        if (isinstance(s, dict) and s.get("contractType") == "TRADIFI_PERPETUAL"
                and s.get("status") == "TRADING" and s.get("symbol")):
            meta[s["symbol"]] = s
    out["universe"] = len(meta)
    have = set(r[0] for r in con.execute("select symbol from shadow_stocksig where day_utc=?", (day,)))
    todo = sorted(s for s in meta if s not in have)
    vol = {}
    if todo:
        c2, tk = getter("/fapi/v1/ticker/24hr", None)
        if c2 == 200 and isinstance(tk, list):
            for t in tk:
                if isinstance(t, dict) and t.get("symbol") in meta:
                    try:
                        vol[t["symbol"]] = float(t.get("quoteVolume"))
                    except Exception:
                        pass
    dt = datetime.datetime.fromtimestamp(t_ms / 1000.0, datetime.timezone.utc)
    for sym in todo:
        code, raw = getter("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": FETCH_LIMIT})
        if is_transient(code, raw):
            out["deferred"] += 1
            sleep(PAUSE)
            continue
        if code != 200 or not isinstance(raw, list):
            u = {"direction": "UNAVAILABLE", "reason": "klines HTTP %s" % code}
        else:
            u = build_unit(raw, t_ms)
        m = meta[sym]
        kind = m.get("underlyingType")
        try:
            age = (now_ms - int(m.get("onboardDate"))) / float(DAY)
        except Exception:
            age = None
        mo = market_open_guess(kind, dt)
        insert_unit(con, sym, day, t_ms, kind, age, vol.get(sym), None if mo is None else int(bool(mo)), u)
        out["new"][u["direction"]] += 1
        sleep(PAUSE)
    con.commit()
    return out
# --- end part 2 ---


def run_grade(con, now_ms, getter, sleep):
    res = {"HIT": 0, "MISS": 0, "VOID": 0, "unavailable": 0, "pending": 0, "deferred": 0, "over": 0}
    rows = con.execute(
        "select u.id, u.symbol, u.t_ms, u.entry, u.direction, u.thr_pct from shadow_stocksig u "
        "left join shadow_stocksig_grade g on g.unit_id = u.id where g.id is null and u.status = 'PENDING' "
        "order by u.id").fetchall()
    due = [r for r in rows if now_ms >= r[2] + DAY + 5 * 60000]
    res["over"] = max(0, len(due) - MAX_GRADE)
    for uid, sym, t_ms, entry, d, thr_pct in due[:MAX_GRADE]:
        want = t_ms + 23 * H1
        code, data = getter("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "startTime": want, "limit": 1})
        if is_transient(code, data):
            res["deferred"] += 1
            sleep(PAUSE)
            continue
        px = None
        if code == 200 and isinstance(data, list) and data:
            try:
                if int(data[0][0]) == want:
                    px = float(data[0][4])
            except Exception:
                px = None
        if px is None or px != px or px <= 0 or entry is None or entry <= 0:
            if now_ms >= t_ms + 3 * DAY:
                insert_grade(con, uid, None, None, None, None, None, "UNAVAILABLE", "no exit candle after 72 hours")
                res["unavailable"] += 1
            else:
                res["pending"] += 1
            sleep(PAUSE)
            continue
        ret = math.log(px / entry)
        result = classify(d, ret, thr_pct / 100.0)
        sgn = 1.0 if d == "UP" else -1.0
        gross = (px / entry - 1.0) * 100.0 * sgn
        insert_grade(con, uid, px, ret, result, gross, gross - COST_PP, "GRADED", "")
        res[result] += 1
        sleep(PAUSE)
    con.commit()
    return res


def stats(rows):
    cnt = [r for r in rows if r[5] in ("HIT", "MISS")]
    s = {"n": len(cnt), "days": 0, "voids": sum(1 for r in rows if r[5] == "VOID"), "total": len(rows)}
    if not cnt:
        return s
    n = len(cnt)
    up = sum(1 for r in cnt if r[3] == "UP") / float(n)
    pu = sum(1 for r in cnt if r[6] > 0) / float(n)
    byd, bysym = {}, {}
    for r in cnt:
        byd.setdefault(r[1], []).append(1.0 if r[5] == "HIT" else 0.0)
        bysym[r[0]] = bysym.get(r[0], 0) + 1
    s.update(days=len(byd), hit=sum(1 for r in cnt if r[5] == "HIT") / float(n), always_up=pu,
             base=up * pu + (1 - up) * (1 - pu), per_day=sum(sum(v) / len(v) for v in byd.values()) / len(byd),
             gross=sum(r[7] for r in cnt) / n, net=sum(r[8] for r in cnt) / n,
             top5=sum(sorted(bysym.values(), reverse=True)[:5]) / float(n))
    return s


def line(name, s, min_n, min_days):
    head = "%-12s" % name
    if s["n"] < min_n or s["days"] < min_days:
        return "%s n=%d days=%d void %d (counts only; needs %d units over %d days)" % (
            head, s["n"], s["days"], s["voids"], min_n, min_days)
    return ("%s n=%d days=%d hit %.1f%% | always-up %.1f%% | base %.1f%% | per-day mean hit %.1f%% | "
            "mean gross %+.3f%% net %+.3f%% | void %.1f%% | top5 symbols %.0f%%"
            % (head, s["n"], s["days"], 100 * s["hit"], 100 * s["always_up"], 100 * s["base"],
               100 * s["per_day"], s["gross"], s["net"], 100.0 * s["voids"] / s["total"], 100 * s["top5"]))


def build_report(con):
    names = set(r[0] for r in con.execute("select name from sqlite_master where type='table'"))
    if "shadow_stocksig_grade" not in names or "shadow_stocksig" not in names:
        return ["no shadow_stocksig tables yet"]
    rows = con.execute(
        "select u.symbol, u.day_utc, u.kind, u.direction, u.market_open, g.result, g.ret, g.gross_pct, g.net_pct "
        "from shadow_stocksig u join shadow_stocksig_grade g on g.unit_id = u.id where g.status = 'GRADED'").fetchall()
    nocall = con.execute("select count(*) from shadow_stocksig where status='NO_CALL'").fetchone()[0]
    unav = (con.execute("select count(*) from shadow_stocksig where status='UNAVAILABLE'").fetchone()[0]
            + con.execute("select count(*) from shadow_stocksig_grade where status='UNAVAILABLE'").fetchone()[0])
    pend = con.execute("select count(*) from shadow_stocksig u left join shadow_stocksig_grade g on g.unit_id=u.id "
                       "where u.status='PENDING' and g.id is null").fetchone()[0]
    c = lambda x: sum(1 for r in rows if r[5] == x)
    out = ["units: graded %d (HIT %d, MISS %d, VOID %d); NO_CALL %d; UNAVAILABLE %d; pending %d."
           % (len(rows), c("HIT"), c("MISS"), c("VOID"), nocall, unav, pend)]
    out.append(line("all", stats(rows), 30, 20))
    for d in ("UP", "DOWN"):
        sub = [r for r in rows if r[3] == d]
        if sub:
            out.append(line(d, stats(sub), 30, 10))
    for k in sorted(set((r[2] or "?") for r in rows)):
        out.append(line("kind:" + k, stats([r for r in rows if (r[2] or "?") == k]), 30, 10))
    for label, pred in (("mkt:open", lambda r: r[4] == 1), ("mkt:closed", lambda r: r[4] == 0),
                        ("mkt:n/a", lambda r: r[4] is None)):
        sub = [r for r in rows if pred(r)]
        if sub:
            out.append(line(label, stats(sub), 30, 10))
    out.append("No pass bar, no causal claim, not a profit claim. Perpetual contracts are not the shares; stocks "
               "move together, so rows cluster by day and the effective sample is much smaller than n.")
    return out
# --- end part 3 ---


def cmd_check():
    now_ms = int(time.time() * 1000)
    print("first day %s (forward only) | now %s UTC | %s" % (
        day_str(FIRST_DAY_MS), fmt_ms(now_ms),
        "eligible" if now_ms >= FIRST_DAY_MS else "no eligible day yet: a run would request nothing"))
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_stocksig'").fetchone()[0]:
        print("tables do not exist yet; `run` would create them. Nothing was requested or written.")
        return
    by = dict(con.execute("select direction, count(*) from shadow_stocksig group by 1").fetchall())
    last = con.execute("select max(day_utc) from shadow_stocksig").fetchone()[0]
    gr = dict(con.execute("select status, count(*) from shadow_stocksig_grade group by 1").fetchall())
    print("stored units by direction %s | last day %s | grade rows %s" % (by, last, gr))


def cmd_run():
    now_ms = int(time.time() * 1000)
    if now_ms < FIRST_DAY_MS:
        print("run: first day is %s UTC. Nothing requested, nothing written." % fmt_ms(FIRST_DAY_MS))
        return
    con = sqlite3.connect(DB, timeout=30)
    ensure_schema(con)
    s = run_snapshot(con, now_ms, http_get, time.sleep)
    if s["error"]:
        print("snapshot: " + s["error"])
    g = run_grade(con, now_ms, http_get, time.sleep)
    n = s["new"]
    print("run: %d TradFi perpetuals | new units UP %d, DOWN %d, NO_CALL %d, UNAVAILABLE %d, deferred %d | "
          "graded HIT %d, MISS %d, VOID %d, unavailable %d, pending %d, deferred %d, over limit %d"
          % (s["universe"], n["UP"], n["DOWN"], n["NO_CALL"], n["UNAVAILABLE"], s["deferred"],
             g["HIT"], g["MISS"], g["VOID"], g["unavailable"], g["pending"], g["deferred"], g["over"]))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    for ln in build_report(con):
        print(ln)


def selftest():
    utc = datetime.timezone.utc

    def close(a, b, e=1e-9):
        return a is not None and abs(a - b) < e

    # 1 constants and forward-only start
    commit_ms = int(datetime.datetime(2026, 11, 10, 23, 1, 39, tzinfo=utc).timestamp() * 1000)
    assert FIRST_DAY_MS % DAY == 0 and day_str(FIRST_DAY_MS) == "2026-11-11"
    assert FIRST_DAY_MS > commit_ms >= FIRST_DAY_MS - DAY
    assert H1 == 3600000 and FAPI == "https://fapi.binance.com"
    assert is_transient(0, None) and is_transient(429, {}) and is_transient(503, None) and is_transient(200, None)
    assert not is_transient(200, []) and not is_transient(400, {}) and is_transient(418, {})

    # 2 the copied rule, checked against hand computations
    assert close(ema([1.0, 2.0, 3.0], 2), 23.0 / 9.0)
    assert close(rsi([1.0, 2.0, 1.0, 2.0], 2), 75.0)
    assert rsi([1.0, 2.0, 3.0, 4.0], 2) == 100.0
    assert close(thr_of([100.0, 110.0, 100.0, 110.0, 100.0]), math.log(1.1) * math.sqrt(2))
    assert signal([100.0 + 0.5 * i for i in range(100)])[0] == "NO_CALL"
    assert signal([200.0 - 0.5 * i for i in range(100)])[0] == "DOWN"
    zig = [100.0]
    for i in range(1, 120):
        zig.append(zig[-1] + (1.2 if i % 2 == 1 else -1.0))
    d, e20, e50, rs = signal(zig[-100:])
    assert d == "UP" and e20 > e50 and 50 <= rs <= 70, (d, e20, e50, rs)
    assert classify("UP", 0.001, 0.01) == "VOID" and classify("UP", 0.02, 0.01) == "HIT"
    assert classify("DOWN", 0.02, 0.01) == "MISS" and classify("DOWN", -0.02, 0.01) == "HIT"
    assert classify("UP", -0.02, 0.01) == "MISS"
    wed = datetime.datetime(2026, 11, 11, 14, 0, tzinfo=utc)
    assert market_open_guess("EQUITY", wed) is True and market_open_guess("ETF", wed) is True
    assert market_open_guess("EQUITY", datetime.datetime(2026, 11, 11, 13, 29, tzinfo=utc)) is False
    assert market_open_guess("EQUITY", datetime.datetime(2026, 11, 11, 21, 0, tzinfo=utc)) is False
    assert market_open_guess("EQUITY", datetime.datetime(2026, 11, 14, 14, 0, tzinfo=utc)) is False
    assert market_open_guess("COMMODITY", wed) is None and market_open_guess(None, wed) is None

    # 3 closed candles and the contiguous suffix
    T = FIRST_DAY_MS + 5 * H1

    def rows_for(closes, t_end, forming=True):
        n = len(closes)
        r = [[t_end - (n - i) * H1, "0", "0", "0", repr(closes[i]), "1"] for i in range(n)]
        if forming:
            r.append([t_end, "0", "0", "0", "999", "1"])
        return r
    suf = closed_suffix(rows_for([1.0, 2.0, 3.0], T), T)
    assert suf == [(T - 3 * H1, 1.0), (T - 2 * H1, 2.0), (T - H1, 3.0)], suf
    gapped = [r for r in rows_for([1.0, 2.0, 3.0, 4.0], T) if r[0] != T - 3 * H1]
    assert [x[1] for x in closed_suffix(gapped, T)] == [3.0, 4.0]
    assert closed_suffix([["bad"], [T + 1, "0", "0", "0", "1", "1"], [T - H1, "0", "0", "0", "-5", "1"]], T) == []
    assert build_unit(rows_for(zig[-30:], T), T)["reason"].startswith("fewer than 60")
    assert build_unit(rows_for(zig, T - H1, forming=False), T)["reason"] == "no closed candle just before T"
    assert build_unit([], T)["direction"] == "UNAVAILABLE"
# --- end part 4 ---

    # 4 snapshot and grading against a fake exchange (no network)
    fall = [200.0 - 0.5 * i for i in range(120)]
    rise = [100.0 + 0.5 * i for i in range(120)]
    now_ms = T + 30 * 60000

    def sm(sym, kind, ctype="TRADIFI_PERPETUAL", status="TRADING", onboard=None):
        m = {"symbol": sym, "contractType": ctype, "status": status, "underlyingType": kind}
        if onboard is not None:
            m["onboardDate"] = onboard
        return m
    metas = [sm("AAAUSDT", "EQUITY", onboard=now_ms - 30 * DAY), sm("BBBUSDT", "ETF", onboard=now_ms - 400 * DAY),
             sm("CCCUSDT", "EQUITY", status="BREAK"), sm("DDDUSDT", "EQUITY", ctype="PERPETUAL"),
             sm("EEEUSDT", "COMMODITY"), sm("FFFUSDT", "EQUITY"), sm("GGGUSDT", "EQUITY"), sm("HHHUSDT", "EQUITY")]
    tickers = [{"symbol": "AAAUSDT", "quoteVolume": "2500000.5"}, {"symbol": "BBBUSDT", "quoteVolume": "100"},
               {"symbol": "ZZZUSDT", "quoteVolume": "1"}]
    world = {"T": T, "exit": {}}
    world["kl"] = {
        "AAAUSDT": lambda: (200, rows_for(zig, world["T"])), "BBBUSDT": lambda: (200, rows_for(fall, world["T"])),
        "EEEUSDT": lambda: (200, rows_for(zig[-30:], world["T"])), "FFFUSDT": lambda: (200, rows_for(rise, world["T"])),
        "GGGUSDT": lambda: (429, None), "HHHUSDT": lambda: (400, {})}
    calls = []

    def getter(path, params=None):
        calls.append((path, dict(params) if params else None))
        if path == "/fapi/v1/exchangeInfo":
            return 200, {"symbols": metas}
        if path == "/fapi/v1/ticker/24hr":
            return 200, tickers
        s = params["symbol"]
        if "startTime" in params:
            mode = world["exit"].get(s)
            if mode == "429":
                return 429, None
            if mode == "wrong":
                return 200, [[params["startTime"] + H1, "0", "0", "0", "1.0", "1"]]
            if mode == "empty" or mode is None:
                return 200, []
            return 200, [[params["startTime"], "0", "0", "0", repr(mode), "1"]]
        return world["kl"][s]()
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    r = run_snapshot(con, now_ms, getter, lambda s: None)
    assert r["universe"] == 6 and r["deferred"] == 1 and r["error"] == "", r
    assert r["new"] == {"UP": 1, "DOWN": 1, "NO_CALL": 1, "UNAVAILABLE": 2}, r
    paths = [c[0] for c in calls]
    assert paths.count("/fapi/v1/exchangeInfo") == 1 and paths.count("/fapi/v1/ticker/24hr") == 1, paths
    assert paths.count("/fapi/v1/klines") == 6, paths
    assert calls[2][1] == {"symbol": "AAAUSDT", "interval": "1h", "limit": 120}, calls[2]
    rows = dict((x[0], x) for x in con.execute(
        "select symbol, direction, status, entry, kind, age_days, vol24, market_open, t_ms, day_utc, thr_pct, "
        "reason from shadow_stocksig"))
    assert set(rows) == {"AAAUSDT", "BBBUSDT", "EEEUSDT", "FFFUSDT", "HHHUSDT"}, set(rows)
    a = rows["AAAUSDT"]
    assert a[1:3] == ("UP", "PENDING") and close(a[3], zig[-1]) and a[4] == "EQUITY" and close(a[5], 30.0), a
    assert close(a[6], 2500000.5) and a[7] == 0 and a[8] == T and a[9] == "2026-11-11", a
    assert close(a[10], thr_of(zig[-100:]) * 100.0), a
    b = rows["BBBUSDT"]
    assert b[1:3] == ("DOWN", "PENDING") and close(b[3], fall[-1]) and b[4] == "ETF" and close(b[6], 100.0), b
    assert rows["FFFUSDT"][1:3] == ("NO_CALL", "NO_CALL")
    e = rows["EEEUSDT"]
    assert e[1:3] == ("UNAVAILABLE", "UNAVAILABLE") and e[4] == "COMMODITY" and e[7] is None, e
    assert e[11].startswith("fewer than 60") and rows["HHHUSDT"][11] == "klines HTTP 400"
    r = run_snapshot(con, now_ms, getter, lambda s: None)
    assert r["new"] == {"UP": 0, "DOWN": 0, "NO_CALL": 0, "UNAVAILABLE": 0} and r["deferred"] == 1, r
    world["T"] = T + 3 * H1
    world["kl"]["GGGUSDT"] = lambda: (200, rows_for(zig, world["T"]))
    r = run_snapshot(con, now_ms + 3 * H1, getter, lambda s: None)
    assert r["new"]["UP"] == 1 and r["deferred"] == 0, r
    g = con.execute("select t_ms, direction from shadow_stocksig where symbol='GGGUSDT'").fetchone()
    assert g == (T + 3 * H1, "UP"), g
    n1 = len(calls)
    r = run_snapshot(con, now_ms + 3 * H1, getter, lambda s: None)
    assert len(calls) - n1 == 1 and sum(r["new"].values()) == 0, (len(calls) - n1, r)
    assert con.execute("select count(*) from shadow_stocksig").fetchone()[0] == 6
    bad = {"symbols": "x"}
    assert run_snapshot(con, now_ms, lambda p, q=None: (200, bad), lambda s: None)["error"].startswith("exchangeInfo failed")

    # 5 grading: exit candle, VOID/HIT/MISS, wrong open time, deferral, 72 hours
    now2 = T + DAY + 10 * 60000
    world["exit"] = {"AAAUSDT": zig[-1] * 1.05, "BBBUSDT": fall[-1] * 1.05}
    n2 = len(calls)
    gr = run_grade(con, now2, getter, lambda s: None)
    assert (gr["HIT"], gr["MISS"], gr["VOID"], gr["pending"], gr["deferred"], gr["over"]) == (1, 1, 0, 0, 0, 0), gr
    assert len(calls) - n2 == 2 and calls[n2][1]["startTime"] == T + 23 * H1 and calls[n2][1]["limit"] == 1, calls[n2]
    gs = dict((x[0], x) for x in con.execute(
        "select u.symbol, g.result, g.gross_pct, g.net_pct, g.status, g.exit_px from shadow_stocksig u "
        "join shadow_stocksig_grade g on g.unit_id = u.id"))
    assert gs["AAAUSDT"][1] == "HIT" and close(gs["AAAUSDT"][2], 5.0, 1e-9) and close(gs["AAAUSDT"][3], 4.86, 1e-9)
    assert gs["BBBUSDT"][1] == "MISS" and close(gs["BBBUSDT"][2], -5.0, 1e-9) and close(gs["BBBUSDT"][3], -5.14, 1e-9)
    assert gs["AAAUSDT"][4] == "GRADED" and close(gs["AAAUSDT"][5], zig[-1] * 1.05)
# --- end part 5 ---
    gt = T + 3 * H1 + DAY + 10 * 60000
    world["exit"] = {"GGGUSDT": "wrong"}
    gr = run_grade(con, gt, getter, lambda s: None)
    assert (gr["HIT"], gr["MISS"], gr["pending"], gr["deferred"], gr["unavailable"]) == (0, 0, 1, 0, 0), gr
    world["exit"] = {"GGGUSDT": "429"}
    gr = run_grade(con, gt, getter, lambda s: None)
    assert gr["deferred"] == 1 and gr["pending"] == 0, gr
    world["exit"] = {"GGGUSDT": "empty"}
    gr = run_grade(con, T + 3 * H1 + 3 * DAY + 1, getter, lambda s: None)
    assert gr["unavailable"] == 1, gr
    row = con.execute("select status, reason, result from shadow_stocksig_grade where unit_id = "
                      "(select id from shadow_stocksig where symbol='GGGUSDT')").fetchone()
    assert row == ("UNAVAILABLE", "no exit candle after 72 hours", None), row
    assert run_grade(con, T + 10 * DAY, getter, lambda s: None) == {
        "HIT": 0, "MISS": 0, "VOID": 0, "unavailable": 0, "pending": 0, "deferred": 0, "over": 0}

    # 6 report on a crafted table (hand-computed expectations)
    def mk(n_units=40):
        c = sqlite3.connect(":memory:")
        ensure_schema(c)
        for i in range(n_units):
            day = "2026-12-%02d" % (i // 2 + 1)
            dr = "UP" if i % 4 != 3 else "DOWN"
            kind = "EQUITY" if i < 20 else "ETF"
            mo = 1 if i % 5 == 0 else (0 if i % 5 == 1 else None)
            c.execute("insert into shadow_stocksig(symbol, day_utc, kind, direction, market_open, status) "
                      "values(?,?,?,?,?,?)", ("S%d" % i, day, kind, dr, mo, "PENDING"))
            uid = c.execute("select last_insert_rowid()").fetchone()[0]
            if i in (0, 2, 4, 6):
                res, ret, gross = "VOID", 0.001, 0.1
            else:
                hit = (i % 3 != 0)
                res = "HIT" if hit else "MISS"
                ret = 0.02 if (hit == (dr == "UP")) else -0.02
                gross = 2.0 if hit else -2.0
            c.execute("insert into shadow_stocksig_grade(unit_id, result, ret, gross_pct, net_pct, status) "
                      "values(?,?,?,?,?,?)", (uid, res, ret, gross, gross - 0.14, "GRADED"))
        return c
    c = mk()
    for sym, st in (("N0", "NO_CALL"), ("N1", "NO_CALL"), ("U0", "UNAVAILABLE"), ("P0", "PENDING"),
                    ("P1", "PENDING"), ("P2", "PENDING"), ("G0", "PENDING")):
        c.execute("insert into shadow_stocksig(symbol, day_utc, kind, direction, status) values(?,?,?,?,?)",
                  (sym, "2026-12-30", "EQUITY", "UP" if st == "PENDING" else st, st))
    uid = c.execute("select id from shadow_stocksig where symbol='G0'").fetchone()[0]
    c.execute("insert into shadow_stocksig_grade(unit_id, status, reason) values(?,?,?)", (uid, "UNAVAILABLE", "x"))
    text = "\n".join(build_report(c))
    assert "units: graded 40 (HIT 24, MISS 12, VOID 4); NO_CALL 2; UNAVAILABLE 2; pending 3." in text, text
    assert ("n=36 days=20 hit 66.7% | always-up 61.1% | base 54.9% | per-day mean hit 67.5% | "
            "mean gross +0.667% net +0.527% | void 10.0% | top5 symbols 14%") in text, text
    assert "n=26 days=18 void 4 (counts only; needs 30 units over 10 days)" in text, text
    assert "n=10 days=10 void 0 (counts only; needs 30 units over 10 days)" in text, text
    assert "kind:EQUITY" in text and "n=16 days=10 void 4" in text, text
    assert "kind:ETF" in text and "n=20 days=10 void 0" in text, text
    assert "mkt:open" in text and "mkt:closed" in text and "mkt:n/a" in text, text
    assert "No pass bar" in text
    small = "\n".join(build_report(mk(10)))
    assert "counts only; needs 30 units over 20 days" in small, small
    assert build_report(sqlite3.connect(":memory:")) == ["no shadow_stocksig tables yet"]
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"selftest": selftest, "check": cmd_check, "run": cmd_run, "report": cmd_report}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
# --- end part 6 ---
