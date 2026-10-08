import shutil
import os, sys, re, time, math, select, shutil
from datetime import datetime, timezone
import lab_engine as E
from lab_data import connect, HERE, HOUR_MS

G, R, C, Y, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[93m", "\033[2m", "\033[0m"
PLAYER = "human"
BLOCK = 20                      # block mode: answers are revealed after every 20 locked calls
CHART_DIR = os.path.join(HERE, "lab_charts")
BARS = " ▁▂▃▄▅▆▇█"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
SCHEMA = ("CREATE TABLE IF NOT EXISTS reveals(set_name TEXT, round_id TEXT, player TEXT, "
          "revealed_at TEXT, PRIMARY KEY(set_name, round_id, player));")


def ensure(conn):
    conn.executescript(SCHEMA)


# ------------------------------------------------------------ chart (uses ONLY the visible candles)
def build_grid(candles, start, ncols, price_rows=26, vol_rows=3):
    hi = max(c[1] for c in candles)
    lo = min(c[2] for c in candles)
    pad = (hi - lo) * 0.02 or 1.0
    hi, lo = hi + pad, lo - pad                      # axis uses all 100 candles, so panning never rescales
    vmax = max(c[4] for c in candles) or 1.0

    def row(p):
        return min(price_rows - 1, max(0, int(round((hi - p) / (hi - lo) * (price_rows - 1)))))

    seg = candles[start:start + ncols]
    pg = [[(" ", None)] * len(seg) for _ in range(price_rows)]
    vg = [[(" ", None)] * len(seg) for _ in range(vol_rows)]
    for j, (o, h, l, c, v) in enumerate(seg):
        col = G if c >= o else R
        for r in range(row(h), row(l) + 1):
            pg[r][j] = ("│", col)
        rt, rb = row(max(o, c)), row(min(o, c))
        ch = "█" if (rt != rb or abs(c - o) >= (hi - lo) / (price_rows * 3)) else "─"
        for r in range(rt, rb + 1):
            pg[r][j] = (ch, col)
        total = int(round(v / vmax * vol_rows * 8))
        for k in range(vol_rows):
            vg[vol_rows - 1 - k][j] = (BARS[max(0, min(8, total - k * 8))], col)
    return pg, vg, hi, lo


def render_chart(candles, start, ncols, price_rows=26, vol_rows=3):
    pg, vg, hi, lo = build_grid(candles, start, ncols, price_rows, vol_rows)

    def paint(cells):
        return "".join((col + ch + X) if col else ch for ch, col in cells)

    lines = []
    for r in range(price_rows):
        label = f"{hi - r * (hi - lo) / (price_rows - 1):7.2f}" if r % 5 == 0 else " " * 7
        lines.append(D + label + X + "│" + paint(pg[r]))
    for k in range(vol_rows):
        label = "volume " if k == 0 else " " * 7
        lines.append(D + label + X + "│" + paint(vg[k]))
    n = len(candles)
    seg = min(ncols, n - start)
    lines.append(f"{D}candles {start + 1}-{start + seg} of {n}  (1 = oldest, {n} = latest, the moment of decision){X}")
    return lines


def html_chart(view, directory=None):
    import json
    d = directory or CHART_DIR
    os.makedirs(d, exist_ok=True)
    cs = view.candles
    n = len(cs)
    W, L, RT, T, PH, GAP, VH, B = 1000, 10, 74, 12, 380, 16, 80, 26
    H = T + PH + GAP + VH + B
    hi, lo = max(c[1] for c in cs), min(c[2] for c in cs)
    pad = (hi - lo) * 0.05 or 1.0
    hi, lo = hi + pad, lo - pad
    vmax = max(c[4] for c in cs) or 1.0
    step = (W - L - RT) / n
    bw = max(2.0, step * 0.68)
    VT = T + PH + GAP
    y = lambda p: T + (hi - p) / (hi - lo) * PH
    raw = (hi - lo) / 7
    mag = 10 ** math.floor(math.log10(raw))
    tick = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    parts = [f'<rect class="frame" x="{L}" y="{T}" width="{W - L - RT}" height="{PH}"/>',
             f'<rect class="frame" x="{L}" y="{VT}" width="{W - L - RT}" height="{VH}"/>',
             f'<text class="ax" x="{L + 6}" y="{VT + 14}">Volume</text>']
    p = math.ceil(lo / tick) * tick
    while p <= hi:
        yy = y(p)
        parts.append(f'<line class="grid" x1="{L}" x2="{W - RT}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
                     f'<text class="ax" x="{W - RT + 8}" y="{yy + 4:.1f}">{p:.2f}</text>')
        p += tick
    for i, (o, h, l, c, v) in enumerate(cs):
        x = L + step * (i + 0.5)
        top, bot = y(max(o, c)), y(min(o, c))
        vh = v / vmax * (VH - 6)
        parts.append(
            f'<g class="c" data-d="{"u" if c >= o else "d"}">'
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y(h):.1f}" y2="{y(l):.1f}" stroke-width="1.4"/>'
            f'<rect x="{x - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(1.2, bot - top):.1f}"/>'
            f'<rect class="vol" x="{x - bw / 2:.1f}" y="{VT + VH - vh:.1f}" width="{bw:.1f}" height="{vh:.1f}"/></g>')
        if i % 10 == 0 or i == n - 1:
            parts.append(f'<text class="ax" x="{x:.1f}" y="{H - 8}" text-anchor="middle">{i + 1}</text>')
    yl = y(100.0)
    parts.append(f'<line class="last" x1="{L}" x2="{W - RT}" y1="{yl:.1f}" y2="{yl:.1f}"/>'
                 f'<rect x="{W - RT + 2}" y="{yl - 10:.1f}" width="66" height="20" rx="3" fill="var(--gold)"/>'
                 f'<text x="{W - RT + 35}" y="{yl + 4:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="#000">100.00</text>')
    parts.append(f'<line id="v" class="xh" y1="{T}" y2="{VT + VH}" style="display:none"/>'
                 f'<line id="h" class="xh" x1="{L}" x2="{W - RT}" style="display:none"/>')
    svg = f'<svg id="ch" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "</svg>"
    tpl = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hex Lab __RID__</title>
<style>
:root{--bg:#131722;--panel:#1e222d;--grid:#2a2e39;--text:#d1d4dc;--muted:#787b86;--up:#26a69a;--down:#ef5350;--gold:#f0b90b}
@media (prefers-color-scheme: light){:root{--bg:#f4f5f7;--panel:#fff;--grid:#e3e5ea;--text:#1e222d;--muted:#6b7280;--up:#089981;--down:#f23645;--gold:#e0a400}}
body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:12px}
h1{font-size:16px;margin:4px 0 2px}
p{color:var(--muted);margin:2px 0 10px;line-height:1.4}
.card{background:var(--panel);border-radius:8px;padding:8px}
#tip{min-height:20px;font:13px ui-monospace,monospace;padding:2px 6px 6px;white-space:nowrap;overflow-x:auto}
svg{display:block;width:100%;height:auto;touch-action:pan-y;user-select:none}
.grid{stroke:var(--grid);stroke-width:1}
.frame{fill:none;stroke:var(--grid)}
.ax{fill:var(--muted);font-size:12px}
.xh{stroke:var(--muted);stroke-dasharray:3 3;stroke-width:1}
.last{stroke:var(--gold);stroke-dasharray:5 4;stroke-width:1}
.c[data-d="u"] line{stroke:var(--up)} .c[data-d="u"] rect{fill:var(--up)}
.c[data-d="d"] line{stroke:var(--down)} .c[data-d="d"] rect{fill:var(--down)}
.vol{opacity:.45}
.up{color:var(--up)} .down{color:var(--down)}
</style></head><body><div class="wrap">
<h1>Round __RID__ &middot; 100 hourly candles</h1>
<p>Prices are rescaled so the last close = 100 (gold line). Will the close 24 candles later finish above or below it?
Tiny moves count as FLAT and are not scored. Candle 1 is the oldest, 100 the latest. Coin and dates are hidden.</p>
<div class="card"><div id="tip">hover or touch a candle</div>__SVG__</div>
</div>
<script>
const D=__DATA__,W=1000,L=__L__,RT=__RT__,T=__T__,PH=__PH__,HI=__HI__,LO=__LO__;
const svg=document.getElementById('ch'),vl=document.getElementById('v'),hl=document.getElementById('h'),tip=document.getElementById('tip');
const step=(W-L-RT)/D.length;
function hide(){vl.style.display='none';hl.style.display='none';}
function mv(e){
  const r=svg.getBoundingClientRect(),s=W/r.width;
  const x=(e.clientX-r.left)*s,y=(e.clientY-r.top)*s;
  const i=Math.floor((x-L)/step);
  if(i<0||i>=D.length||y<T||y>T+PH+110){hide();return;}
  const k=D[i],cx=L+step*(i+.5),chg=(k[3]/k[0]-1)*100,cls=chg>=0?'up':'down';
  vl.setAttribute('x1',cx);vl.setAttribute('x2',cx);vl.style.display='';
  if(y<=T+PH){hl.setAttribute('y1',y);hl.setAttribute('y2',y);hl.style.display='';}else{hl.style.display='none';}
  tip.innerHTML='#'+(i+1)+' &nbsp;O '+k[0].toFixed(2)+' H '+k[1].toFixed(2)+' L '+k[2].toFixed(2)+' C '+k[3].toFixed(2)+
    ' <span class="'+cls+'">'+(chg>=0?'+':'')+chg.toFixed(2)+'%</span> &nbsp;vol x'+k[4].toFixed(2);
}
svg.addEventListener('pointermove',mv);
svg.addEventListener('pointerdown',mv);
svg.addEventListener('pointerleave',hide);
</script></body></html>"""
    data = json.dumps([[round(x, 4) for x in c] for c in cs])
    page = (tpl.replace("__RID__", view.round_id).replace("__SVG__", svg).replace("__DATA__", data)
            .replace("__L__", str(L)).replace("__RT__", str(RT)).replace("__T__", str(T))
            .replace("__PH__", str(PH)).replace("__HI__", repr(hi)).replace("__LO__", repr(lo)))
    path = os.path.join(d, view.round_id + ".html")
    with open(path, "w") as f:
        f.write(page)
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
    import subprocess
    for cmd in (["termux-open", path], ["xdg-open", path]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


# ------------------------------------------------------------ input helpers (tests replace these)
def ask(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "q"


def getkey():
    if not sys.stdin.isatty():
        try:
            s = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "q"
        return s[:1] or "p"
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1).decode(errors="ignore")
        if ch == "\x1b" and select.select([fd], [], [], 0.05)[0]:
            ch += os.read(fd, 2).decode(errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch == "\x03":
        return "q"
    return {"\x1b[D": "left", "\x1b[C": "right", "\r": "p", "\n": "p", " ": "p"}.get(ch, ch.lower())


# ------------------------------------------------------------ state
def played(conn, set_name):
    return [r for (r,) in conn.execute("SELECT round_id FROM predictions WHERE set_name=? AND player=?", (set_name, PLAYER))]


def pending(conn, set_name):
    return [r for (r,) in conn.execute(
        "SELECT round_id FROM predictions WHERE set_name=? AND player=? AND round_id NOT IN "
        "(SELECT round_id FROM reveals WHERE set_name=? AND player=?) ORDER BY locked_at",
        (set_name, PLAYER, set_name, PLAYER))]


def unplayed(conn, set_name):
    done = set(played(conn, set_name))
    return [r for (r,) in conn.execute("SELECT round_id FROM rounds WHERE set_name=? ORDER BY ord", (set_name,)) if r not in done]


def should_reveal(n_pending, n_unplayed, mode):
    if n_pending == 0:
        return False
    if mode == "each":
        return True
    return n_pending >= BLOCK or n_unplayed == 0


def _when(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000))


def reveal_pending(conn, set_name):
    out = []
    for rid in pending(conn, set_name):
        o, (d, cf) = E.reveal(conn, set_name, rid, PLAYER)
        sym, st = conn.execute("SELECT symbol,start_time FROM rounds WHERE set_name=? AND round_id=?", (set_name, rid)).fetchone()
        conn.execute("INSERT OR IGNORE INTO reveals VALUES (?,?,?,?)",
                     (set_name, rid, PLAYER, datetime.now(timezone.utc).isoformat()))
        out.append(dict(rid=rid, symbol=sym, when=_when(st + E.VISIBLE * HOUR_MS), pick=d, conf=cf, o=o))
    conn.commit()
    return out


def show_reveals(rows):
    print(f"\n{C}== reveal =={X}")
    n = k = 0
    for r in rows:
        o = r["o"]
        pct = (math.exp(o.ret) - 1) * 100
        if o.direction == "FLAT":
            col, mark = Y, "FLAT, not scored"
        else:
            n += 1
            ok = o.direction == r["pick"]
            k += ok
            col, mark = (G, "right") if ok else (R, "wrong")
        print(f"{col}{r['rid']} {r['symbol']:9s} {r['when']}  you {r['pick']} {r['conf']}%  "
              f"result {o.direction} ({pct:+.1f}%)  {mark}{X}")
    if n:
        print(f"{C}this block: {k}/{n} right ({k / n * 100:.0f}%){X}")


def session_stats(conn, set_name):
    rows = conn.execute(
        "SELECT p.round_id,p.direction FROM predictions p JOIN reveals r ON r.set_name=p.set_name "
        "AND r.round_id=p.round_id AND r.player=p.player WHERE p.set_name=? AND p.player=?", (set_name, PLAYER)).fetchall()
    n = k = void = up = 0
    for rid, d in rows:
        o = E._outcome(conn, set_name, rid)
        if o.direction == "FLAT":
            void += 1
            continue
        n += 1
        k += (o.direction == d)
        up += (o.direction == "UP")
    return dict(n=n, k=k, void=void, up=up)


def session_summary(conn, set_name):
    s = session_stats(conn, set_name)
    pend = len(pending(conn, set_name))
    if s["n"] + s["void"] == 0:
        print(f"{D}no revealed rounds yet ({pend} locked, waiting for their reveal){X}")
        return
    lo, hi = E.wilson(s["k"], s["n"])
    print(f"{C}== your record on '{set_name}' (revealed rounds only) =={X}")
    print(f"scored {s['n']}, void {s['void']}, right {s['k']} = {s['k'] / max(1, s['n']) * 100:.1f}%  "
          f"[{lo * 100:.0f}-{hi * 100:.0f}%]")
    print(f"always-UP on the same rounds: {s['up'] / max(1, s['n']) * 100:.1f}%")
    print(f"{Y}{E.verdict(s['k'], s['n'])}{X}")
    if pend:
        print(f"{D}{pend} more locked and waiting for the next reveal{X}")


# ------------------------------------------------------------ play
def chart_loop(view, head, ncols, prow, note=""):
    n = len(view.candles)
    start = max(0, n - ncols)
    while True:
        print("\033[2J\033[H" + head)
        for ln in render_chart(view.candles, start, ncols, prow):
            print(ln)
        print(f"{D}Will the close 24 candles after the last one end above (UP) or below (DOWN) 100? Tiny moves are void.{X}")
        print(f"{C}[<-/a] older  [->/d] newer  [h] save HTML chart  [p/Enter] make my call  [q] quit{X}")
        if note:
            print(Y + note + X)
            note = ""
        k = getkey()
        if k in ("left", "a"):
            start = max(0, start - 10)
        elif k in ("right", "d"):
            start = max(0, min(n - ncols, start + 10))
        elif k == "h":
            _p = html_chart(view)
            note = "saved " + _p + (" and opened in your browser" if open_html(_p) else "  (open it with: termux-open " + _p + ")")
        elif k in ("p", ""):
            return "answer"
        elif k == "q":
            return "quit"


def ask_answer():
    while True:
        s = ask("Your call - u = UP, d = DOWN (q = quit): ").strip().lower()
        if s == "q":
            return None
        if s in ("u", "up"):
            d = "UP"
        elif s in ("d", "down"):
            d = "DOWN"
        else:
            print("type u or d")
            continue
        while True:
            t = ask("Confidence (50/60/70/80/90/100, 50 = pure guess): ").strip().replace("%", "")
            if t.lower() == "q":
                return None
            if t.isdigit() and int(t) in E.CONF_LEVELS:
                c = int(t)
                break
            print("pick one of 50, 60, 70, 80, 90, 100")
        if ask(f"Lock {d} at {c}%? Cannot be changed (y/n): ").strip().lower().startswith("y"):
            return d, c


def play(conn, set_name, mode="block", limit=None):
    ensure(conn)
    if not conn.execute("SELECT 1 FROM sets WHERE name=?", (set_name,)).fetchone():
        print(R + f"no set named '{set_name}'. Try: lab list" + X)
        return
    ids = unplayed(conn, set_name)
    total = len(ids) + len(played(conn, set_name))
    cols, lines = shutil.get_terminal_size()
    ncols = max(20, min(78, cols - 10))
    prow = max(10, min(26, lines - 17))
    if should_reveal(len(pending(conn, set_name)), len(ids), mode):
        show_reveals(reveal_pending(conn, set_name))
        ask("Enter to continue: ")
    made = 0
    for rid in ids:
        if limit is not None and made >= limit:
            break
        view = E.get_view(conn, set_name, rid)
        pos = total - len(ids) + made + 1
        head = f"{C}ROUND {pos} of {total}   set {set_name}   mode {mode}   waiting for reveal: {len(pending(conn, set_name))}{X}"
        if chart_loop(view, head, ncols, prow) == "quit":
            break
        ans = ask_answer()
        if ans is None:
            break
        E.lock_prediction(conn, set_name, rid, PLAYER, ans[0], ans[1])
        made += 1
        pend, left = len(pending(conn, set_name)), len(ids) - made
        if should_reveal(pend, left, mode):
            show_reveals(reveal_pending(conn, set_name))
            if ask("Enter = continue, q = stop: ").strip().lower() == "q":
                break
        else:
            print(f"{G}locked. {pend}/{BLOCK} calls until the next reveal.{X}")
            if ask("Enter = next round, q = stop: ").strip().lower() == "q":
                break
    print()
    session_summary(conn, set_name)


def cli(a):
    conn = connect()
    ensure(conn)
    if a and a[0] == "play" and len(a) >= 2:
        mode = a[2] if len(a) > 2 else "block"
        if mode not in ("block", "each"):
            print("mode must be block or each")
            return
        play(conn, a[1], mode, int(a[3]) if len(a) > 3 else None)
    elif a and a[0] == "mine" and len(a) == 2:
        session_summary(conn, a[1])
    else:
        print("usage: lab play SET [block|each] [LIMIT] | lab mine SET")


if __name__ == "__main__":
    cli(sys.argv[1:])
