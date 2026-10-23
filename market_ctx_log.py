#!/usr/bin/env python3
"""market_ctx_log.py - market_ctx_v1 (frozen spec: market_ctx_v1_spec.md). Shadow only.
Writes ONLY shadow_market_ctx, shadow_market_ctx_fwd and shadow_market_breadth in
shadow.db (on `run`). Never touches decisions, plans, the guard, the AIs or the live path.
Usage: python3 market_ctx_log.py selftest | check | run | report"""
import sys
import time
import json
import math
import sqlite3
import datetime

DB = "shadow.db"
H = 3600000
DAY = 24 * H
H4 = 4 * H
MAX_AGE_MIN = 62
MIN_CANDLES = 200
COINS = ("AAVE ADA ALGO APT ARB ATOM AVAX BCH BNB BTC CRV DOGE DOT ENJ ETC ETH FET FIL GRT HBAR "
         "ICP INJ LINK LTC MANA NEAR OP RUNE SAND SEI SHIB SOL STX SUI TIA TRX UNI WLD XLM XRP").split()
SYMS = ["BTCUSDT"] + [c + "USDT" for c in COINS if c != "BTC"]
KEYS = ["pd_high", "pd_low", "pd_close", "d_open", "pd_high_dist", "pd_low_dist", "pd_close_dist",
        "d_open_dist", "pw_high", "pw_low", "w_open", "pw_high_dist", "pw_low_dist", "w_open_dist",
        "vwap_day", "vwap_day_dist", "vwap_roll24", "vwap_roll24_dist", "structure",
        "taker24", "taker168", "r24", "r168", "rs24", "rs168"]
SCHEMA = [
    "create table if not exists shadow_market_ctx(id integer primary key autoincrement, "
    "created_utc text, day_utc text, snap_ms integer, symbol text, source text, status text, "
    "reason text, last_open_ms integer, last_close real, age_min real, candles integer, "
    "numbers_json text, unique(day_utc, symbol))",
    "create table if not exists shadow_market_ctx_fwd(id integer primary key autoincrement, "
    "ctx_id integer unique, graded_utc text, fwd_pct real)",
    "create table if not exists shadow_market_breadth(id integer primary key autoincrement, "
    "created_utc text, day_utc text unique, n_coins integer, n_ok integer, pos24_share real, "
    "pos168_share real, up_struct_share real, median_r24 real)",
]


def pct(a, b):
    if a is None or b is None or b <= 0:
        return None
    return (a / b - 1.0) * 100.0


def parse_raw(raw):
    out = {}
    for k in raw:
        t = int(k[0])
        vals = [float(k[i]) for i in range(1, 6)]
        tk = float(k[9]) if len(k) > 9 else None
        if not all(math.isfinite(x) for x in vals) or (tk is not None and not math.isfinite(tk)):
            raise ValueError("non-finite")
        out[t] = (t, vals[0], vals[1], vals[2], vals[3], vals[4], tk)
    return out


def contiguous(cm, start, n):
    return all((start + i * H) in cm for i in range(n))


def window(cm, start, n):
    return [cm[start + i * H] for i in range(n)]


def vwap(cs):
    sv = sum(c[5] for c in cs)
    if sv <= 0:
        return None
    return sum(((c[2] + c[3] + c[4]) / 3.0) * c[5] for c in cs) / sv


def taker(cm, lo, n):
    s = lo - (n - 1) * H
    if not contiguous(cm, s, n):
        return None
    w = window(cm, s, n)
    if any(c[6] is None for c in w):
        return None
    sv = sum(c[5] for c in w)
    if sv <= 0:
        return None
    return sum(c[6] for c in w) / sv


def ret(cm, lo, n):
    t = lo - n * H
    return pct(cm[lo][4], cm[t][4]) if t in cm else None


