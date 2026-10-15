import sys, os, json, hashlib, time, sqlite3
import numpy as np
import batch1_engine as E

B1 = '7fc3c8c279814d4d72c144a27d9998a489b9fe05a41cb633cd60f1be4d934b10'
EH = '7bbd78e2e9899ac7'
RESULT = 'batch1_real_result_v1.json'
D = 86400000
WORD = 'The calibration did not license inference. Descriptive screen on seen data; not evidence of an edge.'

def load():
    d = json.load(open('batch1_spec_v1.json'))
    if d['hash'] != B1:
        sys.exit('batch1 spec hash changed')
    U = d['spec']['data']['universe']
    END = d['spec']['data']['window_end_utc_ms']
    con = sqlite3.connect('file:fade.db?mode=ro', uri=True)
    cols, early = {}, {}
    for s in U:
        r = con.execute('select t,o,c from k where sym=? and t<? order by t', (s, END)).fetchall()
        if not r:
            sys.exit('no rows for ' + s)
        a = np.array(r, dtype=float)
        t = a[:, 0].astype(np.int64); o = a[:, 1]; c = a[:, 2]
        if len(np.unique(t)) != len(t):
            sys.exit('duplicate candles ' + s)
        day = t // D; hr = (t % D) // 3600000
        ud, cnt = np.unique(day, return_counts=True)
        full = ud[cnt == 24]
        m0 = hr == 0; m23 = hr == 23
        d0, o0 = day[m0], o[m0]; d23, c23 = day[m23], c[m23]
        valid = np.intersect1d(np.intersect1d(full, d0), d23)
        cols[s] = (valid, o0[np.searchsorted(d0, valid)], c23[np.searchsorted(d23, valid)])
        lj = np.abs(np.diff(np.log(c)))
        early[s] = (float(lj[:720].max()), float(lj.max()))
    ENDDAY = END // D
    day0 = min(int(cols[s][0].min()) for s in U)
    T = ENDDAY - day0; N = len(U)
    O = np.full((T, N), np.nan); C = np.full((T, N), np.nan)
    inv = 0
    for i, s in enumerate(U):
        v, o_, c_ = cols[s]
        O[v - day0, i] = o_; C[v - day0, i] = c_
        inv += (ENDDAY - int(v.min())) - len(v)
    return dict(U=U, O=O, C=C, day0=day0, T=T, N=N, inv=inv, early=early)

def dstr(day):
    return str(np.datetime64('1970-01-01') + np.timedelta64(int(day), 'D'))

def checks(P):
    O, C = P['O'], P['C']
    bad = E.selfcheck()
    for b in bad:
        print('FAIL engine', b)
    with np.errstate(all='ignore'):
        R = C / O - 1
        rm = np.nanmean(R, axis=1)
    rb = E.bench(O, C)
    if not np.allclose(rb, rm):
        bad.append('real benchmark != mean of coin returns'); print('FAIL benchmark')
    if P['inv'] != 0:
        bad.append('invalid coin-days %d' % P['inv']); print('FAIL invalid coin-days', P['inv'])
    print('ENGINE+REAL CHECKS:', len(bad), 'FAIL | coins', P['N'], 'days', P['T'], dstr(P['day0']), 'to', dstr(P['day0'] + P['T'] - 1), '| invalid coin-days', P['inv'])
    top = sorted(P['early'].items(), key=lambda kv: -kv[1][0])[:5]
    print('splice check, largest hourly jump in first 720 candles (log), top 5:', [(s, round(v[0], 3)) for s, v in top])
    mx = max(P['early'].items(), key=lambda kv: kv[1][1])
    print('largest hourly jump anywhere:', mx[0], round(mx[1][1], 3))
    enj = None
    if 'ENJUSDT' in P['U']:
        j = P['U'].index('ENJUSDT')
        nact = np.maximum((~np.isnan(C)).sum(1), 1)
        contrib = np.nan_to_num(R[:, j]) / nact
        enj = dict(mean_daily_contribution=float(contrib.mean()), share_of_benchmark_mean=float(contrib.mean() / rb.mean()), max_daily_return=float(np.nanmax(R[:, j])))
        print('ENJ contribution to benchmark mean: %.4f%%/day, share %.1f%%, max daily return %.0f%%' % (100 * enj['mean_daily_contribution'], 100 * enj['share_of_benchmark_mean'], 100 * enj['max_daily_return']))
    return bad, enj, rb

