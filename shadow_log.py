import sys, json, sqlite3, time, urllib.request, urllib.error
import numpy as np
import batch1_engine as E

B1 = '7fc3c8c279814d4d72c144a27d9998a489b9fe05a41cb633cd60f1be4d934b10'
EH = '7bbd78e2e9899ac7'
DBF = 'shadow.db'
D = 86400000
MINCOINS = 38
SCHEMA = '''
create table if not exists shadow_runs(applies_date text primary key, run_utc text, lag_hours real, flag text, n_coins integer, engine_hash text, notes text);
create table if not exists shadow_signals(applies_date text, strategy text, symbol text, weight real, primary key(applies_date, strategy, symbol));
create table if not exists shadow_sentinel(plan_id integer primary key, symbol text, direction text, plan_created_at text, captured_utc text);
'''

def fetch(sym):
    for s in (sym, '1000' + sym):
        for _ in range(3):
            try:
                u = 'https://fapi.binance.com/fapi/v1/klines?symbol=%s&interval=1d&limit=1000' % s
                r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=20)
                return s, json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    break
                time.sleep(2)
            except Exception:
                time.sleep(2)
    return None, None

def main(mode):
    if E.engine_hash()[:16] != EH:
        sys.exit('engine hash changed')
    d = json.load(open('batch1_spec_v1.json'))
    if d['hash'] != B1:
        sys.exit('batch1 spec hash changed')
    U = d['spec']['data']['universe']
    now = int(time.time() * 1000)
    last = now // D - 1
    got, miss, mapped = {}, [], []
    for s in U:
        used, k = fetch(s)
        if not k:
            miss.append(s + ':nofetch'); continue
        a = [(int(x[0]) // D, float(x[1]), float(x[4])) for x in k if int(x[0]) + D <= now]
        days = np.array([x[0] for x in a])
        if len(a) < 30 or days[-1] != last or not (np.diff(days) == 1).all():
            miss.append(s + ':gap/stale'); continue
        if used != s:
            mapped.append(s + '->' + used)
        got[s] = (days, np.array([x[1] for x in a]), np.array([x[2] for x in a]))
        time.sleep(0.2)
    names = [s for s in U if s in got]
    print('coins ok', len(names), 'of', len(U), '| missing', miss, '| mapped', mapped)
    if len(names) < MINCOINS:
        sys.exit('too few coins, nothing written')
    day0 = min(int(got[s][0][0]) for s in names)
    T = last - day0 + 1
    O = np.full((T + 1, len(names)), np.nan)
    C = O.copy()
    for i, s in enumerate(names):
        dd, o, c = got[s]
        O[dd - day0, i] = o
        C[dd - day0, i] = c
    O[T] = C[T - 1]
    C[T] = C[T - 1]
    W = {h: E.run(h, O, C, day0, 0.0)['W'][-1] for h in E.HYP}
    applies = str(np.datetime64('1970-01-01') + np.timedelta64(int(last) + 1, 'D'))
    lag = (now - (last + 1) * D) / 3600000.0
    flag = 'late' if lag > 6 else 'ok'
    print('decision from close of', str(np.datetime64('1970-01-01') + np.timedelta64(int(last), 'D')), '-> applies', applies, '| lag %.1f h (%s)' % (lag, flag))
    for h in E.HYP:
        w = W[h]
        print('%-18s long %2d short %2d gross %.3f net %+.3f' % (h, int((w > 0).sum()), int((w < 0).sum()), np.abs(w).sum(), w.sum()))
    if mode == 'check':
        return print('check mode: nothing written.')
    con = sqlite3.connect(DBF)
    con.executescript(SCHEMA)
    if con.execute('select 1 from shadow_runs where applies_date=?', (applies,)).fetchone():
        sys.exit('already recorded for ' + applies)
    run_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    con.execute('insert into shadow_runs values(?,?,?,?,?,?,?)', (applies, run_utc, lag, flag, len(names), E.engine_hash(), json.dumps(dict(missing=miss, mapped=mapped))))
    for h in E.HYP:
        for i, s in enumerate(names):
            con.execute('insert or ignore into shadow_signals values(?,?,?,?)', (applies, h, s, float(W[h][i])))
    sc = sqlite3.connect('file:sentinel.db?mode=ro', uri=True)
    rows = sc.execute('select id, symbol, direction, created_at from paper_trade_plans').fetchall()
    con.executemany('insert or ignore into shadow_sentinel values(?,?,?,?,?)', [(r[0], r[1], r[2], str(r[3]), run_utc) for r in rows])
    con.commit()
    print('recorded', applies, '| signal rows', 4 * len(names), '| sentinel plans copied', len(rows))

if __name__ == '__main__':
    m = sys.argv[1] if len(sys.argv) > 1 else ''
    if m not in ('check', 'run'):
        sys.exit('usage: check | run')
    main(m)
