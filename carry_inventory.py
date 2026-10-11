import os, sys, json, time, sqlite3, urllib.request, urllib.parse
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "funding.db")
G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
FAPI, SPOT = "https://fapi.binance.com", "https://api.binance.com"
START = 1640995200000          # 2022-01-01 UTC
MIN_MONTHS = 12                # proposed eligibility rule, fixed before any returns are seen


def get(url, params=None, tries=4):
    q = url + (("?" + urllib.parse.urlencode(params)) if params else "")
    for k in range(tries):
        try:
            req = urllib.request.Request(q, headers={"User-Agent": "hex-carry/1"})
            return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                time.sleep(10 * (k + 1))
            elif e.code == 400:
                return None
            else:
                time.sleep(2 * (k + 1))
        except Exception:
            time.sleep(2 * (k + 1))
    return "FAILED"


def coins():
    c = sqlite3.connect(os.path.join(HERE, "fade.db"))
    return [r[0] for r in c.execute("SELECT DISTINCT sym FROM k ORDER BY sym")]


def fetch_funding(conn, sym):
    row = conn.execute("SELECT MAX(t) FROM f WHERE sym=?", (sym,)).fetchone()[0]
    t, ok = (row + 1) if row else START, True
    while True:
        rows = get(FAPI + "/fapi/v1/fundingRate", {"symbol": sym, "startTime": t, "limit": 1000})
        if rows == "FAILED":
            ok = False
            break
        if not rows:
            break
        conn.executemany("INSERT OR IGNORE INTO f VALUES (?,?,?,?)",
                         [(sym, int(r["fundingTime"]), float(r["fundingRate"]), float(r.get("markPrice") or 0)) for r in rows])
        nt = int(rows[-1]["fundingTime"]) + 1
        if nt <= t or len(rows) < 1000:
            break
        t = nt
        time.sleep(0.25)
    conn.commit()
    return ok


def ts(ms): return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def main():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS f(sym TEXT, t INTEGER, rate REAL, mark REAL, PRIMARY KEY(sym,t))")
    syms = coins()
    print(f"{C}{len(syms)} coins from fade.db. Fetching exchange info and funding history (resumable).{X}")
    info = get(FAPI + "/fapi/v1/exchangeInfo")
    perp = {}
    if isinstance(info, dict):
        for s in info.get("symbols", []):
            perp[s["symbol"]] = (s.get("contractType"), s.get("status"), int(s.get("onboardDate", 0)))
    else:
        print(Y + "could not read futures exchangeInfo; perp status will show as unknown" + X)
    fi = get(FAPI + "/fapi/v1/fundingInfo")
    special = {x["symbol"]: x.get("fundingIntervalHours") for x in fi} if isinstance(fi, list) else {}
    now = int(time.time() * 1000)
    hdr = f"{'coin':10s} {'perp':11s} {'spot':5s} {'records':>7s} {'first':10s} {'last':10s} {'months':>6s} {'gaps':>4s} {'interval hours (count)':s}"
    print("\n" + C + hdr + X)
    elig, rows_out = [], []
    for s in syms:
        ok = fetch_funding(conn, s)
        ts_list = [r[0] for r in conn.execute("SELECT t FROM f WHERE sym=? ORDER BY t", (s,))]
        sp = get(SPOT + "/api/v3/ticker/price", {"symbol": s})
        has_spot = isinstance(sp, dict) and "price" in sp
        pc = perp.get(s)
        pstat = f"{pc[0][:4]}/{pc[1][:5]}" if pc and pc[0] else ("unknown" if not perp else "none")
        if not ts_list:
            print(f"{R}{s:10s} {pstat:11s} {'yes' if has_spot else 'NO':5s} {0:7d}  no funding records{X}")
            rows_out.append((s, False, "no funding records"))
            continue
        diffs = [round((b - a) / 3600000) for a, b in zip(ts_list, ts_list[1:])]
        cnt = Counter(diffs)
        gaps = sum(1 for d in diffs if d > 8)
        months = (ts_list[-1] - ts_list[0]) / (30.44 * 86400000)
        stale = (now - ts_list[-1]) > 3 * 86400000
        why = []
        if not (pc and pc[0] == "PERPETUAL" and pc[1] == "TRADING"): why.append("perp not trading")
        if not has_spot: why.append("no spot")
        if months < MIN_MONTHS: why.append("history < %d months" % MIN_MONTHS)
        if gaps: why.append("%d gaps" % gaps)
        if stale or not ok: why.append("stale or fetch incomplete")
        good = not why
        col = G if good else Y
        iv = ", ".join(f"{k}h:{v}" for k, v in sorted(cnt.items()))
        note = "" if s not in special else f"  [fundingInfo interval {special[s]}h]"
        print(f"{col}{s:10s} {pstat:11s} {'yes' if has_spot else 'NO':5s} {len(ts_list):7d} {ts(ts_list[0]):10s} {ts(ts_list[-1]):10s} {months:6.1f} {gaps:4d} {iv}{note}{X}")
        rows_out.append((s, good, "; ".join(why)))
    e = [s for s, g, _ in rows_out if g]
    print(f"\n{C}== eligibility under the proposed rule (perp trading + spot exists + >= {MIN_MONTHS} months + no gaps) =={X}")
    print(f"{G}eligible: {len(e)} of {len(syms)}{X}")
    for s, g, w in rows_out:
        if not g:
            print(f"{Y}  excluded {s}: {w}{X}")
    print(f"\n{D}No funding rates, means or returns were printed or computed. funding.db holds the raw records for the later frozen run.{X}")
    print(f"{D}Not checked here: spot-perp basis history, borrow or margin limits, liquidation behaviour, real fees, delisted coins.{X}")


if __name__ == "__main__":
    main()
