import sys, json, math, time, os
import numpy as np
import fade_calib2 as fc
from carry_spec import SPEC, spec_hash, SPECFILE

G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
K = SPEC["calibration"]
H = K["H"]
CONFIGS = [(hl, sd) for hl in K["half_lives"] for sd in K["noise_sd"]]


def world(rng, hl, sd_e, delta):
    T, phi, sf = K["T_days"], 0.5 ** (1.0 / hl), K["funding_sd"]
    e = rng.standard_normal(T) * sf * math.sqrt(1 - phi * phi)
    t = np.arange(1, T + 1, dtype=float)
    f = np.power(phi, t) * (rng.standard_normal() * sf + np.cumsum(e * np.power(phi, -t)))
    n = rng.standard_t(4, T) / math.sqrt(2.0) * sd_e
    return H / 365 + delta / 365 + f + n


def lower(r, b, rng, B):
    blk = np.arange(len(r)) // b
    nb = int(blk.max()) + 1
    s, n = np.bincount(blk, weights=r), np.bincount(blk).astype(float)
    W = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=B).astype(float)
    return float(np.quantile((W @ s) / (W @ n), K["lower_q"]) * 365)


def batch(seed, n, B, cfg, delta, blocks, label=""):
    hl, sd = cfg
    t0, hits = time.time(), {b: [] for b in blocks}
    for w in range(n):
        rng = np.random.default_rng([seed, w, hl, int(sd * 1e6), int(delta * 1e4)])
        r = world(rng, hl, sd, delta)
        for b in blocks:
            hits[b].append(lower(r, b, rng, B) > H)
        if (w + 1) % max(1, n // 4) == 0:
            el = time.time() - t0
            print(f"{D}{label} {w + 1}/{n}  {el / 60:.1f} min, ~{el / (w + 1) * (n - w - 1) / 60:.1f} left{X}", flush=True)
    return {b: np.array(v) for b, v in hits.items()}


def decide(ok_block, flags):
    """Frozen rule: any precision flag blocks selection. Otherwise the shortest block that passes."""
    if flags:
        return None, "NEEDS MORE WORLDS"
    sel = next((b for b in K["blocks"] if ok_block[b]), None)
    return sel, ("SELECTED" if sel is not None else "NO BLOCK QUALIFIES")


def selfcheck():
    rng, ac, mu, ok = np.random.default_rng(0), [], [], True
    for _ in range(200):
        r = world(rng, 45, 0.0005, 0.0)
        mu.append(r.mean())
        x = r - r.mean()
        ac.append((x[:-30] * x[30:]).sum() / (x * x).sum())
    m, se = np.mean(mu), np.std(mu, ddof=1) / math.sqrt(200)
    ok &= abs(m - H / 365) < 4 * se + 1e-9
    ok &= 0.1 < np.mean(ac) < 0.6
    ok &= world(rng, 20, 0.0005, 0.04).shape[0] == K["T_days"]
    g1 = decide({14: True, 28: True, 56: True}, [((20, 0.0005), 14, 0.03)])
    g2 = decide({14: False, 28: True, 56: True}, [])
    g3 = decide({14: False, 28: False, 56: False}, [])
    gok = g1 == (None, "NEEDS MORE WORLDS") and g2 == (28, "SELECTED") and g3 == (None, "NO BLOCK QUALIFIES")
    ok &= gok
    print((G + "gate test PASS" if gok else R + "gate test FAIL") + X)
    print((G + "selfcheck PASS" if ok else R + "selfcheck FAIL") + X +
          f"{D}  null mean {m * 365 * 100:.2f}%/yr (target {H * 100:.1f}), mean lag-30 autocorr {np.mean(ac):.2f}{X}")
    return bool(ok)


def main(mode):
    if not os.path.exists(SPECFILE) or json.load(open(SPECFILE))["hash"] != spec_hash():
        raise SystemExit(R + "spec is not frozen or has changed: run python3 carry_spec.py first and do not edit it" + X)
    print(f"{C}spec hash {spec_hash()[:16]}{X}")
    if not selfcheck():
        raise SystemExit(R + "selfcheck failed: stop" + X)
    if mode == "quick":
        t0 = time.time()
        h = batch(1, 20, 2000, CONFIGS[2], 0.0, K["blocks"], "quick")
        print(f"{D}false positives in 20 null worlds by block: { {b: int(v.sum()) for b, v in h.items()} }; "
              f"{(time.time() - t0) / 20:.2f}s per world at B=2000, full B is about 5x slower{X}")
        return
    ok_block = {b: True for b in K["blocks"]}
    flags, rows = [], {}
    print(f"\n{C}== false positives in no-edge worlds (true mean = H) =={X}")
    for cfg in CONFIGS:
        res = {s: batch(s, K["worlds"], K["B"], cfg, 0.0, K["blocks"], f"hl{cfg[0]} sd{cfg[1] * 100:.2f}% seed{s}") for s in K["seeds"]}
        print(f"{C}-- half-life {cfg[0]} days, basis noise sd {cfg[1] * 100:.2f}%/day{X}")
        for b in K["blocks"]:
            cnt = [int(res[s][b].sum()) for s in K["seeds"]]
            pool = sum(cnt)
            lo, hi = fc.cp(pool, K["worlds"] * len(K["seeds"]))
            ok = all(c <= K["limit_per_seed"] for c in cnt) and pool <= K["limit_pooled"]
            ok_block[b] &= ok
            if hi > K["precision_upper_max"]:
                flags.append((cfg, b, hi))
            rows[f"{cfg}-{b}"] = cnt
            print(f"{(G + 'PASS ') if ok else (R + 'FAIL ')}block {b:2d}d  seeds {cnt}  pooled {pool}/{K['worlds'] * 2} = {pool / (K['worlds'] * 2) * 100:.2f}%  "
                  f"95% CI [{lo * 100:.2f}, {hi * 100:.2f}]%  limits <= {K['limit_per_seed']} / {K['limit_pooled']}{X}")
    for cfg, b, hi in flags:
        print(f"{Y}precision rule: upper CI {hi * 100:.2f}% > {K['precision_upper_max'] * 100:.0f}% for {cfg}, block {b}{X}")
    sel, status = decide(ok_block, flags)
    if status == "NEEDS MORE WORLDS":
        print(R + "NEEDS MORE WORLDS: a false-positive interval exceeds the frozen precision limit." + X)
        print(R + "No block selected, no power run, no real data. Revise the spec (new version and hash) before any rerun." + X)
        json.dump({"spec_hash": spec_hash(), "status": status, "false_positive_counts": rows,
                   "flags": [str(x) for x in flags]}, open("carry_calib_result.json", "w"), indent=1)
        return
    print(f"\n{C}== block selection (frozen rule) =={X}")
    for b in K["blocks"]:
        print(f"{(G + 'qualifies ') if ok_block[b] else (R + 'rejected   ')}{b} days{X}")
    out = {"spec_hash": spec_hash(), "status": status, "selected_block": sel, "false_positive_counts": rows}
    if sel is None:
        print(R + "NO BLOCK LENGTH QUALIFIES: stop. Do not test real profitability, do not change the limits." + X)
    else:
        print(G + f"selected block: {sel} days" + X)
        print(f"\n{C}== power with block {sel}, one-sided lower bound > H =={X}")
        worst = 1.0
        for cfg in CONFIGS:
            for d in K["power_deltas"]:
                pw = batch(K["power_seed"], K["power_worlds"], K["B"], cfg, d, [sel], f"power hl{cfg[0]} sd{cfg[1] * 100:.2f}% +{d * 100:.0f}%")[sel]
                k = int(pw.sum())
                lo, hi = fc.cp(k, K["power_worlds"])
                if d == K["power_deltas"][0]:
                    worst = min(worst, k / K["power_worlds"])
                col = G if k / K["power_worlds"] >= K["power_target"] else Y
                print(f"{col}hl {cfg[0]:2d}  noise {cfg[1] * 100:.2f}%  +{d * 100:.0f}%/yr  detected {k:3d}/{K['power_worlds']} = {k / K['power_worlds'] * 100:5.1f}%  95% CI [{lo * 100:.0f}, {hi * 100:.0f}]%{X}")
                out[f"power-{cfg}-{d}"] = k
        r2 = worst >= K["power_target"]
        print((G + "Rung 2 may be run (worst-case power at +1% is >= 80%)." if r2 else
               Y + "Rung 2 is logged INCONCLUSIVE and not run (worst-case power at +1% is below 80%; frozen rule).") + X)
        out["rung2_run"] = bool(r2)
    json.dump(out, open("carry_calib_result.json", "w"), indent=1)
    print(f"{D}saved carry_calib_result.json. Passing says only that this bootstrap behaves under these synthetic assumptions; "
          f"accounting and liquidation need their own self-checks in the real script.{X}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "quick")
