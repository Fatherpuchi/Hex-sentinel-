import sys, json
import fade_calib2 as fc

G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"

# ---------------- FROZEN spec v3 ----------------
fc.QLO = 0.0025                       # 99.5% two-sided (1% family budget / 2 tests)
PRIMARY = 1                           # variant index: market-adjusted
SEEDS, WORLDS = (1, 2), 986
LIM_ONE = (7, 11)                     # (per seed, pooled)
LIM_TWO99 = (11, 18)
LIM_TWO95 = 65
POWER_DELTAS, POWER_WORLDS, POWER_SEED, TARGET = (0.0005, 0.001, 0.002, 0.003), 300, 4, 0.80
# ------------------------------------------------


def main(mode):
    if not fc.selfcheck():
        raise SystemExit(R + "selfcheck failed: stop" + X)
    if mode == "quick":
        r = fc.batch(1, 20, 2000, label="quick")
        print(f"{D}false positives in 20 worlds, one-sided, per variant: {r['one99'].sum(0).tolist()}{X}")
        return
    runs = {s: fc.batch(s, WORLDS, fc.B_FULL, label=f"seed {s}") for s in SEEDS}
    ok = True
    print(f"\n{C}== PRIMARY GATE: {fc.VARIANTS[PRIMARY]}, rung 3 minus rung 2, no-edge worlds =={X}")
    o = [int(runs[s]["one99"][:, PRIMARY].sum()) for s in SEEDS]
    t = [int(runs[s]["two99"][:, PRIMARY].sum()) for s in SEEDS]
    f = [int(runs[s]["two95"][:, PRIMARY].sum()) for s in SEEDS]
    for j, s in enumerate(SEEDS):
        ok &= fc.line(f"seed {s} one-sided lower>0", o[j], WORLDS, 0.0025, LIM_ONE[0])
    ok &= fc.line("pooled one-sided lower>0", sum(o), 2 * WORLDS, 0.0025, LIM_ONE[1])
    for j, s in enumerate(SEEDS):
        ok &= fc.line(f"seed {s} two-sided 99.5%", t[j], WORLDS, 0.005, LIM_TWO99[0])
    ok &= fc.line("pooled two-sided 99.5%", sum(t), 2 * WORLDS, 0.005, LIM_TWO99[1])
    for j, s in enumerate(SEEDS):
        ok &= fc.line(f"seed {s} two-sided 95%", f[j], WORLDS, 0.05, LIM_TWO95)
    print(f"\n{C}== reported only (not gating): one-sided false positives per variant =={X}")
    for v, nm in enumerate(fc.VARIANTS):
        k = sum(int(runs[s]["one99"][:, v].sum()) for s in SEEDS)
        lo, hi = fc.cp(k, 2 * WORLDS)
        print(f"{D}{nm:26s} {k:3d}/{2 * WORLDS}  {k / (2 * WORLDS) * 100:.2f}%  95% CI [{lo * 100:.2f}, {hi * 100:.2f}]%{X}")
    print(f"{D}mean trades per world: rung 2 = {sum(runs[s]['n2'].mean() for s in SEEDS) / 2:.0f}, "
          f"rung 3 = {sum(runs[s]['n3'].mean() for s in SEEDS) / 2:.0f}{X}")
    mde, power = None, {}
    for d in POWER_DELTAS:
        pw = fc.batch(POWER_SEED, POWER_WORLDS, fc.B_FULL, delta=d, label=f"power +{d * 100:.2f}%")
        print(f"\n{C}== power: +{d * 100:.2f}% on every rung-3 trade, {POWER_WORLDS} worlds =={X}")
        for v, nm in enumerate(fc.VARIANTS):
            k = int(pw["one99"][:, v].sum())
            lo, hi = fc.cp(k, POWER_WORLDS)
            tag = (G + "ok   " if k / POWER_WORLDS >= TARGET else Y + "WEAK ") if v == PRIMARY else D + "     "
            print(f"{tag}{nm:26s} {k:3d}/{POWER_WORLDS} = {k / POWER_WORLDS * 100:5.1f}%  95% CI [{lo * 100:.0f}, {hi * 100:.0f}]%{X}")
        power[d] = int(pw["one99"][:, PRIMARY].sum())
        if mde is None and power[d] / POWER_WORLDS >= TARGET:
            mde = d
    print()
    print((G + "CALIBRATION PASSED: v3 primary gate may be used." if ok else
           R + "CALIBRATION FAILED: stop. Do not change limits, blocks or statistic; investigate the method.") + X)
    print((G + f"Minimum detectable effect (>= {TARGET * 100:.0f}% power, primary gate): about +{mde * 100:.2f}% per trade, synthetic worlds."
           if mde else Y + "No tested effect reaches 80% power: a null on real data would be inconclusive at all these sizes.") + X)
    json.dump({"spec": "v3", "passed": bool(ok), "one_sided": o, "two99": t, "two95": f,
               "power_hits": {str(k): v for k, v in power.items()}, "mde": mde}, open("calib3_result.json", "w"))
    print(f"{D}saved calib3_result.json{X}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "quick")
