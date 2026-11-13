#!/usr/bin/env python3
"""sigaudit_log.py - sigaudit_v1 (frozen spec: sigaudit_v1_spec.md). Shadow only.
Grades the deterministic engine's own BUY/SELL signal (market_signal in ai_consensus_audit) against the
next 24h price change, by Stage 1 status and seen/unseen group. Reads sentinel.db READ-ONLY; public
Binance 1-minute klines only; no AI, no keys. Writes ONLY shadow_sigaudit in shadow.db (on `run`).
Usage: python3 sigaudit_log.py selftest | check | run | report"""
import sys
import time
import sqlite3
import datetime

SENT_DB = "sentinel.db"
DB = "shadow.db"
M1 = 60000
DAY = 86400000
DUE_MS = DAY + 2 * M1
MAX_UNITS = 60
PAUSE = 0.25
COST_PP = 0.14
MIN_N = 30
MIN_DAYS = 10


def _ms(y, mo, d, h, mi, s):
    return int(datetime.datetime(y, mo, d, h, mi, s, tzinfo=datetime.timezone.utc).timestamp() * 1000)


A_END_MS = _ms(2026, 10, 16, 8, 24, 0)
FREEZE_MS = _ms(2026, 11, 10, 22, 58, 49)
SCHEMA = (
    "create table if not exists shadow_sigaudit(id integer primary key autoincrement, created_utc text, "
    "audit_id integer, ts text, symbol text, day_utc text, strategy_status text, signal text, grp text, "
    "seen integer, entry real, exit_px real, return_pct real, directional_pct real, net_pct real, "
    "source text, status text, reason text, unique(symbol, day_utc))")


def utcnow_s():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_str(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")


def fmt_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def parse_ts(s):
    try:
        t = str(s).strip().replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def group_of(ts_ms, audit_id, plan_ids):
    if ts_ms < A_END_MS:
        return "A_seen" if audit_id in plan_ids else "A_unseen"
    if ts_ms < FREEZE_MS:
        return "B"
    return "C"


def seen_flag(grp):
    return 0 if grp in ("A_unseen", "C") else 1


def build_units(rows, plan_ids):
    """rows: (id, timestamp, symbol, strategy_status, market_signal). One unit per (symbol, UTC day):
    the first directional row by time. Returns (units, info)."""
    cand, bad = [], 0
    for aid, ts, sym, st, sig in rows:
        if str(st).upper() not in ("APPROVED", "WATCH") or str(sig).upper() not in ("BUY", "SELL") or not sym:
            continue
        ms = parse_ts(ts)
        if ms is None:
            bad += 1
            continue
        cand.append((ms, aid if aid is not None else 0, str(sym), str(st).upper(), str(sig).upper(), str(ts)))
    cand.sort(key=lambda x: (x[0], x[1]))
    units, ignored, flips = {}, 0, 0
    for ms, aid, sym, st, sig, ts in cand:
        key = (sym, day_str(ms))
        if key in units:
            ignored += 1
            if sig != units[key]["signal"]:
                flips += 1
            continue
        g = group_of(ms, aid, plan_ids)
        units[key] = {"audit_id": aid, "ts": ts, "ts_ms": ms, "symbol": sym, "day": key[1], "status": st,
                      "signal": sig, "grp": g, "seen": seen_flag(g)}
    return units, {"ignored": ignored, "flips": flips, "bad_ts": bad}
# --- end part 1 ---


def fetch_candle(getter, src, symbol, minute_ms):
    """-> ('ok', open_price) | ('transient', None) | ('none', None)."""
    code, data = getter(src, {"symbol": symbol, "interval": "1m", "startTime": minute_ms, "limit": 1})
    if code in (0, 418, 429) or code >= 500 or (code == 200 and data is None):
        return "transient", None
    if code != 200 or not isinstance(data, list) or not data:
        return "none", None
    try:
        if int(data[0][0]) != minute_ms:
            return "none", None
        px = float(data[0][1])
    except Exception:
        return "none", None
    if px != px or px <= 0 or abs(px) == float("inf"):
        return "none", None
    return "ok", px


def price_pair(getter, symbol, entry_min, sleep):
    """Entry and exit must come from the same source (Spot first, then Futures).
    -> ('ok', source, entry, exit) | ('deferred',) | ('none',)."""
    transient = False
    for src in ("spot", "futures"):
        s1, entry = fetch_candle(getter, src, symbol, entry_min)
        sleep(PAUSE)
        if s1 == "transient":
            transient = True
            continue
        if s1 != "ok":
            continue
        s2, exit_px = fetch_candle(getter, src, symbol, entry_min + DAY)
        sleep(PAUSE)
        if s2 == "transient":
            transient = True
            continue
        if s2 == "ok":
            return ("ok", src, entry, exit_px)
    return ("deferred",) if transient else ("none",)


def http_get(src, params, timeout=15):
    import requests
    import market_facts as mf
    try:
        r = requests.get(mf.URLS[src], params=params, timeout=timeout)
    except Exception:
        return 0, None
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


def ensure_schema(con):
    con.execute(SCHEMA)
    con.commit()


def insert_row(con, u, source, entry, exit_px, status, reason):
    ret = dirp = net = None
    if status == "OK":
        ret = (exit_px - entry) / entry * 100.0
        dirp = ret if u["signal"] == "BUY" else -ret
        net = dirp - COST_PP
    con.execute(
        "insert or ignore into shadow_sigaudit(created_utc, audit_id, ts, symbol, day_utc, strategy_status, "
        "signal, grp, seen, entry, exit_px, return_pct, directional_pct, net_pct, source, status, reason) "
        "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (utcnow_s(), u["audit_id"], u["ts"], u["symbol"], u["day"], u["status"], u["signal"], u["grp"],
         u["seen"], entry, exit_px, ret, dirp, net, source, status, reason))


