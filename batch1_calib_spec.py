import os, sys, json, hashlib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BATCH = os.path.join(HERE, "batch1_spec_v1.json")
FILE = os.path.join(HERE, "batch1_calib_spec_v1.json")
PH = "SET AT FREEZE"


def hs(d): return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def spec(batch_hash, frozen_at):
    return {
        "version": "batch1-calibration-v1", "frozen_at_utc": frozen_at, "batch1_spec_hash": batch_hash,
        "wording": "This is a synthetic-world calibration only. It does not prove that any real strategy works. It checks the false-positive rate and power of the frozen test procedure. No strategy is approved by it; it only licenses or blocks inference.",
        "replaces": "an informal text draft that used accuracy-style limits (FPR <= 0.05) and a 2%-per-day effect size; neither matched the frozen money statistic",
        "tested_quantity": "for each of the four hypotheses (ema50_200, breakout20, weekly_mom_b1, meanrev_short_b1): mean daily active return, defined in batch1 spec as strategy net return minus E_t x benchmark return, over the evaluable days",
        "procedure_under_test": "the exact real-run procedure: build daily bars, run the strategy engine with its warm-up and turnover, compute the daily active-return series, resample blocks of days, take the one-sided lower bound at 1 - alpha_individual",
        "alpha": {"alpha_individual": 0.005, "one_sided": True, "lower_quantile": 0.005,
                  "note": "false positive = lower bound above 0 in a world with no skill"},
        "synthetic_world": {
            "panel": "N coins (as in the frozen universe) by T days (the real evaluable window length), starting on the real first dates and with the real missing-day pattern (invalid coin-days are invalid in the worlds too)",
            "returns": "daily log return of coin i = beta_i x F_t + e_it; F_t = common factor with stochastic volatility; e_it with coin-specific stochastic volatility; innovations Student t(4) scaled to unit variance; zero predictability by construction (no autocorrelation, no cross-sectional or time-series signal)",
            "betas": "uniform 0.6 to 1.4",
            "volatility": "log volatility follows AR(1) with the half-life of the world type; common factor sd 2.0%/day times exp(log vol); coin sd 2.5%/day times exp(coin log vol); log-vol innovation sd 0.25 (common) and 0.30 (coin)",
            "drift": "zero in the base null; one added world type carries drift so that buy-and-hold earns about +60% a year, to show the exposure-matched benchmark removes it",
            "world_types": [{"id": "A", "vol_half_life_days": 20, "drift": 0.0},
                            {"id": "B", "vol_half_life_days": 60, "drift": 0.0},
                            {"id": "C", "vol_half_life_days": 20, "drift_annual_for_bh": 0.6},
                            {"id": "D", "vol_half_life_days": 60, "drift_annual_for_bh": 0.6}],
            "limit_of_the_generator": "volatility persists but returns have no persistent mean regimes; real markets have multi-month trends that give trend rules a real edge or a real drag. This calibration tests the bootstrap's error rate, not realism.",
            "model_selfcheck": "before any calibration, for every world type: simulated daily-return autocorrelation at lags 1 and 30 within 0.03 of zero; simulated volatility persistence (autocorrelation of absolute returns at lag 30) within 0.05 of its theoretical value computed from the AR(1) parameters; mean of F_t within 4 standard errors of its target; a planted +0.05% daily active return recovered within 10% by the engine. Any failure stops everything and nothing is loosened."
        },
        "gross_null": {"rule": "the null worlds are evaluated gross of costs: the statistic is the mean daily active return before transaction costs",
                       "reason": "costs are a deterministic drag known in advance; including them would make the null mean negative and hide false positives. The real run reports and tests net returns.",
                       "consequence": "calibration says nothing about whether costs destroy an edge; the real run's cost handling needs its own engine self-checks"},
        "seeds": [1, 2],
        "worlds_per_seed_stage1": 986,
        "bootstrap_resamples": 10000,
        "blocks_days": [7, 14, 28],
        "stages": [
            {"worlds_per_seed": 986, "limit_per_seed": 11, "limit_pooled": 18},
            {"worlds_per_seed": 1972, "limit_per_seed": 22, "limit_pooled": 36},
            {"worlds_per_seed": 3944, "limit_per_seed": 44, "limit_pooled": 72}
        ],
        "limits_rule": "limits keep the stage-1 rates (11 of 986 per seed, 18 of 1,972 pooled), rounded down; chosen so a correct test at nominal 0.5% is wrongly rejected about 1% of the time",
        "judged_cells": "each hypothesis x world type x block length is one cell; a block length qualifies only if every cell passes both the per-seed and pooled limits",
        "precision_rule": {"upper_max": 0.02, "text": "if a cell that passes the count limits has a pooled 95% Clopper-Pearson upper bound above 2%, that world type expands to the next stage with the same seeds, earlier worlds reused; if still flagged at the last stage the status is NEEDS MORE WORLDS: no block selected, no power run, nothing real read"},
        "selection": "the shortest block length that qualifies in every cell; if none qualifies the status is NO BLOCK QUALIFIES and the real batch is descriptive and forward-only",
        "power": {"planted_daily_active_return": [0.0003, 0.0006, 0.0012], "approx_annual": ["about 11%", "about 22%", "about 44%"],
                  "how": "add the planted amount to every evaluable day of the strategy's active return in a type-A and type-B world; use seed 1 for the planted-world sweep",
                  "target": "80% detection of the one-sided lower bound above 0, per hypothesis",
                  "report": "the smallest planted effect reaching 80% is that hypothesis's minimum detectable effect; the real run states it next to the result",
                  "if_none_reaches_80": "that hypothesis is descriptive only, even if the bootstrap is calibrated"},
        "effects_on_inference": {"calibration_passes_and_power_ok": "inference allowed for hypotheses with MDE reported",
                                 "calibration_passes_but_power_fails": "inference allowed in form only; a null means 'no effect larger than MDE'",
                                 "calibration_fails": "descriptive and forward-only; wording: 'The calibration did not license inference.'"},
        "stop_rules": "a failed model self-check, NO BLOCK QUALIFIES or NEEDS MORE WORLDS stops the batch; limits, block lengths, world types and parameters are never changed afterwards; a changed design is a new version with a new hash",
        "isolation": "the calibration code reads no database and no real return, and writes only a result file",
        "outputs": ["batch1_calib_result.json (counts per cell, selection, MDE per hypothesis, status)"],
        "order": ["freeze batch1 spec", "freeze this addendum", "write the engine and calibration code with its own synthetic self-checks", "review", "run once", "register hypotheses in the harness", "one real run"],
        "not_decided": ["whether the batch-wide alpha 0.0025 replaces per-family 0.005 (this addendum uses 0.005 and must be redone if it changes)",
                        "runtime: the calibration runs the real strategies on 40 x ~1000-day panels for about 986 x 2 x 4 world types; the code must report timing from a quick mode before a full run"]
    }


