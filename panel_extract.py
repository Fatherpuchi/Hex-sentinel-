import json, sqlite3, sys, os
OUT = 'panel_shape.json'
if os.path.exists(OUT):
    sys.exit('panel_shape.json EXISTS, not overwriting')
END = 1791504000000
D = 86400000
ENDDAY = END // D
c = sqlite3.connect('file:fade.db?mode=ro', uri=True)
mis = c.execute('select count(*) from k where t % 3600000 != 0').fetchone()[0]
rows = c.execute('select sym, t/86400000, count(*), count(distinct t) from k where t < ? group by sym, t/86400000', (END,)).fetchall()
by = {}
for s, d, n, u in rows:
    by.setdefault(s, {})[d] = (n, u)
coins = {}
tot_inv = 0
for s in sorted(by):
    full = set(d for d, (n, u) in by[s].items() if n == 24 and u == 24)
    first = min(full)
    inv = [d for d in range(first, ENDDAY) if d not in full]
    tot_inv += len(inv)
    coins[s] = {'first_valid_day': first, 'invalid_days': inv}
out = {'window_end_ms': END, 'end_day_exclusive': ENDDAY, 'day_ms': D, 'misaligned_candles': mis, 'coins': coins}
json.dump(out, open(OUT, 'w'))
f = [v['first_valid_day'] for v in coins.values()]
print('coins', len(coins), 'misaligned', mis)
print('first_valid_day min/max', min(f), max(f), 'end_day', ENDDAY)
print('days per coin min/max', ENDDAY - max(f), ENDDAY - min(f))
print('invalid coin-days inside window', tot_inv)