def open_sentinel():
    return sqlite3.connect("file:%s?mode=ro" % SENT_DB, uri=True)


def read_sentinel_units(sc):
    rows = sc.execute("select id, timestamp, symbol, strategy_status, market_signal from ai_consensus_audit").fetchall()
    plan_ids = set()
    for (v,) in sc.execute("select consensus_id from paper_trade_plans where consensus_id is not null"):
        try:
            plan_ids.add(int(v))
        except Exception:
            pass
    return build_units(rows, plan_ids)


def run_units(con, units, now_ms, getter, sleep, max_units=MAX_UNITS):
    stored = set(con.execute("select symbol, day_utc from shadow_sigaudit").fetchall())
    pend = sorted(((k, u) for k, u in units.items() if k not in stored), key=lambda kv: kv[1]["ts_ms"])
    due = [u for k, u in pend if now_ms >= u["ts_ms"] + DUE_MS]
    out = {"ok": 0, "unavailable": 0, "deferred": 0, "over": max(0, len(due) - max_units),
           "notdue": len(pend) - len(due), "due": len(due)}
    for u in due[:max_units]:
        r = price_pair(getter, u["symbol"], (u["ts_ms"] // M1) * M1, sleep)
        if r[0] == "deferred":
            out["deferred"] += 1
        elif r[0] == "none":
            insert_row(con, u, None, None, None, "UNAVAILABLE", "no 1-minute candle at the entry or exit minute")
            out["unavailable"] += 1
        else:
            insert_row(con, u, r[1], r[2], r[3], "OK", "")
            out["ok"] += 1
        con.commit()
    return out
# --- end part 2 ---


def stats(rows):
    """rows: (symbol, day, signal, return_pct, directional_pct, net_pct)."""
    cnt = [r for r in rows if r[4] != 0]
    s = {"n": len(cnt), "days": 0, "excluded": len(rows) - len(cnt)}
    if not cnt:
        return s
    n = len(cnt)
    byd, bysym = {}, {}
    for r in cnt:
        byd.setdefault(r[1], []).append(1.0 if r[4] > 0 else 0.0)
        bysym[r[0]] = bysym.get(r[0], 0) + 1
    up = sum(1 for r in cnt if r[2] == "BUY") / float(n)
    pu = sum(1 for r in cnt if r[3] > 0) / float(n)
    s.update(days=len(byd), hit=sum(1 for r in cnt if r[4] > 0) / float(n), always_up=pu,
             base=up * pu + (1 - up) * (1 - pu),
             per_day=sum(sum(v) / len(v) for v in byd.values()) / len(byd),
             gross=sum(r[4] for r in cnt) / n, net=sum(r[5] for r in cnt) / n,
             top5=sum(sorted(bysym.values(), reverse=True)[:5]) / float(n))
    return s


def line(name, s):
    head = "%-24s" % name
    if s["n"] < MIN_N or s["days"] < MIN_DAYS:
        return "%s n=%d days=%d excluded %d (counts only; needs %d units over %d days)" % (
            head, s["n"], s["days"], s["excluded"], MIN_N, MIN_DAYS)
    return ("%s n=%d days=%d hit %.1f%% | always-up %.1f%% | base %.1f%% | per-day mean hit %.1f%% | "
            "mean gross %+.3f%% net %+.3f%% | top5 %.0f%% | excluded %d"
            % (head, s["n"], s["days"], 100 * s["hit"], 100 * s["always_up"], 100 * s["base"],
               100 * s["per_day"], s["gross"], s["net"], 100 * s["top5"], s["excluded"]))


def build_report(con):
    if not con.execute("select count(*) from sqlite_master where name='shadow_sigaudit'").fetchone()[0]:
        return ["no shadow_sigaudit table yet"]
    allrows = con.execute("select symbol, day_utc, strategy_status, signal, grp, return_pct, directional_pct, "
                          "net_pct, status from shadow_sigaudit").fetchall()
    ok = [r for r in allrows if r[8] == "OK"]
    out = ["units stored: OK %d, UNAVAILABLE %d. Rule: a row is read only with %d units over %d distinct days."
           % (len(ok), len(allrows) - len(ok), MIN_N, MIN_DAYS)]
    tup = lambda sub: [(r[0], r[1], r[3], r[5], r[6], r[7]) for r in sub]
    for g in ("A_unseen", "A_seen", "B", "C"):
        for st in ("APPROVED", "WATCH"):
            sub = [r for r in ok if r[4] == g and r[2] == st]
            if not sub:
                continue
            tag = "  <- PRIMARY" if (g == "A_unseen" and st == "APPROVED") else ""
            out.append(line("%s %s all" % (g, st), stats(tup(sub))) + tag)
            if st == "APPROVED":
                for sg in ("BUY", "SELL"):
                    s2 = [r for r in sub if r[3] == sg]
                    if s2:
                        out.append(line("%s %s %s" % (g, st, sg), stats(tup(s2))))
    out.append("No pass bar, no causal claim, not a profit claim. SELL is most of the directional rows and the market "
               "mostly fell in Sept-Oct: the base-rate column is the control. Rows cluster by day and coin. "
               "Groups A_seen and B were seen in aggregate before this spec.")
    return out


def cmd_check():
    try:
        units, info = read_sentinel_units(open_sentinel())
    except Exception as e:
        print("cannot read sentinel.db (%s)" % type(e).__name__)
        return
    now_ms = int(time.time() * 1000)
    by = {}
    for u in units.values():
        k = "%s/%s" % (u["grp"], u["status"])
        by[k] = by.get(k, 0) + 1
    print("directional units %d | ignored same-day rows %d, flips %d, bad timestamps %d" % (
        len(units), info["ignored"], info["flips"], info["bad_ts"]))
    print("by group/status %s" % dict(sorted(by.items())))
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_sigaudit'").fetchone()[0]:
        due = sum(1 for u in units.values() if now_ms >= u["ts_ms"] + DUE_MS)
        print("table shadow_sigaudit does not exist yet; %d units are due; `run` would create it. "
              "Nothing was requested or written." % due)
        return
    stored = set(con.execute("select symbol, day_utc from shadow_sigaudit").fetchall())
    pend = [u for k, u in units.items() if k not in stored]
    due = sum(1 for u in pend if now_ms >= u["ts_ms"] + DUE_MS)
    print("stored %d | %d units without a row: %d due, %d not due yet" % (
        len(stored), len(pend), due, len(pend) - due))


def cmd_run():
    try:
        units, info = read_sentinel_units(open_sentinel())
    except Exception as e:
        print("cannot read sentinel.db (%s); nothing requested, nothing written" % type(e).__name__)
        return
    con = sqlite3.connect(DB, timeout=30)
    ensure_schema(con)
    o = run_units(con, units, int(time.time() * 1000), http_get, time.sleep)
    print("run: %d units (ignored same-day rows %d, flips %d, bad timestamps %d) | graded OK %d, UNAVAILABLE %d, "
          "deferred %d, over run limit %d, not due yet %d" % (
              len(units), info["ignored"], info["flips"], info["bad_ts"], o["ok"], o["unavailable"],
              o["deferred"], o["over"], o["notdue"]))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    for ln in build_report(con):
        print(ln)
# --- end part 3 ---


def selftest():
    utc = datetime.timezone.utc

    def close(a, b, e=1e-9):
        return a is not None and abs(a - b) < e

    def ms(y, mo, d, h=0, mi=0, s=0):
        return int(datetime.datetime(y, mo, d, h, mi, s, tzinfo=utc).timestamp() * 1000)

    # 1 constants, timestamps, groups
    assert A_END_MS == ms(2026, 10, 16, 8, 24) and FREEZE_MS == ms(2026, 11, 10, 22, 58, 49)
    assert DUE_MS == DAY + 120000 and COST_PP == 0.14
    assert parse_ts("2026-10-19T22:33:47.977665+00:00") == ms(2026, 10, 19, 22, 33, 47) + 977
    assert parse_ts("2026-10-19T22:33:47Z") == ms(2026, 10, 19, 22, 33, 47)
    assert parse_ts("2026-10-19T22:33:47") == ms(2026, 10, 19, 22, 33, 47)
    assert parse_ts("2026-10-19T23:33:47+01:00") == ms(2026, 10, 19, 22, 33, 47)
    assert parse_ts("garbage") is None and parse_ts(None) is None
    plan = {7}
    assert group_of(A_END_MS - 1, 1, plan) == "A_unseen" and group_of(A_END_MS - 1, 7, plan) == "A_seen"
    assert group_of(A_END_MS, 7, plan) == "B" and group_of(FREEZE_MS - 1, 1, plan) == "B"
    assert group_of(FREEZE_MS, 1, plan) == "C"
    assert [seen_flag(g) for g in ("A_unseen", "A_seen", "B", "C")] == [0, 1, 1, 0]

    # 2 units: directional rows only, first by time per symbol-day, flips, groups
    rows = [
        (1, "2026-10-10T10:00:30+00:00", "AAAUSDT", "APPROVED", "SELL"),
        (2, "2026-10-10T15:00:00+00:00", "AAAUSDT", "APPROVED", "BUY"),
        (3, "2026-10-11T09:15:00+00:00", "BBBUSDT", "WATCH", "BUY"),
        (4, "2026-10-11T09:16:00+00:00", "CCCUSDT", "APPROVED", "HOLD"),
        (5, "2026-10-11T09:17:00+00:00", "DDDUSDT", "REJECTED", "BLOCKED"),
        (6, "2026-10-20T12:00:10+00:00", "EEEUSDT", "APPROVED", "BUY"),
        (7, "2026-11-13T21:00:00+00:00", "FFFUSDT", "APPROVED", "SELL"),
        (8, "2026-11-11T01:00:00+00:00", "GGGUSDT", "APPROVED", "SELL"),
        (9, "garbage", "HHHUSDT", "APPROVED", "BUY"),
        (10, "2026-10-12T07:00:00+00:00", "IIIUSDT", "APPROVED", "BUY"),
        (11, "2026-10-12T06:00:00+00:00", "IIIUSDT", "APPROVED", "SELL"),
    ]
    units, info = build_units(rows, {1})
    assert len(units) == 6 and info == {"ignored": 2, "flips": 2, "bad_ts": 1}, (len(units), info)
    a = units[("AAAUSDT", "2026-10-10")]
    assert (a["audit_id"], a["grp"], a["seen"], a["signal"], a["status"]) == (1, "A_seen", 1, "SELL", "APPROVED"), a
    b = units[("BBBUSDT", "2026-10-11")]
    assert b["grp"] == "A_unseen" and b["status"] == "WATCH" and b["signal"] == "BUY", b
    assert units[("EEEUSDT", "2026-10-20")]["grp"] == "B"
    assert units[("FFFUSDT", "2026-11-13")]["grp"] == "C" and units[("GGGUSDT", "2026-11-11")]["grp"] == "C"
    i = units[("IIIUSDT", "2026-10-12")]
    assert i["audit_id"] == 11 and i["signal"] == "SELL" and i["ts_ms"] == ms(2026, 10, 12, 6, 0), i
    assert all(k[0] not in ("CCCUSDT", "DDDUSDT", "HHHUSDT") for k in units)
    assert build_units([], set()) == ({}, {"ignored": 0, "flips": 0, "bad_ts": 0})
# --- end part 4 ---

    # 3 candle and price-pair logic against a fake exchange (no network)
    calls = []

    def mk(tbl):
        def g(src, params):
            calls.append((src, dict(params)))
            return tbl(src, params)
        return g

    def candle(t, px):
        return [[t, repr(px), "0", "0", "0", "1"]]
    M0 = ms(2026, 10, 10, 10, 0)
    assert fetch_candle(mk(lambda s, p: (200, candle(p["startTime"], 100.0))), "spot", "XUSDT", M0) == ("ok", 100.0)
    assert calls[0] == ("spot", {"symbol": "XUSDT", "interval": "1m", "startTime": M0, "limit": 1}), calls[0]
    for resp, want in (((200, candle(M0 + M1, 1.0)), "none"), ((429, None), "transient"), ((503, None), "transient"),
                       ((0, None), "transient"), ((200, None), "transient"), ((418, {}), "transient"),
                       ((400, {}), "none"), ((200, []), "none"), ((200, [["bad"]]), "none"),
                       ((200, candle(M0, -1.0)), "none"), ((200, candle(M0, float("nan"))), "none")):
        assert fetch_candle(mk(lambda s, p, r=resp: r), "spot", "XUSDT", M0)[0] == want, (resp, want)

    def table(spec):
        return lambda s, p: spec.get((s, p["startTime"]), (400, {}))
    nap = lambda s: None
    full = {("spot", M0): (200, candle(M0, 100.0)), ("spot", M0 + DAY): (200, candle(M0 + DAY, 102.0))}
    assert price_pair(mk(table(full)), "XUSDT", M0, nap) == ("ok", "spot", 100.0, 102.0)
    spec = {("spot", M0): (200, candle(M0 + M1, 5.0)), ("futures", M0): (200, candle(M0, 50.0)),
            ("futures", M0 + DAY): (200, candle(M0 + DAY, 51.0))}
    assert price_pair(mk(table(spec)), "XUSDT", M0, nap) == ("ok", "futures", 50.0, 51.0)
    spec = {("spot", M0): (200, candle(M0, 10.0)), ("spot", M0 + DAY): (200, []),
            ("futures", M0): (200, candle(M0, 11.0)), ("futures", M0 + DAY): (200, candle(M0 + DAY, 12.0))}
    assert price_pair(mk(table(spec)), "XUSDT", M0, nap) == ("ok", "futures", 11.0, 12.0)
    spec = {("spot", M0): (429, None), ("futures", M0): (200, candle(M0, 3.0)),
            ("futures", M0 + DAY): (200, candle(M0 + DAY, 4.0))}
    assert price_pair(mk(table(spec)), "XUSDT", M0, nap) == ("ok", "futures", 3.0, 4.0)
    both = {("spot", M0): (429, None), ("futures", M0): (429, None)}
    assert price_pair(mk(table(both)), "XUSDT", M0, nap) == ("deferred",)
    assert price_pair(mk(table({("spot", M0): (429, None)})), "XUSDT", M0, nap) == ("deferred",)
    assert price_pair(mk(table({})), "XUSDT", M0, nap) == ("none",)
    slept = []
    price_pair(mk(table(full)), "XUSDT", M0, lambda s: slept.append(s))
    assert slept == [PAUSE, PAUSE], slept

    # 4 storage and arithmetic (in memory)
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    u = {"audit_id": 1, "ts": "2026-10-10T10:00:30+00:00", "symbol": "AAAUSDT", "day": "2026-10-10",
         "status": "APPROVED", "signal": "SELL", "grp": "A_seen", "seen": 1}
    insert_row(con, u, "spot", 100.0, 99.0, "OK", "")
    insert_row(con, u, "spot", 100.0, 50.0, "OK", "")
    assert con.execute("select count(*) from shadow_sigaudit").fetchone()[0] == 1
    row = con.execute("select entry, exit_px, return_pct, directional_pct, net_pct, source, status, grp, seen, "
                      "strategy_status, audit_id from shadow_sigaudit").fetchone()
    assert close(row[2], -1.0) and close(row[3], 1.0) and close(row[4], 0.86), row
    assert row[5:] == ("spot", "OK", "A_seen", 1, "APPROVED", 1), row
    insert_row(con, dict(u, symbol="BBBUSDT", signal="BUY"), "futures", 50.0, 51.0, "OK", "")
    r = con.execute("select return_pct, directional_pct, net_pct from shadow_sigaudit "
                    "where symbol='BBBUSDT'").fetchone()
    assert close(r[0], 2.0) and close(r[1], 2.0) and close(r[2], 1.86), r
    insert_row(con, dict(u, symbol="ZZZUSDT"), None, None, None, "UNAVAILABLE", "x")
    r = con.execute("select entry, return_pct, status, reason from shadow_sigaudit where symbol='ZZZUSDT'").fetchone()
    assert r == (None, None, "UNAVAILABLE", "x"), r
# --- end part 5 ---

    # 5 run_units against a fake exchange: sources, gaps, deferral, unavailable, limits
    now = FREEZE_MS + 3 * DAY
    a_min, b_min = ms(2026, 10, 10, 10, 0), ms(2026, 10, 11, 9, 15)
    e_min, g_min = ms(2026, 10, 20, 12, 0), ms(2026, 11, 11, 1, 0)
    spec = {("spot", a_min): (200, candle(a_min, 100.0)), ("spot", a_min + DAY): (200, candle(a_min + DAY, 99.0)),
            ("spot", b_min): (200, candle(b_min + M1, 7.0)), ("futures", b_min): (200, candle(b_min, 50.0)),
            ("futures", b_min + DAY): (200, candle(b_min + DAY, 51.0)),
            ("spot", e_min): (429, None), ("futures", e_min): (200, candle(e_min, 10.0)),
            ("futures", e_min + DAY): (200, candle(e_min + DAY, 10.0)),
            ("spot", g_min): (429, None), ("futures", g_min): (429, None)}
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    calls[:] = []
    o = run_units(con, units, now, mk(table(spec)), nap)
    assert o == {"ok": 3, "unavailable": 1, "deferred": 1, "over": 0, "notdue": 1, "due": 5}, o
    assert len(calls) == 12, len(calls)
    got = dict((x[0], x) for x in con.execute(
        "select symbol, source, entry, exit_px, return_pct, directional_pct, net_pct, grp, seen, "
        "strategy_status, status, reason from shadow_sigaudit"))
    assert set(got) == {"AAAUSDT", "BBBUSDT", "EEEUSDT", "IIIUSDT"}, set(got)
    r = got["AAAUSDT"]
    assert r[1:3] == ("spot", 100.0) and close(r[4], -1.0) and close(r[5], 1.0) and close(r[6], 0.86), r
    assert r[7:11] == ("A_seen", 1, "APPROVED", "OK"), r
    r = got["BBBUSDT"]
    assert r[1] == "futures" and close(r[5], 2.0) and r[7] == "A_unseen" and r[9] == "WATCH", r
    r = got["EEEUSDT"]
    assert r[1] == "futures" and r[5] == 0 and r[7] == "B" and r[10] == "OK", r
    r = got["IIIUSDT"]
    assert r[10] == "UNAVAILABLE" and r[3] is None, r
    assert r[11] == "no 1-minute candle at the entry or exit minute", r
    spec[("spot", g_min)] = (200, candle(g_min, 20.0))
    spec[("spot", g_min + DAY)] = (200, candle(g_min + DAY, 19.0))
    calls[:] = []
    o = run_units(con, units, now, mk(table(spec)), nap)
    assert o == {"ok": 1, "unavailable": 0, "deferred": 0, "over": 0, "notdue": 1, "due": 1}, o
    assert len(calls) == 2 and con.execute("select count(*) from shadow_sigaudit").fetchone()[0] == 5
    r = con.execute("select source, directional_pct, grp from shadow_sigaudit where symbol='GGGUSDT'").fetchone()
    assert r[0] == "spot" and close(r[1], 5.0) and r[2] == "C", r
    o = run_units(con, units, now, mk(table(spec)), nap)
    assert o["ok"] == 0 and o["due"] == 0 and o["notdue"] == 1, o
    c2 = sqlite3.connect(":memory:")
    ensure_schema(c2)
    o = run_units(c2, units, now, mk(table(spec)), nap, max_units=2)
    assert o["ok"] == 2 and o["over"] == 3 and o["due"] == 5, o
    assert set(x[0] for x in c2.execute("select symbol from shadow_sigaudit")) == {"AAAUSDT", "BBBUSDT"}
    assert run_units(c2, {}, now, mk(table(spec)), nap) == {
        "ok": 0, "unavailable": 0, "deferred": 0, "over": 0, "notdue": 0, "due": 0}
# --- end part 6 ---

    # 6 report on a crafted table (hand-computed expectations)
    c = sqlite3.connect(":memory:")
    ensure_schema(c)

    def put(sym, day, st, sg, grp, ret):
        v = {"audit_id": 1, "ts": "t", "symbol": sym, "day": day, "status": st, "signal": sg, "grp": grp, "seen": 0}
        if ret is None:
            insert_row(c, v, None, None, None, "UNAVAILABLE", "x")
        else:
            insert_row(c, v, "spot", 100.0, 100.0 + ret, "OK", "")
    for d in range(1, 21):
        day = "2026-10-%02d" % d
        put("B%d" % (d % 5), day, "APPROVED", "BUY", "A_unseen", 2.0 if d <= 12 else -2.0)
        put("T%d" % (d % 5), day, "APPROVED", "SELL", "A_unseen", -1.0 if d <= 10 else 1.0)
    for k in range(1, 4):
        put("W%d" % k, "2026-10-%02d" % k, "WATCH", "BUY", "A_unseen", 1.0)
    for k, ret in enumerate([1.0, 1.0, 0.0, -1.0, 2.0]):
        put("E%d" % k, "2026-10-%02d" % (21 + k), "APPROVED", "BUY", "B", ret)
    put("U1", "2026-10-30", "APPROVED", "BUY", "C", None)
    put("U2", "2026-10-30", "APPROVED", "SELL", "C", None)
    text = "\n".join(build_report(c))
    head = "units stored: OK 48, UNAVAILABLE 2. Rule: a row is read only with 30 units over 10 distinct days."
    assert text.startswith(head), text
    assert ("n=40 days=20 hit 55.0% | always-up 55.0% | base 50.0% | per-day mean hit 55.0% | "
            "mean gross +0.200% net +0.060% | top5 50% | excluded 0") in text, text
    assert "A_unseen APPROVED BUY    n=20 days=20 excluded 0 (counts only; needs 30 units over 10 days)" in text, text
    assert "A_unseen APPROVED SELL   n=20 days=20 excluded 0 (counts only; needs 30 units over 10 days)" in text, text
    assert text.count("<- PRIMARY") == 1 and "A_unseen APPROVED all" in text and "A_unseen WATCH all" in text, text
    assert "n=3 days=3 excluded 0 (counts only; needs 30 units over 10 days)" in text, text
    assert "n=4 days=4 excluded 1 (counts only; needs 30 units over 10 days)" in text, text
    assert "B APPROVED BUY" in text and "B APPROVED SELL" not in text and "C APPROVED" not in text, text
    assert "No pass bar" in text
    empty = sqlite3.connect(":memory:")
    ensure_schema(empty)
    assert "\n".join(build_report(empty)).startswith("units stored: OK 0, UNAVAILABLE 0.")
    assert build_report(sqlite3.connect(":memory:")) == ["no shadow_sigaudit table yet"]
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"selftest": selftest, "check": cmd_check, "run": cmd_run, "report": cmd_report}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
# --- end part 7 ---
