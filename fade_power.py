import fade_calib2 as fc

G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
DELTAS, WORLDS, SEED, TARGET = (0.0005, 0.001, 0.002), 300, 4, 0.80   # FROZEN


def main():
    mde = None
    for d in DELTAS:
        pw = fc.batch(SEED, WORLDS, fc.B_FULL, delta=d, label=f"+{d * 100:.2f}%")
        print(f"\n{C}== planted +{d * 100:.2f}% on every rung-3 trade, {WORLDS} worlds =={X}")
        for v, nm in enumerate(fc.VARIANTS):
            k = int(pw["one99"][:, v].sum())
            lo, hi = fc.cp(k, WORLDS)
            col = G + "ok   " if k / WORLDS >= TARGET else Y + "WEAK "
            print(f"{col}{nm:26s} detected {k:3d}/{WORLDS} = {k / WORLDS * 100:5.1f}%  95% CI [{lo * 100:.0f}, {hi * 100:.0f}]%{X}")
        k = int(pw["comb"].sum())
        lo, hi = fc.cp(k, WORLDS)
        print(f"{D}combined real pass rule: {k}/{WORLDS} = {k / WORLDS * 100:.1f}%  95% CI [{lo * 100:.0f}, {hi * 100:.0f}]%{X}")
        if mde is None and k / WORLDS >= TARGET:
            mde = d
    print()
    if mde is None:
        print(Y + f"No tested effect reaches {TARGET * 100:.0f}% on the combined rule. A null on real data would mean nothing at these sizes." + X)
    else:
        print(G + f"Minimum detectable effect (combined rule, >= {TARGET * 100:.0f}% power): about +{mde * 100:.2f}% per trade, on synthetic worlds." + X)
    print(f"{D}Informational only. Limits and the bar are not changed by this result.{X}")


if __name__ == "__main__":
    main()
