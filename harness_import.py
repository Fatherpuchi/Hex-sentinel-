import os, sys, json, hashlib, sqlite3, shutil
from datetime import datetime, timezone
import harness_spec as H

G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
HERE = os.path.dirname(os.path.abspath(__file__))
DB, LOG = os.path.join(HERE, "harness.db"), os.path.join(HERE, "experiments.json")
CARRY_SPEC = os.path.join(HERE, "carry_spec_v2_3.json")
FAMILIES = {"reversal after extremes": "After a large 24h move, does price reverse over the next 24h by more than costs?",
            "continuation after momentum": "Does a 24h move continue over the next 24h by more than costs, and does filtering add value?",
            "funding carry": "Does holding spot long against a perp short earn funding that survives costs and liquidation risk?"}
ALPHA = 0.01
PLAN = [dict(eid="E001", sid="fade24", fam="reversal after extremes", final="REJECTED"),
        dict(eid="E002", sid="momentum_ladder_r1_3", fam="continuation after momentum", final="RESEARCH"),
        dict(eid="E004", sid="carry_v2_3", fam="funding carry", final="WATCH")]


def sha(b): return hashlib.sha256(b).hexdigest()
def canon(d): return sha(json.dumps(d, sort_keys=True).encode())


def sources():
    log = json.load(open(LOG))
    by = {e["id"]: e for e in log}
    for k in ("E001", "E002", "E004"):
        if k not in by:
            sys.exit(R + "experiments.json has no entry " + k + X)
    e1, e2, e4 = by["E001"], by["E002"], by["E004"]
    bad = []
    if not (e1.get("name") == "fade24" and e1.get("result") == "FAILED"): bad.append("E001 is not the failed fade24 entry")
    if not (e2.get("type") == "experiment" and e2.get("status") == "FAIL" and e2.get("spec_hash")): bad.append("E002 is not the failed momentum ladder experiment")
    elif canon(e2["spec"]) != e2["spec_hash"]: bad.append("E002 stored spec does not hash to its spec_hash")
    hist = json.load(open(CARRY_SPEC))
    if not (e4.get("type") == "historical_screen" and str(e4.get("status", "")).startswith("DESCRIPTIVE SCREEN COMPLETED")): bad.append("E004 is not the carry screen entry")
    if canon(hist["spec"]) != hist["hash"] or e4.get("historical_spec_hash") != hist["hash"]: bad.append("carry v2.3 spec hash does not match E004")
    import carry_verify
    ok, msg = carry_verify.verify()
    if not ok: bad.append("carry_verify: " + msg)
    st = json.load(open(H.FILE))
    if H.hs(H.spec(st["spec"]["frozen_at_utc"])) != st["hash"] or H.hs(st["spec"]) != st["hash"]: bad.append("harness spec does not match its hash")
    if bad:
        sys.exit(R + "REFUSED:\n  " + "\n  ".join(bad) + X)
    unmet = sorted(k for k, v in e4["thresholds"].items() if v is False)
    return dict(
        E001=dict(spec_hash=canon(e1), spec_json=json.dumps(e1, sort_keys=True), frozen=e1["timestamp"], ts=e1["timestamp"], code=None,
                  outcome="REJECTED: net return per trade negative on about 10,000 events",
                  note="no frozen spec existed for E001; spec_hash is the sha256 of the log entry itself, not of a pre-registered spec"),
        E002=dict(spec_hash=e2["spec_hash"], spec_json=json.dumps(e2["spec"], sort_keys=True), frozen=e2["timestamp"], ts=e2["timestamp"], code=json.dumps(e2.get("code_hash")),
                  outcome="INCONCLUSIVE: primary gate not met; minimum detectable effect about +0.20% per trade, so a null is not a rejection",
                  note="the log entry E002 records status FAIL; that original is preserved unchanged in experiments.json"),
        E004=dict(spec_hash=hist["hash"], spec_json=json.dumps(hist["spec"], sort_keys=True), frozen=hist["spec"]["frozen_at_utc"], ts=e4["timestamp"], code=e4.get("code_sha256"),
                  outcome="SCREEN NOT PASSED: criteria %s unmet" % ",".join(unmet), note="descriptive screen, no significance claimed; forward collection continues separately"))


def do_import(c, src, now):
    for fam, q in FAMILIES.items():
        c.execute("INSERT INTO families VALUES(?,?,?,?)", (fam, q, ALPHA, now))
    for p in PLAN:
        s = src[p["eid"]]
        c.execute("INSERT INTO strategies VALUES(?,?,?)", (p["sid"], p["fam"], now))
        c.execute("INSERT INTO spec_versions VALUES(?,?,?,?)", (p["sid"], s["spec_hash"], s["frozen"], s["spec_json"]))
        hid = "H-" + p["eid"]
        c.execute("INSERT INTO hypotheses VALUES(?,?,?,?,?)", (hid, p["fam"], p["sid"], s["spec_hash"], now))
        c.execute("INSERT INTO hypothesis_outcomes VALUES(?,?,?,?)", (hid, s["ts"], s["outcome"], s["note"]))
        c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (p["eid"], p["sid"], s["spec_hash"], "historical", 1, s["code"], s["ts"]))
        c.execute("INSERT INTO status_log VALUES(?,?,?,?,?,?)", (p["sid"], "NONE", "RESEARCH", now, "migrated historical record %s; original id and hash preserved" % p["eid"], s["spec_hash"]))
        if p["final"] != "RESEARCH":
            c.execute("INSERT INTO status_log VALUES(?,?,?,?,?,?)", (p["sid"], "RESEARCH", p["final"], now, s["outcome"], s["spec_hash"]))


