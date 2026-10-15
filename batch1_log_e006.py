import os, json, hashlib
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(HERE, f)
sha = lambda b: hashlib.sha256(b).hexdigest()
fsha = lambda f: sha(open(P(f), 'rb').read())
B1 = '7fc3c8c279814d4d72c144a27d9998a489b9fe05a41cb633cd60f1be4d934b10'
V1 = '0ec1ecb0121a168e1f484e8f9361674ac409b9bbfc0271556028c0aed12e47b0'
V2 = '858abaf89c9566eca245b28b12e60f8cb0f3121c074569b713bca4cfd963dfde'
V3 = '27d0842649a8256ed75c3415c29dfa53fe6a230b92ddfa5a13e76a205dd718d8'
RES = 'batch1_calib_result_v3.json'
FILES = ['batch1_engine.py', 'batch1_calib.py', 'panel_extract.py', 'freeze_calib_v3.py', 'panel_shape.json', 'batch1_errata_v1.md']

def main():
    b1 = json.load(open(P('batch1_spec_v1.json')))
    if b1['hash'] != B1:
        raise SystemExit('batch1 spec hash changed: nothing logged')
    s3 = json.load(open(P('batch1_calib_spec_v3.json')))
    h3 = sha(json.dumps(s3['spec'], sort_keys=True, separators=(',', ':')).encode())
    if s3['hash'] != V3 or h3 != V3:
        raise SystemExit('v3 calibration spec hash mismatch: nothing logged')
    res = json.load(open(P(RES)))
    if res.get('status') != 'NO BLOCK QUALIFIES' or res.get('calib_spec_hash') != V3:
        raise SystemExit('result is not NO BLOCK QUALIFIES for the v3 hash: nothing logged')
    if res.get('engine_hash') != fsha('batch1_engine.py'):
        raise SystemExit('engine file changed since the run: nothing logged')
    fb = {str(k): v for k, v in res['fails_per_block'].items()}
    if fb != {'7': 1, '14': 2, '28': 3}:
        raise SystemExit('fails_per_block differs from what was reviewed: ' + str(fb))
    log = json.load(open(P('experiments.json')))
    if any(e.get('spec_hash') == V3 for e in log):
        raise SystemExit('v3 already logged. Nothing written.')
    bad = [c for c in res['cells'] if not c['ok']]
    worst = max(res['cells'], key=lambda c: c['pooled'])
    cells = ['%s %s block %d: seed1 %d, seed2 %d, pooled %d of %d' % (c['type'], c['hyp'], c['block'], c['seed1'], c['seed2'], c['pooled'], 2 * c['worlds_per_seed']) for c in bad]
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(), 'type': 'calibration',
        'name': 'batch1 daily-bar calibration v3', 'status': 'CALIBRATION DID NOT LICENSE INFERENCE: NO BLOCK QUALIFIES',
        'spec_hash': V3, 'batch1_spec_hash': B1,
        'spec_file_sha256': {'batch1_spec_v1.json': fsha('batch1_spec_v1.json'), 'batch1_calib_spec_v3.json': fsha('batch1_calib_spec_v3.json')},
        'result_file_sha256': fsha(RES),
        'code_sha256': {f: fsha(f) for f in FILES},
        'supersedes': [
            {'version': 'batch1-calibration-v1', 'hash': V1, 'status': 'STOPPED: quick mode failed 3 model self-checks; worlds B and D numerically absurd; its false-positive counts do not exist; never claimed as passed'},
            {'version': 'batch1-calibration-v2', 'hash': V2, 'status': 'STOPPED: full run hit its own WORLD INVALID guard at type A seed 1 world 651; its false-positive counts were deliberately not read; never claimed as passed'}],
        'fails_per_block': fb, 'failing_cells': cells,
        'worst_pooled_cell': '%s %s block %d: %d of %d' % (worst['type'], worst['hyp'], worst['block'], worst['pooled'], 2 * worst['worlds_per_seed']),
        'clipped_coin_days': res['flags'].get('clipped'), 'nonfinite_worlds': res['flags'].get('nonfinite'),
        'observation': 'No block length (7, 14, 28 days) qualified in all 16 of its cells, so no block was selected and no power run happened. %d of 48 cells exceeded the frozen limits (11 per seed, 18 pooled at stage 1). All four world types finished at stage 1. No real data or strategy return was read.' % len(bad),
        'interpretation': 'The test procedure was not validated on these synthetic worlds, so inference is not licensed. The batch is descriptive and forward-only. This says nothing about whether any strategy works. Block 7 missed by one cell and was not used. A sparse, heavy-tailed active-return series for meanrev_short_b1 is a hypothesis for its failures, untested.',
        'limitations': ['worlds are synthetic; the clip made tails lighter than the frozen t(4) design',
                        '48 cells make a failure likely even for a correct test',
                        'null worlds are gross of costs',
                        'v1 and v2 were stopped by their own rules and their counts are not in this entry',
                        'failing cells were read after the run, for the record only',
                        'harness.db registrations came from an unreviewed tool (errata 2 and 16)',
                        'batch1 spec was frozen before approval (errata 1)']}
    entry['prev_hash'] = sha(json.dumps(log, sort_keys=True).encode())
    entry['id'] = 'E%03d' % (len(log) + 1)
    log.append(entry)
    tmp = P('experiments.json') + '.tmp'
    json.dump(log, open(tmp, 'w'), indent=1)
    os.replace(tmp, P('experiments.json'))
    print('logged', entry['id'], entry['status'], '| failing cells:', len(bad))

if __name__ == '__main__':
    main()
