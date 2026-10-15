import os, json, hashlib
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(HERE, f)
sha = lambda b: hashlib.sha256(b).hexdigest()
fsha = lambda f: sha(open(P(f), 'rb').read())
B1 = '7fc3c8c279814d4d72c144a27d9998a489b9fe05a41cb633cd60f1be4d934b10'
V3 = '27d0842649a8256ed75c3415c29dfa53fe6a230b92ddfa5a13e76a205dd718d8'
EH = '7bbd78e2e9899ac7'
RES = 'batch1_real_result_v1.json'
ORDER = ['ema50_200', 'breakout20', 'weekly_mom_b1', 'meanrev_short_b1']

def main():
    if json.load(open(P('batch1_spec_v1.json')))['hash'] != B1:
        raise SystemExit('batch1 spec hash changed: nothing logged')
    res = json.load(open(P(RES)))
    if 'did not license inference' not in res.get('wording', '') or res.get('batch1_spec_hash') != B1:
        raise SystemExit('result wording or spec hash wrong: nothing logged')
    if res.get('engine_hash') != fsha('batch1_engine.py') or not res['engine_hash'].startswith(EH):
        raise SystemExit('engine hash mismatch: nothing logged')
    log = json.load(open(P('experiments.json')))
    if not any(e.get('id') == 'E006' and e.get('spec_hash') == V3 for e in log):
        raise SystemExit('E006 not found in log: nothing logged')
    rsha = fsha(RES)
    if any(e.get('result_file_sha256') == rsha for e in log):
        raise SystemExit('this result is already logged. Nothing written.')
    st, bm = res['strategies'], res['benchmark']
    lines, ratios = [], {}
    for h in ORDER:
        x = st[h]
        ratios[h] = abs(x['mean_active']) / x['mde_best_case']
        lines.append('%s: %d days, annualized %.1f%%, mean active %+.4f%%/day, best-case MDE %.4f%%/day, max drawdown %.1f%%, avg net exposure %.2f, stress active %+.4f%%/day, halves %+.4f%% / %+.4f%%' % (
            h, x['n_days'], 100 * x['annualized'], 100 * x['mean_active'], 100 * x['mde_best_case'], 100 * x['max_drawdown'], x['avg_net_exposure'],
            100 * x['stress_mean_active'], 100 * x['first_half_active'], 100 * x['second_half_active']))
    allsmall = all(v < 1 for v in ratios.values())
    obs = ('Window %s to %s, 40 coins, %d days, %d invalid coin-days. Benchmark (equal weight, no costs): annualized %.1f%%, total %.1f%%, max drawdown %.1f%%. Costs 0.10%% per side, stress 0.15%%. ' % (
        res['window'][0], res['window'][1], bm['n_days'], res['invalid_coin_days'], 100 * bm['annualized'], 100 * bm['total_compounded'], 100 * bm['max_drawdown'])
        + ' | '.join(lines))
    interp = ('No inference was licensed (E006), so the pass bar does not apply and nothing is reported as passing or failing. ')
    if allsmall:
        interp += 'Every mean active return is smaller than its best-case minimum detectable effect, so none is distinguishable from zero. '
    else:
        interp += 'At least one mean active return exceeds its best-case minimum detectable effect; with no licensed test this is still not evidence, see the numbers. '
    interp += 'Sign changes between halves or at stress costs argue against reading anything into the point estimates. Nothing is integrated or approved.'
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(), 'type': 'descriptive_screen',
        'name': 'batch1 daily-bar real descriptive run (no inference)', 'status': 'DESCRIPTIVE ONLY: CALIBRATION DID NOT LICENSE INFERENCE',
        'spec_hash': B1, 'calibration_entry': 'E006', 'result_file_sha256': rsha, 'data_hash': res['data_hash'],
        'code_sha256': {f: fsha(f) for f in ('batch1_engine.py', 'batch1_real.py')},
        'benchmark': bm, 'results': st, 'ratio_abs_mean_active_to_best_case_mde': {k: round(v, 3) for k, v in ratios.items()},
        'enj': res.get('enj'), 'observation': obs, 'interpretation': interp,
        'limitations': ['seen data (fade.db was used in E001 and E002)', 'survivorship: the 40 coins are today listed survivors',
                        'weekly_mom shorts carry no funding cost; longs carry none either', 'annualization uses the mean daily return, which flatters compounded results',
                        'the best-case MDE assumes independent days; the real value is larger', 'one run, no tuning, no rerun']}
    entry['prev_hash'] = sha(json.dumps(log, sort_keys=True).encode())
    entry['id'] = 'E%03d' % (len(log) + 1)
    log.append(entry)
    tmp = P('experiments.json') + '.tmp'
    json.dump(log, open(tmp, 'w'), indent=1)
    os.replace(tmp, P('experiments.json'))
    print('logged', entry['id'], '| all |mean active| < best-case MDE:', allsmall, '| ratios', entry['ratio_abs_mean_active_to_best_case_mde'])

if __name__ == '__main__':
    main()
