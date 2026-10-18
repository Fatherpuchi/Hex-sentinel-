# held_plan_grade.py - grader for plans the agreement guard held (errata 48).
# Reads sentinel.db read-only, writes ONLY shadow.db, public Binance candles only. No AI calls.
import os, re, sys, time, sqlite3, datetime
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SENT = os.path.join(HERE, "sentinel.db")
SHAD = os.path.join(HERE, "shadow.db")
START_UTC = "2026-10-18T00:00:00"
WINDOW_MS = 24 * 3600 * 1000
MARGIN_MS = 5 * 60 * 1000
MIN_CANDLES = 1380
MIN_REPORT = 30
MAX_GROUPS = 80
URLS = [("spot", "https://api.binance.com/api/v3/klines"),
        ("futures", "https://fapi.binance.com/fapi/v1/klines")]
FIELDS = ["DIRECTION", "ENTRY_LOW", "ENTRY_HIGH", "STOP_LOSS", "TP1", "TP2", "TP3"]
GRADED = ("TP1", "TP2", "TP3", "STOP", "NONE", "AMBIGUOUS")


def now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ms_from_iso(ts):
    dt = datetime.datetime.fromisoformat(str(ts))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_plan(text):
    out = {}
    for f in FIELDS:
        m = re.search(r"(?m)^\s*" + f + r":\s*([^\n]+?)\s*$", str(text or ""))
        if not m:
            return None
        out[f] = m.group(1).strip().upper().replace("**", "")
    if out["DIRECTION"] not in ("BUY", "SELL"):
        return None
    try:
        for f in FIELDS[1:]:
            out[f] = float(out[f].replace(",", ""))
    except Exception:
        return None
    return out


def levels_ok(p):
    d = p["DIRECTION"]
    lo, hi, sl, t1, t2, t3 = [p[k] for k in FIELDS[1:]]
    if min(lo, hi, sl, t1, t2, t3) <= 0 or lo > hi:
        return False
    if d == "SELL":
        return sl > hi and t1 > t2 > t3
    return sl < lo and t1 < t2 < t3


def grade_path(p, candles):
    """candles: list of (open_ms, high, low). Returns outcome and first-touch times."""
    d = p["DIRECTION"]
    lv = {"tp1": p["TP1"], "tp2": p["TP2"], "tp3": p["TP3"]}
    first = {"tp1": None, "tp2": None, "tp3": None, "stop": None}
    entered = 0
    for t, h, l in candles:
        if l <= p["ENTRY_HIGH"] and h >= p["ENTRY_LOW"]:
            entered = 1
        for k, v in lv.items():
            if first[k] is None and ((d == "SELL" and l <= v) or (d == "BUY" and h >= v)):
                first[k] = t
        if first["stop"] is None and ((d == "SELL" and h >= p["STOP_LOSS"]) or (d == "BUY" and l <= p["STOP_LOSS"])):
            first["stop"] = t
    st = first["stop"]
    names = ("tp1", "tp2", "tp3")
    before = [k for k in names if first[k] is not None and (st is None or first[k] < st)]
    same = [k for k in names if first[k] is not None and st is not None and first[k] == st]
    note = ""
    if before:
        outcome = before[-1].upper()
        if same:
            note = "higher TP in same candle as stop"
    elif same:
        outcome = "AMBIGUOUS"
    elif st is not None:
        outcome = "STOP"
    else:
        outcome = "NONE"
    return {"outcome": outcome, "entered": entered, "first": first, "note": note}


def get_candles(sym, start_ms, end_ms):
    for name, base in URLS:
        try:
            out = []
            cur = start_ms
            for _ in range(3):
                r = requests.get(base, params={"symbol": sym, "interval": "1m", "startTime": cur,
                                               "endTime": end_ms - 1, "limit": 1000}, timeout=20)
                r.raise_for_status()
                d = r.json()
                if not isinstance(d, list) or not d:
                    break
                out += [(int(k[0]), float(k[2]), float(k[3])) for k in d]
                cur = int(d[-1][0]) + 60000
                if cur >= end_ms or len(d) < 1000:
                    break
            if len(out) >= MIN_CANDLES:
                return name, out
        except Exception:
            continue
    return None, []


