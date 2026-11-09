#!/usr/bin/env python3
"""make_manifest.py - writes HEX_MANIFEST.md: facts about this installation, with no secrets.
Reads files, git metadata and databases READ-ONLY. Lists .env variable NAMES only and aborts if a
secret-named .env value (6+ characters) or a known key shape appears in the output.
Usage: python3 make_manifest.py selftest | run"""
import os
import re
import sys
import glob
import hashlib
import sqlite3
import platform
import tempfile
import subprocess
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "HEX_MANIFEST.md")
BACKUP_RE = re.compile(r"(\.bak|\.broken|before_|\.tmp$|~$)")
SECRET_RE = re.compile(r"tvly-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{20,}")
SECRET_NAME_RE = re.compile(r"KEY|TOKEN|SECRET|PASS", re.I)
HOST_RE = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,})")
FROZEN_NAMES = ("batch1_spec_v1.json", "batch1_calib_spec_v1.json", "batch1_calib_spec_v2.json",
                "batch1_calib_spec_v3.json", "batch1_engine.py", "experiments.json")
TOOLS = ("market_facts.py held_plan_grade.py levels_log.py levelcmp_log.py market_ctx_log.py "
         "codeplan_log.py webdir_log.py noiseband_log.py breakout19_log.py research_log.py make_manifest.py")
