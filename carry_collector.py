import os, sys, json, time, sqlite3, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB, LOGF, COINS = (os.path.join(HERE, n) for n in ("carry_forward.db", "carry_forward_log.jsonl", "carry_forward_coins.json"))
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
FAPI, SPOT, HOUR = "https://fapi.binance.com", "https://api.binance.com", 3600000
SERIES = {"sp": (SPOT + "/api/v3/klines", 1000), "pp": (FAPI + "/fapi/v1/klines", 1500), "mk": (FAPI + "/fapi/v1/markPriceKlines", 1500)}


def now_iso(): return datetime.now(timezone.utc).isoformat()


def log(entry):
    entry = dict(entry, timestamp=now_iso())
    with open(LOGF, "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def get(url, params, tries=4):
    q = url + "?" + urllib.parse.urlencode(params)
    for k in range(tries):
        try:
            req = urllib.request.Request(q, headers={"User-Agent": "hex-carry-forward/1"})
            return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return None
            time.sleep(15 * (k + 1) if e.code in (418, 429) else 2 * (k + 1))
        except Exception:
            time.sleep(2 * (k + 1))
    return "FAILED"


def verified():
    try:
        import carry_verify
        return carry_verify.verify()
    except SystemExit as e:
        return False, "spec module refused to load: %s" % e
    except Exception as e:
        return False, "verification error: %r" % e


def forward_start_ms():
    import carry_spec23 as S
    fz = json.load(open(S.FWD_FILE))["spec"]["forward_start_utc"]
    ms = int(datetime.fromisoformat(fz).timestamp() * 1000)
    return -(-ms // HOUR) * HOUR, fz


def coin_list():
    if os.path.exists(COINS):
        return json.load(open(COINS))["coins"]
    f = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "funding.db"), uri=True)
    coins = [r[0] for r in f.execute("SELECT DISTINCT sym FROM f ORDER BY sym")]
    json.dump({"coins": coins, "created": now_iso(), "source": "symbols in funding.db (read only)"}, open(COINS, "w"), indent=1)
    return coins


