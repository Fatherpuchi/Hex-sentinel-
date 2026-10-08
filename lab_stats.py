import sys, math, random
import lab_engine as E
from lab_data import connect

G, R, C, Y, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[93m", "\033[2m", "\033[0m"


def opp_composite(view):
    from composite_rating import composite_rating
    cs = [{"high": c[1], "low": c[2], "close": c[3]} for c in view.candles]
    res = composite_rating(cs)
    score, lab = res["score"], res["rating"]
    conf = 70 if lab.startswith("STRONG") else (60 if lab in ("BUY", "SELL") else 50)
    if score > 0:
        return "UP", conf
    if score < 0:
        return "DOWN", conf
    return "UP", 50


def exact_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def load(conn, name):
    ids = [r for (r,) in conn.execute("SELECT round_id FROM rounds WHERE set_name=? ORDER BY ord", (name,))]
    out = {rid: E._outcome(conn, name, rid).direction for rid in ids}
    preds = {}
    for rid, p, d, cf in conn.execute("SELECT round_id,player,direction,confidence FROM predictions WHERE set_name=?", (name,)):
        preds.setdefault(p, {})[rid] = (d, cf)
    return ids, out, preds


def correct_map(ids, out, pr):
    return {r: int(pr[r][0] == out[r]) for r in ids if r in pr and out[r] != "FLAT"}


def report(conn, name):
    ids, out, preds = load(conn, name)
    if "always_up" not in preds:
        print("run the opponents first"); return
    cm = {p: correct_map(ids, out, pr) for p, pr in preds.items()}
    players = sorted(preds)
    print(f"{C}== accuracy, Brier (coin flip = 0.250), vs always_up on the same rounds =={X}")
    base = cm["always_up"]
    for p in players:
        m = cm[p]; n = len(m); k = sum(m.values())
        lo, hi = E.wilson(k, n)
        brier = sum((preds[p][r][1] / 100 - m[r]) ** 2 for r in m) / n
        com = [r for r in m if r in base]
        diff = (sum(m[r] for r in com) - sum(base[r] for r in com)) / len(com) * 100
        print(f"{p:11s} n={n:3d} acc={k/n*100:5.1f}% [{lo*100:3.0f}-{hi*100:3.0f}%] brier={brier:.3f} vs always_up {diff:+5.1f} pts")
    print(f"\n{C}== calibration (accuracy at each stated confidence) =={X}")
    for p in players:
        parts = []
        for lv in E.CONF_LEVELS:
            rs = [r for r in cm[p] if preds[p][r][1] == lv]
            if rs:
                parts.append(f"{lv}%: {sum(cm[p][r] for r in rs)/len(rs)*100:.0f}% (n={len(rs)})")
        print(f"{p:11s} " + "  ".join(parts))
    print(f"\n{C}== paired comparisons (only rounds where both are scored) =={X}")
    for i, a in enumerate(players):
        for b in players[i + 1:]:
            com = [r for r in cm[a] if r in cm[b]]
            if not com:
                continue
            w = sum(1 for r in com if cm[a][r] and not cm[b][r])
            l = sum(1 for r in com if cm[b][r] and not cm[a][r])
            agree = sum(1 for r in com if preds[a][r][0] == preds[b][r][0]) / len(com) * 100
            d = [cm[a][r] - cm[b][r] for r in com]
            rng = random.Random(1)
            bs = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(2000))
            lo, hi = bs[50] * 100, bs[1949] * 100
            p = exact_p(w, l)
            sig = len(com) >= 100 and p < 0.05 and (lo > 0 or hi < 0)
            col = G if sig else Y
            print(f"{col}{a} vs {b}: agree {agree:.0f}%, disagree {w+l} (a right {w}, b right {l}), "
                  f"exact p={p:.3f}, diff {(sum(d)/len(d))*100:+.1f} pts [{lo:+.1f},{hi:+.1f}]  "
                  f"{'DIFFERENT' if sig else 'not distinguishable'}{X}")
    print(f"{D}Several pairs are tested at once: treat a lone p just under 0.05 as weak. "
          f"Nothing here is a reason to change Hex.{X}")


def selftest():
    ok = abs(exact_p(0, 10) - 2 / 1024) < 1e-12 and exact_p(5, 5) == 1.0 and exact_p(0, 0) == 1.0
    print((G + "selftest passed" if ok else R + "selftest FAILED") + X)


def cli(a):
    if a[0] == "selftest":
        return selftest()
    conn = connect()
    if a[0] == "runall" and len(a) == 2:
        E.OPPONENTS["composite"] = opp_composite
        print(f"{G}locked {E.run_opponents(conn, a[1])} new opponent predictions{X}")
    elif a[0] == "report" and len(a) == 2:
        report(conn, a[1])
    else:
        print("usage: lab_stats.py selftest | runall NAME | report NAME")


if __name__ == "__main__":
    cli(sys.argv[1:] or ["help"])
