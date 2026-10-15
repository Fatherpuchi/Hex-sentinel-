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
    print(f"{D}{'symbol':20s} {'type':10s} {'price':>12s} {'24h':>8s} {'24h vol $':>14s} {'days listed':>11s}{X}")
    for r in rows[:n]:
        col = G if r["chg"] > 0 else (R if r["chg"] < 0 else X)
        print(f"{col}{r['sym']:20s} {r['kind']:10s} {r['px']:12.4f} {r['chg']:+7.2f}% {r['vol']:14,.0f} {r['age']:11.0f}{X}{D}{' thin' if r['vol'] < 1e6 else ''}{' new' if r['age'] < 30 else ''}{X}")
    print(f"{D}'thin' = under $1M traded in 24h, 'new' = listed under 30 days. The stock's own market is closed nights and weekends. Paper research only.{X}")


ALIASES = {"apple":"AAPL","tesla":"TSLA","nvidia":"NVDA","amazon":"AMZN","google":"GOOGL","alphabet":"GOOGL","microsoft":"MSFT","meta":"META","facebook":"META","netflix":"NFLX","amd":"AMD","intel":"INTC","oracle":"ORCL","adobe":"ADBE","coinbase":"COIN","microstrategy":"MSTR","strategy":"MSTR","paypal":"PYPL","disney":"DIS","nike":"NKE","boeing":"BA","walmart":"WMT","costco":"COST","visa":"V","mastercard":"MA","jpmorgan":"JPM","goldman":"GS","exxon":"XOM","chevron":"CVX","pfizer":"PFE","uber":"UBER","airbnb":"ABNB","palantir":"PLTR","broadcom":"AVGO","qualcomm":"QCOM","micron":"MU","salesforce":"CRM","spotify":"SPOT","shopify":"SHOP","robinhood":"HOOD","amc":"AMC"}


def resolve(text, rows):
    t = "".join(text.lower().split())
    if t in ALIASES:
        text = ALIASES[t]
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


def africa(arg=""):
    import urllib.request, json
    try:
        req = urllib.request.Request("https://dev.kwayisi.org/apis/gse/live", headers={"User-Agent": "Mozilla/5.0"})
        d = json.load(urllib.request.urlopen(req, timeout=15))
    except Exception as e:
        return print("Africa data unavailable: " + repr(e)[:100])
    a = arg.strip().lower()
    if a in ("", "volume"):
        d = sorted(d, key=lambda x: -x["volume"]); t = "by volume"
    elif a == "gainers":
        d = sorted([x for x in d if x["volume"] > 0], key=lambda x: -x["change"]); t = "gainers (volume > 0 only)"
    elif a == "losers":
        d = sorted([x for x in d if x["volume"] > 0], key=lambda x: x["change"]); t = "losers (volume > 0 only)"
    elif a == "all":
        d = sorted(d, key=lambda x: x["name"]); t = "all tickers"
    else:
        d = [x for x in d if a in x["name"].lower()]; t = "match " + arg
        if not d:
            return print("No GSE ticker matches '%s'." % arg)
    print(C + "Ghana Stock Exchange (GSE), " + t + " - external data, research only, not on Binance" + X)
    print("%-12s %10s %10s %12s" % ("ticker", "price GHS", "chg(unit?)", "volume"))
    for x in d[:25]:
        col = D if x["volume"] == 0 else (G if x["change"] > 0 else (R if x["change"] < 0 else X))
        print("%s%-12s %10.2f %10.2f %12.0f  %s%s" % (col, x["name"], x["price"], x["change"], x["volume"], "no trades" if x["volume"] == 0 else "", X))
    print("Source: dev.kwayisi.org (delayed, no timestamp). A no-trade price is stale, not a 0% return. No predictions.")


def africa_menu():
    while True:
        print("=" * 60)
        print(C + "AFRICA - GHANA STOCK EXCHANGE (GSE)" + X)
        print("External data, research only, not on Binance")
        for k, v in (("1", "Top Gainers"), ("2", "Top Losers"), ("3", "Highest Trading Volume"), ("4", "All GSE Stocks"), ("5", "Search by Ticker"), ("6", "Back")):
            print("%s%3s.%s %s" % (C, k, X, v))
        c = input("Choose an option: ").strip()
        if c == "6": return
        if c == "1": africa("gainers")
        elif c == "2": africa("losers")
        elif c == "3": africa("volume")
        elif c == "4": africa("all")
        elif c == "5":
            q = input("GSE ticker (e.g. MTNGH): ").strip()
            if q: africa(q)
        else: print("Unknown option.")


