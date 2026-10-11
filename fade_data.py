import sqlite3, time, json, os, sys, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "fade.db")
HOUR = 3600000
SPOT = "https://api.binance.com/api/v3/klines"
FUT = "https://fapi.binance.com/fapi/v1/klines"
COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
         "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "NEARUSDT", "UNIUSDT", "APTUSDT",
         "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT",
         "BCHUSDT", "ETCUSDT", "FILUSDT", "AAVEUSDT", "ALGOUSDT", "XLMUSDT", "HBARUSDT", "ICPUSDT",
         "SANDUSDT", "MANAUSDT", "CRVUSDT", "SHIBUSDT", "FETUSDT", "RUNEUSDT", "TIAUSDT", "SEIUSDT",
         "WLDUSDT", "STXUSDT", "GRTUSDT", "ENJUSDT"]


def get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "hex-fade/1"})
    return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())


def fill(conn, url, sym, t0, t1):
    t, added = t0, 0
    while t <= t1:
        rows = None
        for k in range(3):
            try:
                rows = get(url, {"symbol": sym, "interval": "1h", "limit": 1000, "startTime": t})
                break
            except Exception:
                time.sleep(1.5 * (k + 1))
        if rows is None:
            print(f"\033[93m  {sym}: request failed at {time.strftime('%Y-%m-%d', time.gmtime(t / 1000))}, rerun to resume\033[0m")
            conn.commit()
            return added
        if not rows:
            break
        conn.executemany("INSERT OR IGNORE INTO k VALUES (?,?,?,?,?,?,?)",
                         [(sym, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
                          for r in rows if int(r[0]) <= t1])
        added += len(rows)
        nt = int(rows[-1][0]) + HOUR
        if nt <= t:
            break
        t = nt
        time.sleep(0.12)
    conn.commit()
    return added


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1095
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS k(sym TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,v REAL,PRIMARY KEY(sym,t))")
    now = int(time.time() * 1000) // HOUR * HOUR
    t1 = now - HOUR                                  # last fully closed candle
    t0 = now - days * 24 * HOUR
    for sym in COINS:
        have = conn.execute("SELECT MIN(t),MAX(t) FROM k WHERE sym=?", (sym,)).fetchone()
        for url in (SPOT, FUT):
            if have[0] is None:
                a = fill(conn, url, sym, t0, t1)
            else:
                a = fill(conn, url, sym, t0, have[0] - HOUR) + fill(conn, url, sym, have[1] + HOUR, t1)
            if a > 0 or have[0] is not None:
                break
        n, a, b = conn.execute("SELECT COUNT(*),MIN(t),MAX(t) FROM k WHERE sym=?", (sym,)).fetchone()
        if not n:
            print(f"\033[91m{sym}: no data\033[0m")
            continue
        ts = [r[0] for r in conn.execute("SELECT t FROM k WHERE sym=? ORDER BY t", (sym,))]
        gaps = sum(1 for x, y in zip(ts, ts[1:]) if y - x != HOUR)
        f = lambda x: time.strftime("%Y-%m-%d", time.gmtime(x / 1000))
        print(f"\033[96m{sym:10s}\033[0m {n:6d}  {f(a)} -> {f(b)}  gaps {gaps}")


if __name__ == "__main__":
    main()