def fetch_series(conn, tbl, sym, start, t_end):
    url, lim = SERIES[tbl]
    last = conn.execute("SELECT MAX(t) FROM %s WHERE sym=?" % tbl, (sym,)).fetchone()[0]
    t, added = max(start, (last + HOUR) if last else start), 0
    while t < t_end:
        rows = get(url, dict(symbol=sym, interval="1h", limit=lim, startTime=t))
        if rows is None or rows == "FAILED":
            return False, added, "bad response" if rows is None else "network failure"
        if not rows:
            break
        conn.executemany("INSERT OR IGNORE INTO %s VALUES (?,?,?,?,?,?)" % tbl,
                         [(sym, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows if int(r[0]) + HOUR <= t_end])
        added += len(rows)
        nt = int(rows[-1][0]) + HOUR
        if nt <= t or len(rows) < lim:
            break
        t = nt
        time.sleep(0.25)
    conn.commit()
    return True, added, ""


def fetch_funding(conn, sym, start):
    last = conn.execute("SELECT MAX(t) FROM f WHERE sym=?", (sym,)).fetchone()[0]
    t, added = max(start, (last + 1) if last else start), 0
    while True:
        rows = get(FAPI + "/fapi/v1/fundingRate", dict(symbol=sym, startTime=t, limit=1000))
        if rows is None or rows == "FAILED":
            return False, added, "bad response" if rows is None else "network failure"
        if not rows:
            break
        conn.executemany("INSERT OR IGNORE INTO f VALUES (?,?,?,?)",
                         [(sym, int(r["fundingTime"]), float(r["fundingRate"]), float(r.get("markPrice") or 0)) for r in rows])
        added += len(rows)
        nt = int(rows[-1]["fundingTime"]) + 1
        if nt <= t or len(rows) < 1000:
            break
        t = nt
        time.sleep(0.25)
    conn.commit()
    return True, added, ""


def completeness(conn, coins, start, t_end):
    exp = max(0, (t_end - start) // HOUR)
    miss, fgaps = {}, {}
    for tbl in SERIES:
        for s in coins:
            have = conn.execute("SELECT COUNT(*) FROM %s WHERE sym=? AND t>=? AND t<?" % tbl, (s, start, t_end)).fetchone()[0]
            if exp - have:
                miss["%s:%s" % (tbl, s)] = int(exp - have)
    for s in coins:
        ts = [r[0] for r in conn.execute("SELECT t FROM f WHERE sym=? AND t>=? ORDER BY t", (s, start))]
        g = sum(1 for a, b in zip(ts, ts[1:]) if (b - a) > 8 * HOUR + 60000)
        if g:
            fgaps[s] = g
    return exp, miss, fgaps


def run(dry=False):
    ok, msg = verified()
    if not ok:
        print(R + "REFUSED: " + msg + X)
        log({"status": "REFUSED", "verification": msg})
        return 1
    print(G + "specs verified: " + msg + X)
    start, fz = forward_start_ms()
    t_end = int(time.time() * 1000) // HOUR * HOUR
    coins = coin_list()
    print(f"{C}forward start (hour rounded up) {datetime.fromtimestamp(start / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, {len(coins)} coins, "
          f"collecting closed hours before {datetime.fromtimestamp(t_end / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC{X}")
    if dry:
        print(Y + "dry run: nothing fetched or written" + X)
        return 0
    conn = sqlite3.connect(DB)
    for t in SERIES:
        conn.execute("CREATE TABLE IF NOT EXISTS %s(sym TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,PRIMARY KEY(sym,t))" % t)
    conn.execute("CREATE TABLE IF NOT EXISTS f(sym TEXT,t INTEGER,rate REAL,mark REAL,PRIMARY KEY(sym,t))")
    added, fails = {k: 0 for k in list(SERIES) + ["f"]}, []
    for _k, s in enumerate(coins):
        print(f"{D}{_k + 1}/{len(coins)} {s}{X}", flush=True)
        for t in SERIES:
            good, n, why = fetch_series(conn, t, s, start, t_end)
            added[t] += n
            if not good:
                fails.append("%s:%s %s" % (t, s, why))
        good, n, why = fetch_funding(conn, s, start)
        added["f"] += n
        if not good:
            fails.append("f:%s %s" % (s, why))
    exp, miss, fgaps = completeness(conn, coins, start, t_end)
    status = "OK" if not fails and not miss and not fgaps else ("FAILED" if fails else "PARTIAL")
    log({"status": status, "verification": msg, "rows_added": added, "expected_hours": int(exp), "coins": len(coins),
         "fetch_failures": fails, "missing_candles": miss, "funding_gaps_over_8h": fgaps, "forward_start": fz})
    col = G if status == "OK" else (Y if status == "PARTIAL" else R)
    print(f"{col}{status}{X}  rows added {added}  expected hours per series {exp}")
    if fails: print(R + "fetch failures: " + "; ".join(fails[:10]) + (" ..." if len(fails) > 10 else "") + X)
    if miss: print(Y + f"missing candles in {len(miss)} coin-series (first: {list(miss.items())[:3]})" + X)
    if fgaps: print(Y + f"funding gaps over 8h: {fgaps}" + X)
    return 0 if status == "OK" else (2 if status == "PARTIAL" else 1)


def status():
    if not os.path.exists(LOGF):
        print(Y + "no runs logged yet" + X)
        return
    runs = [json.loads(l) for l in open(LOGF) if l.strip()]
    last_ok = next((r for r in reversed(runs) if r["status"] == "OK"), None)
    print(f"{C}{len(runs)} runs logged. Last 5:{X}")
    for r in runs[-5:]:
        print(f"  {r['timestamp'][:19]}  {r['status']}  fails {len(r.get('fetch_failures', []))}  missing {len(r.get('missing_candles', {}))}")
    if last_ok:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_ok["timestamp"])).total_seconds() / 86400
        print((R if age > 8 else G) + f"last OK run {age:.1f} days ago" + (" : OVERDUE, run it by hand" if age > 8 else "") + X)
    else:
        print(R + "no OK run yet" + X)
    ok, msg = verified()
    print((G + "specs verified" if ok else R + "specs NOT verified: " + msg) + X)
    if ok:
        start, _ = forward_start_ms()
        wk = (time.time() * 1000 - start) / (7 * 24 * HOUR)
        print(f"{D}{wk:.1f} weeks since forward start (minimum review at 26){X}")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "status"
    sys.exit(run() if m == "run" else run(dry=True) if m == "dry" else (status() or 0))
