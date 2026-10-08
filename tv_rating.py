"""tv_rating.py - TradingView 'Technical Ratings' rules (26 indicators), numpy only.
Assumptions where the page is silent: uptrend/downtrend = EMA13 slope;
Ichimoku spans shifted 26 bars; Hull MA length 9.
"""
import numpy as np

N = np.nan


def _ema(x, n):
    out = np.empty(len(x))
    out[0] = x[0]
    a = 2.0 / (n + 1)
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _rma(x, n):
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = (x[i] + (n - 1) * out[i - 1]) / n
    return out


def _valid(f):
    def g(x, n):
        x = np.asarray(x, dtype=float)
        ok = np.where(~np.isnan(x))[0]
        out = np.full(len(x), N)
        if len(ok) >= n:
            s = ok[0]
            out[s:] = f(x[s:], n)
        return out
    return g


@_valid
def _sma(x, n):
    out = np.full(len(x), N)
    c = np.cumsum(np.insert(x, 0, 0.0))
    if len(x) >= n:
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


@_valid
def _wma(x, n):
    out = np.full(len(x), N)
    w = np.arange(1, n + 1, dtype=float)
    for i in range(n - 1, len(x)):
        out[i] = np.dot(x[i - n + 1:i + 1], w) / w.sum()
    return out


def _hh(x, n):
    return np.array([N if i < n - 1 else x[i - n + 1:i + 1].max() for i in range(len(x))])


def _ll(x, n):
    return np.array([N if i < n - 1 else x[i - n + 1:i + 1].min() for i in range(len(x))])


def _shift(x, k):
    out = np.full(len(x), N)
    out[k:] = x[:-k]
    return out


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = _rma(np.maximum(d, 0), n), _rma(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + np.where(dn == 0, np.inf, up / dn))


def _sig(a, b):
    return 1 if a > b else -1 if a < b else 0


def _ok(*v):
    return not any(np.isnan(x) for x in v)


