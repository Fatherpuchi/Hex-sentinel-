"""oi_collector.py - saves Binance futures positioning stats before they expire.

Binance only keeps ~30 days of open interest and long/short statistics.
Each run downloads whatever is new since the last run (first run: backfills
the last ~29 days) into market_stats.db. It only stores data - Hex's
decisions and databases are not touched.

Usage:  python oi_collector.py            collect now
        python oi_collector.py status     show what has been saved
        python oi_collector.py BTCUSDT XRPUSDT   collect only these coins
Run it at least every couple of weeks (daily is better).
"""
import glob
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

DB = "market_stats.db"
BASE = "https://fapi.binance.com/futures/data/"
PERIOD, PAGE = "1h", 500
DEFAULT_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "NEARUSDT", "DOGEUSDT",
                 "ADAUSDT", "LINKUSDT", "AVAXUSDT", "SUIUSDT", "FILUSDT", "ZECUSDT", "DASHUSDT"]
MAX_COINS = 60
LS = ("longShortRatio", "longAccount", "shortAccount")
METRICS = {
    "oi": ("openInterestHist", ("sumOpenInterest", "sumOpenInterestValue", "CMCCirculatingSupply")),
    "ls_global": ("globalLongShortAccountRatio", LS),
    "ls_top_acct": ("topLongShortAccountRatio", LS),
    "ls_top_pos": ("topLongShortPositionRatio", LS),
    "taker": ("takerlongshortRatio", ("buySellRatio", "buyVol", "sellVol")),
}
G, R, Y, C, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"


def connect():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS futures_stats (
        metric TEXT NOT NULL, symbol TEXT NOT NULL, ts INTEGER NOT NULL,
        a REAL, b REAL, c REAL, raw TEXT,
        PRIMARY KEY (metric, symbol, ts))""")
    return conn


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def get(url, params):
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 400:
                raise ValueError("HTTP 400 (no futures data for this symbol?)")
            r.raise_for_status()
            return r.json()
        except ValueError:
            raise
        except Exception as e:
            last = e
            time.sleep(1.5)
    raise last


def watchlist(args):
    if args:
        return [a.upper() for a in args]
    coins = list(DEFAULT_COINS)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for path in glob.glob("sentinel*.db"):
        if not re.fullmatch(r"sentinel(?:_\d+h)?\.db", path):
            continue
        try:
            c = sqlite3.connect(path)
            for (s,) in c.execute("SELECT DISTINCT symbol FROM paper_signals WHERE created_at >= ?", (cutoff,)):
                if s and s not in coins:
                    coins.append(s)
            c.close()
        except sqlite3.Error:
            pass
    return coins[:MAX_COINS]


def collect(conn, symbol, metric, since_floor):
    endpoint, fields = METRICS[metric]
    row = conn.execute("SELECT MAX(ts) FROM futures_stats WHERE metric=? AND symbol=?", (metric, symbol)).fetchone()
    start = max((row[0] + 1) if row and row[0] else 0, since_floor)
    new = 0
    for _ in range(8):
        d = get(BASE + endpoint, {"symbol": symbol, "period": PERIOD, "limit": PAGE, "startTime": start})
        if not d:
            break
        for x in d:
            ts = int(x["timestamp"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO futures_stats (metric, symbol, ts, a, b, c, raw) VALUES (?,?,?,?,?,?,?)",
                (metric, symbol, ts, num(x.get(fields[0])), num(x.get(fields[1])), num(x.get(fields[2])), json.dumps(x)))
            new += cur.rowcount
        start = max(int(x["timestamp"]) for x in d) + 1
        time.sleep(0.2)
        if len(d) < PAGE:
            break
    conn.commit()
    return new


def run(args):
    conn = connect()
    floor = int((datetime.now(timezone.utc) - timedelta(days=29)).timestamp() * 1000)
    coins = watchlist(args)
    print(f"{C}Collecting {len(coins)} coins into {DB}{X}")
    totals, errors, skipped = {m: 0 for m in METRICS}, {}, []
    for sym in coins:
        coin_new, bad = 0, 0
        for m in METRICS:
            try:
                n = collect(conn, sym, m, floor)
                totals[m] += n
                coin_new += n
            except ValueError as e:
                if m == "oi":                     # no futures market -> skip the coin
                    skipped.append(sym)
                    break
                errors.setdefault(m, str(e))
                bad += 1
            except Exception as e:
                errors.setdefault(m, str(e)[:80])
                bad += 1
        print(f"  {sym:<12} +{coin_new} rows" + (f"  {Y}({bad} metric(s) failed){X}" if bad else ""))
    print(f"\n{C}New rows this run:{X} " + ", ".join(f"{m} {n}" for m, n in totals.items()))
    if skipped:
        print(f"{Y}Skipped (no futures stats): {', '.join(skipped)}{X}")
    for m, e in errors.items():
        print(f"{R}{m} had errors, e.g.: {e}{X}")
    print("Run again daily (or at least every couple of weeks) - history on Binance expires after ~30 days.")


def status():
    conn = connect()
    rows = conn.execute("SELECT metric, COUNT(*), COUNT(DISTINCT symbol), MIN(ts), MAX(ts) FROM futures_stats GROUP BY metric").fetchall()
    if not rows:
        print("Nothing saved yet. Run: python oi_collector.py")
        return
    print(f"{C}market_stats.db{X}")
    for m, n, coins, lo, hi in rows:
        f = lambda t: datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%m-%d %H:%M")
        print(f"  {m:<12} {n:>7} rows  {coins:>3} coins  {f(lo)} -> {f(hi)} UTC")
    age = (time.time() * 1000 - max(r[4] for r in rows)) / 3.6e6
    print(f"\nNewest data is {age:.1f}h old." + (f" {Y}Time to run the collector.{X}" if age > 48 else ""))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "status":
        status()
    else:
        run(sys.argv[1:])