def region_menu():
    rows = load()
    groups = {"1": ("North America: US-listed equities and ETFs (incl. leveraged)", ("EQUITY",)), "2": ("Asia (Hong Kong, South Korea, China)", ("HK_EQUITY", "KR_EQUITY", "CN_EQUITY"))}
    while True:
        print("=" * 60)
        print(C + "WORLD REGIONS" + X)
        print("Binance contracts where listed; Africa is external data. Research only.")
        for k, v in (("1", "North America: US-listed equities and ETFs (incl. leveraged)"), ("2", "Asia (Hong Kong, South Korea, China)"), ("3", "Europe (no separate market on Binance)"), ("4", "Africa - Ghana (external, not on Binance)"), ("5", "Back")):
            print("%s%3s.%s %s" % (Y if k == "4" else C, k, X, v))
        c = input("Choose an option: ").strip()
        if c == "5": return
        if c in groups:
            show(sorted([r for r in rows if r["kind"] in groups[c][1]], key=lambda r: -r["vol"]), groups[c][0], 25)
        elif c == "3":
            print("No European market appears among Binance TradFi contract types (seen: " + ", ".join(sorted(set(r["kind"] for r in rows))) + ").")
            print("Some EQUITY contracts may be European listings; not checked. No external European source verified yet.")
        elif c == "4": africa_menu()
        else: print("Unknown option.")


def menu():
    rows = load()
    kinds = {"4": ("EQUITY", "US-listed equities and ETFs (incl. leveraged)"), "5": ("HK_EQUITY", "Hong Kong"), "6": ("KR_EQUITY", "South Korea"), "7": ("COMMODITY", "Commodities"), "8": ("PREMARKET", "Pre-IPO / premarket")}
    while True:
        print("=" * 60)
        print(C + "HEX SENTINEL - TRADFI MARKETS" + X)
        print("Market: Binance TradFi USDM Perpetuals | Mode: PAPER RESEARCH ONLY")
        for k, v in (("1", "Top Gainers"), ("2", "Top Losers"), ("3", "Highest Trading Volume"), ("4", "US-listed equities and ETFs (incl. leveraged)"), ("5", "Hong Kong Stocks"), ("6", "South Korean Stocks"), ("7", "Commodities"), ("8", "Pre-IPO Markets"), ("9", "All Available Markets"), ("10", "Search by Ticker or Name (e.g. Apple)"), ("11", "Watchlist (not built yet)"), ("12", "Market Information"), ("13", "Back"), ("14", "World Regions (Africa = external data)"), ("15", "Exit")):
            print("%s%3s.%s %s" % (Y if k == "14" else C, k, X, v))
        c = input("Choose an option: ").strip().lower()
        if c in ("13", "15"): return
        if c == "1": show(sorted(rows, key=lambda r: -r["chg"]), "Biggest 24h gainers", 15)
        elif c == "2": show(sorted(rows, key=lambda r: r["chg"]), "Biggest 24h losers", 15)
        elif c == "3": show(sorted(rows, key=lambda r: -r["vol"]), "Highest 24h volume", 15)
        elif c in kinds: show(sorted([r for r in rows if r["kind"] == kinds[c][0]], key=lambda r: -r["vol"]), kinds[c][1], 20)
        elif c == "9": show(sorted(rows, key=lambda r: -r["vol"]), "All TradFi perpetuals by volume (%d)" % len(rows), 25)
        elif c == "10":
            sym, near = resolve(input("Ticker or name: "), rows)
            if sym: show([x for x in rows if x["sym"] == sym], sym, 1)
            else: print("Not found." + (" Did you mean: " + ", ".join(near) if near else ""))
        elif c == "11": print("Watchlist is not built yet (needs its own spec).")
        elif c == "12":
            import collections
            print(dict(collections.Counter(r["kind"] for r in rows)), "contracts:", len(rows))
        elif c == "14": region_menu()
        elif c == "a": africa_menu()
        else: print("Unknown option.")


def main(a):
    mode = a[0].lower() if a else "gainers"
    n = int(a[-1]) if len(a) > 1 and a[-1].isdigit() else 15
    if mode == "predict":
        return predict(" ".join(a[1:])) if len(a) > 1 else print("usage: stocks predict <ticker>")
    if mode in ("score", "log"):
        return score()
    if mode == "menu":
        return menu()
    if mode == "africa":
        return africa(" ".join(a[1:]))
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
