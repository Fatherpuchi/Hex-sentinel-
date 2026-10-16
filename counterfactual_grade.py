import sys, os, json, time, math, sqlite3, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
H = {'User-Agent': 'Mozilla/5.0'}
URLS = [('spot', 'https://api.binance.com/api/v3/klines'), ('futures', 'https://fapi.binance.com/fapi/v1/klines')]
NEED = 30

def kl(sym, interval, **kw):
    q = '&'.join('%s=%s' % (k, v) for k, v in kw.items())
    for name, base in URLS:
        try:
            u = '%s?symbol=%s&interval=%s&%s' % (base, sym, interval, q)
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=15))
            if d:
                return name, d
        except Exception:
            continue
    return None, None

def exit_price(sym, due_ms):
    t0 = (due_ms // 60000) * 60000
    name, d = kl(sym, '1m', startTime=t0, limit=1)
    if not d or abs(int(d[0][0]) - t0) > 120000:
        return None, None
    return float(d[0][1]), name

def baseline(sym, created_ms, direction):
    name, d = kl(sym, '1d', endTime=created_ms, limit=30)
    if not d:
        return None
    d = [x for x in d if int(x[0]) + 86400000 <= created_ms]
    if len(d) < 20:
        return None
    up = sum(float(x[4]) > float(x[1]) for x in d) / len(d)
    return up if direction == 'BUY' else 1 - up

def has_table(con):
    return con.execute("select 1 from sqlite_master where type='table' and name='shadow_counterfactual'").fetchone() is not None

def grade(con):
    now = int(time.time() * 1000)
    rows = con.execute('select id,symbol,direction,price,created_ms,due_ms from shadow_counterfactual where graded_utc is null and due_ms <= ? order by id', (now - 180000,)).fetchall()
    n = 0
    for id_, sym, d, px, cm, dm in rows:
        xp, src = exit_price(sym, dm)
        if xp is None:
            print('%s #%d: exit price unavailable, will retry' % (sym, id_))
            continue
        right = int(xp < px) if d == 'SELL' else int(xp > px)
        bl = baseline(sym, cm, d)
        con.execute('update shadow_counterfactual set graded_utc=?, exit_price=?, exit_source=?, move_pct=?, was_right=?, baseline_rate=? where id=? and graded_utc is null',
                    (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), xp, src, (xp / px - 1) * 100, right, bl, id_))
        con.commit()
        n += 1
        print('%s #%d %s: entry %.6g exit %.6g move %+.2f%% -> %s (baseline %s)' % (sym, id_, d, px, xp, (xp / px - 1) * 100, 'RIGHT' if right else 'WRONG', 'n/a' if bl is None else '%.0f%%' % (100 * bl)))
    print('graded', n, 'of', len(rows), 'due')

def report(con):
    tot = con.execute('select count(*) from shadow_counterfactual').fetchone()[0]
    rows = con.execute('select was_right, baseline_rate from shadow_counterfactual where graded_utc is not null').fetchall()
    n = len(rows)
    print('%d logged, %d graded. Rule: read nothing before %d graded rows.' % (tot, n, NEED))
    if n < NEED:
        return print('NOT READ: too few rows. No conclusions.')
    hits = sum(r[0] for r in rows)
    bl = [r[1] for r in rows if r[1] is not None]
    print('blocked calls that would have been right: %d of %d = %.1f%%' % (hits, n, 100 * hits / n))
    if bl:
        p = sum(bl) / len(bl)
        print('baseline (share of prior 30 days that moved that way): %.1f%% over %d rows; 1 sd of chance at this n is about %.1f points' % (100 * p, len(bl), 100 * math.sqrt(p * (1 - p) / n)))
    print('A gap under about 2 sd is indistinguishable from chance. Same-day rows are correlated, so the real noise is larger. The guard is unchanged by this report.')

def selftest():
    now = int(time.time() * 1000)
    print('exit price test (BTCUSDT, 2h ago):', exit_price('BTCUSDT', now - 7200000))
    print('baseline test (BTCUSDT SELL):', baseline('BTCUSDT', now, 'SELL'))

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'selftest':
        return selftest()
    dbp = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'shadow.db')
    if not os.path.exists(dbp):
        sys.exit('no shadow.db yet')
    con = sqlite3.connect(dbp)
    if not has_table(con):
        return print('no counterfactual rows yet (table not created)')
    if mode == 'grade':
        grade(con)
    elif mode == 'report':
        report(con)
    else:
        print('usage: grade | report | selftest [dbpath]')

if __name__ == '__main__':
    main()
