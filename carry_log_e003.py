import os, json, hashlib
from datetime import datetime, timezone
from carry_spec22 import spec_hash, SPECFILE

HERE = os.path.dirname(os.path.abspath(__file__))
LOG, RES = os.path.join(HERE, "experiments.json"), os.path.join(HERE, "carry_calib22_result.json")
V22 = "f9bbfb1d1f3d3d485a32ad20cad4fff1d275e38bceb898dcbc0560d68823a1df"
sha = lambda b: hashlib.sha256(b).hexdigest()


def fsha(p):
    return sha(open(p, "rb").read())


def main():
    if spec_hash() != V22 or json.load(open(SPECFILE))["hash"] != V22:
        raise SystemExit("v2.2 spec hash changed: stop, the record must stay intact.")
    res = json.load(open(RES))
    if res.get("status") != "NO BLOCK QUALIFIES" or res.get("spec_hash") != V22:
        raise SystemExit("result file does not show NO BLOCK QUALIFIES for the v2.2 hash. Nothing logged.")
    log = json.load(open(LOG))
    if any(e.get("spec_hash") == V22 for e in log):
        raise SystemExit("v2.2 is already logged. Nothing written.")
    rates = {k: sum(v) / 1972 for k, v in res["false_positive_counts"].items()}
    best, worst = min(rates, key=rates.get), max(rates, key=rates.get)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "type": "calibration",
        "name": "carry v2.2 block-bootstrap calibration", "status": "CALIBRATION FAILED: NO BLOCK QUALIFIES",
        "spec_hash": V22, "spec_file_sha256": fsha(SPECFILE), "result_file_sha256": fsha(RES),
        "code_sha256": {f: fsha(os.path.join(HERE, f)) for f in ("carry_calib22.py", "carry_spec22.py")},
        "supersedes": {"version": "carry-v2.1", "hash": "4f857ebdd3873c27c8c58ca24c0326b9ede5080faac009f731915f4f11fda237",
                       "status": "superseded before any calibration result or real return was seen; never claimed as passed"},
        "false_positive_rates_pooled_1972_worlds": {"best": [best, rates[best]], "worst": [worst, rates[worst]], "target": 0.005,
                                                     "all_world_types_and_blocks_exceeded_limits": all(
                                                         sum(v) > 18 for v in res["false_positive_counts"].values())},
        "observation": "Every world type and block length (14, 28, 56 days) exceeded the frozen false-positive limits; no block was selected; power was not run.",
        "interpretation": "Under the tested persistence assumptions the block-bootstrap intervals were far too narrow, because 4.7 years holds only a few "
                          "independent funding regimes. The test design cannot support a significance claim. This is not evidence that carry does or does not work.",
        "limitations": ["synthetic parameters were assumptions; real funding persistence may differ",
                        "no real funding rates or returns were read", "v2.2 is not to be rerun or edited"]}
    entry["prev_hash"] = sha(json.dumps(log, sort_keys=True).encode())
    entry["id"] = "E%03d" % (len(log) + 1)
    log.append(entry)
    tmp = LOG + ".tmp"
    json.dump(log, open(tmp, "w"), indent=1)
    os.replace(tmp, LOG)
    print(f"\033[96mlogged {entry['id']}: best {best} {rates[best] * 100:.2f}%, worst {worst} {rates[worst] * 100:.2f}%\033[0m")


if __name__ == "__main__":
    main()
