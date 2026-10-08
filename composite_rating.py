"""
composite_rating.py - numpy-only composite rating for Hex (no pandas).
Input: list of dicts with "high", "low", "close", oldest -> newest.
Not financial advice.
"""
import numpy as np

MA_PERIODS = (10, 20, 30, 50, 100, 200)


def _ema(x, n):
    x = np.asarray(x, dtype=float)
    out = np.empty(len(x))
    out[0] = x[0]
    a = 2.0 / (n + 1)
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _wilder(x, n):
    x = np.asarray(x, dtype=float)
    out = np.empty(len(x))
    out[0] = x[0]
    a = 1.0 / n
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _roll(x, n, fn):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = fn(x[i - n + 1:i + 1])
    return out


def _atr(h, l, c, n=14):
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    return _wilder(tr, n)


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = _wilder(np.maximum(d, 0), n)
    dn = _wilder(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(dn == 0, np.inf, up / dn)
    return 100 - 100 / (1 + rs)


def _stoch_k(h, l, c, n=14, smooth=3):
    lo, hi = _roll(l, n, np.min), _roll(h, n, np.max)
    with np.errstate(divide="ignore", invalid="ignore"):
        k = 100 * (c - lo) / (hi - lo)
    return _roll(k, smooth, np.mean)


def _cci(h, l, c, n=20):
    tp = (h + l + c) / 3
    ma = _roll(tp, n, np.mean)
    md = _roll(tp, n, lambda w: np.mean(np.abs(w - w.mean())))
    with np.errstate(divide="ignore", invalid="ignore"):
        return (tp - ma) / (0.015 * md)


def _willr(h, l, c, n=14):
    hi, lo = _roll(h, n, np.max), _roll(l, n, np.min)
    with np.errstate(divide="ignore", invalid="ignore"):
        return -100 * (hi - c) / (hi - lo)


def _turning(series, lo_cut, hi_cut):
    s = series[~np.isnan(series)]
    if len(s) < 2:
        return None
    now, prev = s[-1], s[-2]
    if now < lo_cut and now > prev:
        return 1
    if now > hi_cut and now < prev:
        return -1
    return 0


def ma_votes(h, l, c, k=1.0, slope_k=0.5, slope_bars=10):
    a = _atr(h, l, c)[-1]
    band, sband = k * a, slope_k * a
    votes = {}
    for n in MA_PERIODS:
        if len(c) < n + slope_bars:
            continue
        m = _ema(c, n)
        diff, slope = c[-1] - m[-1], m[-1] - m[-1 - slope_bars]
        if diff > band and slope > sband:
            votes[f"EMA{n}"] = 1
        elif diff < -band and slope < -sband:
            votes[f"EMA{n}"] = -1
        else:
            votes[f"EMA{n}"] = 0
    return votes


def osc_votes(h, l, c):
    v = {}
    for name, val in (
        ("RSI", _turning(_rsi(c), 30, 70)),
        ("Stoch", _turning(_stoch_k(h, l, c), 20, 80)),
        ("CCI", _turning(_cci(h, l, c), -100, 100)),
        ("WilliamsR", _turning(_willr(h, l, c), -80, -20)),
    ):
        if val is not None:
            v[name] = val

    hist = _ema(c, 12) - _ema(c, 26)
    hist = hist - _ema(hist, 9)
    hband = 0.1 * np.mean(np.abs(hist[-50:]))
    v["MACD"] = 1 if hist[-1] > hband else -1 if hist[-1] < -hband else 0

    if len(c) > 11:
        mom, band = c[-1] - c[-11], 0.5 * _atr(h, l, c)[-1]
        v["Momentum"] = 1 if mom > band else -1 if mom < -band else 0
    return v


def label(score):
    if score >= 0.5:
        return "STRONG BUY"
    if score >= 0.1:
        return "BUY"
    if score <= -0.5:
        return "STRONG SELL"
    if score <= -0.1:
        return "SELL"
    return "NEUTRAL"


def composite_rating(candles, atr_k=1.0):
    h = np.array([float(r["high"]) for r in candles])
    l = np.array([float(r["low"]) for r in candles])
    c = np.array([float(r["close"]) for r in candles])
    if len(c) < 60:
        return {"rating": "NEUTRAL", "score": 0.0, "ma_score": 0.0,
                "osc_score": 0.0, "ma_votes": {}, "osc_votes": {},
                "note": "not enough candles"}
    mv, ov = ma_votes(h, l, c, k=atr_k), osc_votes(h, l, c)
    ma_s = float(np.mean(list(mv.values()))) if mv else 0.0
    os_s = float(np.mean(list(ov.values()))) if ov else 0.0
    final = 0.5 * ma_s + 0.5 * os_s
    return {"ma_score": round(ma_s, 3), "osc_score": round(os_s, 3),
            "score": round(final, 3), "rating": label(final),
            "ma_votes": mv, "osc_votes": ov}
