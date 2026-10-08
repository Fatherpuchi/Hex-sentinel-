"""rating_report.py - views over rating_log for the Sentinel prompt.
Reads every profile database (sentinel.db = 24h, sentinel_48h.db = 48h, ...)
and shows them together, tagged by horizon.
"""
import glob
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import requests

RESET, BOLD = "\033[0m", "\033[1m"
GREEN, RED, YELLOW, CYAN, DIM = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m"


def _c(text, color, bold=False):
    return f"{BOLD if bold else ''}{color}{text}{RESET}"


def _sig_color(label):
    u = str(label).upper()
    if "BUY" in u:
        return GREEN
    if "SELL" in u:
        return RED
    return YELLOW


def _db():
    return os.getenv("SENTINEL_DB", "sentinel.db")


def _dbs():
    """[(path, horizon_hours)] for every profile database next to the active one."""
    cur = os.path.abspath(_db())
    base = os.path.dirname(cur)
    out = []
    for p in sorted(glob.glob(os.path.join(base, "sentinel*.db"))):
        m = re.fullmatch(r"sentinel(?:_(\d+)h)?\.db", os.path.basename(p))
        if m:
            out.append((p, int(m.group(1) or 24)))
    if cur not in [p for p, _ in out]:
        out.append((cur, int(os.getenv("SENTINEL_HORIZON_HOURS", "24"))))
    return out


def _rows(path):
    if not os.path.exists(path):
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM rating_log ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return rows


def show_ratings(limit=20):
    allrows, counts = [], []
    for path, h in _dbs():
        rows = _rows(path)
        counts.append(f"{h}h: {len(rows)}")
        allrows += [(r["created_at"], h, r) for r in rows]
    print("\n" + _c("=" * 60, CYAN))
    print(_c("COMPOSITE RATING LOG - ALL PROFILES (newest first)", CYAN, True))
    print(_c("=" * 60, CYAN))
    if not allrows:
        print("No ratings logged yet. Run: predict <coin>")
        return
    for _, h, r in sorted(allrows, key=lambda x: x[0], reverse=True)[:limit]:
        tag = _c(f"{h:>2}h", CYAN if h == 24 else YELLOW, True)
        hx = _c(f"{r['hex_signal']:<8}", _sig_color(r["hex_signal"]))
        rt = _c(f"{r['rating']:<11}", _sig_color(r["rating"]), True)
        sc = _c(f"{r['score']:+.2f}", _sig_color("BUY" if r["score"] >= 0.1 else "SELL" if r["score"] <= -0.1 else ""))
        print(
            f"{tag} {_c(r['created_at'][5:16], DIM)}  {r['symbol']:<10} hex={hx} "
            f"{rt} {sc}  "
            f"{_c('ma=%+.2f osc=%+.2f' % (r['ma_score'], r['osc_score']), DIM)}  ${r['price']}"
        )
    print(f"\nLogged ({', '.join(counts)})   (use: rating performance [hours])")


def _price_at(symbol, when):
    """Price (1m open) at `when`: spot first, futures if the coin is futures-only."""
    ms = int(when.timestamp() * 1000)
    params = {"symbol": symbol, "interval": "1m", "startTime": ms, "limit": 1}
    last = None
    for url in ("https://api.binance.com/api/v3/klines",
                "https://fapi.binance.com/fapi/v1/klines"):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0][1])
        except Exception as e:
            last = e
    if last:
        raise last
    return None


def _summ(label, pairs):
    n = len(pairs)
    if n == 0:
        print(f"  {label:<22} n=0")
        return
    hits = sum(1 for d, r in pairs if d * r > 0)
    avg = sum(d * r for d, r in pairs) / n
    pct = 100 * hits / n
    pc = GREEN if pct >= 55 else RED if pct <= 45 else YELLOW
    ac = GREEN if avg > 0 else RED if avg < 0 else YELLOW
    print(f"  {label:<22} n={n:<3} hit={_c('%5.1f%%' % pct, pc, True)}  avg={_c('%+.2f%%' % avg, ac)}")


def _perf_block(rows, hours):
    now = datetime.now(timezone.utc)
    eligible = []
    for r in rows:
        try:
            t = datetime.fromisoformat(r["created_at"])
        except Exception:
            continue
        if now - t >= timedelta(hours=hours):
            eligible.append((r, t))

    print("\n" + _c("=" * 60, CYAN))
    print(_c(f"RATING PERFORMANCE ({hours}h forward return)", CYAN, True))
    print(_c("=" * 60, CYAN))
    if not eligible:
        print(f"No rows are {hours}h old yet ({len(rows)} logged).")
        return

    data, skipped = [], 0
    for r, t in eligible:
        try:
            p2 = _price_at(r["symbol"], t + timedelta(hours=hours))
            time.sleep(0.2)
        except Exception:
            skipped += 1
            continue
        if not p2 or not r["price"]:
            skipped += 1
            continue
        ret = (p2 / r["price"] - 1) * 100
        rd = 1 if r["score"] >= 0.1 else -1 if r["score"] <= -0.1 else 0
        sig = r["hex_signal"]
        hd = 1 if sig == "BUY" else -1 if sig == "SELL" else 0
        data.append((rd, hd, ret))

    print(f"Scored {len(data)} rows ({skipped} skipped: no price data)")
    print("hit = price moved the way the signal pointed; avg = mean signed return\n")
    _summ("Rating (directional)", [(rd, ret) for rd, hd, ret in data if rd])
    _summ("Hex signal", [(hd, ret) for rd, hd, ret in data if hd])
    _summ("Both agree", [(rd, ret) for rd, hd, ret in data if rd and rd == hd])
    dis = [(rd, hd, ret) for rd, hd, ret in data if rd and hd and rd != hd]
    _summ("Disagree: rating side", [(rd, ret) for rd, hd, ret in dis])
    _summ("Disagree: Hex side", [(hd, ret) for rd, hd, ret in dis])
    if len(data) < 30:
        print(_c(f"\nOnly {len(data)} rows: too few to conclude anything (aim for 30-50+).", YELLOW))
    print("Note: runs minutes apart on one coin overlap, so they are not independent.")


def rating_performance(hours=None):
    """Score each profile database over its own horizon (or `hours` if given)."""
    shown = False
    for path, h in _dbs():
        rows = _rows(path)
        if rows:
            shown = True
            _perf_block(rows, hours or h)
    if not shown:
        print("No ratings logged yet. Run: predict <coin>")
