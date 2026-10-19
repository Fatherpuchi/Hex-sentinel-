# market_facts.py - facts_v1: market figures computed in code from public Binance 1h candles.
# Pure functions plus one public klines request. Writes nothing. No AI calls. (errata 50)
import re
import sys
import time
import requests

FACTS_VERSION = "facts_v1"
HOUR_MS = 3600000
H4_MS = 14400000
MAX_AGE_MIN = 62
MAX_DEV_PCT = 5.0
URLS = {"spot": "https://api.binance.com/api/v3/klines",
        "futures": "https://fapi.binance.com/fapi/v1/klines"}


def ema(values, n):
    out = [None] * len(values)
    if n < 1 or len(values) < n:
        return out
    prev = sum(values[:n]) / float(n)
    out[n - 1] = prev
    a = 2.0 / (n + 1)
    for i in range(n, len(values)):
        prev = a * values[i] + (1.0 - a) * prev
        out[i] = prev
    return out


def rsi_wilder(closes, n=14):
    if len(closes) < n + 1:
        return None
    ch = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [x if x > 0 else 0.0 for x in ch]
    losses = [-x if x < 0 else 0.0 for x in ch]
    ag = sum(gains[:n]) / float(n)
    al = sum(losses[:n]) / float(n)
    for i in range(n, len(ch)):
        ag = (ag * (n - 1) + gains[i]) / float(n)
        al = (al * (n - 1) + losses[i]) / float(n)
    if ag == 0 and al == 0:
        return 50.0
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def atr_wilder(cs, n=14):
    # cs items: (open_ms, o, h, l, c, v)
    if len(cs) < n + 1:
        return None
    tr = []
    for i in range(1, len(cs)):
        h = cs[i][2]
        lo = cs[i][3]
        pc = cs[i - 1][4]
        tr.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    atr = sum(tr[:n]) / float(n)
    for i in range(n, len(tr)):
        atr = (atr * (n - 1) + tr[i]) / float(n)
    return atr


def macd_hist(closes):
    # returns (hist_last, hist_prev) or None
    if len(closes) < 150:
        return None
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    m = [e12[i] - e26[i] for i in range(25, len(closes))]
    sig = ema(m, 9)
    if len(m) < 10 or sig[-1] is None or sig[-2] is None:
        return None
    return m[-1] - sig[-1], m[-2] - sig[-2]


def bollinger_pctb(closes, n=20, k=2.0):
    if len(closes) < n:
        return None
    w = closes[-n:]
    mean = sum(w) / float(n)
    sd = (sum((x - mean) ** 2 for x in w) / float(n)) ** 0.5
    if sd == 0:
        return None
    up = mean + k * sd
    lo = mean - k * sd
    return (closes[-1] - lo) / (up - lo)


def rel_volume(vols):
    if len(vols) < 504:
        return None
    last = len(vols) - 1
    recent = sum(vols[last - 23:last + 1])
    base = [sum(vols[last - 24 * k - 23:last - 24 * k + 1]) for k in range(1, 21)]
    m = sum(base) / 20.0
    if m <= 0:
        return None
    return recent / m


def range_pct(cs, w):
    if len(cs) < w:
        return None
    win = cs[-w:]
    lo = min(x[3] for x in win)
    hi = max(x[2] for x in win)
    c = cs[-1][4]
    return (lo / c - 1.0) * 100.0, (hi / c - 1.0) * 100.0


def gap_free_suffix(cs):
    if not cs:
        return []
    i = len(cs) - 1
    while i > 0 and cs[i][0] - cs[i - 1][0] == HOUR_MS:
        i -= 1
    return cs[i:]


def build_4h(cs):
    groups = {}
    order = []
    for k in cs:
        s = k[0] - (k[0] % H4_MS)
        if s not in groups:
            groups[s] = []
            order.append(s)
        groups[s].append(k)
    blocks = []
    for s in order:
        g = groups[s]
        if len(g) == 4 and [x[0] for x in g] == [s + j * HOUR_MS for j in range(4)]:
            blocks.append((s, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[3][4], sum(x[5] for x in g)))
    return blocks


