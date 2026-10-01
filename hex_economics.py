import json, os, sqlite3, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone

LEVERAGE = 5
MARGIN_USDT = 100.0
TAKER_FEE = 0.0005
MMR = 0.004
FAPI = "https://fapi.binance.com"
LONG = {"LONG", "BUY", "BULLISH", "UP"}
SHORT = {"SHORT", "SELL", "BEARISH", "DOWN"}
NEW_COLS = {
    "econ_leverage": "REAL", "econ_margin": "REAL", "econ_qty": "REAL",
    "econ_fees": "REAL", "econ_funding": "REAL", "econ_net_pnl": "REAL",
    "econ_roi_pct": "REAL", "econ_liquidated": "INTEGER",
    "econ_liq_price": "REAL", "econ_stop_beyond_liq": "INTEGER",
    "econ_note": "TEXT",
}


def default_db():
    return os.environ.get("SENTINEL_DB") or "sentinel.db"


def http_json(path, params):
    url = FAPI + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "hex-econ/0.1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def to_ms(s):
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def side_of(direction):
    d = str(direction).upper().strip()
    if d in LONG:
        return 1
    if d in SHORT:
        return -1
    return None


def liq_price(side, entry, qty, margin):
    return (margin - side * qty * entry) / (qty * (MMR - side))


def funding_paid(symbol, start_ms, end_ms, side, qty, entry):
    rows = http_json("/fapi/v1/fundingRate", {
        "symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": 1000})
    total = 0.0
    for r in rows:
        mark = float(r.get("markPrice") or entry)
        total += side * qty * mark * float(r["fundingRate"])
    return total


def touched_liq(symbol, side, liq, start_ms, end_ms):
    if end_ms - start_ms > 1500 * 300000:
        return None
    rows = http_json("/fapi/v1/markPriceKlines", {
        "symbol": symbol, "interval": "5m",
        "startTime": start_ms, "endTime": end_ms, "limit": 1500})
    if not rows:
        return None
    if side == 1:
        return min(float(k[3]) for k in rows) <= liq
    return max(float(k[2]) for k in rows) >= liq


def compute(row):
    s = side_of(row["direction"])
    try:
        entry = float(row["entry_price"])
        exit_p = float(row["exit_price"])
        start_ms, end_ms = to_ms(row["created_at"]), to_ms(row["resolved_at"])
    except Exception as e:
        return {"econ_note": f"skipped: bad data ({e})"}
    if s is None or entry <= 0:
        return {"econ_note": f"skipped: unknown direction {row['direction']!r}"}

    qty = MARGIN_USDT * LEVERAGE / entry
    gross = s * qty * (exit_p - entry)
    entry_fee = qty * entry * TAKER_FEE
    exit_fee = qty * exit_p * TAKER_FEE
    liq = liq_price(s, entry, qty, MARGIN_USDT)

    stop_beyond = None
    if row["stop_loss"] is not None:
        stop = float(row["stop_loss"])
        stop_beyond = int(stop <= liq) if s == 1 else int(stop >= liq)

    notes = []
    try:
        liquidated = touched_liq(row["symbol"], s, liq, start_ms, end_ms)
    except Exception as e:
        liquidated = None
    if liquidated is None:
        notes.append("liq_check_unavailable")

    funding = None
    if not liquidated:
        try:
            funding = funding_paid(row["symbol"], start_ms, end_ms, s, qty, entry)
        except Exception:
            notes.append("funding_unavailable")

    if liquidated:
        net, fees = -MARGIN_USDT, entry_fee
    else:
        fees = entry_fee + exit_fee
        net = gross - fees - (funding or 0.0)
        if net < -MARGIN_USDT:
            net = -MARGIN_USDT
            notes.append("capped_at_margin")

    return {
        "econ_leverage": LEVERAGE, "econ_margin": MARGIN_USDT, "econ_qty": qty,
        "econ_fees": fees, "econ_funding": funding, "econ_net_pnl": net,
        "econ_roi_pct": net / MARGIN_USDT * 100,
        "econ_liquidated": None if liquidated is None else int(liquidated),
        "econ_liq_price": liq, "econ_stop_beyond_liq": stop_beyond,
        "econ_note": ",".join(notes) or "ok",
    }


def apply(db_path=None, write=True, limit=200):
    conn = sqlite3.connect(db_path or default_db())
    conn.row_factory = sqlite3.Row
    out = []
    try:
        cols = {r[1] for r in conn.execute("pragma table_info(paper_trade_plans)")}
        if not cols:
            return out
        if write:
            for name, typ in NEW_COLS.items():
                if name not in cols:
                    conn.execute(f"ALTER TABLE paper_trade_plans ADD COLUMN {name} {typ}")
            conn.commit()
            cols |= set(NEW_COLS)
        where = "exit_price IS NOT NULL AND resolved_at IS NOT NULL"
        if "econ_net_pnl" in cols:
            where += (" AND econ_net_pnl IS NULL AND "
                      "(econ_note IS NULL OR econ_note NOT LIKE 'skipped:%')")
        rows = conn.execute(
            "SELECT id, symbol, direction, entry_price, stop_loss, exit_price, "
            f"created_at, resolved_at FROM paper_trade_plans WHERE {where} "
            f"ORDER BY id LIMIT {int(limit)}").fetchall()
        for row in rows:
            res = compute(row)
            out.append((row, res))
            if write:
                sets = ", ".join(f"{k} = :{k}" for k in res)
                conn.execute(f"UPDATE paper_trade_plans SET {sets} WHERE id = :id",
                             dict(res, id=row["id"]))
                conn.commit()
            time.sleep(0.2)
    finally:
        conn.close()
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    results = apply(args[0] if args else None, write=write)
    total = 0.0
    for row, r in results:
        net = r.get("econ_net_pnl")
        total += net or 0.0
        print(f"#{row['id']} {row['symbol']} {row['direction']} "
              f"entry={row['entry_price']} exit={row['exit_price']} "
              f"net={net if net is None else round(net, 2)} "
              f"liq={r.get('econ_liq_price') and round(r['econ_liq_price'], 6)} "
              f"liquidated={r.get('econ_liquidated')} "
              f"stop_beyond_liq={r.get('econ_stop_beyond_liq')} "
              f"note={r.get('econ_note')}")
    print(f"\n{len(results)} trades | total net {total:+.2f} USDT | "
          f"mode={'WRITE' if write else 'DRY RUN (nothing saved)'}")
