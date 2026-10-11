import os, sys, json
import carry_spec23 as S

G, R, X = "\033[92m", "\033[91m", "\033[0m"


def verify():
    """Read-only. Uses the freeze module's own hs() so the canonical JSON is identical."""
    for p in (S.HIST_FILE, S.FWD_FILE, S.LOG):
        if not os.path.exists(p):
            return False, "missing file: " + os.path.basename(p)
    h, f = json.load(open(S.HIST_FILE)), json.load(open(S.FWD_FILE))
    if S.hs(h["spec"]) != h["hash"]:
        return False, "historical spec content does not match its stored hash"
    if S.hs(f["spec"]) != f["hash"]:
        return False, "forward spec content does not match its stored hash"
    if f["spec"]["historical_spec_hash"] != h["hash"]:
        return False, "forward spec does not point to the historical spec's hash"
    if f["spec"]["frozen_at_utc"] != h["spec"]["frozen_at_utc"]:
        return False, "the two specs do not share one freeze timestamp"
    if not S.e003_entry():
        return False, "E003 (failed v2.2 calibration) not found in experiments.json"
    return True, "historical %s  forward %s  frozen_at %s" % (h["hash"][:16], f["hash"][:16], h["spec"]["frozen_at_utc"])


if __name__ == "__main__":
    ok, msg = verify()
    print((G + "VERIFIED: " if ok else R + "REFUSED: ") + msg + X)
    sys.exit(0 if ok else 1)