def stat(o, o2, rb, yrs):
    s = o['start']; net = o['net'][s:]; act = o['active'][s:]; n = len(net)
    cur = np.cumprod(1 + net)
    dd = float((cur / np.maximum.accumulate(cur) - 1).min())
    yr = yrs[s:]
    yearly = {int(y): [int((yr == y).sum()), float(act[yr == y].mean())] for y in np.unique(yr)}
    h = n // 2
    sd = float(act.std(ddof=1))
    return dict(first_evaluable_row=int(s), n_days=n, mean_daily_net=float(net.mean()), annualized=float((1 + net.mean()) ** 365 - 1),
                total_compounded=float(cur[-1] - 1), max_drawdown=dd, mean_active=float(act.mean()), sd_active=sd,
                mde_best_case=float(3.418 * sd / np.sqrt(n)), avg_net_exposure=float(o['E'][s:].mean()),
                avg_gross_exposure=float(np.abs(o['W'][s:]).sum(1).mean()), mean_daily_turnover=float(o['turn'][s:].mean()),
                yearly_mean_active=yearly, first_half_active=float(act[:h].mean()), second_half_active=float(act[h:].mean()),
                stress_mean_active=float(o2['active'][s:].mean()), stress_mean_net=float(o2['net'][s:].mean()),
                bench_mean_same_days=float(rb[s:].mean()))

def main(mode):
    if os.path.exists(RESULT) and mode == 'run':
        sys.exit('result exists, one run only')
    if E.engine_hash()[:16] != EH:
        sys.exit('engine hash changed')
    P = load()
    bad, enj, rb = checks(P)
    if mode == 'check':
        return print('check mode: no strategy results computed.')
    if bad:
        sys.exit('STOP: checks failed, no result written')
    O, C, day0, T = P['O'], P['C'], P['day0'], P['T']
    yrs = (np.datetime64('1970-01-01') + (day0 + np.arange(T)).astype('timedelta64[D]')).astype('datetime64[Y]').astype(int) + 1970
    runs = {h: (E.run(h, O, C, day0, 0.001), E.run(h, O, C, day0, 0.0015)) for h in E.HYP}
    st = {h: stat(runs[h][0], runs[h][1], rb, yrs) for h in E.HYP}
    s0 = max(runs[h][0]['start'] for h in E.HYP)
    M = np.vstack([rb[s0:]] + [runs[h][0]['net'][s0:] for h in E.HYP])
    corr = np.corrcoef(M).round(3).tolist()
    cur = np.cumprod(1 + rb)
    bench = dict(mean_daily=float(rb.mean()), annualized=float((1 + rb.mean()) ** 365 - 1), total_compounded=float(cur[-1] - 1),
                 max_drawdown=float((cur / np.maximum.accumulate(cur) - 1).min()), n_days=T)
    res = dict(wording=WORD, batch1_spec_hash=B1, engine_hash=E.engine_hash(), data_hash=hashlib.sha256(O.tobytes() + C.tobytes()).hexdigest(),
               window=[dstr(day0), dstr(day0 + T - 1)], invalid_coin_days=P['inv'], cost_per_side=0.001, stress_per_side=0.0015,
               benchmark=bench, strategies=st, corr_order=['bh_equal_weight'] + E.HYP, corr=corr, corr_shared_days=int(T - s0), enj=enj,
               finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(res, open(RESULT, 'x'), indent=1)
    print(WORD)
    print('benchmark: ann %.1f%%  total %.1f%%  maxDD %.1f%%' % (100 * bench['annualized'], 100 * bench['total_compounded'], 100 * bench['max_drawdown']))
    for h in E.HYP:
        x = st[h]
        print('%-18s n %4d  ann %7.1f%%  act %+.4f%%/d  maxDD %6.1f%%  expo %.2f  stress act %+.4f%%/d  1st/2nd half %+.4f/%+.4f' % (
            h, x['n_days'], 100 * x['annualized'], 100 * x['mean_active'], 100 * x['max_drawdown'], x['avg_net_exposure'],
            100 * x['stress_mean_active'], 100 * x['first_half_active'], 100 * x['second_half_active']))
    print('written', RESULT)

if __name__ == '__main__':
    m = sys.argv[1] if len(sys.argv) > 1 else ''
    if m not in ('check', 'run'):
        sys.exit('usage: check | run')
    main(m)
