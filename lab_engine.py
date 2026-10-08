import sqlite3, hashlib, math, random, sys, json
from dataclasses import dataclass
from datetime import datetime, timezone
from lab_data import connect, DB, HOUR_MS

G, R, C, Y, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[93m", "\033[2m", "\033[0m"

# ---- frozen design constants (changing these changes what a benchmark means) ----
VISIBLE, AHEAD = 100, 24
SPAN = VISIBLE + AHEAD
FLAT_K = 0.25                 # FLAT if |ret| < FLAT_K * visible-sigma * sqrt(AHEAD)
TREND_Z = 0.75                # |trend z| above this = UP/DOWN stratum, else SIDE
EXCLUDE_LATEST_DAYS = 30      # windows ending inside the newest 30 days are never used
MAX_PER_DAY = 3               # max rounds per UTC decision day, all coins together
CONF_LEVELS = (50, 60, 70, 80, 90, 100)
STRATA = [(t, v) for t in ("DOWN", "SIDE", "UP") for v in ("LOW", "MID", "HIGH")]
DAY_MS = 24 * HOUR_MS


# ---------------------------------------------------------------- maths
def _sigma(closes):
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    m = sum(rets) / len(rets)
    return math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))


def trend_z(closes):
    s = _sigma(closes)
    if s == 0:
        return 0.0
    return math.log(closes[-1] / closes[0]) / (s * math.sqrt(len(closes) - 1))


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return ctr - hw, ctr + hw


# ---------------------------------------------------------------- views / outcomes
# DB row format everywhere: (open_time, o, h, l, c, v)
@dataclass(frozen=True)
class RoundView:
    round_id: str
    candles: tuple          # 100 x (o, h, l, c, v), price-normalised (last close = 100), no time, no symbol


@dataclass(frozen=True)
class RoundOutcome:
    round_id: str
    ret: float
    threshold: float
    direction: str          # UP / DOWN / FLAT


def make_view(round_id, visible_rows):
    scale = visible_rows[-1][4] / 100.0
    vmean = sum(r[5] for r in visible_rows) / len(visible_rows)
    candles = tuple((r[1] / scale, r[2] / scale, r[3] / scale, r[4] / scale,
                     (r[5] / vmean if vmean else 0.0)) for r in visible_rows)
    return RoundView(round_id, candles)


def make_outcome(round_id, visible_rows, ahead_rows):
    closes = [r[4] for r in visible_rows]
    thr = FLAT_K * _sigma(closes) * math.sqrt(AHEAD)
    ret = math.log(ahead_rows[-1][4] / closes[-1])
    if ret == 0 or abs(ret) < thr:
        d = "FLAT"
    else:
        d = "UP" if ret > 0 else "DOWN"
    return RoundOutcome(round_id, ret, thr, d)


def _window_rows(conn, symbol, start):
    return conn.execute(
        "SELECT open_time,o,h,l,c,v FROM candles WHERE symbol=? AND open_time>=? AND open_time<? ORDER BY open_time",
        (symbol, start, start + SPAN * HOUR_MS)).fetchall()


def get_view(conn, set_name, round_id):
    """What an opponent may see: ONLY the 100 visible candles are ever queried."""
    r = conn.execute("SELECT symbol,start_time FROM rounds WHERE set_name=? AND round_id=?",
                     (set_name, round_id)).fetchone()
    if not r:
        raise ValueError("unknown round")
    rows = conn.execute(
        "SELECT open_time,o,h,l,c,v FROM candles WHERE symbol=? AND open_time>=? AND open_time<? ORDER BY open_time",
        (r[0], r[1], r[1] + VISIBLE * HOUR_MS)).fetchall()
    if len(rows) != VISIBLE:
        raise RuntimeError(f"round {round_id}: expected {VISIBLE} visible candles, got {len(rows)}")
    return make_view(round_id, rows)


def _outcome(conn, set_name, round_id):
    """Scorer-only. Opponents never get a connection or this function."""
    r = conn.execute("SELECT symbol,start_time FROM rounds WHERE set_name=? AND round_id=?",
                     (set_name, round_id)).fetchone()
    if not r:
        raise ValueError("unknown round")
    rows = _window_rows(conn, r[0], r[1])
    if len(rows) != SPAN:
        raise RuntimeError(f"round {round_id}: expected {SPAN} candles, got {len(rows)}")
    return make_outcome(round_id, rows[:VISIBLE], rows[VISIBLE:])


# ---------------------------------------------------------------- sampling
@dataclass
class Cand:
    symbol: str
    start: int
    z: float
    sigma: float
    stratum: tuple = None


def candidates(conn):
    series = {}
    for (sym,) in conn.execute("SELECT DISTINCT symbol FROM candles ORDER BY symbol").fetchall():
        series[sym] = {r[0]: r for r in conn.execute(
            "SELECT open_time,o,h,l,c,v FROM candles WHERE symbol=?", (sym,)).fetchall()}
    if not series:
        return []
    tmax = max(max(d) for d in series.values())
    cutoff = tmax - EXCLUDE_LATEST_DAYS * DAY_MS
    out = []
    for sym, d in sorted(series.items()):
        times = sorted(d)
        off = int(hashlib.sha256(sym.encode()).hexdigest()[:8], 16) % SPAN   # per-coin grid offset
        s_h = -(-((times[0] // HOUR_MS) - off) // SPAN) * SPAN + off      # fixed absolute grid, ceil to grid
        last_h = times[-1] // HOUR_MS
        while s_h <= last_h and (s_h + SPAN) * HOUR_MS <= cutoff:
            rows = [d.get((s_h + i) * HOUR_MS) for i in range(SPAN)]
            if None not in rows:
                closes = [r[4] for r in rows[:VISIBLE]]      # visible window ONLY
                out.append(Cand(sym, s_h * HOUR_MS, trend_z(closes), _sigma(closes)))
            s_h += SPAN
    return out


def assign_strata(cands):
    sig = sorted(c.sigma for c in cands)
    lo, hi = sig[len(sig) // 3], sig[2 * len(sig) // 3]
    for c in cands:
        t = "DOWN" if c.z < -TREND_Z else ("UP" if c.z > TREND_Z else "SIDE")
        v = "LOW" if c.sigma < lo else ("HIGH" if c.sigma >= hi else "MID")
        c.stratum = (t, v)


def sample(cands, n, seed, banned=()):
    rng = random.Random(seed)
    pool = sorted((c for c in cands if (c.symbol, c.start) not in banned), key=lambda c: (c.symbol, c.start))
    if not pool:
        raise SystemExit("no candidate windows available")
    ncoins = len({c.symbol for c in pool})
    coin_cap = math.ceil(2 * n / ncoins)
    by = {s: [c for c in pool if c.stratum == s] for s in STRATA}
    for s in STRATA:
        rng.shuffle(by[s])
    base, extra = divmod(n, len(STRATA))
    chosen, day, coin, short = [], {}, {}, {}

    def take(c):
        d = (c.start + VISIBLE * HOUR_MS) // DAY_MS
        if day.get(d, 0) >= MAX_PER_DAY or coin.get(c.symbol, 0) >= coin_cap:
            return False
        day[d] = day.get(d, 0) + 1
        coin[c.symbol] = coin.get(c.symbol, 0) + 1
        chosen.append(c)
        return True

    for i, s in enumerate(STRATA):
        quota, got = base + (1 if i < extra else 0), 0
        for c in by[s]:
            if got >= quota:
                break
            if take(c):
                got += 1
        if got < quota:
            short[s] = quota - got
    if len(chosen) < n:
        taken = {(c.symbol, c.start) for c in chosen}
        rest = [c for c in pool if (c.symbol, c.start) not in taken]
        rng.shuffle(rest)
        for c in rest:
            if len(chosen) >= n:
                break
            take(c)
    rng.shuffle(chosen)
    return chosen, short


def round_id_for(name, symbol, start):
    return "R" + hashlib.sha256(f"{name}|{symbol}|{start}".encode()).hexdigest()[:10]


def set_hash(conn, name):
    h = hashlib.sha256()
    for rid, sym, st in conn.execute(
            "SELECT round_id,symbol,start_time FROM rounds WHERE set_name=? ORDER BY round_id", (name,)).fetchall():
        h.update(f"{rid}|{sym}|{st}".encode())
        for r in _window_rows(conn, sym, st):
            h.update(repr(r).encode())
    return h.hexdigest()


def build_set(conn, name, n, seed):
    if conn.execute("SELECT 1 FROM sets WHERE name=?", (name,)).fetchone():
        raise SystemExit(f"set '{name}' already exists and is frozen")
    cands = candidates(conn)
    assign_strata(cands)
    used = conn.execute("SELECT symbol,start_time FROM rounds").fetchall()
    span_ms = SPAN * HOUR_MS
    cands = [c for c in cands if not any(c.symbol == s and abs(c.start - t) < span_ms for s, t in used)]
    chosen, short = sample(cands, n, seed)
    for i, c in enumerate(chosen):
        conn.execute("INSERT INTO rounds VALUES (?,?,?,?,?,?)",
                     (name, round_id_for(name, c.symbol, c.start), i, c.symbol, c.start, f"{c.stratum[0]}/{c.stratum[1]}"))
    h = set_hash(conn, name)
    params = json.dumps(dict(VISIBLE=VISIBLE, AHEAD=AHEAD, FLAT_K=FLAT_K, TREND_Z=TREND_Z,
                             EXCLUDE_LATEST_DAYS=EXCLUDE_LATEST_DAYS, MAX_PER_DAY=MAX_PER_DAY))
    conn.execute("INSERT INTO sets VALUES (?,?,?,?,?,?)",
                 (name, seed, len(chosen), datetime.now(timezone.utc).isoformat(), h, params))
    conn.commit()
    return chosen, short, h, len(cands)


def verify(conn, name):
    r = conn.execute("SELECT hash FROM sets WHERE name=?", (name,)).fetchone()
    return bool(r) and r[0] == set_hash(conn, name)


# ---------------------------------------------------------------- locking / reveal
class LockedError(Exception):
    pass


def lock_prediction(conn, set_name, round_id, player, direction, confidence):
    if direction not in ("UP", "DOWN"):
        raise ValueError("direction must be UP or DOWN")
    if confidence not in CONF_LEVELS:
        raise ValueError(f"confidence must be one of {CONF_LEVELS}")
    if not conn.execute("SELECT 1 FROM rounds WHERE set_name=? AND round_id=?", (set_name, round_id)).fetchone():
        raise ValueError("unknown round")
    try:
        conn.execute("INSERT INTO predictions VALUES (?,?,?,?,?,?)",
                     (set_name, round_id, player, direction, confidence, datetime.now(timezone.utc).isoformat()))
    except sqlite3.IntegrityError:
        raise LockedError(f"{player} already locked a prediction for {round_id}")
    conn.commit()


def reveal(conn, set_name, round_id, player):
    p = conn.execute("SELECT direction,confidence FROM predictions WHERE set_name=? AND round_id=? AND player=?",
                     (set_name, round_id, player)).fetchone()
    if not p:
        raise LockedError("no locked prediction for this player: cannot reveal")
    return _outcome(conn, set_name, round_id), p


# ---------------------------------------------------------------- opponents (see RoundView only)
def _ema(vals, n):
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes, n=14):
    ch = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ag = sum(max(x, 0) for x in ch[:n]) / n
    al = sum(max(-x, 0) for x in ch[:n]) / n
    for x in ch[n:]:
        ag = (ag * (n - 1) + max(x, 0)) / n
        al = (al * (n - 1) + max(-x, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def opp_always_up(view):
    return "UP", 50


def opp_random(view):
    seed = int(hashlib.sha256((view.round_id + "|random").encode()).hexdigest()[:16], 16)
    return random.Random(seed).choice(["UP", "DOWN"]), 50


def opp_ema_rsi(view):
    closes = [c[3] for c in view.candles]
    e20, e50, r = _ema(closes, 20), _ema(closes, 50), _rsi(closes)
    if e20 > e50:
        return ("UP", 60) if 50 <= r <= 70 else ("UP", 50)
    return "DOWN", 60


OPPONENTS = {"always_up": opp_always_up, "random": opp_random, "ema_rsi": opp_ema_rsi}


def run_opponents(conn, set_name):
    ids = [r for (r,) in conn.execute("SELECT round_id FROM rounds WHERE set_name=? ORDER BY ord", (set_name,))]
    new = 0
    for rid in ids:
        view = get_view(conn, set_name, rid)
        for name, fn in OPPONENTS.items():
            d, cf = fn(view)
            try:
                lock_prediction(conn, set_name, rid, name, d, cf)
                new += 1
            except LockedError:
                pass
    return new


# ---------------------------------------------------------------- scoring (basic; full stats = Milestone 2)
def score_player(conn, set_name, player):
    rows = conn.execute("SELECT round_id,direction FROM predictions WHERE set_name=? AND player=?",
                        (set_name, player)).fetchall()
    n = void = correct = 0
    for rid, d in rows:
        o = _outcome(conn, set_name, rid)
        if o.direction == "FLAT":
            void += 1
            continue
        n += 1
        correct += (o.direction == d)
    return dict(n=n, void=void, correct=correct)


def verdict(k, n):
    if n < 100:
        return "too small to judge"
    lo, hi = wilson(k, n)
    if lo <= 0.5 <= hi:
        return "not distinguishable from a coin flip"
    return "above 50% (interval excludes it)" if lo > 0.5 else "below 50% (interval excludes it)"


def summary(conn, set_name):
    players = [p for (p,) in conn.execute(
        "SELECT DISTINCT player FROM predictions WHERE set_name=? ORDER BY player", (set_name,))]
    if not players:
        print("no predictions locked yet")
        return
    print(f"{C}{'player':12s} {'n':>5s} {'void':>5s} {'acc':>7s}   95% interval   verdict{X}")
    for p in players:
        s = score_player(conn, set_name, p)
        acc = s["correct"] / s["n"] if s["n"] else 0
        lo, hi = wilson(s["correct"], s["n"])
        col = G if s["n"] >= 100 and lo > 0.5 else (R if s["n"] >= 100 and hi < 0.5 else Y)
        print(f"{col}{p:12s} {s['n']:5d} {s['void']:5d} {acc * 100:6.1f}%   {lo * 100:4.0f}-{hi * 100:3.0f}%   "
              f"{verdict(s['correct'], s['n'])}{X}")


# ---------------------------------------------------------------- CLI
def main():
    a = sys.argv[1:]
    usage = ("usage: lab_engine.py list | build NAME N SEED | verify NAME | run NAME | runall NAME | summary NAME | report NAME | play NAME [block|each] [LIMIT] | mine NAME")
    if not a:
        print(usage)
        return
    conn = connect()
    cmd = a[0]
    if cmd == "list":
        for name, seed, n, created, h in conn.execute("SELECT name,seed,n,created,hash FROM sets"):
            print(f"{C}{name}{X} n={n} seed={seed} {created[:19]} hash={h[:16]}")
    elif cmd == "build" and len(a) == 4:
        chosen, short, h, ncand = build_set(conn, a[1], int(a[2]), int(a[3]))
        syms = len({c.symbol for c in chosen})
        print(f"{G}built '{a[1]}': {len(chosen)} rounds from {ncand} candidate windows, {syms} coins{X}")
        cnt = {}
        for c in chosen:
            cnt[c.stratum] = cnt.get(c.stratum, 0) + 1
        for s in STRATA:
            print(f"  {s[0]:5s}/{s[1]:4s} {cnt.get(s, 0)}")
        if short:
            print(f"{Y}stratum shortfalls (filled from other strata): {short}{X}")
        print(f"{C}frozen hash: {h}{X}")
        print(f"{D}Do not rebuild or tweak this set after looking at results.{X}")
    elif cmd == "verify" and len(a) == 2:
        ok = verify(conn, a[1])
        print((G + "hash matches: set and its candles are unchanged" if ok else R + "HASH MISMATCH: data or rounds changed") + X)
    elif cmd == "run" and len(a) == 2:
        print(f"{G}locked {run_opponents(conn, a[1])} new opponent predictions{X}")
    elif cmd == "summary" and len(a) == 2:
        summary(conn, a[1])
    elif cmd in ("runall", "report", "selftest"):
        import lab_stats
        lab_stats.cli(a)
    elif cmd in ("play", "mine"):
        import lab_play
        lab_play.cli(a)
    else:
        print(usage)


if __name__ == "__main__":
    main()
