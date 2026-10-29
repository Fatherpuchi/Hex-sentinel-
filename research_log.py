#!/usr/bin/env python3
"""research_log.py - research_v1 (frozen spec: research_v1_spec.md). Web research LEADS only.
Stores links, titles and short snippets in shadow_research_leads (shadow.db). A lead is not
evidence. Nothing here is fed to an AI, the guard or any decision, and nothing imports this
module. The key TAVILY_API_KEY is read from the environment or .env and is never printed.
Usage: python3 research_log.py selftest | check | run | report"""
import os
import re
import sys
import json
import time
import sqlite3
import datetime
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "shadow.db")
ENV_PATH = os.path.join(HERE, ".env")
STATE_PATH = os.path.join(HERE, "research_state.json")
KEY_NAME = "TAVILY_API_KEY"
URL = "https://api.tavily.com/search"
CREDITS_PER_SEARCH = 2
MONTH_CAP = 300
MIN_GAP_DAYS = 6
RESULTS_PER_QUERY = 5
SNIPPET_MAX = 400
TITLE_MAX = 200
TIMEOUT = 20
PAUSE = 1.0
QUERIES = [
    "cryptocurrency time-series momentum out-of-sample study",
    "bitcoin trend following moving average backtest transaction costs",
    "crypto intraday momentum strategy peer reviewed",
    "cryptocurrency mean reversion strategy out-of-sample evidence",
    "crypto volatility breakout strategy evidence",
    "Donchian channel breakout cryptocurrency study",
    "cryptocurrency perpetual funding rate strategy research",
    "technical analysis cryptocurrency profitability data snooping",
    "crypto cross-sectional momentum factor research",
    "crypto trading strategy replication failed out-of-sample",
]
SCHEMA = (
    "create table if not exists shadow_research_leads(id integer primary key autoincrement, "
    "run_utc text, query_no integer, url text unique, title text, snippet text, domain text, "
    "published text, provider_score real, source_note text)")


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def month_key(dt):
    return dt.strftime("%Y-%m")


def parse_utc(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def clean(text, n):
    t = "" if text is None else str(text)
    t = "".join(ch if ch.isprintable() else " " for ch in t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n]


def redact(text, key):
    t = str(text)
    if key:
        t = t.replace(key, "[REDACTED]")
    t = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", t)
    t = re.sub(r"tvly-[A-Za-z0-9_\-]+", "[REDACTED]", t)
    return t


def domain_of(url):
    try:
        h = urlparse(url).netloc.lower()
    except Exception:
        return ""
    h = h.split("@")[-1].split(":")[0]
    return h[4:] if h.startswith("www.") else h


def load_key(environ=None, env_path=ENV_PATH):
    environ = os.environ if environ is None else environ
    v = environ.get(KEY_NAME)
    if v and v.strip():
        return v.strip()
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:].lstrip()
                k, _, val = line.partition("=")
                if k.strip() == KEY_NAME:
                    val = val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                        val = val[1:-1]
                    return val.strip() or None
    except Exception:
        return None
    return None


def load_state(path):
    if not os.path.exists(path):
        return {"last_run_utc": None, "credits": {}}, None
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict):
            raise ValueError("not an object")
        cr = st.get("credits", {})
        if not isinstance(cr, dict) or any(
                (not isinstance(v, int)) or isinstance(v, bool) or v < 0 for v in cr.values()):
            raise ValueError("bad credits")
        lr = st.get("last_run_utc")
        if lr is not None:
            parse_utc(lr)
        return {"last_run_utc": lr, "credits": dict(cr)}, None
    except Exception:
        return None, ("state file unreadable or corrupt; refusing to run. Check your credit use in the "
                      "Tavily dashboard before fixing or deleting it by hand.")


