import sys, json, time, sqlite3, os, difflib, math, urllib.request, urllib.parse
from datetime import datetime, timezone
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
FAPI = "https://fapi.binance.com"
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "stock_paper.db")
HOUR = 3600000
GROUPS = {"us": "EQUITY", "hk": "HK_EQUITY", "kr": "KR_EQUITY", "cn": "CN_EQUITY", "commodity": "COMMODITY", "preipo": "PREMARKET", "index": "INDEX", "fx": "FX"}
WARN = "UNVALIDATED paper research. The EMA/RSI rule showed no edge on coins, stock perps have under 8 months of history, and nothing here is a recommendation."


def get(path, params=None):
    q = FAPI + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    return json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "hex-stocks/2"}), timeout=25).read().decode())


def meta():
    return {s["symbol"]: s for s in get("/fapi/v1/exchangeInfo")["symbols"] if s.get("contractType") == "TRADIFI_PERPETUAL" and s.get("status") == "TRADING"}


def load():
    m = meta()
    tk = {t["symbol"]: t for t in get("/fapi/v1/ticker/24hr") if t["symbol"] in m}
    rows = []
    for sym, mm in m.items():
        t = tk.get(sym)
        if t:
            rows.append(dict(sym=sym, kind=mm.get("underlyingType"), px=float(t["lastPrice"]), chg=float(t["priceChangePercent"]),
                             vol=float(t["quoteVolume"]), age=(time.time() * 1000 - int(mm.get("onboardDate", 0))) / 86400000))
    return rows


def show(rows, title, n):
    print(f"{C}{title}{X}")
    print(f"{D}{'symbol':16s} {'type':10s} {'price':>12s} {'24h':>8s} {'24h vol $':>14s} {'days listed':>11s}{X}")
    for r in rows[:n]:
        col = G if r["chg"] > 0 else (R if r["chg"] < 0 else X)
        print(f"{col}{r['sym']:16s} {r['kind']:10s} {r['px']:12.4f} {r['chg']:+7.2f}% {r['vol']:14,.0f} {r['age']:11.0f}{X}{D}{' thin' if r['vol'] < 1e6 else ''}{' new' if r['age'] < 30 else ''}{X}")
    print(f"{D}'thin' = under $1M traded in 24h, 'new' = listed under 30 days. The stock's own market is closed nights and weekends. Paper research only.{X}")


def resolve(text, rows):
    sym = "".join(text.upper().split())
    sym = sym if sym.endswith("USDT") else sym + "USDT"
    names = [r["sym"] for r in rows]
    if sym in names:
        return sym, None
    near = [x[:-4] for x in difflib.get_close_matches(sym, names, n=3, cutoff=0.6)]
    return None, near


def ema(v, n):
    k, e = 2 / (n + 1), v[0]
    for x in v[1:]:
        e = x * k + e * (1 - k)
    return e


def rsi(c, n=14):
    ch = [c[i] - c[i - 1] for i in range(1, len(c))]
    ag, al = sum(max(x, 0) for x in ch[:n]) / n, sum(max(-x, 0) for x in ch[:n]) / n
    for x in ch[n:]:
        ag, al = (ag * (n - 1) + max(x, 0)) / n, (al * (n - 1) + max(-x, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def market_open_guess(kind, now=None):
    t = now or datetime.now(timezone.utc)
    if kind not in ("EQUITY", "ETF"):
        return None
    return t.weekday() < 5 and (13 * 60 + 30) <= t.hour * 60 + t.minute < 21 * 60


def signal(closes):
    e20, e50, r = ema(closes, 20), ema(closes, 50), rsi(closes)
    if e20 > e50 and 50 <= r <= 70:
        return "UP", e20, e50, r
    if e20 < e50:
        return "DOWN", e20, e50, r
    return "NO CALL", e20, e50, r


def db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS preds(id INTEGER PRIMARY KEY, sym TEXT, kind TEXT, created_ms INTEGER, entry REAL, direction TEXT, thr REAL, "
              "end_ms INTEGER, scored_ms INTEGER, exit_px REAL, ret REAL, result TEXT)")
    return c


def predict(text):
    rows = load()
    sym, near = resolve(text, rows)
    if not sym:
        print(Y + "'%s' is not a trading TradFi perpetual." % text + (" Did you mean: " + ", ".join(near) + "?" if near else " Try: stocks all") + X)
        return
    r = next(x for x in rows if x["sym"] == sym)
    k = get("/fapi/v1/klines", dict(symbol=sym, interval="1h", limit=120))
    k = [x for x in k if int(x[0]) + HOUR <= time.time() * 1000][-100:]
    if len(k) < 60:
        print(Y + "only %d closed hourly candles: too little history to apply the rule" % len(k) + X)
        return
    cl = [float(x[4]) for x in k]
    d, e20, e50, rs = signal(cl)
    lr = [math.log(cl[i] / cl[i - 1]) for i in range(1, len(cl))]
    m = sum(lr) / len(lr)
    sd = math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1))
    thr = 0.25 * sd * math.sqrt(24)
    now = int(time.time() * 1000)
    mo = market_open_guess(r["kind"])
    print(f"{C}{sym}  ({r['kind']}, listed {r['age']:.0f} days, 24h volume ${r['vol']:,.0f}){X}")
    print(f"price {cl[-1]:.4f}   EMA20 {e20:.4f}   EMA50 {e50:.4f}   RSI14 {rs:.1f}   hourly vol {sd * 100:.2f}%")
    col = G if d == "UP" else (R if d == "DOWN" else Y)
    print(f"{col}rule output: {d}{X}   (24h horizon; moves smaller than {thr * 100:.2f}% would be void)")
    if mo is False:
        print(Y + "US market likely closed now (weekday window 13:30-21:00 UTC, holidays ignored): price may be set by Binance's own market, and the open can gap." + X)
    if r["vol"] < 1e6:
        print(Y + "thin: under $1M traded in 24h" + X)
    if r["age"] < 30:
        print(Y + "new: listed under 30 days, very short history" + X)
    print(D + WARN + X)
    if d == "NO CALL":
        print(D + "no prediction saved" + X)
        return
    c = db()
    c.execute("INSERT INTO preds(sym,kind,created_ms,entry,direction,thr,end_ms) VALUES(?,?,?,?,?,?,?)", (sym, r["kind"], now, cl[-1], d, thr, now + 24 * HOUR))
    c.commit()
    print(G + "paper prediction saved. Grade it after %s UTC with: stocks score" % datetime.fromtimestamp((now + 24 * HOUR) / 1000, timezone.utc).strftime("%m-%d %H:%M") + X)