RESTORE = """1. Install Termux (the F-Droid build is the one guides recommend), then: pkg update && pkg install python git openssl-tool (package names are from memory; verify).
2. pip install numpy requests (versions in section 1; install python-dotenv too if the code imports it).
3. git clone <remote from section 2> binance-sentinel, then cd binance-sentinel and git checkout <branch from section 2>.
4. Restore the data into a NEW folder: bash restore_hex.sh hex_data_DATE.tar.gz.enc ~/binance-sentinel_restored (never over a working folder).
5. Recreate .env from the NAMES in section 3 with fresh keys (Groq, Gemini x3, OpenRouter, Tavily). Binance order keys are not needed by any shadow tool.
6. Run each selftest (all offline): for f in %s; do python3 $f selftest; done
7. Run bash daily.sh once and read the summary line. Missed days only delay the counts; forward data that was lost cannot be recreated.""" % TOOLS


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def parse_env(path):
    """[(name, value)]. Values are used only for the leak check and are never written out."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:].lstrip()
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
                    out.append((k, v))
    except Exception:
        pass
    return out


def code_files(root):
    return [p for p in sorted(glob.glob(os.path.join(root, "*.py")))
            if not BACKUP_RE.search(os.path.basename(p))]


def key_usage(names, files):
    texts = [(os.path.basename(p), read_text(p)) for p in files]
    return dict((n, sorted(b for b, t in texts if n in t)) for n in names)


def hosts(files):
    d = {}
    for p in files:
        for h in set(m.lower() for m in HOST_RE.findall(read_text(p))):
            d.setdefault(h, set()).add(os.path.basename(p))
    return d


def errata_index(text):
    out = []
    for line in text.splitlines():
        m = re.match(r"^## Errata (\d+): (.*)", line)
        if m:
            out.append((int(m.group(1)), m.group(2)[:110]))
            continue
        m = re.match(r"^(\d+)\. (\d{4}-\d{2}-\d{2}) (.*)", line)
        if m:
            out.append((int(m.group(1)), m.group(3)[:110]))
    out.sort(key=lambda x: x[0])
    return out


def db_report(path):
    lines = []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        tabs = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table' and name != 'sqlite_sequence' order by name")]
        for t in tabs:
            cols = [r[1] for r in con.execute('pragma table_info("%s")' % t)]
            try:
                n = con.execute('select count(*) from "%s"' % t).fetchone()[0]
            except Exception:
                n = "?"
            lines.append("  - %s (%s rows): %s" % (t, n, ", ".join(cols)))
        con.close()
    except Exception as e:
        lines.append("  - unreadable: %s" % type(e).__name__)
    return lines


def git(root, *args):
    try:
        r = subprocess.run(["git"] + list(args), cwd=root, capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def version_of(pkg):
    try:
        from importlib import metadata
        return metadata.version(pkg)
    except Exception:
        return "not installed"


def leak_check(text, env_pairs):
    for k, v in env_pairs:
        if SECRET_NAME_RE.search(k) and len(v) >= 6 and v in text:
            return "the value of %s appears in the output" % k
    if SECRET_RE.search(text):
        return "a secret-like string appears in the output"
    return None


def build(root, env_pairs, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    L = []
    A = L.append
    files = code_files(root)
    uses = key_usage([k for k, _ in env_pairs], files)
    A("# HEX MANIFEST (generated facts, no secrets)")
    A("")
    A("Generated %s UTC by make_manifest.py. Regenerate weekly. HANDOFF.md holds the rules and the status."
      % now.strftime("%Y-%m-%d %H:%M"))
    A("")
    A("## 1. Environment")
    A("- python %s | %s %s" % (platform.python_version(), platform.system(), platform.machine()))
    A("- numpy %s | requests %s | python-dotenv %s"
      % (version_of("numpy"), version_of("requests"), version_of("python-dotenv")))
    A("")
    A("## 2. Git")
    br = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if br:
        A("- branch %s | HEAD %s" % (br, git(root, "log", "-1", "--format=%h %ad", "--date=iso")))
        A("- commits %s | unpushed %s" % (git(root, "rev-list", "--count", "HEAD"),
                                          git(root, "rev-list", "--count", "origin/%s..HEAD" % br) or "unknown"))
        A("- remote: %s" % re.sub(r"//[^@/]*@", "//***@", git(root, "remote", "get-url", "origin")))
        A("- last 15 commits:")
        for ln in git(root, "log", "--oneline", "-n", "15").splitlines():
            A("  - " + ln)
    else:
        A("- no git data")
    A("")
    A("## 3. API inventory (names only; values are never written here)")
    A("")
    A("Variables in .env (and the code files that mention each name):")
    for k, v in env_pairs:
        A("- %s: %s | %s" % (k, "set" if v else "empty",
                             ", ".join(uses.get(k, [])[:6]) or "not referenced by name in any .py file"))
    A("")
    A("External hosts mentioned in code (host: files):")
    hs = hosts(files)
    for h in sorted(hs):
        if h != "localhost":
            A("- %s: %s" % (h, ", ".join(sorted(hs[h])[:4])))
    A("")
    A("## 4. Tracked files (path | bytes | sha256[:16]); FROZEN = never edit by hand")
    tracked = [p for p in git(root, "ls-files").splitlines() if p]
    if not tracked:
        A("(git not available)")
    for p in tracked:
        fp = os.path.join(root, p)
        if os.path.isfile(fp):
            nm = os.path.basename(p)
            tag = " FROZEN" if (nm in FROZEN_NAMES or "_spec" in nm) else ""
            A("- %s | %d | %s%s" % (p, os.path.getsize(fp), sha16(fp), tag))
    A("")
    A("## 5. Files present but NOT in git (names and sizes; contents are never listed)")
    trk = set(tracked)
    for n in sorted(os.listdir(root)):
        fp = os.path.join(root, n)
        if not os.path.isfile(fp) or n in trk or BACKUP_RE.search(n) or n == "HEX_MANIFEST.md":
            continue
        line = "- %s | %d bytes" % (n, os.path.getsize(fp))
        if n in ("harness.db", "experiments.json"):
            line += " | sha256[:16] %s" % sha16(fp)
        A(line)
    A("")
    A("## 6. Databases (read-only: tables, row counts, columns)")
    for p in sorted(glob.glob(os.path.join(root, "*.db"))):
        A("")
        A("### " + os.path.basename(p))
        for ln in db_report(p):
            A(ln)
    A("")
    A("## 7. Errata index (number: title)")
    ep = os.path.join(root, "batch1_errata_v1.md")
    if os.path.isfile(ep):
        for n, t in errata_index(read_text(ep)):
            A("- %d: %s" % (n, t))
    A("")
    A("## 8. Daily routine (daily.sh)")
    dp = os.path.join(root, "daily.sh")
    if os.path.isfile(dp):
        A("```")
        A(read_text(dp).rstrip())
        A("```")
    A("")
    A("## 9. How to rebuild")
    A(RESTORE)
    return "\n".join(L) + "\n"


def run():
    pairs = parse_env(os.path.join(HERE, ".env"))
    text = build(HERE, pairs)
    bad = leak_check(text, pairs)
    if bad:
        print("ABORT: %s; nothing written" % bad)
        sys.exit(1)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, OUT)
    print("wrote HEX_MANIFEST.md: %d lines, %d bytes; .env names listed: %d"
          % (text.count("\n"), len(text.encode("utf-8")), len(pairs)))


def selftest():
    with tempfile.TemporaryDirectory() as td:
        env = os.path.join(td, ".env")
        with open(env, "w") as f:
            f.write('# c\nexport TEST_KEY="supersecretvalue123"\nOTHER=abc\nbad line\n')
        pairs = parse_env(env)
        assert pairs == [("TEST_KEY", "supersecretvalue123"), ("OTHER", "abc")], pairs
        assert parse_env(os.path.join(td, "nope")) == []
        with open(os.path.join(td, "a.py"), "w") as f:
            f.write('import os\nos.getenv("TEST_KEY")\nU = "https://api.example-host.com/v1/x"\n')
        for n in ("a.py.bak_old", "b.py.before_x_20260101.py", "c.tmp"):
            with open(os.path.join(td, n), "w") as f:
                f.write('os.getenv("TEST_KEY") https://hidden-host.com/')
        files = code_files(td)
        assert [os.path.basename(p) for p in files] == ["a.py"], files
        assert key_usage(["TEST_KEY", "NOPE"], files) == {"TEST_KEY": ["a.py"], "NOPE": []}
        assert sorted(hosts(files)) == ["api.example-host.com"]
        with open(os.path.join(td, "abc.txt"), "w") as f:
            f.write("abc")
        assert sha16(os.path.join(td, "abc.txt")) == "ba7816bf8f01cfea"
        sample = "## Errata 52: history search (display only)\n- x\n48. 2026-10-18 Held-plan grader rules (approved)\nnot a heading\n"
        assert errata_index(sample) == [(48, "Held-plan grader rules (approved)"),
                                        (52, "history search (display only)")], errata_index(sample)
        dbp = os.path.join(td, "t.db")
        con = sqlite3.connect(dbp)
        con.execute("create table x(a, b)")
        con.executemany("insert into x values(?,?)", [(1, 2), (3, 4)])
        con.commit()
        con.close()
        assert db_report(dbp) == ["  - x (2 rows): a, b"], db_report(dbp)
        assert db_report(os.path.join(td, "missing.db"))[0].startswith("  - unreadable")
        text = build(td, pairs, datetime.datetime(2026, 11, 9, 12, 0, tzinfo=datetime.timezone.utc))
        assert "- TEST_KEY: set | a.py" in text and "- api.example-host.com: a.py" in text, text
        assert "supersecretvalue123" not in text and "hidden-host" not in text
        assert "no git data" in text and "### t.db" in text and "x (2 rows)" in text
        assert "Generated 2026-11-09 12:00 UTC" in text and "## 9. How to rebuild" in text
        assert leak_check(text, pairs) is None
        assert leak_check(text + " supersecretvalue123", pairs) is not None
        assert leak_check("x tvly-abcdefghij12345", []) is not None
        assert leak_check("short ab", [("K_KEY", "ab")]) is None
        assert leak_check("a plain https://api.binance.com value", [("BASE_URL", "https://api.binance.com")]) is None
    print("SELFTEST OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"selftest": selftest, "run": run}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