def ensure(con):
    con.execute("create table if not exists shadow_held_plans(id integer primary key autoincrement, audit_id int, ai text, created_utc text, created_ms int, hour_bucket int, symbol text, direction text, entry_low real, entry_high real, stop_loss real, tp1 real, tp2 real, tp3 real, source text, graded_utc text, entered int, tp1_min int, tp2_min int, tp3_min int, stop_min int, outcome text, note text, unique(audit_id, ai))")


def scan():
    s = sqlite3.connect("file:" + SENT + "?mode=ro", uri=True)
    rows = s.execute("select id,timestamp,symbol,market_signal,groq_assessment,gemini_assessment from ai_consensus_audit where strategy_status='APPROVED' and consensus_status='AGREEMENT' and final_action='PAPER_HOLD' and risk_status='AI_CONSENSUS_LOW_RELIABILITY' and market_signal in ('BUY','SELL') and timestamp >= ? order by id", (START_UTC,)).fetchall()
    s.close()
    con = sqlite3.connect(SHAD, timeout=10)
    ensure(con)
    new = 0
    for aid, ts, sym, sig, gtxt, mtxt in rows:
        try:
            ms = ms_from_iso(ts)
        except Exception:
            continue
        for ai, txt in (("groq", gtxt), ("gemini", mtxt)):
            p = parse_plan(txt)
            outcome = None
            note = ""
            if p is None:
                outcome, note = "UNPARSED", "levels not found"
            elif p["DIRECTION"] != sig:
                outcome, note = "DIRECTION_MISMATCH", "%s vs %s" % (p["DIRECTION"], sig)
            elif not levels_ok(p):
                outcome, note = "INVALID_LEVELS", "stop side or TP order"
            q = p or {}
            cur = con.execute("insert or ignore into shadow_held_plans(audit_id,ai,created_utc,created_ms,hour_bucket,symbol,direction,entry_low,entry_high,stop_loss,tp1,tp2,tp3,graded_utc,outcome,note) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (aid, ai, str(ts), ms, ms // 3600000, sym, q.get("DIRECTION"), q.get("ENTRY_LOW"), q.get("ENTRY_HIGH"), q.get("STOP_LOSS"), q.get("TP1"), q.get("TP2"), q.get("TP3"), now_utc() if outcome else None, outcome, note))
            new += cur.rowcount
    con.commit()
    total = con.execute("select count(*), sum(graded_utc is null) from shadow_held_plans").fetchone()
    con.close()
    print("scan: %d qualifying audit rows, %d new plan rows, table now %s rows (%s pending)" % (len(rows), new, total[0], total[1] or 0))


def grade():
    con = sqlite3.connect(SHAD, timeout=10)
    ensure(con)
    now_ms = int(time.time() * 1000)
    rows = con.execute("select id,symbol,created_ms,direction,entry_low,entry_high,stop_loss,tp1,tp2,tp3 from shadow_held_plans where graded_utc is null and created_ms + ? <= ? order by created_ms", (WINDOW_MS + MARGIN_MS, now_ms)).fetchall()
    cache = {}
    done = 0
    skipped = 0
    groups = 0
    for rid, sym, ms, d, lo, hi, sl, t1, t2, t3 in rows:
        start = (ms // 60000 + 1) * 60000
        key = (sym, start)
        if key not in cache:
            if groups >= MAX_GROUPS:
                skipped += 1
                continue
            groups += 1
            cache[key] = get_candles(sym, start, start + WINDOW_MS)
        src, cs = cache[key]
        if not cs:
            skipped += 1
            continue
        p = {"DIRECTION": d, "ENTRY_LOW": lo, "ENTRY_HIGH": hi, "STOP_LOSS": sl, "TP1": t1, "TP2": t2, "TP3": t3}
        g = grade_path(p, cs)
        f = g["first"]
        mins = {k: (None if f[k] is None else (f[k] - start) // 60000) for k in f}
        con.execute("update shadow_held_plans set source=?, graded_utc=?, entered=?, tp1_min=?, tp2_min=?, tp3_min=?, stop_min=?, outcome=?, note=? where id=?",
                    (src, now_utc(), g["entered"], mins["tp1"], mins["tp2"], mins["tp3"], mins["stop"], g["outcome"], g["note"], rid))
        done += 1
    con.commit()
    con.close()
    print("grade: %d due rows, %d graded, %d left pending (no or short candle data, or run limit)" % (len(rows), done, skipped))


def report():
    con = sqlite3.connect("file:" + SHAD + "?mode=ro", uri=True)
    ph = ",".join("?" * len(GRADED))
    counts = {}
    for ai in ("groq", "gemini"):
        counts[ai] = dict(con.execute("select outcome,count(*) from shadow_held_plans where ai=? and outcome in (%s) group by 1" % ph, (ai,) + GRADED).fetchall())
    other = con.execute("select outcome,count(*) from shadow_held_plans where outcome not in (%s) and outcome is not null group by 1" % ph, GRADED).fetchall()
    pend = con.execute("select count(*) from shadow_held_plans where graded_utc is null").fetchone()[0]
    days = con.execute("select count(distinct symbol || substr(created_utc,1,10)) from shadow_held_plans where outcome in (%s)" % ph, GRADED).fetchone()[0]
    con.close()
    n = {ai: sum(c.values()) for ai, c in counts.items()}
    print("graded rows: groq %d, gemini %d (need %d each) | pending %d | distinct coin-days %d | not graded: %s" % (n["groq"], n["gemini"], MIN_REPORT, pend, days, other))
    if min(n.values()) < MIN_REPORT:
        print("report refused: too few graded rows. Counts only, no inference.")
        return
    for ai in ("groq", "gemini"):
        print(ai, {k: counts[ai].get(k, 0) for k in GRADED})
    print("Counts only. Same-day rows are correlated; no profit claim; no baseline yet.")


def selftest():
    sell = {"DIRECTION": "SELL", "ENTRY_LOW": .755, "ENTRY_HIGH": .765, "STOP_LOSS": .77, "TP1": .75, "TP2": .735, "TP3": .72}
    c1 = [(0, .762, .758), (60000, .758, .749), (120000, .755, .73), (180000, .78, .76)]
    g = grade_path(sell, c1)
    assert g["outcome"] == "TP2" and g["first"]["stop"] == 180000 and g["entered"] == 1, g
    assert grade_path(sell, [(0, .78, .749)])["outcome"] == "AMBIGUOUS"
    assert grade_path(sell, [(0, .78, .76), (60000, .76, .74)])["outcome"] == "STOP"
    assert grade_path(sell, [(0, .762, .758)])["outcome"] == "NONE"
    buy = {"DIRECTION": "BUY", "ENTRY_LOW": .755, "ENTRY_HIGH": .765, "STOP_LOSS": .75, "TP1": .77, "TP2": .785, "TP3": .80}
    assert grade_path(buy, [(0, .76, .756), (60000, .775, .76)])["outcome"] == "TP1"
    assert levels_ok(sell) and not levels_ok(dict(sell, STOP_LOSS=.74))
    txt = "ASSESSMENT: BEARISH\nDIRECTION: SELL\nENTRY_LOW: 0.7550\nENTRY_HIGH: 0.7650\nSTOP_LOSS: 0.7700\nTP1: 0.7500\nTP2: 0.7350\nTP3: 0.7200\n"
    assert parse_plan(txt)["TP1"] == 0.75 and parse_plan("nothing here") is None
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "scan":
        scan()
    elif cmd == "grade":
        grade()
    elif cmd == "run":
        scan()
        grade()
    elif cmd == "report":
        report()
    elif cmd == "selftest":
        selftest()
    else:
        print("usage: python3 held_plan_grade.py scan|grade|run|report|selftest")
