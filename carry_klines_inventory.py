import os, sys, json, time, sqlite3, urllib.request, urllib.parse, urllib.error
from collections import Counter
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
KDB, FDB = os.path.join(HERE, "carry_klines.db"), os.path.join(HERE, "funding.db")
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
FAPI, SPOT = "https://fapi.binance.com", "https://api.binance.com"
HOUR, START = 3600000, 1640995200000          # 2022-01-01 UTC, same floor as funding.db
SERIES = {"sp": (SPOT + "/api/v3/klines", {}, 1000),
          "pp": (FAPI + "/fapi/v1/klines", {}, 1500),
          "mk": (FAPI + "/fapi/v1/markPriceKlines", {}, 1500)}


def get(url, params=None, tries=4):
    q = url + (("?" + urllib.parse.urlencode(params)) if params else "")
    for k in range(tries):
        try:
            req = urllib.request.Request(q, headers={"User-Agent": "hex-carry/1"})
            return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                time.sleep(15 * (k + 1))
            elif e.code == 400:
                return None
            else:
                time.sleep(2 * (k + 1))
        except Exception:
            time.sleep(2 * (k + 1))
    return "FAILED"


def fetch(conn, tbl, sym, t_end):
    url, extra, lim = SERIES[tbl]
    row = conn.execute(f"SELECT MAX(t) FROM {tbl} WHERE sym=?", (sym,)).fetchone()[0]
    t, ok = (row + HOUR) if row else START, True
    while t < t_end:
        rows = get(url, dict(symbol=sym, interval="1h", limit=lim, startTime=t, **extra))
        if rows == "FAILED":
            ok = False
            break
        if not rows:
            break
        conn.executemany(f"INSERT OR IGNORE INTO {tbl} VALUES (?,?,?,?,?,?)",
                         [(sym, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]))
                          for r in rows if int(r[0]) + HOUR <= t_end])
        nt = int(rows[-1][0]) + HOUR
        if nt <= t or len(rows) < lim:
            break
        t = nt
        time.sleep(0.3)
    conn.commit()
    return ok


