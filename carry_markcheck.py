import json, sqlite3
from collections import Counter
import carry_screen as S

G, R, Y, C, D, X = S.G, S.R, S.Y, S.C, S.D, S.X
spec = json.load(open(S.HIST_FILE))["spec"]
w = S.load_world(spec["global_cutoff"]["window_end_utc_ms"])
H = w["H"]
r = S.simulate(w, S.params())
kc = sqlite3.connect("file:%s?mode=ro" % S.KDB, uri=True)
rebs = S.rebalance_hours(H)


def cand(tbl, s, h):
    return kc.execute("SELECT o,h,l,c FROM %s WHERE sym=? AND t=?" % tbl, (s, S.T0 + h * S.HOUR)).fetchone()


print(f"{C}base-model liquidation events: {len(r['events'])}   trigger multiple = 2/1.025 = {2 / 1.025:.4f} x month-start perp price{X}")
print(f"{D}{'coin':10s} {'date':10s} {'mk_hi/e':>8s} {'perp_hi/e':>9s} {'spot_hi/e':>9s} {'mk/perp':>8s} {'mk wick':>8s}  class{X}")
cls, bymonth, rows = Counter(), Counter(), []
for s, hv, ps, cash in sorted(r["events"], key=lambda e: e[1]):
    kh = hv - 1
    rb = max(x for x in rebs if x <= kh)
    e = cand("pp", s, rb)
    mk, pp, sp = cand("mk", s, kh), cand("pp", s, kh), cand("sp", s, kh)
    if not (e and mk and pp and sp):
        print(f"{Y}{s:10s} {S.fd(kh)} missing candle for the check{X}")
        cls["UNCHECKED"] += 1
        continue
    e0 = e[0]
    mk_hi, pp_hi, sp_hi = mk[1], pp[1], sp[1]
    wick = mk_hi / max(mk[0], mk[3])
    bad = (mk_hi / pp_hi > 1.10) or (wick > 1.5)
    conf = pp_hi / e0 >= 1.9 and sp_hi / e0 >= 1.9
    k = "BAD-MARK?" if bad else ("CONFIRMED" if conf else "MIXED")
    cls[k] += 1
    bymonth[S.fd(kh)[:7]] += 1
    rows.append((s, kh, k))
    col = R if k == "BAD-MARK?" else (G if k == "CONFIRMED" else Y)
    print(f"{col}{s:10s} {S.fd(kh)} {mk_hi / e0:8.2f} {pp_hi / e0:9.2f} {sp_hi / e0:9.2f} {mk_hi / pp_hi:8.3f} {wick:8.2f}  {k}{X}")
print(f"\n{C}== classification =={X}\n{dict(cls)}")
print(f"{C}== events per month (clustering) =={X}\n{dict(sorted(bymonth.items()))}")
worst = min(((v, s) for s, v in r["ratio"].items()), default=None)
if worst:
    s = worst[1]
    ev = [x for x in rows if x[0] == s]
    print(f"\n{C}== closest approach {worst[0]:.2f} at {s}: hourly context around its event =={X}")
    if ev:
        kh = ev[0][1]
        for h in range(kh - 3, kh + 4):
            m, p, q = cand("mk", s, h), cand("pp", s, h), cand("sp", s, h)
            if m and p and q:
                print(f"{S.fd(h)} h{h - kh:+d}  mark o/h/l/c {m[0]:.4f} {m[1]:.4f} {m[2]:.4f} {m[3]:.4f}   perp hi {p[1]:.4f}   spot hi {q[1]:.4f}")
print(f"\n{D}Read-only. Nothing logged, nothing written. This explains E004; it does not change it.{X}")