def parse_klines(raw):
    out = []
    for k in raw:
        out.append((int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
    out.sort(key=lambda x: x[0])
    return out


def parse_report(txt):
    txt = txt or ""
    src = None
    px = None
    m = re.search(r"Data source:\s*([A-Za-z]+)", txt)
    if m:
        src = m.group(1).lower()
    for m in re.finditer(r"Latest Price:\s*\$?\s*([0-9][0-9,]*\.?[0-9]*)", txt):
        try:
            px = float(m.group(1).replace(",", ""))
        except Exception:
            pass
    return src, px


def fetch_klines(symbol, prefer="spot", timeout=15):
    order = [prefer] + [x for x in ("spot", "futures") if x != prefer]
    for name in order:
        try:
            r = requests.get(URLS[name], params={"symbol": symbol, "interval": "1h", "limit": 1000}, timeout=timeout)
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, list) and len(d) >= 30:
                    return name, d
        except Exception:
            continue
    return None, []


def _pct(x):
    return "n/a" if x is None else "%+.2f%%" % x


def _cross(a, b):
    if a is None or b is None:
        return None
    if a > b:
        return "EMA20 above EMA50"
    if a < b:
        return "EMA20 below EMA50"
    return "EMA20 equals EMA50"


def build_facts(symbol, report_text=None, now_ms=None, fetch=None):
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    info = {"version": FACTS_VERSION, "symbol": symbol, "status": "UNAVAILABLE", "reason": "", "text": "",
            "source": None, "last_open_ms": None, "age_min": None, "candles_used": 0,
            "deviation_pct": None, "numbers": {}}

    def fail(reason):
        info["status"] = "UNAVAILABLE"
        info["reason"] = reason
        info["text"] = "MARKET FACTS: UNAVAILABLE (%s)" % reason
        return info

    try:
        src_rep, px_rep = parse_report(report_text)
        prefer = "futures" if (src_rep or "").startswith("fut") else "spot"
        name, raw = (fetch or fetch_klines)(symbol, prefer)
        if not raw:
            return fail("no candle data")
        info["source"] = name
        kl = parse_klines(raw)
        if any(k[0] > now_ms + 120000 for k in kl):
            return fail("clock skew")
        closed = [k for k in kl if k[0] + HOUR_MS <= now_ms]
        cs = gap_free_suffix(closed)
        if len(cs) < 30:
            return fail("too few consecutive closed candles (%d)" % len(cs))
        last_open = cs[-1][0]
        age = (now_ms - (last_open + HOUR_MS)) / 60000.0
        info["last_open_ms"] = last_open
        info["age_min"] = round(age, 1)
        info["candles_used"] = len(cs)
        if age > MAX_AGE_MIN:
            return fail("stale: newest closed candle is %d min old" % int(age))
        close = cs[-1][4]
        if px_rep:
            dev = (close / px_rep - 1.0) * 100.0
            info["deviation_pct"] = round(dev, 2)
            if abs(dev) > MAX_DEV_PCT:
                return fail("price check failed: candle close differs %.1f%% from the report price" % dev)
        closes = [k[4] for k in cs]

        def dist(n):
            if len(closes) < 3 * n:
                return None, None
            e = ema(closes, n)[-1]
            return (close / e - 1.0) * 100.0, e

        d20, e20 = dist(20)
        d50, e50 = dist(50)
        d200, _ = dist(200)
        cross = _cross(e20, e50)

        c4 = [b[4] for b in build_4h(cs)]
        d4 = None
        cross4 = None
        if len(c4) >= 150:
            e50_4 = ema(c4, 50)[-1]
            e20_4 = ema(c4, 20)[-1]
            d4 = (c4[-1] / e50_4 - 1.0) * 100.0
            cross4 = _cross(e20_4, e50_4)

        rsi = rsi_wilder(closes, 14) if len(closes) >= 100 else None
        mh = macd_hist(closes)
        mpct = None
        mdir = None
        if mh:
            mpct = mh[0] / close * 100.0
            mdir = "rising" if mh[0] > mh[1] else ("falling" if mh[0] < mh[1] else "flat")
        atr = atr_wilder(cs, 14) if len(cs) >= 100 else None
        atr_pct = None if atr is None else atr / close * 100.0
        bb = bollinger_pctb(closes)
        rv = rel_volume([k[5] for k in cs])
        r24 = range_pct(cs, 24)
        r168 = range_pct(cs, 168)

        groups = [
            [d20, d50, d200, cross],
            [d4, cross4],
            [rsi, mpct, mdir],
            [atr_pct, bb],
            [rv],
            [r24[0] if r24 else None, r24[1] if r24 else None, r168[0] if r168 else None, r168[1] if r168 else None],
        ]
        complete = sum(1 for g in groups if all(v is not None for v in g))
        has = sum(1 for g in groups if any(v is not None for v in g))
        if complete == 6:
            status = "OK"
        elif has >= 3:
            status = "PARTIAL"
        else:
            return fail("too few indicators available")

        now_s = time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(now_ms / 1000.0))
        last_s = time.strftime("%H:%MZ", time.gmtime(last_open / 1000.0))
        pc = "" if info["deviation_pct"] is None else " | price check %+.2f%% vs report" % info["deviation_pct"]
        lines = [
            "MARKET FACTS (computed by code, %s, not AI-generated)" % FACTS_VERSION,
            "Source: Binance %s 1h | %s | analysed %s" % (name, symbol, now_s),
            "Last closed candle open %s (age %d min) | candles used %d | status %s%s" % (last_s, int(age), len(cs), status, pc),
            "1h trend: close vs EMA20 %s, EMA50 %s, EMA200 %s | %s" % (_pct(d20), _pct(d50), _pct(d200), cross or "EMA cross n/a"),
            "4h trend (%d blocks): close vs EMA50 %s | %s" % (len(c4), _pct(d4), cross4 or "EMA cross n/a"),
            "Momentum 1h: RSI14 %s | MACD hist %s of close (%s)" % ("n/a" if rsi is None else "%.1f" % rsi, _pct(mpct), mdir or "n/a"),
            "Volatility 1h: ATR14 %s of close | Bollinger20 %%B %s" % ("n/a" if atr_pct is None else "%.2f%%" % atr_pct, "n/a" if bb is None else "%.2f" % bb),
            "Volume: last 24h = %s of the 20-day average" % ("n/a" if rv is None else "x%.2f" % rv),
            "Range: 24h low %s high %s | 7d low %s high %s" % (_pct(r24[0] if r24 else None), _pct(r24[1] if r24 else None), _pct(r168[0] if r168 else None), _pct(r168[1] if r168 else None)),
        ]
        info["status"] = status
        info["reason"] = ""
        info["text"] = "\n".join(lines)
        info["numbers"] = {"d20": d20, "d50": d50, "d200": d200, "cross": cross, "d4": d4, "cross4": cross4,
                           "rsi": rsi, "macd_hist_pct": mpct, "macd_dir": mdir, "atr_pct": atr_pct, "pctb": bb,
                           "relvol": rv, "r24": r24, "r168": r168, "blocks4h": len(c4)}
        return info
    except Exception as e:
        return fail("error %s" % str(e)[:60])


