import shutil
import sys, os, json, time, math, subprocess, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "charts")
URLS = (("Spot", "https://api.binance.com/api/v3/klines"), ("Futures", "https://fapi.binance.com/fapi/v1/klines"))


def fetch(sym, interval="1h", limit=150):
    q = urllib.parse.urlencode({"symbol": sym, "interval": interval, "limit": limit})
    for name, u in URLS:
        try:
            req = urllib.request.Request(u + "?" + q, headers={"User-Agent": "hex-chart/1"})
            rows = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            if rows:
                return name, [[int(k[0]) / 1000, *map(float, k[1:6])] for k in rows]
        except Exception:
            continue
    return None, []


def ema(vals, n):
    k, e, out = 2 / (n + 1), vals[0], []
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def build(sym, src, interval, rows, levels=None):
    levels = levels or {}
    n = len(rows)
    W, L, RT, T, PH, GAP, VH, B = 1000, 10, 84, 12, 400, 16, 80, 30
    H = T + PH + GAP + VH + B
    VT = T + PH + GAP
    vals = [r[2] for r in rows] + [r[3] for r in rows] + list(levels.values())
    hi, lo = max(vals), min(vals)
    pad = (hi - lo) * 0.05 or 1
    hi, lo = hi + pad, lo - pad
    vmax = max(r[5] for r in rows) or 1
    step = (W - L - RT) / n
    bw = max(2, step * 0.68)
    y = lambda p: T + (hi - p) / (hi - lo) * PH
    fmt = lambda p: f"{p:.6g}" if p < 1 else f"{p:.2f}"
    raw = (hi - lo) / 7
    mag = 10 ** math.floor(math.log10(raw))
    tick = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    P = [f'<rect class="frame" x="{L}" y="{T}" width="{W-L-RT}" height="{PH}"/>',
         f'<rect class="frame" x="{L}" y="{VT}" width="{W-L-RT}" height="{VH}"/>']
    p = math.ceil(lo / tick) * tick
    while p <= hi:
        P.append(f'<line class="grid" x1="{L}" x2="{W-RT}" y1="{y(p):.1f}" y2="{y(p):.1f}"/>'
                 f'<text class="ax" x="{W-RT+6}" y="{y(p)+4:.1f}">{fmt(p)}</text>')
        p += tick
    cl = [r[4] for r in rows]
    for i, (t, o, h, l, c, v) in enumerate(rows):
        x = L + step * (i + .5)
        top, bot, vh = y(max(o, c)), y(min(o, c)), v / vmax * (VH - 6)
        P.append(f'<g class="c" data-d="{"u" if c >= o else "d"}"><line x1="{x:.1f}" x2="{x:.1f}" y1="{y(h):.1f}" y2="{y(l):.1f}" stroke-width="1.3"/>'
                 f'<rect x="{x-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(1.2,bot-top):.1f}"/>'
                 f'<rect class="vol" x="{x-bw/2:.1f}" y="{VT+VH-vh:.1f}" width="{bw:.1f}" height="{vh:.1f}"/></g>')
        if i % max(1, n // 8) == 0:
            P.append(f'<text class="ax" x="{x:.1f}" y="{H-9}" text-anchor="middle">{time.strftime("%m-%d %H:%M", time.gmtime(t))}</text>')
    for nm, col in ((20, "#f0b90b"), (50, "#4aa3ff")):
        pts = " ".join(f"{L+step*(i+.5):.1f},{y(v):.1f}" for i, v in enumerate(ema(cl, nm)))
        P.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.4"/>')
    last = cl[-1]
    P.append(f'<line class="last" x1="{L}" x2="{W-RT}" y1="{y(last):.1f}" y2="{y(last):.1f}"/>'
             f'<rect x="{W-RT+2}" y="{y(last)-10:.1f}" width="78" height="20" rx="3" fill="#f0b90b"/>'
             f'<text x="{W-RT+41}" y="{y(last)+4:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="#000">{fmt(last)}</text>')
    for nm, v in levels.items():
        col = "#ef5350" if nm.lower().startswith("stop") else ("#26a69a" if nm.lower().startswith("tp") else "#b39ddb")
        P.append(f'<line x1="{L}" x2="{W-RT}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{col}" stroke-dasharray="6 4"/>'
                 f'<text x="{L+4}" y="{y(v)-4:.1f}" fill="{col}" font-size="12" font-weight="700">{nm} {fmt(v)}</text>')
    P.append(f'<line id="v" class="xh" y1="{T}" y2="{VT+VH}" style="display:none"/>')
    svg = f'<svg id="ch" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">' + "".join(P) + "</svg>"
    tpl = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__T__</title><style>
:root{--bg:#131722;--panel:#1e222d;--grid:#2a2e39;--text:#d1d4dc;--muted:#787b86;--up:#26a69a;--down:#ef5350}
@media (prefers-color-scheme:light){:root{--bg:#f4f5f7;--panel:#fff;--grid:#e3e5ea;--text:#1e222d;--muted:#6b7280;--up:#089981;--down:#f23645}}
body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}.wrap{max-width:1100px;margin:0 auto;padding:12px}
h1{font-size:17px;margin:4px 0}p{color:var(--muted);margin:2px 0 8px}.card{background:var(--panel);border-radius:8px;padding:8px}
#tip{min-height:20px;font:13px ui-monospace,monospace;padding:2px 6px 6px;white-space:nowrap;overflow-x:auto}
svg{display:block;width:100%;height:auto;touch-action:pan-y}.grid{stroke:var(--grid)}.frame{fill:none;stroke:var(--grid)}.ax{fill:var(--muted);font-size:12px}
.xh{stroke:var(--muted);stroke-dasharray:3 3}.last{stroke:#f0b90b;stroke-dasharray:5 4}
.c[data-d=u] line{stroke:var(--up)}.c[data-d=u] rect{fill:var(--up)}.c[data-d=d] line{stroke:var(--down)}.c[data-d=d] rect{fill:var(--down)}.vol{opacity:.45}
</style></head><body><div class="wrap"><h1>__T__</h1><p>Yellow line = EMA20, blue = EMA50. Times are UTC. Not financial advice.</p>
<div class="card"><div id="tip">hover or touch a candle</div>__SVG__</div></div><script>
const D=__D__,W=1000,L=__L__,RT=__RT__,T=__TT__,PH=__PH__,svg=document.getElementById('ch'),vl=document.getElementById('v'),tip=document.getElementById('tip'),st=(W-L-RT)/D.length;
function mv(e){const r=svg.getBoundingClientRect(),s=W/r.width,x=(e.clientX-r.left)*s,y=(e.clientY-r.top)*s,i=Math.floor((x-L)/st);
if(i<0||i>=D.length||y<T||y>T+PH+110){vl.style.display='none';return}
const k=D[i],cx=L+st*(i+.5),ch=(k[4]/k[1]-1)*100;vl.setAttribute('x1',cx);vl.setAttribute('x2',cx);vl.style.display='';
tip.textContent=new Date(k[0]*1000).toISOString().slice(0,16).replace('T',' ')+'  O '+k[1]+' H '+k[2]+' L '+k[3]+' C '+k[4]+'  '+(ch>=0?'+':'')+ch.toFixed(2)+'%  vol '+Math.round(k[5])}
svg.addEventListener('pointermove',mv);svg.addEventListener('pointerdown',mv);svg.addEventListener('pointerleave',()=>vl.style.display='none');
</script></body></html>"""
    title = f"{sym} {interval} ({src}), {n} candles"
    for a, b in (("__T__", title), ("__SVG__", svg), ("__D__", json.dumps(rows)), ("__L__", str(L)),
                 ("__RT__", str(RT)), ("__TT__", str(T)), ("__PH__", str(PH))):
        tpl = tpl.replace(a, b)
    return tpl


def make(coin, interval="1h", limit=150, levels=None):
    sym = coin.upper().replace("/", "")
    if not sym.endswith("USDT"):
        sym += "USDT"
    src, rows = fetch(sym, interval, limit)
    if not rows:
        return None
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{sym}_{interval}.html")
    open(path, "w").write(build(sym, src, interval, rows, levels))
    return path


def _share(path):
    """Copy to shared Downloads so the phone's browser can read it."""
    base = os.path.expanduser("~/storage/downloads")
    if not os.path.isdir(base):
        return path
    try:
        d = os.path.join(base, "hex_charts")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, os.path.basename(path))
        shutil.copyfile(path, dst)
        return dst
    except Exception:
        return path


def open_html(path):
    path = _share(path)
    for cmd in (["termux-open", path], ["xdg-open", path]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    return False


def _plan_db(prof):
    return os.path.join(HERE, "sentinel.db" if prof in ("", "24h") else "sentinel_%s.db" % prof)


def plans_list(prof="24h"):
    import sqlite3
    c = sqlite3.connect(_plan_db(prof))
    for r in c.execute("SELECT id,symbol,direction,status,outcome,created_at FROM paper_trade_plans ORDER BY id DESC LIMIT 10"):
        print("%5s  %-10s %-5s %-10s %-12s %s" % (r[0], r[1], r[2], r[3], r[4] or "-", str(r[5])[:16]))


def plan_chart(pid, prof="24h"):
    import sqlite3
    from datetime import datetime, timezone
    c = sqlite3.connect(_plan_db(prof))
    r = c.execute("SELECT symbol,direction,entry_price,stop_loss,tp1,tp2,tp3,status,outcome,created_at "
                  "FROM paper_trade_plans WHERE id=?", (pid,)).fetchone()
    if not r:
        print("\033[91mno plan with that id in " + _plan_db(prof) + "\033[0m")
        return None
    sym, d, en, sl, t1, t2, t3, st, oc, ca = r
    try:
        dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hrs = int((datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except Exception:
        hrs = 60
    lv = {"Entry": en, "TP1": t1, "TP2": t2, "TP3": t3, "Stop": sl}
    lv = {k: v for k, v in lv.items() if v}
    path = make(sym, "1h", max(80, min(1000, hrs + 48)), lv)
    if path:
        note = "plan #%s %s, %s, outcome %s" % (pid, d, st, oc or "-")
        html = open(path).read()
        title = html.split("<title>")[1].split("</title>")[0]
        open(path, "w").write(html.replace(title, title + " | " + note))
    return path


TERM_WORDS = ("term", "text", "terminal", "txt", "tty")


def term_chart(coin, iv="1h", lim=150, lv=None):
    import shutil as _sh
    G, R, Y, B, D, C, X = "\033[92m", "\033[91m", "\033[93m", "\033[94m", "\033[2m", "\033[96m", "\033[0m"
    lv = lv or {}
    sym = coin.upper().replace("/", "")
    if not sym.endswith("USDT"):
        sym += "USDT"
    src, rows = fetch(sym, iv, lim)
    if not rows:
        print(R + "no data for that coin (spot and futures both failed)" + X)
        return
    closes = [r[4] for r in rows]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    cols, lines = _sh.get_terminal_size()
    nc = max(20, min(len(rows), cols - 12))
    rows, e20, e50 = rows[-nc:], e20[-nc:], e50[-nc:]
    pr, vr = max(10, min(30, lines - 10)), 3
    vals = [r[2] for r in rows] + [r[3] for r in rows] + list(lv.values())
    hi, lo = max(vals), min(vals)
    pad = (hi - lo) * 0.03 or 1.0
    hi, lo = hi + pad, lo - pad
    row = lambda p: min(pr - 1, max(0, int(round((hi - p) / (hi - lo) * (pr - 1)))))
    fmt = lambda p: ("%.6g" % p) if p < 1 else ("%.2f" % p)
    g = [[(" ", None)] * nc for _ in range(pr)]
    for nm, v in lv.items():
        col = R if nm.lower().startswith("stop") else (G if nm.lower().startswith("tp") else C)
        for j in range(nc):
            g[row(v)][j] = ("┄", col)
    for j, (t, o, h, l, c, v) in enumerate(rows):
        col = G if c >= o else R
        for r in range(row(h), row(l) + 1):
            g[r][j] = ("│", col)
        rt, rb = row(max(o, c)), row(min(o, c))
        ch = "█" if rt != rb else "─"
        for r in range(rt, rb + 1):
            g[r][j] = (ch, col)
    for series, col in ((e50, B), (e20, Y)):
        for j, v in enumerate(series):
            r = row(v)
            if g[r][j][0] in (" ", "┄"):
                g[r][j] = ("·", col)
    lastr = row(rows[-1][4])
    vmax = max(r[5] for r in rows) or 1.0
    vg = [[(" ", None)] * nc for _ in range(vr)]
    for j, r in enumerate(rows):
        tot = int(round(r[5] / vmax * vr * 8))
        col = G if r[4] >= r[1] else R
        for k in range(vr):
            vg[vr - 1 - k][j] = (" ▁▂▃▄▅▆▇█"[max(0, min(8, tot - k * 8))], col)
    paint = lambda cells: "".join((col + ch + X) if col else ch for ch, col in cells)
    print()
    for r in range(pr):
        lab = fmt(hi - r * (hi - lo) / (pr - 1)) if (r % 5 == 0 or r == lastr) else ""
        lab = (Y + lab.rjust(9) + X) if r == lastr else (D + lab.rjust(9) + X)
        print(lab + "│" + paint(g[r]))
    for k in range(vr):
        print(D + ("volume".rjust(9) if k == 0 else " " * 9) + X + "│" + paint(vg[k]))
    chg = (rows[-1][4] / rows[0][4] - 1) * 100
    t0 = time.strftime("%m-%d %H:%M", time.gmtime(rows[0][0]))
    t1 = time.strftime("%m-%d %H:%M", time.gmtime(rows[-1][0]))
    print(f"{C}{sym} {iv} ({src}){X}  {t0} -> {t1} UTC  last {fmt(rows[-1][4])}  "
          f"{(G if chg >= 0 else R)}{chg:+.2f}%{X}")
    print(f"{D}{nc} candles   {Y}· EMA20{X}{D}   {B}· EMA50{X}{D}   dashed = your levels{X}")


def main(a):
    if not a:
        print("usage: chart <coin> [interval e.g. 1h/4h/15m] [number of candles e.g. 100] [entry=.. tp1=.. tp2=.. tp3=.. stop=..]")
        return
    if a[0] == "plans":
        return plans_list(a[1] if len(a) > 1 else "24h")
    if a[0] == "plan" and len(a) >= 2:
        p = plan_chart(int(a[1]), a[2] if len(a) > 2 else "24h")
        if p:
            print("\033[96msaved " + p + "\033[0m" + ("  (opened)" if open_html(p) else "  (open with: termux-open " + p + ")"))
        return
    term = any(x.lower() in TERM_WORDS for x in a)
    a = [x for x in a if x.lower() not in TERM_WORDS]
    pos = [x for x in a if "=" not in x]
    if not pos:
        print("usage: chart <coin> [term] [interval] [number of candles]")
        return
    lv = {k: float(v) for k, v in (x.split("=", 1) for x in a if "=" in x)}
    iv, lim = "1h", 150
    for w in pos[1:]:
        if w.lower() in ("candles", "candle", "bars"):
            continue
        if w.isdigit():
            lim = max(20, min(1000, int(w)))
        else:
            iv = w.lower()
    if term:
        term_chart(pos[0], iv, lim, lv)
        return
    p = make(pos[0], iv, lim, lv)
    if not p:
        print("\033[91mno data for that coin (spot and futures both failed)\033[0m")
        return
    print("\033[96msaved " + p + "\033[0m" + ("  (opened)" if open_html(p) else "  (open with: termux-open " + p + ")"))


if __name__ == "__main__":
    main(sys.argv[1:])
