import sqlite3, time, json, os, sys, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lab.db")
HOUR_MS = 3600000
SPOT = "https://api.binance.com/api/v3/klines"
FUT = "https://fapi.binance.com/fapi/v1/klines"
COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
         "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "NEARUSDT",
         "UNIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles(
  symbol TEXT, source TEXT, open_time INTEGER,
  o REAL, h REAL, l REAL, c REAL, v REAL,
  PRIMARY KEY(symbol, open_time));
CREATE TABLE IF NOT EXISTS sets(
  name TEXT PRIMARY KEY, seed INTEGER, n INTEGER, created TEXT, hash TEXT, params TEXT);
CREATE TABLE IF NOT EXISTS rounds(
  set_name TEXT, round_id TEXT, ord INTEGER, symbol TEXT, start_time INTEGER, stratum TEXT,
  PRIMARY KEY(set_name, round_id));
CREATE TABLE IF NOT EXISTS predictions(
  set_name TEXT, round_id TEXT, player TEXT, direction TEXT, confidence INTEGER, locked_at TEXT,
  PRIMARY KEY(set_name, round_id, player));
"""


def connect(path=DB):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def _get(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "hex-lab/1"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def fetch_symbol(conn, symbol, days):
    now = int(time.time() * 1000)
    start = (now - days * 24 * HOUR_MS) // HOUR_MS * HOUR_MS
    row = conn.execute("SELECT MAX(open_time), MAX(source) FROM candles WHERE symbol=?", (symbol,)).fetchone()
    sources = ["spot", "futures"]
    resuming = bool(row[0])
    if resuming:
        start = max(start, row[0] + HOUR_MS)
        sources = [row[1]]
    for src in sources:
        url = SPOT if src == "spot" else FUT
        t, added = start, 0
        while t < now:
            try:
                rows = _get(url, {"symbol": symbol, "interval": "1h", "limit": 1000, "startTime": t})
            except Exception:
                break
            if not rows:
                break
            batch = [(symbol, src, int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
                     for k in rows if int(k[0]) + HOUR_MS <= now]
            conn.executemany("INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?)", batch)
            added += len(batch)
            t = int(rows[-1][0]) + HOUR_MS
            time.sleep(0.15)
        conn.commit()
        if added > 0 or resuming:
            return src, added
    return None, 0


def gap_count(conn, symbol):
    ts = [r[0] for r in conn.execute("SELECT open_time FROM candles WHERE symbol=? ORDER BY open_time", (symbol,))]
    return sum(1 for a, b in zip(ts, ts[1:]) if b - a != HOUR_MS)


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    conn = connect()
    for sym in COINS:
        src, added = fetch_symbol(conn, sym, days)
        if src is None:
            print(f"\033[91m{sym}: no data (spot and futures both failed)\033[0m")
            continue
        n, a, b = conn.execute("SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM candles WHERE symbol=?", (sym,)).fetchone()
        f = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t / 1000))
        print(f"\033[96m{sym:10s}\033[0m {src:8s} +{added:5d}  total {n:6d}  {f(a)} -> {f(b)}  gaps {gap_count(conn, sym)}")


if __name__ == "__main__":
    main()