def validate(c, label):
    ok = []
    def chk(n, v, d=""):
        ok.append(bool(v)); print((G + "PASS " if v else R + "FAIL ") + label + ": " + n + X + (D + "  " + str(d) + X if d else ""))
    cnt = lambda t: c.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
    exp = dict(families=3, strategies=3, spec_versions=3, hypotheses=3, hypothesis_outcomes=3, runs=3, status_log=5, observations=0, health_events=0)
    for t, n in exp.items():
        chk("%s has %d rows" % (t, n), cnt(t) == n, cnt(t))
    for p in PLAN:
        cur = c.execute("SELECT to_status FROM status_log WHERE strategy_id=? ORDER BY rowid DESC LIMIT 1", (p["sid"],)).fetchone()[0]
        chk("%s latest status is %s" % (p["sid"], p["final"]), cur == p["final"], cur)
    chk("foreign_key_check is empty", c.execute("PRAGMA foreign_key_check").fetchall() == [])
    chk("all runs marked data_seen_before=1", c.execute("SELECT COUNT(*) FROM runs WHERE data_seen_before<>1").fetchone()[0] == 0)
    chk("alpha_family is 0.01 for every family", c.execute("SELECT COUNT(*) FROM families WHERE alpha_family<>0.01").fetchone()[0] == 0)
    return all(ok)


def preview(c):
    print(f"{C}-- preview{X}")
    for r in c.execute("SELECT strategy_id,family FROM strategies"): print("strategy", r)
    for r in c.execute("SELECT strategy_id,from_status,to_status,substr(reason,1,70) FROM status_log"): print("status  ", r)
    for r in c.execute("SELECT hyp_id,outcome FROM hypothesis_outcomes"): print("outcome ", r[0], r[1][:90])
    for r in c.execute("SELECT strategy_id,substr(spec_hash,1,16),length(spec_json) FROM spec_versions"): print("spec    ", r)


def memdb():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    for s in json.load(open(H.FILE))["spec"]["database"]["ddl"]: c.execute(s)
    return c


def main(mode):
    src = sources()
    now = datetime.now(timezone.utc).isoformat()
    m = memdb()
    do_import(m, src, now); m.commit()
    preview(m)
    good = validate(m, "dry run")
    try:
        do_import(m, src, now); again = False
    except sqlite3.DatabaseError:
        again = True
    print((G + "PASS " if again else R + "FAIL ") + "dry run: a second import is refused" + X)
    if not (good and again):
        sys.exit(R + "validation failed: nothing written" + X)
    if mode != "commit":
        print(Y + "dry run only. harness.db was not opened. To write: python3 harness_import.py commit" + X)
        return
    if not os.path.exists(DB): sys.exit(R + "harness.db missing" + X)
    c = sqlite3.connect(DB); c.execute("PRAGMA foreign_keys=ON")
    if c.execute("SELECT COUNT(*) FROM strategies").fetchone()[0] or c.execute("SELECT COUNT(*) FROM families").fetchone()[0]:
        sys.exit(R + "harness.db is not empty: refusing (already imported?)" + X)
    schema = lambda k: sorted((r[0], r[1]) for r in k.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    if schema(c) != schema(memdb()): sys.exit(R + "harness.db schema differs from the frozen DDL: refusing" + X)
    shutil.copy(DB, DB + ".bak_pre_import")
    try:
        do_import(c, src, now)
        if not validate(c, "real db (before commit)"):
            c.rollback(); sys.exit(R + "post-import validation failed: rolled back" + X)
        c.commit()
    except Exception as e:
        c.rollback(); sys.exit(R + "import failed, rolled back: %r" % e + X)
    log = json.load(open(LOG))
    entry = dict(id="E%03d" % (len(log) + 1), timestamp=now, type="registry_import", name="harness registry import of E001, E002, E004",
                 harness_spec_hash=json.load(open(H.FILE))["hash"], families=list(FAMILIES), strategies=[p["sid"] for p in PLAN],
                 limitations=["E001 had no frozen spec; its spec_hash is the hash of the log entry", "hypotheses were registered retroactively at import time, so they count toward m but were not registered before their tests"],
                 prev_hash=sha(json.dumps(log, sort_keys=True).encode()))
    log.append(entry)
    json.dump(log, open(LOG + ".tmp", "w"), indent=1); os.replace(LOG + ".tmp", LOG)
    print(G + "imported into harness.db and logged as " + entry["id"] + X)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dry")
