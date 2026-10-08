"""pred_report.py - independent check of Hex's 24h directional predictions.

Reads paper_trade_plans (DIRECTIONAL_PREDICTION rows), keeps the first
prediction per coin per day, fetches the real price 24h later from Binance,
and compares the success rate with what random guessing would have scored.
Usage: python pred_report.py
"""
import os
import sqlite3
import statistics
from math import comb
from datetime import datetime, timedelta, timezone

import rating_report as rr

G, R, Y, C, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"


def load():
    conn = sqlite3.connect(os.getenv("SENTINEL_DB", "sentinel.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM paper_trade_plans "
        "WHERE consensus_status='DIRECTIONAL_PREDICTION' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return rows


def main():
    rows = load()
    seen, uniq = set(), []
    for r in rows:
        key = (r["symbol"], r["created_at"][:10])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    print(f"{C}{'=' * 60}\nHEX 24H PREDICTIONS - INDEPENDENT CHECK\n{'=' * 60}{X}")
    print(f"{len(rows)} rows -> {len(uniq)} unique predictions after removing re-runs")

    now = datetime.now(timezone.utc)
    scored, pending, skipped = [], 0, 0
    for r in uniq:
        t = datetime.fromisoformat(r["created_at"])
        if now - t < timedelta(hours=24):
            pending += 1
            continue
        try:
            p2 = rr._price_at(r["symbol"], t + timedelta(hours=24))
        except Exception:
            p2 = None
        if not p2 or not r["entry_price"]:
            skipped += 1
            continue
        move = (p2 / r["entry_price"] - 1) * 100
        sign = 1 if r["direction"] == "BUY" else -1
        scored.append((r, move, sign))
    print(f"scored {len(scored)} | still within 24h {pending} | no price data {skipped}\n")
    if not scored:
        return

    for r, move, sign in scored:
        ok = sign * move > 0
        print(f"{r['created_at'][5:16]} {r['symbol']:<11} {r['direction']:<4} "
              f"entry {r['entry_price']:<10g} 24h move {move:+6.2f}%  "
              f"{G + 'HIT ' if ok else R + 'MISS'}{X}")

    n = len(scored)
    hits = sum(1 for _, m, s in scored if s * m > 0)
    up = sum(1 for _, m, _ in scored if m > 0) / n
    exp = sum(up if s == 1 else 1 - up for _, _, s in scored) / n
    dr = sorted((s * m for _, m, s in scored), reverse=True)
    mean, med = sum(dr) / n, statistics.median(dr)
    luck = sum(comb(n, k) * exp ** k * (1 - exp) ** (n - k) for k in range(hits, n + 1))

    def col(v):
        return G if v > 0 else R if v < 0 else Y

    print(f"\n{C}SUMMARY{X}")
    print(f"Success rate:        {100 * hits / n:.0f}%  ({hits}/{n})  vs random-guess {100 * exp:.0f}%")
    print(f"Chance of this many hits by luck alone: {100 * luck:.0f}%  (small = more convincing)")
    print(f"Avg directional move {col(mean)}{mean:+.2f}%{X}   median {col(med)}{med:+.2f}%{X}")
    if n >= 8:
        t3 = sum(dr[3:]) / (n - 3)
        t1 = sum(dr[1:]) / (n - 1)
        print(f"Avg without top 1:   {col(t1)}{t1:+.2f}%{X}   without top 3: {col(t3)}{t3:+.2f}%{X}")
        total_pos = sum(x for x in dr if x > 0)
        if total_pos > 0 and dr[0] / total_pos > 0.4:
            print(f"{Y}One prediction is {100 * dr[0] / total_pos:.0f}% of all gains - the average is not representative.{X}")

    print(f"\n{C}BY DIRECTION{X}")
    for d in ("BUY", "SELL"):
        v = [s_ * m for r, m, s_ in scored if r["direction"] == d]
        if not v:
            continue
        h = sum(1 for x in v if x > 0)
        mu, md = sum(v) / len(v), statistics.median(v)
        print(f"{d:<5} n={len(v):<3} hits={h:<3} ({100 * h / len(v):.0f}%)  "
              f"avg {col(mu)}{mu:+.2f}%{X}  median {col(md)}{md:+.2f}%{X}")

    times = sorted(datetime.fromisoformat(r["created_at"]) for r, _, _ in scored)
    clustered = sum(1 for a, b in zip(times, times[1:]) if (b - a) < timedelta(minutes=30))
    if clustered:
        print(f"{Y}{clustered} predictions were made within 30 min of another - treat them as one market snapshot.{X}")
    if n < 30:
        print(f"{Y}Only {n} predictions: too few to say anything about skill (aim for 30+).{X}")

    econ = [r["econ_net_pnl"] for r, _, _ in scored if r["econ_net_pnl"] is not None]
    if econ:
        liq = sum(1 for r, _, _ in scored if r["econ_liquidated"])
        print(f"\nHex's own economics on these: net PnL {sum(econ):+.2f} over {len(econ)} trades, {liq} liquidated")


if __name__ == "__main__":
    main()
