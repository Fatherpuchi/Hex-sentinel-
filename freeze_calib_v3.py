import json, hashlib, copy, time, os
V2 = 'batch1_calib_spec_v2.json'
OUT = 'batch1_calib_spec_v3.json'
if os.path.exists(OUT):
    raise SystemExit('EXISTS, not overwriting')
d = json.load(open(V2))
V2H = d['hash']
assert V2H == '858abaf89c9566eca245b28b12e60f8cb0f3121c074569b713bca4cfd963dfde'
s = copy.deepcopy(d['spec'])
s['version'] = 'batch1-calibration-v3'
s['frozen_at_utc'] = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
s['supersedes_hash'] = V2H
s['v2_status'] = 'STOPPED: full run hit its own WORLD INVALID guard at type A, seed 1, world 651 (max daily simple return 222.67 vs +1000% guard); 650 worlds done; false-positive counts deliberately not read; no real data or strategy result used.'
s['the_one_change'] = 'each coin daily log return in every synthetic world is clipped to [-ln2, +ln2] (about -50% / +100% simple), applied after beta x F + e + drift and after the pre-start days are zeroed; the number of clipped coin-days is counted and reported. Justified by synthetic numerics only; no real-data or strategy result used; not tuned to make any strategy pass. Everything else is unchanged from v2.'
s['numerical_guard'] = 'the run stops with WORLD INVALID only if a world is non-finite; clipped coin-days are counted and reported per run; the +1000% rule of v2 is removed because the clip makes it unreachable'
s['model_selfcheck_note'] = 'self-checks test the unclipped factor and coin components with unchanged tolerances; any failure stops everything; no v4 on the same ground, batch stays descriptive and forward-only'
s['outputs'] = ['batch1_calib_result_v3.json (counts per cell, selection, MDE per hypothesis, status, engine hash, clipped coin-day count, per-type max daily return)']
h = hashlib.sha256(json.dumps(s, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
json.dump({'hash': h, 'hash_method': 'sha256 of json.dumps(spec, sort_keys=True, separators=(",",":"))', 'spec': s}, open(OUT, 'x'), indent=1)
print('frozen', OUT, h)
