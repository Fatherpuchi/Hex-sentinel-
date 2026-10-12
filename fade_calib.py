import numpy as np
import fade_audit as A
import fade_study as fs

G, R, C, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[2m", "\033[0m"
REPS, B = 120, 1500
BLOCKS = (1, 7, 14, 28)
LEVELS = (95, 99)


def ci(vals, blk, level, rng):
    ud, inv = np.unique(blk, return_inverse=True)
    s, n = np.bincount(inv, weights=vals), np.bincount(inv)
    idx = rng.integers(0, len(ud), (B, len(ud)))
    mm = s[idx].sum(1) / n[idx].sum(1)
    a = (100 - level) / 2
    return float(np.percentile(mm, a)), float(np.percentile(mm, 100 - a))


def main():
    rng = np.random.default_rng(11)
    fp = {(b, l): 0 for b in BLOCKS for l in LEVELS}
    nblocks = {}
    for s in range(REPS):
        evs = A.world(500 + s)
        net = fs.net_of(evs, "fade24", 0.0)
        days = np.array([e["day"] for e in evs])
        for b in BLOCKS:
            blk = (days - days.min()) // b
            nblocks[b] = len(np.unique(blk))
            for l in LEVELS:
                lo, hi = ci(net, blk, l, rng)
                fp[(b, l)] += (lo > 0 or hi < 0)
        if (s + 1) % 20 == 0:
            print(f"{D}{s + 1}/{REPS} worlds done{X}", flush=True)
    print(f"\n{C}false positives in {REPS} no-edge worlds (valid test: ~{REPS * .05:.0f} at 95%, ~{REPS * .01:.1f} at 99%){X}")
    ok_any = False
    for b in BLOCKS:
        a, c = fp[(b, 95)], fp[(b, 99)]
        ok = a <= 9 and c <= 3
        ok_any |= ok
        print(f"{(G + 'ACCEPT ') if ok else (R + 'REJECT ')}block {b:2d} days ({nblocks[b]:3d} blocks)  95%: {a:3d}   99%: {c:3d}{X}")
    print((G + "At least one block length meets the rule." if ok_any else
           R + "No block length meets the rule: the bootstrap bar cannot carry the strategy as designed.") + X)
    print(f"{D}Synthetic worlds have ~46 weeks. Real fade.db has ~150, so real coverage should be somewhat better, not worse.{X}")


if __name__ == "__main__":
    main()