def main(mode):
    if os.path.exists(FILE):
        st = json.load(open(FILE))
        s = st["spec"]
        ok = hs(spec(s["batch1_spec_hash"], s["frozen_at_utc"])) == st["hash"] == hs(s)
        print(("\033[92mbatch1 calibration spec unchanged: " if ok else "\033[91mCALIBRATION SPEC CHANGED: ") + st["hash"] + "\033[0m")
        return
    if mode == "freeze":
        if not os.path.exists(BATCH):
            raise SystemExit("\033[91mbatch1_spec_v1.json is not frozen yet. Freeze the batch1 spec first. Nothing frozen.\033[0m")
        b = json.load(open(BATCH))
        if hs(b["spec"]) != b["hash"]:
            raise SystemExit("\033[91mbatch1 spec does not match its hash. Nothing frozen.\033[0m")
        fz = datetime.now(timezone.utc).isoformat()
        s = spec(b["hash"], fz)
        json.dump({"hash": hs(s), "spec": s}, open(FILE, "w"), indent=1)
        print("\033[96mfrozen batch1-calibration-v1 at %s\nsha256 %s\033[0m" % (fz, hs(s)))
        return
    print(json.dumps(spec(PH, PH), indent=1))
    print("\033[93mNothing frozen. Freeze order: python3 batch1_spec.py freeze, then python3 batch1_calib_spec.py freeze\033[0m")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "show")
