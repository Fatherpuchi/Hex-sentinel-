import sys, json, math, time, os
import numpy as np
import fade_calib2 as fc
from carry_spec22 import SPEC, spec_hash, SPECFILE

G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
K = SPEC["calibration"]
H, SF, T = K["H"], K["funding_sd"], K["T_days"]
BLOCKS, SEEDS, STAGES, PREC = K["blocks"], K["seeds"], K["stages"], K["precision_upper_max"]
CONFIGS = [(hl, sd) for hl in K["half_lives"] for sd in K["noise_sd"]]


def share(sd_e): return SF ** 2 / (SF ** 2 + sd_e ** 2)
def acf_theory(hl, sd_e, k): return share(sd_e) * 0.5 ** (k / hl)


def funding(rng, hl):
    phi = 0.5 ** (1.0 / hl)
    e = rng.standard_normal(T) * SF * math.sqrt(1 - phi * phi)
    t = np.arange(1, T + 1, dtype=float)
    return np.power(phi, t) * (rng.standard_normal() * SF + np.cumsum(e * np.power(phi, -t)))


def noise(rng, sd_e):
    return rng.standard_t(4, T) / math.sqrt(2.0) * sd_e


def world(rng, hl, sd_e, delta):
    return H / 365 + delta / 365 + funding(rng, hl) + noise(rng, sd_e)


def lower(r, b, rng, B):
    blk = np.arange(len(r)) // b
    nb = int(blk.max()) + 1
    s, n = np.bincount(blk, weights=r), np.bincount(blk).astype(float)
    W = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=B).astype(float)
    return float(np.quantile((W @ s) / (W @ n), K["lower_q"]) * 365)


