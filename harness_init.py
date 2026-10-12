import os, sys, json, sqlite3
import harness_spec as S

G, R, X = "\033[92m", "\033[91m", "\033[0m"
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "harness.db")


def build(path, ddl):
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys=ON")
    for s in ddl:
        c.execute(s)
    c.commit()
    return c


def refused(c, sql, args=()):
    try:
        c.execute(sql, args)
        return False
    except sqlite3.DatabaseError:
        return True


def selfcheck(ddl):
    c = build(":memory:", ddl)
    out = []
    chk = lambda n, ok: (out.append(bool(ok)), print((G + "PASS " if ok else R + "FAIL ") + n + X))
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    chk("21 triggers exist", len(names) == 21 and all(("%s_no_update" % t in names and "%s_no_delete" % t in names) for t in S.TABLES))
    chk("foreign keys are ON", c.execute("PRAGMA foreign_keys").fetchone()[0] == 1)
    chk("outcome for an unregistered hypothesis refused", refused(c, "INSERT INTO hypothesis_outcomes VALUES('nope','t','x',NULL)"))
    c.execute("INSERT INTO strategies VALUES('s','fam','t')")
    c.execute("INSERT INTO families VALUES('fam','q',0.01,'t')")
    c.execute("INSERT INTO hypotheses VALUES('h','fam','s','hash','t')")
    c.execute("INSERT INTO hypothesis_outcomes VALUES('h','t','INCONCLUSIVE',NULL)")
    c.execute("INSERT INTO runs VALUES('r','s','hash','historical',1,'c','t')")
    c.execute("INSERT INTO spec_versions VALUES('s','hash','t','{}')")
    c.execute("INSERT INTO health_events VALUES('s','t','dd',0.1,0.2,'none')")
    c.execute("INSERT INTO status_log VALUES('s','NONE','RESEARCH','t','start','hash')")
    c.execute("INSERT INTO observations VALUES('s','hash','r','d1',0,0.0,0,NULL)")
    for t in S.TABLES:
        chk("%s: update refused" % t, refused(c, "UPDATE %s SET rowid=rowid" % t))
        chk("%s: delete refused" % t, refused(c, "DELETE FROM %s" % t))
    chk("bad run kind refused", refused(c, "INSERT INTO runs VALUES('r2','s','h','bogus',0,'c','t')"))
    chk("data_seen_before must be 0 or 1", refused(c, "INSERT INTO runs VALUES('r3','s','h','forward',2,'c','t')"))
    return all(out)


def main():
    if not os.path.exists(S.FILE):
        sys.exit(R + "harness spec not frozen" + X)
    st = json.load(open(S.FILE))
    if S.hs(S.spec(st["spec"]["frozen_at_utc"])) != st["hash"] or S.hs(st["spec"]) != st["hash"]:
        sys.exit(R + "frozen harness spec does not match its hash: stop" + X)
    ddl = st["spec"]["database"]["ddl"]
    seed = {(a, b) for a, bs in st["spec"]["lifecycle"]["allowed"].items() for b in bs}
    if not selfcheck(ddl):
        sys.exit(R + "self-checks failed: harness.db NOT created" + X)
    c = sqlite3.connect(":memory:")
    for s in ddl:
        c.execute(s)
    if {(a, b) for a, b in c.execute("SELECT from_status,to_status FROM allowed_transitions")} != seed:
        sys.exit(R + "transition seed differs from the frozen lifecycle" + X)
    if os.path.exists(DB):
        sys.exit(R + "harness.db already exists: refusing to touch it" + X)
    build(DB, ddl).close()
    print(G + "created harness.db from the frozen spec (spec %s)" % st["hash"][:16] + X)


if __name__ == "__main__":
    main()