def day(ms): return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def analyze(sym, kc, fc, onboard):
    f = fc.execute("SELECT t,mark FROM f WHERE sym=? ORDER BY t", (sym,)).fetchall()   # no funding RATE is read
    if not f:
        return None
    ts = np.array([r[0] for r in f], dtype=np.int64)
    mk = np.array([r[1] for r in f], dtype=float)
    hrs = (np.round(ts / HOUR).astype(np.int64) * HOUR)
    jit = int(np.abs(ts - hrs).max())
    dup = len(hrs) - len(set(hrs.tolist()))
    d = np.round(np.diff(ts) / HOUR).astype(int)
    irreg = int((~np.isin(d, [1, 2, 4, 8])).sum())
    gaps = int((d > 8).sum())
    poss = sum(1 for i in range(1, len(d) - 1) if d[i] > max(d[i - 1], d[i + 1]) and d[i] <= 8)
    runs, trans = [], []
    for i, v in enumerate(d.tolist()):
        if runs and runs[-1][0] == v:
            runs[-1][1] += 1
        else:
            if runs:
                trans.append((day(int(ts[i])), runs[-1][0], v))
            runs.append([v, 1])
    hl = hrs.tolist()
    sets = {t: {r[0] for r in kc.execute(f"SELECT t FROM {t} WHERE sym=?", (sym,))} for t in SERIES}
    miss = {t: sum(1 for h in hl if h not in sets[t]) for t in SERIES}
    mkmap = {r[0]: r[1] for r in kc.execute("SELECT t,o FROM mk WHERE sym=?", (sym,))}
    dev, ctl, zero = [], [], int((mk <= 0).sum())
    for h, m in zip(hl, mk.tolist()):
        if m > 0 and h in mkmap and (h - HOUR) in mkmap:
            dev.append(abs(m / mkmap[h] - 1) * 1e4)
            ctl.append(abs(m / mkmap[h - HOUR] - 1) * 1e4)
    md, mc = (float(np.median(dev)), float(np.median(ctl))) if dev else (float("nan"), float("nan"))
    cov = {}
    for t in SERIES:
        s = sorted(sets[t])
        cov[t] = (len(s), (s[-1] - s[0]) // HOUR + 1 - len(s)) if s else (0, 0)
    bad = sum(kc.execute(f"SELECT COUNT(*) FROM {t} WHERE sym=? AND (o<=0 OR h<=0 OR l<=0 OR c<=0 OR h<l)", (sym,)).fetchone()[0] for t in SERIES)
    return dict(n=len(ts), jit=jit, dup=dup, irreg=irreg, gaps=gaps, poss=poss, trans=trans, miss=miss, zero=zero,
                md=md, mc=mc, cov=cov, bad=bad, first=int(ts[0]), onboard=onboard)


def main(mode):
    if not os.path.exists(FDB):
        raise SystemExit(R + "funding.db missing: run carry_inventory.py first" + X)
    fc = sqlite3.connect(FDB)
    syms = [r[0] for r in fc.execute("SELECT DISTINCT sym FROM f ORDER BY sym")]
    kc = sqlite3.connect(KDB)
    for t in SERIES:
        kc.execute(f"CREATE TABLE IF NOT EXISTS {t}(sym TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,PRIMARY KEY(sym,t))")
    info = get(FAPI + "/fapi/v1/exchangeInfo")
    onb, have = {}, set()
    if isinstance(info, dict):
        for s in info.get("symbols", []):
            have.add(s["symbol"])
            onb[s["symbol"]] = int(s.get("onboardDate", 0))
    t_end = int(time.time() * 1000) // HOUR * HOUR
    fetched = {}
    if mode == "fetch":
        print(f"{C}{len(syms)} coins with funding records. Fetching spot, perp and mark-price 1h klines (resumable, roughly 30-50 min).{X}")
        t0 = time.time()
        for k, s in enumerate(syms):
            fetched[s] = all([fetch(kc, t, s, t_end) for t in SERIES])
            print(f"{D}{k + 1}/{len(syms)} {s} {'ok' if fetched[s] else 'INCOMPLETE'}  {(time.time() - t0) / 60:.1f} min{X}", flush=True)
    res = {s: analyze(s, kc, fc, onb.get(s, 0)) for s in syms}
    print(f"\n{C}{'coin':10s} {'rec':>5s} {'jitMs':>5s} {'irr':>3s} {'gap':>3s} {'poss':>4s} {'chg':>4s} {'missSpot':>8s} {'missPerp':>8s} {'missMark':>8s} {'mk0':>4s} {'alignBps':>9s} {'ctrlBps':>8s} {'bad':>4s}  onboard{X}")
    elig, why = [], {}
    for s in syms:
        a = res[s]
        w = []
        if a is None:
            continue
        if any(a["miss"].values()): w.append("candles missing at settlement hours")
        if a["gaps"]: w.append("funding gaps >8h")
        if a["irreg"]: w.append("irregular interval")
        if a["dup"]: w.append("duplicate settlement hours")
        if a["bad"]: w.append("bad candles")
        if not (a["md"] == a["md"]) or a["md"] >= a["mc"]: w.append("settlement-hour alignment not clearly better than shifted control")
        if fetched and not fetched.get(s, True): w.append("fetch incomplete")
        if not w: elig.append(s)
        why[s] = w
        col = G if not w else Y
        print(f"{col}{s:10s} {a['n']:5d} {a['jit']:5d} {a['irreg']:3d} {a['gaps']:3d} {a['poss']:4d} {len(a['trans']):4d} {a['miss']['sp']:8d} {a['miss']['pp']:8d} {a['miss']['mk']:8d} {a['zero']:4d} {a['md']:9.2f} {a['mc']:8.2f} {a['bad']:4d}  {day(a['onboard']) if a['onboard'] else '?'}{X}")
    print(f"\n{C}== interval changes taken from actual settlement spacing (first 6 per coin) =={X}")
    for s in syms:
        a = res[s]
        if a and a["trans"]:
            tr = ", ".join(f"{d_}: {x}h->{y}h" for d_, x, y in a["trans"][:6])
            print(f"{s:10s} {len(a['trans']):4d} changes   {tr}{' ...' if len(a['trans']) > 6 else ''}")
    print(f"\n{C}== coverage windows (candle counts and internal holes) =={X}")
    for s in syms:
        a = res[s]
        if a:
            print(f"{D}{s:10s} spot {a['cov']['sp'][0]:6d} (holes {a['cov']['sp'][1]})  perp {a['cov']['pp'][0]:6d} (holes {a['cov']['pp'][1]})  mark {a['cov']['mk'][0]:6d} (holes {a['cov']['mk'][1]})  first funding {day(a['first'])}{X}")
    print(f"\n{C}== data-completeness eligibility (fixed now: zero missing candles at settlement hours, zero gaps, zero irregular intervals, aligned) =={X}")
    print(f"{G}eligible: {len(elig)} of {len(syms)}{X}")
    for s in syms:
        if why.get(s):
            print(f"{Y}  excluded {s}: {'; '.join(why[s])}{X}")
    poss = {s: res[s]['poss'] for s in syms if res[s] and res[s]['poss']}
    if poss:
        print(f"{Y}possibly missed records (spacing larger than both neighbours), listed not gating: {poss}{X}")
    print(f"{G if '1000SHIBUSDT' in have else Y}1000SHIBUSDT perp {'exists' if '1000SHIBUSDT' in have else 'not found'} (different contract size from spot SHIB; stays excluded under the written rule){X}")
    print(f"\n{D}No funding rate, basis, price level or return was printed or computed. alignBps = median |record markPrice / mark candle open - 1| at the settlement hour; ctrlBps = same against the previous hour (control).{X}")
    print(f"{D}Not checked: maintenance-margin and leverage-bracket rules (need account data), real fee tier, delisted coins, spot-perp borrow or transfer limits.{X}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fetch")