def _c(t, o, h, lo, c, v):
    return (t, o, h, lo, c, v)


def _synth(now_open_index=999):
    base = 1700000000000 - (1700000000000 % HOUR_MS)
    raw = []
    for i in range(1000):
        c = 100 + 0.01 * i + (i % 5) * 0.02
        raw.append([base + i * HOUR_MS, str(c), str(c + 0.05), str(c - 0.05), str(c), str(100 + (i % 7)), base + (i + 1) * HOUR_MS - 1])
    return base, raw


def selftest():
    assert ema([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    assert abs(rsi_wilder([10, 11, 10, 11], 2) - 75.0) < 1e-9
    assert rsi_wilder([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], 14) == 100.0
    assert rsi_wilder([5.0] * 20, 14) == 50.0
    cs = [_c(0, 10, 11, 9, 10, 1), _c(1, 10, 12, 10, 11, 1), _c(2, 11, 13, 11, 12, 1), _c(3, 12, 13, 10, 12, 1)]
    assert abs(atr_wilder(cs, 2) - 2.5) < 1e-9
    assert abs(bollinger_pctb([1.0, 2.0, 3.0], 3) - 0.80619) < 1e-4
    assert bollinger_pctb([2.0] * 5, 5) is None
    h0, h1 = macd_hist([100.0] * 150)
    assert abs(h0) < 1e-9 and abs(h1) < 1e-9
    assert macd_hist([float(i) for i in range(1, 201)]) is not None
    assert macd_hist([1.0] * 149) is None
    assert abs(rel_volume([1.0] * 504) - 1.0) < 1e-9
    assert abs(rel_volume([1.0] * 480 + [2.0] * 24) - 2.0) < 1e-9
    assert rel_volume([1.0] * 503) is None
    rc = [_c(0, 0, 12, 8, 10, 1), _c(1, 0, 15, 9, 11, 1), _c(2, 0, 13, 7, 12, 1)]
    lo, hi = range_pct(rc, 3)
    assert abs(lo - (7 / 12.0 - 1) * 100) < 1e-9 and abs(hi - 25.0) < 1e-9
    gp = [_c(h * HOUR_MS, 1, 1, 1, 1, 1) for h in (0, 1, 2, 5, 6)]
    assert len(gap_free_suffix(gp)) == 2
    assert len(build_4h([_c(j * HOUR_MS, 1, 2, 0, 1, 1) for j in range(8)])) == 2
    assert len(build_4h([_c(j * HOUR_MS, 1, 2, 0, 1, 1) for j in range(1, 9)])) == 1
    assert parse_report("Data source: Futures\nLatest Price: $81,263.15\n") == ("futures", 81263.15)
    base, raw = _synth()
    now = base + 999 * HOUR_MS + 1800000
    ok = build_facts("TESTUSDT", "Data source: Spot\nLatest Price: $110.00\n", now_ms=now, fetch=lambda s, p: ("spot", raw))
    assert ok["status"] == "OK" and ok["candles_used"] == 999 and ok["age_min"] == 30.0, ok["reason"]
    assert "MARKET FACTS" in ok["text"] and "n/a" not in ok["text"]
    old = build_facts("TESTUSDT", None, now_ms=base + 1005 * HOUR_MS, fetch=lambda s, p: ("spot", raw))
    assert old["status"] == "UNAVAILABLE" and "stale" in old["reason"]
    bad = build_facts("TESTUSDT", "Latest Price: $150.00\n", now_ms=now, fetch=lambda s, p: ("spot", raw))
    assert bad["status"] == "UNAVAILABLE" and "price check" in bad["reason"]
    skew = build_facts("TESTUSDT", None, now_ms=base, fetch=lambda s, p: ("spot", raw))
    assert skew["status"] == "UNAVAILABLE"
    short = build_facts("TESTUSDT", None, now_ms=now, fetch=lambda s, p: ("spot", raw[-60:]))
    assert short["status"] in ("PARTIAL", "UNAVAILABLE")
    assert build_facts("TESTUSDT", None, now_ms=now, fetch=lambda s, p: (None, []))["status"] == "UNAVAILABLE"
    print(ok["text"])
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selftest":
        selftest()
    elif cmd == "show" and len(sys.argv) > 2:
        s = sys.argv[2].upper()
        s = s if s.endswith("USDT") else s + "USDT"
        r = build_facts(s, None)
        print(r["text"])
        print("status:", r["status"], r["reason"])
    else:
        print("usage: python3 market_facts.py selftest | show SYMBOL")