def save_state(path, st):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run_allowed(st, now):
    lr = st.get("last_run_utc")
    if lr:
        nxt = parse_utc(lr) + datetime.timedelta(days=MIN_GAP_DAYS)
        if now < nxt:
            return False, "last run %s; the next run is allowed from %s UTC" % (lr, fmt(nxt))
    used = st["credits"].get(month_key(now), 0)
    if used + CREDITS_PER_SEARCH > MONTH_CAP:
        return False, "monthly cap reached (%d of %d credits counted)" % (used, MONTH_CAP)
    return True, ""


def ensure_schema(con):
    con.execute(SCHEMA)
    con.commit()


def run_core(con, st, state_path, key, now, post, sleep):
    ensure_schema(con)
    st["last_run_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    save_state(state_path, st)
    run_utc = st["last_run_utc"]
    mk = month_key(now)
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    done = new_total = dup_total = 0
    stopped = ""
    for qno, q in enumerate(QUERIES, 1):
        used = st["credits"].get(mk, 0)
        if used + CREDITS_PER_SEARCH > MONTH_CAP:
            stopped = "monthly cap reached"
            break
        st["credits"][mk] = used + CREDITS_PER_SEARCH
        save_state(state_path, st)
        body = {"query": q, "search_depth": "basic", "max_results": RESULTS_PER_QUERY,
                "include_answer": False, "include_raw_content": False, "include_images": False}
        try:
            r = post(URL, headers=headers, json=body, timeout=TIMEOUT)
        except Exception as e:
            stopped = "q%d request error: %s" % (qno, clean(redact(e, key), 120))
            break
        if r.status_code != 200:
            stopped = "q%d HTTP %s: %s" % (qno, r.status_code, clean(redact(getattr(r, "text", ""), key), 120))
            break
        try:
            results = r.json()["results"]
            if not isinstance(results, list):
                raise ValueError("results is not a list")
        except Exception:
            stopped = "q%d unexpected response shape" % qno
            break
        used_n = results[:RESULTS_PER_QUERY]
        n_new = n_dup = n_skip = 0
        for item in used_n:
            if not isinstance(item, dict):
                n_skip += 1
                continue
            raw = str(item.get("url") or "").strip()
            if len(raw) > 500 or clean(raw, 600) != raw or not re.match(r"^https?://\S+$", raw):
                n_skip += 1
                continue
            content = item.get("content")
            if content is None:
                content = item.get("snippet")
            try:
                score = float(item.get("score"))
            except Exception:
                score = None
            cur = con.execute(
                "insert or ignore into shadow_research_leads(run_utc, query_no, url, title, snippet, "
                "domain, published, provider_score, source_note) values(?,?,?,?,?,?,?,?,?)",
                (run_utc, qno, raw, clean(item.get("title"), TITLE_MAX), clean(content, SNIPPET_MAX),
                 domain_of(raw), clean(item.get("published_date") or item.get("published") or "", 40),
                 score, "tavily search basic; query: " + q))
            if cur.rowcount > 0:
                n_new += 1
            else:
                n_dup += 1
        con.commit()
        done += 1
        new_total += n_new
        dup_total += n_dup
        print("q%d: %d results used, %d new, %d already stored, %d skipped"
              % (qno, len(used_n), n_new, n_dup, n_skip))
        if qno < len(QUERIES):
            sleep(PAUSE)
    print("run: %d of %d queries done, %d new leads, %d already stored; credits counted this month "
          "%d of %d (assumed %d per search)%s"
          % (done, len(QUERIES), new_total, dup_total, st["credits"].get(mk, 0), MONTH_CAP,
             CREDITS_PER_SEARCH, (" | stopped: " + stopped) if stopped else ""))
    return {"done": done, "new": new_total, "stopped": stopped}


def build_report(con, credits_line):
    if not con.execute("select count(*) from sqlite_master where name='shadow_research_leads'").fetchone()[0]:
        return ["no shadow_research_leads table yet"]
    rows = con.execute("select query_no, domain, title, url, published from shadow_research_leads "
                       "order by query_no, id").fetchall()
    lines = []
    cur = None
    for qn, dom, title, url, pub in rows:
        if qn != cur:
            cur = qn
            lines.append("")
            lines.append("Q%d: %s" % (qn, QUERIES[qn - 1] if 1 <= qn <= len(QUERIES) else "?"))
        lines.append("  %s | %s%s" % (dom, title, (" [%s]" % pub) if pub else ""))
        lines.append("    %s" % url)
    lines.append("")
    lines.append("%d leads stored; %s. Leads are not evidence: each needs its own pre-registered "
                 "shadow test." % (len(rows), credits_line))
    return lines


def credits_text(st, now):
    if st is None:
        return "credits unknown (state file problem)"
    return "credits counted this month (assumed %d per search): %d of %d" % (
        CREDITS_PER_SEARCH, st["credits"].get(month_key(now), 0), MONTH_CAP)


def cmd_check():
    key = load_key()
    print("key %s: %s" % (KEY_NAME, "found" if key else "NOT found"))
    st, err = load_state(STATE_PATH)
    if st is None:
        print(err)
        return
    now = utcnow()
    ok, why = run_allowed(st, now)
    print("last run: %s | %s" % (st["last_run_utc"], credits_text(st, now)))
    print("a run would be %s" % ("allowed now" if ok else "refused: " + why))
    con = sqlite3.connect(DB, timeout=30)
    has = con.execute("select count(*) from sqlite_master where name='shadow_research_leads'").fetchone()[0]
    n = con.execute("select count(*) from shadow_research_leads").fetchone()[0] if has else 0
    print("stored leads: %d | nothing was requested or written" % n)


def cmd_run():
    key = load_key()
    if not key:
        print("%s not found in the environment or .env; nothing requested" % KEY_NAME)
        return
    st, err = load_state(STATE_PATH)
    if st is None:
        print(err)
        return
    now = utcnow()
    ok, why = run_allowed(st, now)
    if not ok:
        print("refused: " + why)
        return
    import requests
    con = sqlite3.connect(DB, timeout=30)
    run_core(con, st, STATE_PATH, key, now, requests.post, time.sleep)


def cmd_report():
    con = sqlite3.connect(DB, timeout=30)
    st, err = load_state(STATE_PATH)
    if st is None:
        print(err)
    for line in build_report(con, credits_text(st, utcnow())):
        print(line)


def selftest():
    import io
    import tempfile
    from contextlib import redirect_stdout
    utc = datetime.timezone.utc
    KEY = "tvly-SECRET-KEY-123"

    # 1 clean, domain, redact
    assert clean("a\x1b[31mb\nc\t d", 50) == "a [31mb c d"
    assert clean(None, 5) == "" and clean("abcdefgh", 5) == "abcde" and clean("  x   y ", 10) == "x y"
    assert domain_of("https://www.Example.com:8080/a?b=1") == "example.com"
    assert domain_of("http://user@pub.org/x") == "pub.org"
    red = redact("Authorization: Bearer abc.DEF-1 and tvly-XYZ_9 and " + KEY, KEY)
    assert "SECRET" not in red and "abc.DEF-1" not in red and "XYZ_9" not in red, red

    # 2 key loading
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, ".env")
        assert load_key({"TAVILY_API_KEY": " k1 "}, p) == "k1"
        assert load_key({}, p) is None
        for body, want in (('# c\nOTHER=zzz\nexport TAVILY_API_KEY="quoted-key"\n', "quoted-key"),
                           ("TAVILY_API_KEY='sq'\n", "sq"), ("TAVILY_API_KEY=plain\n", "plain"),
                           ("TAVILY_API_KEY=\n", None), ("OTHER=1\n", None)):
            with open(p, "w") as f:
                f.write(body)
            assert load_key({}, p) == want, (body, want)
        with open(p, "w") as f:
            f.write("TAVILY_API_KEY=fromfile\n")
        assert load_key({"TAVILY_API_KEY": "fromenv"}, p) == "fromenv"

    # 3 state and rules
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "state.json")
        assert load_state(sp) == ({"last_run_utc": None, "credits": {}}, None)
        save_state(sp, {"last_run_utc": "2026-10-24T12:00:00Z", "credits": {"2026-10": 20}})
        assert not os.path.exists(sp + ".tmp")
        assert load_state(sp) == ({"last_run_utc": "2026-10-24T12:00:00Z", "credits": {"2026-10": 20}}, None)
        for bad in ("not json", '{"credits": {"2026-10": -1}}', '{"last_run_utc": "garbage", "credits": {}}',
                    '{"credits": {"2026-10": true}}', "[1]"):
            with open(sp, "w") as f:
                f.write(bad)
            st, err = load_state(sp)
            assert st is None and "refusing" in err, bad
    now = datetime.datetime(2026, 10, 30, 12, 0, tzinfo=utc)
    assert run_allowed({"last_run_utc": None, "credits": {}}, now) == (True, "")
    ok, why = run_allowed({"last_run_utc": "2026-10-25T12:00:00Z", "credits": {}}, now)
    assert not ok and "2026-10-31 12:00" in why, why
    assert run_allowed({"last_run_utc": "2026-10-24T12:00:00Z", "credits": {}}, now)[0]
    assert run_allowed({"last_run_utc": None, "credits": {"2026-10": 298}}, now)[0]
    assert not run_allowed({"last_run_utc": None, "credits": {"2026-10": 299}}, now)[0]
    assert run_allowed({"last_run_utc": None, "credits": {"2026-09": 300}}, now)[0]

    # 4 runs with a fake post (no network)
    class Resp:
        def __init__(self, code, data=None, text=""):
            self.status_code, self._d, self.text = code, data, text

        def json(self):
            if isinstance(self._d, Exception):
                raise self._d
            return self._d

    def make_post(script, calls):
        def post(url, headers=None, json=None, timeout=None):
            calls.append((url, dict(headers), dict(json), timeout))
            x = script(len(calls))
            if isinstance(x, Exception):
                raise x
            return x
        return post

    def go(script, credits=None, con=None):
        td = tempfile.mkdtemp()
        sp = os.path.join(td, "state.json")
        st = {"last_run_utc": None, "credits": dict(credits or {})}
        calls, sleeps = [], []
        con = con if con is not None else sqlite3.connect(":memory:")
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = run_core(con, st, sp, KEY, now, make_post(script, calls), lambda s: sleeps.append(s))
        out = buf.getvalue()
        assert KEY not in out and "SECRET" not in out, out
        return con, st, sp, calls, sleeps, out, res

    def sa(n):
        if n == 1:
            return Resp(200, {"results": [
                {"url": "https://www.A.com/x", "title": "T1", "content": "c" * 500, "score": 0.9,
                 "published_date": "2024-01-01"},
                {"url": "https://www.A.com/x", "title": "dup"},
                {"url": "ftp://x/y", "title": "bad"},
                {"url": "https://b.org/1", "title": "T\x1b[2J2"},
                {"url": "https://c.org/1", "title": "C", "content": "z"},
                {"url": "https://d.org/1", "title": "D"},
                {"url": "https://e.org/1", "title": "E"},
                {"url": "javascript:alert(1)", "title": "J"}]})
        return Resp(200, {"results": [{"url": "https://site%d.org/p" % n, "title": "t", "content": "x"}]})
    con, st, sp, calls, sleeps, out, res = go(sa)
    assert len(calls) == 10 and len(sleeps) == 9 and res["done"] == 10 and res["stopped"] == ""
    assert calls[0][0] == URL and calls[0][3] == TIMEOUT
    assert calls[0][1] == {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    assert calls[0][2] == {"query": QUERIES[0], "search_depth": "basic", "max_results": 5,
                           "include_answer": False, "include_raw_content": False, "include_images": False}
    assert KEY not in json.dumps(calls[0][2]) and KEY not in calls[0][0]
    assert st["credits"] == {"2026-10": 20} and st["last_run_utc"] == "2026-10-30T12:00:00Z"
    assert load_state(sp) == (st, None)
    assert con.execute("select count(*), count(distinct url) from shadow_research_leads").fetchone() == (12, 12)
    row = con.execute("select query_no, title, snippet, domain, published, provider_score, run_utc "
                      "from shadow_research_leads where url='https://www.A.com/x'").fetchone()
    assert row == (1, "T1", "c" * 400, "a.com", "2024-01-01", 0.9, "2026-10-30T12:00:00Z"), row
    row = con.execute("select title, snippet, provider_score from shadow_research_leads "
                      "where url='https://b.org/1'").fetchone()
    assert row == ("T [2J2", "", None), row
    assert con.execute("select count(*) from shadow_research_leads where url like '%d.org%' "
                       "or url like '%e.org%' or url like 'ftp%' or url like 'javascript%'").fetchone()[0] == 0
    assert "q1: 5 results used, 3 new, 1 already stored, 1 skipped" in out, out
    assert "10 of 10 queries done, 12 new leads" in out and "credits counted this month 20 of 300" in out, out
    con2, st2, sp2, calls2, sleeps2, out2, res2 = go(sa, con=con)
    assert res2["new"] == 0
    assert con.execute("select count(*) from shadow_research_leads").fetchone()[0] == 12
    assert "0 new leads, 13 already stored" in out2, out2

    con, st, sp, calls, sleeps, out, res = go(
        lambda n: Resp(429, {}, "rate limited " + KEY) if n == 3 else Resp(200, {"results": []}))
    assert len(calls) == 3 and st["credits"] == {"2026-10": 6} and "q3 HTTP 429" in out, out
    assert "[REDACTED]" in out and res["stopped"].startswith("q3 HTTP 429")
    con, st, sp, calls, sleeps, out, res = go(
        lambda n: RuntimeError("boom " + KEY) if n == 2 else Resp(200, {"results": []}))
    assert len(calls) == 2 and st["credits"] == {"2026-10": 4} and "q2 request error" in out, out
    con, st, sp, calls, sleeps, out, res = go(lambda n: Resp(401, {}, "unauthorized"))
    assert len(calls) == 1 and st["credits"] == {"2026-10": 2} and "q1 HTTP 401" in out, out
    assert load_state(sp)[0]["last_run_utc"] == "2026-10-30T12:00:00Z"
    for bad in (Resp(200, {"nope": 1}), Resp(200, ValueError("bad json")), Resp(200, {"results": "x"})):
        con, st, sp, calls, sleeps, out, res = go(lambda n, b=bad: b)
        assert len(calls) == 1 and "unexpected response shape" in out and st["credits"] == {"2026-10": 2}, out
    con, st, sp, calls, sleeps, out, res = go(lambda n: Resp(200, {"results": []}), credits={"2026-10": 296})
    assert len(calls) == 2 and st["credits"] == {"2026-10": 300} and "monthly cap reached" in out, out

    # 5 report and query list
    con, st, sp, calls, sleeps, out, res = go(sa)
    rep = "\n".join(build_report(con, "credits counted this month (assumed 2 per search): 20 of 300"))
    assert "Q1: " + QUERIES[0] in rep and "a.com | T1 [2024-01-01]" in rep and "https://www.A.com/x" in rep, rep
    assert "12 leads stored" in rep and "Leads are not evidence" in rep and KEY not in rep, rep
    assert build_report(sqlite3.connect(":memory:"), "x") == ["no shadow_research_leads table yet"]
    assert credits_text(None, now) == "credits unknown (state file problem)"
    assert len(QUERIES) == 10 and len(set(QUERIES)) == 10
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"selftest": selftest, "check": cmd_check, "run": cmd_run, "report": cmd_report}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