def tv_rating(candles):
    h = np.array([float(r["high"]) for r in candles])
    l = np.array([float(r["low"]) for r in candles])
    c = np.array([float(r["close"]) for r in candles])
    has_vol = "volume" in candles[0]
    v = np.array([float(r["volume"]) for r in candles]) if has_vol else None
    p, pc = c[-1], np.concatenate(([c[0]], c[:-1]))
    ma, osc = {}, {}

    for n in (10, 20, 30, 50, 100, 200):
        for name, f in (("SMA", _sma), ("EMA", _ema)):
            m = f(c, n)[-1]
            if _ok(m):
                ma[f"{name}{n}"] = _sig(p, m)
    hma = _wma(2 * _wma(c, 4) - _wma(c, 9), 3)[-1]
    if _ok(hma):
        ma["Hull9"] = _sig(p, hma)
    if has_vol:
        vw = _sma(c * v, 20)[-1] / _sma(v, 20)[-1]
        if _ok(vw):
            ma["VWMA20"] = _sig(p, vw)
    conv, base = (_hh(h, 9) + _ll(l, 9)) / 2, (_hh(h, 26) + _ll(l, 26)) / 2
    span_a = _shift((conv + base) / 2, 26)
    span_b = _shift((_hh(h, 52) + _ll(l, 52)) / 2, 26)
    if _ok(conv[-1], base[-1], span_a[-1], span_b[-1]):
        a, b, cv, bs = span_a[-1], span_b[-1], conv[-1], base[-1]
        ma["Ichimoku"] = (1 if (a > b and bs > a and cv > bs and p > cv)
                          else -1 if (a < b and bs < a and cv < bs and p < cv) else 0)

    r = _rsi(c)
    osc["RSI"] = 1 if (r[-1] < 30 and r[-1] > r[-2]) else -1 if (r[-1] > 70 and r[-1] < r[-2]) else 0

    raw = 100 * (c - _ll(l, 14)) / (_hh(h, 14) - _ll(l, 14))
    k = _sma(raw, 3)
    d = _sma(k, 3)
    if _ok(k[-1], d[-1]):
        osc["Stoch"] = (1 if (k[-1] < 20 and d[-1] < 20 and k[-1] > d[-1])
                        else -1 if (k[-1] > 80 and d[-1] > 80 and k[-1] < d[-1]) else 0)

    tp = (h + l + c) / 3
    tp_ma = _sma(tp, 20)
    md = np.array([N if i < 19 else np.abs(tp[i - 19:i + 1] - tp[i - 19:i + 1].mean()).mean()
                   for i in range(len(tp))])
    with np.errstate(divide="ignore", invalid="ignore"):
        cci = (tp - tp_ma) / (0.015 * md)
    if _ok(cci[-1], cci[-2]):
        osc["CCI"] = 1 if (cci[-1] < -100 and cci[-1] > cci[-2]) else -1 if (cci[-1] > 100 and cci[-1] < cci[-2]) else 0

    up, dn = h - _shift(h, 1), _shift(l, 1) - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    trr = _rma(tr, 14)
    pdi, mdi = 100 * _rma(pdm, 14) / trr, 100 * _rma(mdm, 14) / trr
    with np.errstate(divide="ignore", invalid="ignore"):
        adx = _rma(np.nan_to_num(100 * np.abs(pdi - mdi) / (pdi + mdi)), 14)
    if _ok(adx[-1], adx[-2]):
        osc["ADX"] = (1 if (pdi[-1] > mdi[-1] and adx[-1] > 20 and adx[-1] > adx[-2])
                      else -1 if (pdi[-1] < mdi[-1] and adx[-1] > 20 and adx[-1] < adx[-2]) else 0)

    med = (h + l) / 2
    ao = _sma(med, 5) - _sma(med, 34)
    if _ok(ao[-1], ao[-2], ao[-3]):
        a0, a1, a2 = ao[-1], ao[-2], ao[-3]
        buy = (a1 <= 0 < a0) or (a0 > 0 and a1 > 0 and a0 > a1 and a1 < a2)
        sell = (a1 >= 0 > a0) or (a0 < 0 and a1 < 0 and a0 < a1 and a1 > a2)
        osc["AO"] = 1 if buy else -1 if sell else 0

    if len(c) > 12:
        mom = c - _shift(c, 10)
        osc["Momentum"] = _sig(mom[-1], mom[-2])

    macd = _ema(c, 12) - _ema(c, 26)
    osc["MACD"] = _sig(macd[-1], _ema(macd, 9)[-1])

    sr = (r - _ll(r, 14)) / (_hh(r, 14) - _ll(r, 14))
    sk = _sma(sr * 100, 3)
    sd = _sma(sk, 3)
    e13 = _ema(c, 13)
    uptrend, downtrend = e13[-1] > e13[-2], e13[-1] < e13[-2]
    if _ok(sk[-1], sd[-1]):
        osc["StochRSI"] = (1 if (downtrend and sk[-1] < 20 and sd[-1] < 20 and sk[-1] > sd[-1])
                           else -1 if (uptrend and sk[-1] > 80 and sd[-1] > 80 and sk[-1] < sd[-1]) else 0)

    hh, ll = _hh(h, 14), _ll(l, 14)
    wr = -100 * (hh - c) / (hh - ll)
    if _ok(wr[-1], wr[-2]):
        osc["WilliamsR"] = 1 if (wr[-1] < -80 and wr[-1] > wr[-2]) else -1 if (wr[-1] > -20 and wr[-1] < wr[-2]) else 0

    bull, bear = h - e13, l - e13
    osc["BullBear"] = (1 if (uptrend and bear[-1] < 0 and bear[-1] > bear[-2])
                       else -1 if (downtrend and bull[-1] > 0 and bull[-1] < bull[-2]) else 0)

    bp = c - np.minimum(l, pc)
    trg = np.maximum(h, pc) - np.minimum(l, pc)

    def avg(n):
        return _sma(bp, n)[-1] / _sma(trg, n)[-1]
    uo = 100 * (4 * avg(7) + 2 * avg(14) + avg(28)) / 7
    if _ok(uo):
        osc["UO"] = 1 if uo > 70 else -1 if uo < 30 else 0

    ma_s = float(np.mean(list(ma.values()))) if ma else 0.0
    os_s = float(np.mean(list(osc.values()))) if osc else 0.0
    score = (ma_s + os_s) / 2
    lab = ("STRONG BUY" if score > 0.5 else "BUY" if score > 0.1 else
           "STRONG SELL" if score < -0.5 else "SELL" if score < -0.1 else "NEUTRAL")
    return {"ma_score": round(ma_s, 3), "osc_score": round(os_s, 3), "score": round(score, 3),
            "rating": lab, "ma_votes": ma, "osc_votes": osc, "n_ma": len(ma), "n_osc": len(osc)}
