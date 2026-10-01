import json, time, urllib.request, urllib.parse
from dataclasses import dataclass, asdict

FAPI = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
TIMEOUT = 10
PRICE_DEVIATION_MAX_PCT = 0.5
PREMIUM_MAX_AGE = 120
HIST_MAX_AGE = 3 * 3600 + 300


@dataclass
class Observation:
    source: str
    timestamp: int | None
    data_age: int | None
    metric: str
    value: object
    direction: str
    interpretation: str
    kind: str = "signal"


def http_json(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "sentinel/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def obs(source, metric, value, direction, interp, ts_ms=None, max_age=None, kind="signal"):
    age = None if ts_ms is None else max(0, round(time.time() - ts_ms / 1000))
    if max_age is not None and age is not None and age > max_age:
        direction, interp = "UNAVAILABLE", f"stale data ({age}s old); original: {interp}"
    return Observation(source, ts_ms, age, metric, value, direction, interp, kind)


def unavailable(source, metric, err, kind="signal"):
    return Observation(source, None, None, metric, None, "UNAVAILABLE", f"fetch failed: {err}", kind)


def classify_funding(rate):
    if rate > 0.0003:  return "BEARISH", "funding very positive: crowded longs"
    if rate < -0.0001: return "BULLISH", "funding negative: crowded shorts"
    return "NEUTRAL", "funding near baseline"

def classify_global_ratio(r):
    if r > 1.8: return "BEARISH", "retail heavily long: crowding risk"
    if r < 0.8: return "BULLISH", "retail heavily short: squeeze potential"
    return "NEUTRAL", "retail positioning balanced"

def classify_top_ratio(r):
    if r > 1.2:  return "BULLISH", "top traders net long"
    if r < 0.85: return "BEARISH", "top traders net short"
    return "NEUTRAL", "top traders balanced"

def classify_taker(r):
    if r > 1.1: return "BULLISH", "aggressive buying dominates"
    if r < 0.9: return "BEARISH", "aggressive selling dominates"
    return "NEUTRAL", "taker flow balanced"

def classify_oi_price(oi_chg, px_chg):
    if oi_chg > 2 and px_chg > 0.5:  return "BULLISH", "OI rising with price: new longs, trend confirmed"
    if oi_chg > 2 and px_chg < -0.5: return "BEARISH", "OI rising as price falls: new shorts, trend confirmed"
    if oi_chg < -2:                  return "NEUTRAL", "OI falling: deleveraging, no new conviction"
    return "NEUTRAL", "no meaningful OI/price relationship"


def collect_binance():
    out, mark = [], None

    try:
        p = http_json(FAPI + "/fapi/v1/premiumIndex", {"symbol": SYMBOL})
        ts, mark, rate = p["time"], float(p["markPrice"]), float(p["lastFundingRate"])
        out.append(obs("BINANCE", "mark_price", mark, "NEUTRAL", "reference price", ts, PREMIUM_MAX_AGE))
        d, i = classify_funding(rate)
        out.append(obs("BINANCE", "funding_rate", rate, d, i, ts, PREMIUM_MAX_AGE))
    except Exception as e:
        out.append(unavailable("BINANCE", "mark_price", e))
        out.append(unavailable("BINANCE", "funding_rate", e))

    try:
        oi = http_json(FAPI + "/futures/data/openInterestHist",
                       {"symbol": SYMBOL, "period": "1h", "limit": 25})
        kl = http_json(FAPI + "/fapi/v1/klines",
                       {"symbol": SYMBOL, "interval": "1h", "limit": 25})
        oi_chg = (float(oi[-1]["sumOpenInterestValue"]) / float(oi[0]["sumOpenInterestValue"]) - 1) * 100
        px_chg = (float(kl[-1][4]) / float(kl[0][4]) - 1) * 100
        d, i = classify_oi_price(oi_chg, px_chg)
        out.append(obs("BINANCE", "oi_change_24h_vs_price_pct",
                       {"oi_pct": round(oi_chg, 2), "price_pct": round(px_chg, 2)},
                       d, i, oi[-1]["timestamp"], HIST_MAX_AGE))
    except Exception as e:
        out.append(unavailable("BINANCE", "oi_change_24h_vs_price_pct", e))

    for metric, path, field, clf in (
        ("global_long_short_ratio", "globalLongShortAccountRatio", "longShortRatio", classify_global_ratio),
        ("top_trader_position_ratio", "topLongShortPositionRatio", "longShortRatio", classify_top_ratio),
    ):
        try:
            rows = http_json(FAPI + "/futures/data/" + path,
                             {"symbol": SYMBOL, "period": "1h", "limit": 1})
            v = float(rows[-1][field])
            d, i = clf(v)
            out.append(obs("BINANCE", metric, v, d, i, rows[-1]["timestamp"], HIST_MAX_AGE))
        except Exception as e:
            out.append(unavailable("BINANCE", metric, e))

    try:
        rows = http_json(FAPI + "/futures/data/takerlongshortRatio",
                         {"symbol": SYMBOL, "period": "1h", "limit": 4})
        buy = sum(float(r["buyVol"]) for r in rows)
        sell = sum(float(r["sellVol"]) for r in rows)
        v = round(buy / sell, 4)
        d, i = classify_taker(v)
        out.append(obs("BINANCE", "taker_buy_sell_ratio_4h", v, d, i, rows[-1]["timestamp"], HIST_MAX_AGE))
    except Exception as e:
        out.append(unavailable("BINANCE", "taker_buy_sell_ratio_4h", e))

    return out, mark


def integrity(source, price, mark, ts_ms):
    dev = abs(price - mark) / mark * 100
    if dev > PRICE_DEVIATION_MAX_PCT:
        return obs(source, "price_vs_binance_mark_pct", round(dev, 3), "DATA_CONFLICT",
                   f"deviates {dev:.2f}% from Binance mark", ts_ms, kind="integrity")
    return obs(source, "price_vs_binance_mark_pct", round(dev, 3), "CONSISTENT",
               f"within {PRICE_DEVIATION_MAX_PCT}% of Binance mark", ts_ms, kind="integrity")


def collect_integrity(mark):
    out = []
    if mark is None:
        return [unavailable(s, "price_vs_binance_mark_pct", "no Binance mark price", "integrity")
                for s in ("COINGECKO", "COINLORE")]

    try:
        j = http_json("https://api.coingecko.com/api/v3/simple/price",
                      {"ids": "bitcoin", "vs_currencies": "usd", "include_last_updated_at": "true"})
        out.append(integrity("COINGECKO", float(j["bitcoin"]["usd"]), mark,
                             j["bitcoin"]["last_updated_at"] * 1000))
    except Exception as e:
        out.append(unavailable("COINGECKO", "price_vs_binance_mark_pct", e, "integrity"))

    try:
        j = http_json("https://api.coinlore.net/api/ticker/", {"id": "90"})
        out.append(integrity("COINLORE", float(j[0]["price_usd"]), mark, int(time.time() * 1000)))
    except Exception as e:
        out.append(unavailable("COINLORE", "price_vs_binance_mark_pct", e, "integrity"))

    return out


def evaluate(observations):
    core = any(o.source == "BINANCE" and o.metric == "mark_price" and o.direction != "UNAVAILABLE"
               for o in observations)
    if not core:
        return {"status": "NO_TRADE", "reason": "Binance mandatory market data unavailable"}

    integ = [o for o in observations if o.kind == "integrity"]
    if any(o.direction == "DATA_CONFLICT" for o in integ):
        return {"status": "NO_TRADE", "reason": "price data conflict between sources; skip this cycle"}
    if not any(o.direction == "CONSISTENT" for o in integ):
        return {"status": "NO_TRADE", "reason": "no independent integrity source available"}

    sig = [o for o in observations if o.kind == "signal"]
    bull = [o.metric for o in sig if o.direction == "BULLISH"]
    bear = [o.metric for o in sig if o.direction == "BEARISH"]
    unav = [o.metric for o in sig if o.direction == "UNAVAILABLE"]
    return {
        "status": "OK",
        "bullish": bull, "bearish": bear, "unavailable": unav,
        "needs_reconsideration": bool(bull and bear),
        "prefer_more_sources": sum(o.direction == "CONSISTENT" for o in integ) < 2,
    }


def collect_all():
    b_obs, mark = collect_binance()
    all_obs = b_obs + collect_integrity(mark)
    return all_obs, evaluate(all_obs)


if __name__ == "__main__":
    observations, verdict = collect_all()
    print(json.dumps({"observations": [asdict(o) for o in observations],
                      "verdict": verdict}, indent=2))
