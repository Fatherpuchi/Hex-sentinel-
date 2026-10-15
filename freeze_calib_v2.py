import json, hashlib, copy, time, os
V1 = 'batch1_calib_spec_v1.json'
OUT = 'batch1_calib_spec_v2.json'
if os.path.exists(OUT):
    raise SystemExit('EXISTS, not overwriting')
d = json.load(open(V1))
V1H = d['hash']
assert V1H == '0ec1ecb0121a168e1f484e8f9361674ac409b9bbfc0271556028c0aed12e47b0'
s = copy.deepcopy(d['spec'])
s['version'] = 'batch1-calibration-v2'
s['frozen_at_utc'] = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
s['supersedes_hash'] = V1H
s['v1_status'] = 'STOPPED: quick mode failed 3 model self-checks (B coin lag1 -0.081, B coin abs lag30 0.257 vs 0.149, D factor lag1 -0.071); worlds B and D numerically absurd (daily returns up to 1e16+). No calibration result, no real data read.'
s['the_one_change'] = 'log-vol values 0.25 (common) and 0.30 (coin) are the STATIONARY sd of log volatility, not the AR(1) shock sd; shock sd = stationary sd x sqrt(1-phi^2), phi = 0.5^(1/half-life). Justified by synthetic numerical failure only; no real-data or strategy result used; not tuned to make any strategy pass. Everything else is unchanged from v1.'
w = s['synthetic_world']
assert 'volatility' in w and 'model_selfcheck' in w
w['volatility'] = 'log volatility follows AR(1) with the half-life of the world type and stationary sd 0.25 (common) and 0.30 (coin); shock sd = stationary sd x sqrt(1-phi^2); common factor sd 2.0%/day times exp(log vol); coin sd 2.5%/day times exp(coin log vol); stationary start'
w['model_selfcheck'] = w['model_selfcheck'] + ' [v2: tolerances unchanged; theoretical lag-30 abs-return autocorrelation recomputed with stationary variance 0.0625 (common) and 0.09 (coin); any failure stops everything, no v3 on the same ground, batch stays descriptive and forward-only]'
s['numerical_guard'] = 'result reports the largest daily simple return per world type; if any world is non-finite or any daily return exceeds +1000%, status is WORLD INVALID and the run stops'
s['drift_note'] = 'drift added equally to every coin daily log return (ln1.6/365), not scaled by beta; mean gross active return per cell reported as a diagnostic'
s['outputs'] = ['batch1_calib_result_v2.json (counts per cell, selection, MDE per hypothesis, status, engine hash, per-type max daily return)']
s['not_decided'] = ['whether batch-wide alpha 0.0025 replaces per-family 0.005 (this addendum uses 0.005)', 'runtime: re-timed by quick mode on v2 worlds before any full run']
h = hashlib.sha256(json.dumps(s, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
json.dump({'hash': h, 'hash_method': 'sha256 of json.dumps(spec, sort_keys=True, separators=(",",":")); may differ from the v1 method', 'spec': s}, open(OUT, 'x'), indent=1)
print('frozen', OUT, h)