def batch(seed, start, end, B, cfg, delta, blocks, label=""):
    hl, sd = cfg
    t0, hits, total = time.time(), {b: [] for b in blocks}, end - start
    for k, w in enumerate(range(start, end)):
        rng = np.random.default_rng([seed, w, hl, round(sd * 1e6), round(delta * 1e4)])
        r = world(rng, hl, sd, delta)
        for b in blocks:
            hits[b].append(bool(lower(r, b, rng, B) > H))
        if (k + 1) % max(1, total // 4) == 0:
            el = time.time() - t0
            print(f"{D}{label} {k + 1}/{total}  {el / 60:.1f} min, ~{el / (k + 1) * (total - k - 1) / 60:.1f} left{X}", flush=True)
    return hits


def judge(counts, stage, prec=None):
    """counts: false positives per seed at this stage. Returns (passes, flagged, ci_lo, ci_hi)."""
    prec = PREC if prec is None else prec
    st = STAGES[stage]
    pooled = sum(counts)
    passes = all(c <= st["per_seed"] for c in counts) and pooled <= st["pooled"]
    lo, hi = fc.cp(pooled, st["worlds"] * len(counts))
    return passes, bool(passes and hi > prec), lo, hi


def decide(block_pass, unresolved):
    if unresolved:
        return None, "NEEDS MORE WORLDS"
    sel = next((b for b in BLOCKS if block_pass[b]), None)
    return sel, ("SELECTED" if sel is not None else "NO BLOCK QUALIFIES")


def run_cfg(cfg, prec=None, label=""):
    """Runs stages for one world type. Returns (verdict per block, final stage index, unresolved)."""
    store = {s: {b: [] for b in BLOCKS} for s in SEEDS}
    for si, st in enumerate(STAGES):
        n = st["worlds"]
        for s in SEEDS:
            have = len(store[s][BLOCKS[0]])
            if have < n:
                part = batch(s, have, n, K["B"], cfg, 0.0, BLOCKS, f"{label} seed{s} stage{si + 1}")
                for b in BLOCKS:
                    store[s][b].extend(part[b])
        verdict, flagged = {}, False
        for b in BLOCKS:
            counts = [int(sum(store[s][b][:n])) for s in SEEDS]
            passes, flag, lo, hi = judge(counts, si, prec)
            verdict[b] = dict(counts=counts, passes=passes, flag=flag, lo=lo, hi=hi, n=n)
            flagged |= flag
        if not flagged:
            return verdict, si, False
        print(f"{Y}{label}: precision flag at stage {si + 1} ({n} worlds per seed)" +
              (", expanding" if si < len(STAGES) - 1 else ", no stage left") + X)
    return verdict, len(STAGES) - 1, True


def selfcheck():
    S = K["selfcheck"]
    ok, lag, N = True, S["acf_lag"], S["worlds"]
    print(f"{C}-- model check: theory against simulation, every world type{X}")
    for hl, sd in CONFIGS:
        sh = share(sd)
        rng = np.random.default_rng([77, hl, round(sd * 1e6)])
        num = den = 0.0
        fv, mu = [], []
        for _ in range(N):
            f = funding(rng, hl)
            r = H / 365 + f + noise(rng, sd)
            x = r - H / 365
            num += float((x[:-lag] * x[lag:]).sum())
            den += float((x * x).sum())
            fv.append(float((f * f).mean()))
            mu.append(float(r.mean()))
        acf_s = (num / (N * (T - lag))) / (den / (N * T))
        acf_t = acf_theory(hl, sd, lag)
        var_ratio = (den / (N * T)) / (SF ** 2 + sd ** 2)
        f_ratio = float(np.mean(fv)) / SF ** 2
        mu_z = (np.mean(mu) - H / 365) / (np.std(mu, ddof=1) / math.sqrt(N))
        checks = [("persistent share >= %.0f%%" % (K["min_persistent_share"] * 100), sh >= K["min_persistent_share"]),
                  ("lag-%d autocorrelation within %.2f of theory" % (lag, S["acf_abs_tol"]), abs(acf_s - acf_t) <= S["acf_abs_tol"]),
                  ("total variance within %.0f%% of theory" % (S["var_rel_tol"] * 100), abs(var_ratio - 1) <= S["var_rel_tol"]),
                  ("funding stationary variance within %.0f%%" % (S["var_rel_tol"] * 100), abs(f_ratio - 1) <= S["var_rel_tol"]),
                  ("null mean equals H/365 (|z|<4)", abs(mu_z) < 4)]
        good = all(c for _, c in checks)
        ok &= good
        print(f"{(G + 'PASS ') if good else (R + 'FAIL ')}half-life {hl:2d}d noise {sd * 100:.2f}%: share {sh * 100:4.1f}%  "
              f"acf30 sim {acf_s:.3f} vs theory {acf_t:.3f}  var ratio {var_ratio:.3f}  funding var ratio {f_ratio:.3f}  mean z {mu_z:+.2f}{X}")
        for name, c in checks:
            if not c:
                print(f"{R}     failed: {name}" + (" (UNINFORMATIVE world type: calibration must stop, not drop it)" if name.startswith("persistent") else "") + X)
    print(f"{C}-- gate and control-flow tests (fake inputs){X}")
    t = [judge([3, 4], 0)[:2] == (True, False),
         judge([12, 3], 0)[0] is False,
         judge([11, 7], 0)[0] is True,
         judge([11, 8], 0)[0] is False,
         judge([22, 14], 1)[0] is True,
         judge([22, 15], 1)[0] is False,
         judge([3, 4], 0, prec=0.001)[:2] == (True, True),
         judge([12, 3], 0, prec=0.001)[:2] == (False, False),
         decide({14: False, 28: True, 56: True}, False) == (28, "SELECTED"),
         decide({14: True, 28: True, 56: True}, True) == (None, "NEEDS MORE WORLDS"),
         decide({14: False, 28: False, 56: False}, False) == (None, "NO BLOCK QUALIFIES")]
    g = globals()
    orig = g["batch"]
    g["batch"] = lambda seed, start, end, B, cfg, delta, blocks, label="": {b: [False] * (end - start) for b in blocks}
    try:
        quiet = sys.stdout
        sys.stdout = open(os.devnull, "w")
        v2 = run_cfg(CONFIGS[0], prec=0.001)
        v3 = run_cfg(CONFIGS[0], prec=0.0001)
        v1 = run_cfg(CONFIGS[0], prec=0.5)
        v4 = run_cfg(CONFIGS[0], prec=0.0007)
    finally:
        sys.stdout = quiet
        g["batch"] = orig
    t += [v1[1:] == (0, False), v2[1:] == (1, False), v3[1:] == (2, True), v4[1:] == (2, False)]
    gate_ok = all(t)
    ok &= gate_ok
    print((G + "gate test PASS" if gate_ok else R + f"gate test FAIL {t}") + X +
          f"{D}  ({sum(t)}/{len(t)}: count limits per stage, flag logic, expansion to later stages, unresolved at the last stage){X}")
    print((G + "selfcheck PASS" if ok else R + "selfcheck FAIL") + X)
    return bool(ok)


def main(mode):
    if not os.path.exists(SPECFILE) or json.load(open(SPECFILE))["hash"] != spec_hash():
        raise SystemExit(R + "v2.2 spec is not frozen or has changed: run python3 carry_spec22.py and do not edit it" + X)
    print(f"{C}spec carry-v2.2 hash {spec_hash()[:16]}{X}")
    if not selfcheck():
        raise SystemExit(R + "selfcheck failed: stop. Do not loosen tolerances; report the numbers." + X)
    if mode == "quick":
        t0 = time.time()
        h = batch(1, 0, 20, 2000, CONFIGS[2], 0.0, BLOCKS, "quick")
        per = (time.time() - t0) / 20
        full = per * 5
        null_min = full * len(CONFIGS) * len(SEEDS) * STAGES[0]["worlds"] / 60
        pow_min = full / 3 * len(CONFIGS) * len(K["power_deltas"]) * K["power_worlds"] / 60
        print(f"{D}false positives in 20 null worlds by block: { {b: int(sum(v)) for b, v in h.items()} }{X}")
        print(f"{D}{per:.2f}s per world at B=2000. Estimate for full at B=10000: null stage 1 about {null_min:.0f} min, power about {pow_min:.0f} min "
              f"(each expansion stage adds more){X}")
        return
    verdicts, unresolved, flags_left, rows = {}, False, [], {}
    print(f"\n{C}== false positives in no-edge worlds (true mean = H) =={X}")
    for cfg in CONFIGS:
        v, si, un = run_cfg(cfg, label=f"hl{cfg[0]} sd{cfg[1] * 100:.2f}%")
        verdicts[cfg] = v
        unresolved |= un
        print(f"{C}-- half-life {cfg[0]} days, noise sd {cfg[1] * 100:.2f}%/day, persistent share {share(cfg[1]) * 100:.1f}%, resolved at stage {si + 1} ({STAGES[si]['worlds']} worlds per seed){X}")
        st = STAGES[si]
        for b in BLOCKS:
            x = v[b]
            rows[f"{cfg}-{b}"] = x["counts"]
            tag = (Y + "FLAG ") if x["flag"] else ((G + "PASS ") if x["passes"] else (R + "FAIL "))
            print(f"{tag}block {b:2d}d  seeds {x['counts']}  pooled {sum(x['counts'])}/{st['worlds'] * 2} = {sum(x['counts']) / (st['worlds'] * 2) * 100:.2f}%  "
                  f"95% CI [{x['lo'] * 100:.2f}, {x['hi'] * 100:.2f}]%  limits <= {st['per_seed']} / {st['pooled']}{X}")
    block_pass = {b: all(verdicts[c][b]["passes"] for c in CONFIGS) for b in BLOCKS}
    sel, status = decide(block_pass, unresolved)
    out = {"spec_hash": spec_hash(), "status": status, "selected_block": sel, "false_positive_counts": rows}
    print(f"\n{C}== block selection (frozen rule) =={X}")
    if status == "NEEDS MORE WORLDS":
        print(R + "NEEDS MORE WORLDS: precision not reached at the last stage. No block selected, no power run, no real data." + X)
        json.dump(out, open("carry_calib22_result.json", "w"), indent=1)
        return
    for b in BLOCKS:
        print(f"{(G + 'qualifies ') if block_pass[b] else (R + 'rejected   ')}{b} days{X}")
    if sel is None:
        print(R + "NO BLOCK LENGTH QUALIFIES: stop. Do not test real profitability, do not change the limits." + X)
        json.dump(out, open("carry_calib22_result.json", "w"), indent=1)
        return
    print(G + f"selected block: {sel} days" + X)
    print(f"\n{C}== power with block {sel}, one-sided lower bound > H =={X}")
    worst = 1.0
    for cfg in CONFIGS:
        for d in K["power_deltas"]:
            h = batch(K["power_seed"], 0, K["power_worlds"], K["B"], cfg, d, [sel], f"power hl{cfg[0]} sd{cfg[1] * 100:.2f}% +{d * 100:.0f}%")[sel]
            k = int(sum(h))
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
    json.dump(out, open("carry_calib22_result.json", "w"), indent=1)
    print(f"{D}saved carry_calib22_result.json. Passing says only that this bootstrap behaves under these synthetic assumptions; "
          f"accounting and liquidation need their own self-checks in the real script.{X}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "quick")
