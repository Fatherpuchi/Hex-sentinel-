import os, json, copy, hashlib
from carry_spec import SPEC as OLD, spec_hash as old_hash

HERE = os.path.dirname(os.path.abspath(__file__))
SPECFILE = os.path.join(HERE, "carry_spec_v2_2.json")
V21_HASH = "4f857ebdd3873c27c8c58ca24c0326b9ede5080faac009f731915f4f11fda237"

if old_hash() != V21_HASH:
    raise SystemExit("v2.1 spec has changed since it was frozen. Stop: the record must stay intact.")

SPEC = copy.deepcopy(OLD)
SPEC["version"] = "carry-v2.2"
SPEC["supersedes"] = {
    "version": "carry-v2.1", "hash": V21_HASH,
    "status": "superseded before any calibration result or real return was seen; v2.1 calibration never completed and is not claimed as passed",
    "reason": "The v2.1 synthetic funding component (sd 0.0001/day) was too small relative to basis noise to meaningfully stress "
              "persistent regimes (persistent share of variance about 4% and about 0.2%). The self-check exposed it. "
              "Calibration parameters were revised before any real funding rates or strategy returns were examined."}
SPEC["calibration"] = {
    "T_days": 1740, "H": 0.04, "blocks": [14, 28, 56], "seeds": [1, 2], "B": 10000, "lower_q": 0.005,
    "funding_sd": 0.0005, "funding_sd_meaning": "stationary sd of the AR(1) persistent funding component, per day",
    "half_lives": [20, 45, 90], "noise_sd": [0.0005, 0.0015], "noise": "Student t(4) scaled to unit variance times noise_sd",
    "stages": [{"worlds": 986, "per_seed": 11, "pooled": 18},
               {"worlds": 1972, "per_seed": 22, "pooled": 36},
               {"worlds": 3944, "per_seed": 44, "pooled": 72}],
    "limits_rule": "stage-1 limits are the v2.1 limits; later stages keep the same rates (11/986 per seed, 18/1972 pooled), rounded down",
    "precision_upper_max": 0.02,
    "precision_rule": "for a world type, if any block that passes the count limits has a pooled 95% Clopper-Pearson upper bound above 2%, "
                      "that world type moves to the next stage (more worlds, same seeds, earlier worlds reused). If still flagged at the last stage, "
                      "status is NEEDS MORE WORLDS: no block selected, no power run, no real data. Blocks failing the count limits are rejected and need no precision.",
    "min_persistent_share": 0.05,
    "uninformative_rule": "a world type whose persistent variance share is below min_persistent_share stops the calibration (UNINFORMATIVE); it is never silently dropped",
    "selfcheck": {"worlds": 300, "acf_lag": 30, "acf_abs_tol": 0.03, "var_rel_tol": 0.10,
                  "theory": "share = sf^2/(sf^2+se^2); combined lag-k autocorrelation = share * 2^(-k/half_life); stationary funding variance = sf^2"},
    "power_deltas": [0.01, 0.02, 0.04], "power_worlds": 300, "power_seed": 4, "power_target": 0.80,
    "selection": "shortest block that passes every world type; if none passes, stop and do not test real profitability",
    "rung2_rule": "Rung 2 is run only if worst-case power at +1% per year is >= 80%; otherwise logged INCONCLUSIVE and not run",
    "assumption_status": "all synthetic parameters are provisional stress assumptions, not estimates of real crypto behaviour; "
                         "the real run must report its realised daily sd and persistence",
    "does_not_cover": "accounting, liquidation logic, costs, delistings; the real script needs its own self-checks"}


def spec_hash():
    return hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":
    h = spec_hash()
    if os.path.exists(SPECFILE):
        old = json.load(open(SPECFILE))["hash"]
        print(("\033[92mspec unchanged: " if old == h else "\033[91mSPEC CHANGED since it was frozen: ") + h + "\033[0m")
    else:
        json.dump({"hash": h, "spec": SPEC}, open(SPECFILE, "w"), indent=1)
        print("\033[96mfrozen carry-v2.2, sha256 " + h + "\033[0m")