def score():
    c = db()
    now = int(time.time() * 1000)
    due = c.execute("SELECT id,sym,created_ms,entry,direction,thr,end_ms FROM preds WHERE scored_ms IS NULL AND end_ms<=?", (now - HOUR,)).fetchall()
    for pid, sym, cm, en, d, thr, em in due:
        try:
            k = get("/fapi/v1/klines", dict(symbol=sym, interval="1h", startTime=em - HOUR, limit=1))
            px = float(k[0][4])
        except Exception as e:
            print(Y + "%s #%d: could not fetch exit price (%s)" % (sym, pid, e) + X)
            continue
        ret = math.log(px / en)
        res = "VOID" if abs(ret) < thr else ("HIT" if (ret > 0) == (d == "UP") else "MISS")
        c.execute("UPDATE preds SET scored_ms=?,exit_px=?,ret=?,result=? WHERE id=?", (now, px, ret, res, pid))
    c.commit()
    rows = c.execute("SELECT id,sym,direction,datetime(created_ms/1000,'unixepoch'),entry,exit_px,ret,result FROM preds ORDER BY id DESC LIMIT 30").fetchall()
    if not rows:
        print(Y + "no stock paper predictions yet. Make one with: stocks predict aapl" + X)
        return
    print(f"{C}{'id':>3s} {'symbol':14s} {'call':5s} {'created (UTC)':19s} {'entry':>10s} {'exit':>10s} {'return':>8s}  result{X}")
    for pid, sym, d, t, en, ex, ret, res in rows:
        col = G if res == "HIT" else (R if res == "MISS" else (D if res == "VOID" else Y))
        print(f"{col}{pid:3d} {sym:14s} {d:5s} {t:19s} {en:10.4f} {(ex or 0):10.4f} {(ret or 0) * 100:+7.2f}%  {res or 'pending'}{X}")
    h, mi = sum(1 for r in rows if r[7] == "HIT"), sum(1 for r in rows if r[7] == "MISS")
    print(f"{D}scored: {h} hit, {mi} miss ({h + mi} counted). Under 100 counted calls this says nothing. Compare with always-UP before believing any rate.{X}")


def main(a):
    mode = a[0].lower() if a else "gainers"
    n = int(a[-1]) if len(a) > 1 and a[-1].isdigit() else 15
    if mode == "predict":
        return predict(" ".join(a[1:])) if len(a) > 1 else print("usage: stocks predict <ticker>")
    if mode in ("score", "log"):
        return score()
    rows = load()
    if mode == "gainers":
        show(sorted(rows, key=lambda r: -r["chg"]), "Stock perpetuals: biggest 24h gainers", n)
    elif mode == "losers":
        show(sorted(rows, key=lambda r: r["chg"]), "Stock perpetuals: biggest 24h losers", n)
    elif mode == "volume":
        show(sorted(rows, key=lambda r: -r["vol"]), "Stock perpetuals: highest 24h volume", n)
    elif mode in GROUPS:
        show(sorted([r for r in rows if r["kind"] == GROUPS[mode]], key=lambda r: -r["vol"]), "Stock perpetuals: " + mode, n if len(a) > 1 else 40)
    elif mode == "all":
        show(sorted(rows, key=lambda r: -r["vol"]), "All TradFi perpetuals by volume (%d)" % len(rows), n if len(a) > 1 else len(rows))
    else:
        sym, near = resolve(" ".join(a), rows)
        if sym:
            show([x for x in rows if x["sym"] == sym], sym, 1)
        else:
            print(Y + "'%s' is not a trading TradFi perpetual." % " ".join(a) + (" Did you mean: " + ", ".join(near) + "?" if near else " Try: stocks all") + X)


if __name__ == "__main__":
    main(sys.argv[1:])