def structure(cm, lo):
    cutoff = lo - 30 * DAY
    starts = sorted(set((t // H4) * H4 for t in cm if t >= cutoff))
    blocks = []
    for s in starts:
        if s >= cutoff and contiguous(cm, s, 4):
            w = window(cm, s, 4)
            blocks.append((s, max(c[2] for c in w), min(c[3] for c in w)))
    runs, cur = [], []
    for b in blocks:
        if cur and b[0] - cur[-1][0] != H4:
            runs.append(cur)
            cur = []
        cur.append(b)
    if cur:
        runs.append(cur)
    sh, sl = [], []
    for run in runs:
        for i in range(2, len(run) - 2):
            nb = (i - 2, i - 1, i + 1, i + 2)
            if all(run[i][1] > run[j][1] for j in nb):
                sh.append((run[i][0], run[i][1]))
            if all(run[i][2] < run[j][2] for j in nb):
                sl.append((run[i][0], run[i][2]))
    if len(sh) < 2 or len(sl) < 2:
        return None
    sh.sort()
    sl.sort()
    hu, hd = sh[-1][1] > sh[-2][1], sh[-1][1] < sh[-2][1]
    lu, ld = sl[-1][1] > sl[-2][1], sl[-1][1] < sl[-2][1]
    if hu and lu:
        return "UP"
    if hd and ld:
        return "DOWN"
    return "MIXED"


def features(cm, btc=None):
    lo = max(cm)
    lc = cm[lo][4]
    f = {"last_open_ms": lo, "last_close": lc}
    d0 = (lo // DAY) * DAY
    pd0 = d0 - DAY
    ph = pl = pcl = None
    if contiguous(cm, pd0, 24):
        w = window(cm, pd0, 24)
        ph = max(c[2] for c in w)
        pl = min(c[3] for c in w)
        pcl = w[-1][4]
    dop = cm[d0][1] if d0 in cm else None
    f.update({"pd_high": ph, "pd_low": pl, "pd_close": pcl, "d_open": dop,
              "pd_high_dist": pct(lc, ph), "pd_low_dist": pct(lc, pl),
              "pd_close_dist": pct(lc, pcl), "d_open_dist": pct(lc, dop)})
    dn = lo // DAY
    wk0 = (dn - (dn + 3) % 7) * DAY
    pw0 = wk0 - 7 * DAY
    wh = wl = None
    if contiguous(cm, pw0, 168):
        w = window(cm, pw0, 168)
        wh = max(c[2] for c in w)
        wl = min(c[3] for c in w)
    wop = cm[wk0][1] if wk0 in cm else None
    f.update({"pw_high": wh, "pw_low": wl, "w_open": wop,
              "pw_high_dist": pct(lc, wh), "pw_low_dist": pct(lc, wl), "w_open_dist": pct(lc, wop)})
    n = (lo - d0) // H + 1
    vd = vwap(window(cm, d0, n)) if n >= 3 and contiguous(cm, d0, n) else None
    vr = vwap(window(cm, lo - 23 * H, 24)) if contiguous(cm, lo - 23 * H, 24) else None
    f.update({"vwap_day": vd, "vwap_day_dist": pct(lc, vd),
              "vwap_roll24": vr, "vwap_roll24_dist": pct(lc, vr)})
    f["structure"] = structure(cm, lo)
    f["taker24"] = taker(cm, lo, 24)
    f["taker168"] = taker(cm, lo, 168)
    r24, r168 = ret(cm, lo, 24), ret(cm, lo, 168)
    rs24 = rs168 = None
    if btc and btc.get("last_open_ms") == lo:
        if r24 is not None and btc.get("r24") is not None:
            rs24 = r24 - btc["r24"]
        if r168 is not None and btc.get("r168") is not None:
            rs168 = r168 - btc["r168"]
    f.update({"r24": r24, "r168": r168, "rs24": rs24, "rs168": rs168})
    return f


def na(reason):
    return {"status": "UNAVAILABLE", "reason": reason, "numbers": None, "last_open": None,
            "last_close": None, "age": None, "candles": 0, "cm": None}


def snapshot(symbol, raw, snap_ms, btc=None):
    try:
        allc = parse_raw(raw)
    except Exception:
        return na("non-numeric prices")
    if len(allc) < MIN_CANDLES:
        return na("fewer than 200 candles")
    cm = dict((t, c) for t, c in allc.items() if t + H <= snap_ms)
    if not cm:
        return na("no closed candle")
    lo = max(cm)
    age = (snap_ms - (lo + H)) / 60000.0
    if age > MAX_AGE_MIN:
        return na("last closed candle %.0f min old" % age)
    if cm[lo][4] <= 0:
        return na("non-positive close")
    f = features(cm, btc)
    is_btc = symbol == "BTCUSDT"
    miss = [k for k in KEYS if f.get(k) is None and not (is_btc and k in ("rs24", "rs168"))]
    st = "OK" if not miss else "PARTIAL"
    return {"status": st, "reason": "" if not miss else "n/a: " + ",".join(miss), "numbers": f,
            "last_open": lo, "last_close": cm[lo][4], "age": age, "candles": len(allc), "cm": cm}


def fwd_return(cm, last_open, last_close):
    t = last_open + 24 * H
    return pct(cm[t][4], last_close) if t in cm else None


def ensure_schema(con):
    for s in SCHEMA:
        con.execute(s)
    con.commit()


def store(con, day, snap_ms, sym, source, snap):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nj = json.dumps(snap["numbers"]) if snap["numbers"] is not None else None
    con.execute(
        "insert or ignore into shadow_market_ctx(created_utc, day_utc, snap_ms, symbol, source, "
        "status, reason, last_open_ms, last_close, age_min, candles, numbers_json) "
        "values(?,?,?,?,?,?,?,?,?,?,?,?)",
        (now, day, snap_ms, sym, source, snap["status"], snap["reason"], snap["last_open"],
         snap["last_close"], snap["age"], snap["candles"], nj))
    con.commit()


def grade_pending(con, sym, cm):
    rows = con.execute(
        "select c.id, c.last_open_ms, c.last_close from shadow_market_ctx c "
        "left join shadow_market_ctx_fwd f on f.ctx_id = c.id "
        "where c.symbol=? and f.id is null and c.status in ('OK','PARTIAL')", (sym,)).fetchall()
    n = 0
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for cid, lo, lc in rows:
        v = fwd_return(cm, lo, lc)
        if v is None:
            continue
        con.execute("insert or ignore into shadow_market_ctx_fwd(ctx_id, graded_utc, fwd_pct) "
                    "values(?,?,?)", (cid, now, v))
        n += 1
    con.commit()
    return n


def median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def breadth(nums):
    n = len(nums)
    if n == 0:
        return None

    def share(fn):
        return sum(1 for x in nums if fn(x)) / float(n)
    r24 = [x["r24"] for x in nums if x.get("r24") is not None]
    return {"n": n, "pos24": share(lambda x: (x.get("r24") or 0) > 0),
            "pos168": share(lambda x: (x.get("r168") or 0) > 0),
            "up": share(lambda x: x.get("structure") == "UP"), "med24": median(r24)}


def write_breadth(con, day, expected=len(SYMS)):
    rows = con.execute("select status, numbers_json from shadow_market_ctx where day_utc=?",
                       (day,)).fetchall()
    if len(rows) != expected:
        return False
    if con.execute("select count(*) from shadow_market_breadth where day_utc=?", (day,)).fetchone()[0]:
        return False
    b = breadth([json.loads(nj) for st, nj in rows if st == "OK" and nj])
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if b is None:
        con.execute("insert or ignore into shadow_market_breadth(created_utc, day_utc, n_coins, n_ok) "
                    "values(?,?,?,0)", (now, day, expected))
    else:
        con.execute("insert or ignore into shadow_market_breadth(created_utc, day_utc, n_coins, n_ok, "
                    "pos24_share, pos168_share, up_struct_share, median_r24) values(?,?,?,?,?,?,?,?)",
                    (now, day, expected, b["n"], b["pos24"], b["pos168"], b["up"], b["med24"]))
    con.commit()
    return True


def calls(nums):
    def sg(x, mid=0.0):
        if x is None or x == mid:
            return None
        return 1 if x > mid else -1
    s = nums.get("structure")
    return {"S": 1 if s == "UP" else (-1 if s == "DOWN" else None),
            "V": sg(nums.get("vwap_day_dist")), "T": sg(nums.get("taker24"), 0.5),
            "R": sg(nums.get("rs24"))}


def eval_rules(rows):
    out = {}
    for rule in "SVTR":
        use = []
        for day, nums, fwd in rows:
            if fwd is None or fwd == 0:
                continue
            c = calls(nums).get(rule)
            if c is None:
                continue
            use.append((day, c, fwd))
        n = len(use)
        if n == 0:
            out[rule] = {"n": 0}
            continue
        hits = sum(1 for _, c, f in use if (c > 0) == (f > 0))
        pf = sum(1 for _, _, f in use if f > 0) / float(n)
        pc = sum(1 for _, c, _ in use if c > 0) / float(n)
        byd = {}
        for d, c, f in use:
            byd.setdefault(d, []).append(1.0 if (c > 0) == (f > 0) else 0.0)
        out[rule] = {"n": n, "hit": hits / float(n), "always_up": pf,
                     "base": pc * pf + (1 - pc) * (1 - pf), "days": len(byd),
                     "per_day": sum(sum(v) / len(v) for v in byd.values()) / len(byd)}
    return out


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def load_btc(con, day):
    r = con.execute("select numbers_json from shadow_market_ctx where day_utc=? and symbol='BTCUSDT' "
                    "and status in ('OK','PARTIAL')", (day,)).fetchone()
    if not r or not r[0]:
        return None
    d = json.loads(r[0])
    return {"last_open_ms": d.get("last_open_ms"), "r24": d.get("r24"), "r168": d.get("r168")}


def cmd_check():
    con = sqlite3.connect(DB, timeout=30)
    has = con.execute("select count(*) from sqlite_master where name='shadow_market_ctx'").fetchone()[0]
    if not has:
        print("tables do not exist yet; `run` would create them. Nothing was requested or written.")
        return
    day = _utcnow().strftime("%Y-%m-%d")
    rows = con.execute("select status, count(*) from shadow_market_ctx where day_utc=? group by status",
                       (day,)).fetchall()
    total = sum(r[1] for r in rows)
    ungraded = con.execute(
        "select count(*) from shadow_market_ctx c left join shadow_market_ctx_fwd f on f.ctx_id=c.id "
        "where f.id is null and c.status in ('OK','PARTIAL')").fetchone()[0]
    print("today %s: %d of %d coins have a row %s; %d snapshots not graded yet"
          % (day, total, len(SYMS), dict(rows), ungraded))


def cmd_run():
    import market_facts as mf
    con = sqlite3.connect(DB, timeout=30)
    ensure_schema(con)
    snap_ms = int(time.time() * 1000)
    day = datetime.datetime.fromtimestamp(snap_ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")
    have = set(r[0] for r in con.execute("select symbol from shadow_market_ctx where day_utc=?", (day,)))
    btc = load_btc(con, day)
    cnt = {"OK": 0, "PARTIAL": 0, "UNAVAILABLE": 0}
    graded = 0
    for sym in [s for s in SYMS if s not in have]:
        name, raw = mf.fetch_klines(sym, "spot")
        snap = na("request failed or too few candles") if name is None else snapshot(sym, raw, snap_ms, btc)
        store(con, day, snap_ms, sym, name, snap)
        cnt[snap["status"]] += 1
        if sym == "BTCUSDT" and snap["numbers"]:
            btc = dict((k, snap["numbers"].get(k)) for k in ("last_open_ms", "r24", "r168"))
        if snap["cm"]:
            graded += grade_pending(con, sym, snap["cm"])
        if snap["status"] == "UNAVAILABLE":
            print("%s UNAVAILABLE %s" % (sym, snap["reason"]))
        time.sleep(0.3)
    wrote = write_breadth(con, day)
    print("run %s: %d new rows (OK %d, PARTIAL %d, UNAVAILABLE %d), %d graded, breadth row %s, "
          "%d coins already had a row"
          % (day, sum(cnt.values()), cnt["OK"], cnt["PARTIAL"], cnt["UNAVAILABLE"], graded,
             "written" if wrote else "not written", len(have)))


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    if not con.execute("select count(*) from sqlite_master where name='shadow_market_ctx_fwd'").fetchone()[0]:
        print("no tables yet")
        return
    rows = con.execute(
        "select c.day_utc, c.numbers_json, f.fwd_pct from shadow_market_ctx c "
        "join shadow_market_ctx_fwd f on f.ctx_id=c.id where c.status in ('OK','PARTIAL')").fetchall()
    data = [(d, json.loads(nj), fw) for d, nj, fw in rows if nj]
    days = len(set(d for d, _, _ in data))
    print("%d graded snapshots over %d distinct days. Rule: read nothing before 20 distinct days "
          "and 30 usable rows per rule." % (len(data), days))
    if days < 20:
        print("NOT READ: too few days. No conclusions.")
        return
    res = eval_rules(data)
    names = {"S": "structure", "V": "vwap-day", "T": "taker24", "R": "rel-str"}
    for rule in "SVTR":
        r = res[rule]
        if r["n"] < 30:
            print("%s %-9s NOT READ (%d usable rows)" % (rule, names[rule], r["n"]))
            continue
        print("%s %-9s n=%d days=%d hit %.1f%% | always-up %.1f%% | base %.1f%% | per-day mean %.1f%%"
              % (rule, names[rule], r["n"], r["days"], 100 * r["hit"], 100 * r["always_up"],
                 100 * r["base"], 100 * r["per_day"]))
    print("No pass bar, no causal claim. Rows correlate across coins and days. Four rules read "
          "together raise the chance of a false finding.")


def selftest():
    utc = datetime.timezone.utc

    def ms(y, mo, d, h=0, mi=0):
        return int(datetime.datetime(y, mo, d, h, mi, tzinfo=utc).timestamp() * 1000)

    def close(a, b, e=1e-6):
        return a is not None and abs(a - b) < e

    snap = ms(2026, 10, 21, 13, 10)
    lo = ms(2026, 10, 21, 12)
    d0 = ms(2026, 10, 21)
    wk0 = ms(2026, 10, 19)
    pd0 = ms(2026, 10, 20)
    t1 = ms(2026, 10, 15, 10)

    def build(mod=None, drop=(), n_closed=1000, with_open=True, tk_field=True):
        c = {}
        for i in range(n_closed):
            t = lo - (n_closed - 1 - i) * H
            c[t] = [t, 100.0, 101.0, 99.0, 100.0, 1.0, 0.6]
        if mod:
            mod(c)
        raw = []
        for t in sorted(c):
            if t in drop:
                continue
            _, o, h, l, cl, v, tk = c[t]
            row = [t, str(o), str(h), str(l), str(cl), str(v), t + H - 1, "0", 1, str(tk), "0", "0"]
            raw.append(row if tk_field else row[:6])
        if with_open:
            t = lo + H
            raw.append([t, "100", "999", "1", "100", "1", t + H - 1, "0", 1, "0.5", "0", "0"])
        return raw

    # 1 flat market: levels, vwap, taker, partial status, open candle ignored
    s = snapshot("ETHUSDT", build(), snap)
    n = s["numbers"]
    assert s["status"] == "PARTIAL" and "structure" in s["reason"], s["reason"]
    assert s["last_open"] == lo and s["candles"] == 1001 and close(s["age"], 10.0), s
    assert n["pd_high"] == 101.0 and n["pd_low"] == 99.0 and n["pd_close"] == 100.0, n
    assert close(n["pd_high_dist"], (100.0 / 101.0 - 1) * 100) and close(n["d_open_dist"], 0.0), n
    assert n["pw_high"] == 101.0 and n["pw_low"] == 99.0 and n["w_open"] == 100.0, n
    assert close(n["vwap_day"], 100.0) and close(n["vwap_roll24"], 100.0), n
    assert close(n["taker24"], 0.6) and close(n["taker168"], 0.6) and close(n["r24"], 0.0), n
    assert n["structure"] is None and n["rs24"] is None, n
    b = snapshot("BTCUSDT", build(), snap)
    assert b["status"] == "PARTIAL" and "rs24" not in b["reason"], b["reason"]
    # 2 gap inside the previous day: day levels n/a, week levels still fine
    g = snapshot("ETHUSDT", build(drop=(pd0 + 5 * H,)), snap)["numbers"]
    assert g["pd_high"] is None and g["pd_close_dist"] is None and g["d_open"] == 100.0, g
    assert g["pw_high"] == 101.0, g
    # 3 stale, 4 too few candles, 5 no taker field
    st = snapshot("ETHUSDT", build(with_open=False), snap + 60 * 60000)
    assert st["status"] == "UNAVAILABLE" and "old" in st["reason"], st
    assert snapshot("ETHUSDT", build(n_closed=150), snap)["reason"] == "fewer than 200 candles"
    nt = snapshot("ETHUSDT", build(tk_field=False), snap)
    assert nt["numbers"]["taker24"] is None and "taker24" in nt["reason"], nt

    # 6 vwap weighting
    def m6(c):
        c[d0] = [d0, 200.0, 200.0, 200.0, 200.0, 3.0, 1.8]
    n = snapshot("ETHUSDT", build(m6), snap)["numbers"]
    assert close(n["vwap_day"], 120.0) and close(n["vwap_day_dist"], (100.0 / 120.0 - 1) * 100), n
    assert close(n["vwap_roll24"], 2900.0 / 26.0) and close(n["d_open_dist"], -50.0), n
    assert close(n["taker24"], 0.6), n

    # 7 returns and relative strength (BTC must share the same last candle)
    def m7(c):
        c[lo - 24 * H][4] = 80.0
        c[lo - 168 * H][4] = 50.0
    btc = {"last_open_ms": lo, "r24": 1.0, "r168": 2.0}
    n = snapshot("ETHUSDT", build(m7), snap, btc)["numbers"]
    assert close(n["r24"], 25.0) and close(n["r168"], 100.0), n
    assert close(n["rs24"], 24.0) and close(n["rs168"], 98.0), n
    n = snapshot("ETHUSDT", build(m7), snap, {"last_open_ms": lo - H, "r24": 1.0, "r168": 2.0})["numbers"]
    assert n["rs24"] is None, n

    # 8 week levels: previous week high/low and Monday open
    def m8(c):
        c[t1][2] = 150.0
        c[t1][3] = 50.0
        c[wk0][1] = 123.0
    n = snapshot("ETHUSDT", build(m8), snap)["numbers"]
    assert n["pw_high"] == 150.0 and n["pw_low"] == 50.0 and n["w_open"] == 123.0, n
    assert close(n["w_open_dist"], (100.0 / 123.0 - 1) * 100), n

    # 9 market structure on 4h blocks
    def bcm(highs, lows):
        base = H4 * 100000
        c = {}
        for k in range(len(highs)):
            for j in range(4):
                t = base + k * H4 + j * H
                c[t] = (t, 10.0, float(highs[k]), float(lows[k]), 10.0, 1.0, 0.5)
        return c
    HI = [10, 12, 15, 12, 10, 12, 16, 12, 10, 12, 17, 12, 10, 12]
    LO = [8, 6, 3, 6, 8, 6, 4, 6, 8, 6, 5, 6, 8, 6]
    HI2 = [20 - x for x in LO]
    LO2 = [20 - x for x in HI]
    c = bcm(HI, LO)
    assert structure(c, max(c)) == "UP"
    c = bcm(HI2, LO2)
    assert structure(c, max(c)) == "DOWN"
    c = bcm(HI, LO2)
    assert structure(c, max(c)) == "MIXED"
    c = bcm(HI[:7], LO[:7])
    assert structure(c, max(c)) is None

    # 10 forward return and storage (in memory)
    assert close(fwd_return({lo + 24 * H: (0, 0, 0, 0, 110.0, 0, 0)}, lo, 100.0), 10.0)
    assert fwd_return({}, lo, 100.0) is None and fwd_return({lo + 24 * H: (0, 0, 0, 0, 1.0, 0, 0)}, lo, 0.0) is None
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    ok = {"status": "OK", "reason": "", "numbers": {"last_open_ms": lo, "r24": 1.0, "r168": 1.0,
          "structure": "UP"}, "last_open": lo, "last_close": 100.0, "age": 5.0, "candles": 1000, "cm": None}
    store(con, "2026-10-21", snap, "XUSDT", "spot", ok)
    store(con, "2026-10-21", snap, "XUSDT", "spot", ok)
    store(con, "2026-10-21", snap, "YUSDT", None, na("request failed or too few candles"))
    assert con.execute("select count(*) from shadow_market_ctx").fetchone()[0] == 2
    cmx = {lo + 24 * H: (0, 0, 0, 0, 110.0, 0, 0)}
    assert grade_pending(con, "XUSDT", cmx) == 1 and grade_pending(con, "XUSDT", cmx) == 0
    assert grade_pending(con, "YUSDT", cmx) == 0
    assert close(con.execute("select fwd_pct from shadow_market_ctx_fwd").fetchone()[0], 10.0)
    assert write_breadth(con, "2026-10-21", expected=2) and not write_breadth(con, "2026-10-21", expected=2)
    assert con.execute("select n_ok from shadow_market_breadth").fetchone()[0] == 1

    # 11 rules, evaluation, breadth
    rows = [("d1", {"vwap_day_dist": 1.0}, 2.0), ("d2", {"vwap_day_dist": 1.0}, -1.0),
            ("d3", {"vwap_day_dist": -1.0}, -3.0), ("d4", {"vwap_day_dist": -1.0}, 1.0),
            ("d5", {"vwap_day_dist": 1.0}, 0.0)]
    r = eval_rules(rows)
    assert r["V"]["n"] == 4 and close(r["V"]["hit"], 0.5) and close(r["V"]["always_up"], 0.5), r
    assert close(r["V"]["base"], 0.5) and close(r["V"]["per_day"], 0.5) and r["S"]["n"] == 0, r
    cl = calls({"structure": "MIXED", "vwap_day_dist": 0.0, "taker24": 0.5, "rs24": -2.0})
    assert cl == {"S": None, "V": None, "T": None, "R": -1}, cl
    bd = breadth([{"r24": 1, "r168": 1, "structure": "UP"}, {"r24": -2, "r168": 1, "structure": "DOWN"},
                  {"r24": 3, "r168": -1, "structure": "UP"}])
    assert bd["n"] == 3 and close(bd["pos24"], 2 / 3.0) and close(bd["pos168"], 2 / 3.0), bd
    assert close(bd["up"], 2 / 3.0) and close(bd["med24"], 1.0), bd
    assert len(SYMS) == 40 and SYMS[0] == "BTCUSDT" and len(set(SYMS)) == 40
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"selftest": selftest, "check": cmd_check, "run": cmd_run, "report": cmd_report}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
