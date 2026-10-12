import os, sys, json, hashlib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "harness_spec_v1.json")


def hs(d): return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


ALLOWED = {"NONE": ["RESEARCH"], "RESEARCH": ["WATCH", "REJECTED"], "WATCH": ["PAPER-ACTIVE", "REJECTED", "RESEARCH"],
           "PAPER-ACTIVE": ["SUSPENDED", "REJECTED"], "SUSPENDED": ["WATCH", "REJECTED"], "REJECTED": []}
TABLES = ["strategies", "spec_versions", "families", "hypotheses", "hypothesis_outcomes", "runs", "observations", "health_events",
          "status_log", "allowed_transitions"]


def ddl():
    d = [
        "CREATE TABLE strategies(strategy_id TEXT PRIMARY KEY, family TEXT NOT NULL, created_utc TEXT NOT NULL)",
        "CREATE TABLE spec_versions(strategy_id TEXT NOT NULL, spec_hash TEXT NOT NULL, frozen_at_utc TEXT NOT NULL, spec_json TEXT NOT NULL, PRIMARY KEY(strategy_id, spec_hash))",
        "CREATE TABLE families(family TEXT PRIMARY KEY, question TEXT NOT NULL, alpha_family REAL NOT NULL, defined_utc TEXT NOT NULL)",
        "CREATE TABLE hypotheses(hyp_id TEXT PRIMARY KEY, family TEXT NOT NULL, strategy_id TEXT NOT NULL, spec_hash TEXT NOT NULL, registered_utc TEXT NOT NULL)",
        "CREATE TABLE hypothesis_outcomes(hyp_id TEXT PRIMARY KEY REFERENCES hypotheses(hyp_id), test_run_utc TEXT NOT NULL, outcome TEXT NOT NULL, note TEXT)",
        "CREATE TABLE runs(run_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, spec_hash TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('historical','forward','rerun')), data_seen_before INTEGER NOT NULL CHECK(data_seen_before IN (0,1)), code_sha256 TEXT, started_utc TEXT NOT NULL)",
        "CREATE TABLE observations(strategy_id TEXT NOT NULL, spec_hash TEXT NOT NULL, run_id TEXT NOT NULL, obs_utc TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), "
        "value REAL, missing INTEGER NOT NULL CHECK(missing IN (0,1)), reason TEXT, PRIMARY KEY(strategy_id, obs_utc, revision), "
        "CHECK((missing=1 AND value IS NULL) OR (missing=0 AND value IS NOT NULL)), CHECK(revision=0 OR (reason IS NOT NULL AND length(trim(reason))>0)))",
        "CREATE TABLE health_events(strategy_id TEXT NOT NULL, obs_utc TEXT NOT NULL, rule TEXT NOT NULL, value REAL, threshold REAL, action TEXT NOT NULL)",
        "CREATE TABLE allowed_transitions(from_status TEXT NOT NULL, to_status TEXT NOT NULL, PRIMARY KEY(from_status, to_status))",
        "CREATE TABLE status_log(strategy_id TEXT NOT NULL, from_status TEXT NOT NULL, to_status TEXT NOT NULL, changed_utc TEXT NOT NULL, reason TEXT, spec_hash TEXT NOT NULL)"]
    for a, bs in ALLOWED.items():
        for b in bs:
            d.append("INSERT INTO allowed_transitions VALUES('%s','%s')" % (a, b))
    for t in TABLES:
        for op in ("UPDATE", "DELETE"):
            d.append("CREATE TRIGGER %s_no_%s BEFORE %s ON %s BEGIN SELECT RAISE(ABORT,'%s is append-only'); END" % (t, op.lower(), op, t, t))
    d.append("CREATE TRIGGER status_log_valid BEFORE INSERT ON status_log WHEN NEW.reason IS NULL OR length(trim(NEW.reason))=0 "
             "OR NOT EXISTS(SELECT 1 FROM allowed_transitions a WHERE a.from_status=NEW.from_status AND a.to_status=NEW.to_status) "
             "OR COALESCE((SELECT s.to_status FROM status_log s WHERE s.strategy_id=NEW.strategy_id ORDER BY s.rowid DESC LIMIT 1),'NONE')<>NEW.from_status "
             "BEGIN SELECT RAISE(ABORT,'invalid status transition, missing reason, or from_status does not match current status'); END")
    return d


def spec(frozen_at):
    return {
        "version": "harness-v1", "frozen_at_utc": frozen_at,
        "changes_from_reviewed_draft": [
            "transitions and append-only behaviour are enforced by database triggers, not only by text",
            "observations carry a revision and a mandatory reason for corrections",
            "hypothesis outcomes moved to their own insert-only table",
            "E002 recorded as INCONCLUSIVE, not as a proven rejection; outcome and lifecycle status kept separate",
            "default forward minimum set to 14 weeks; alpha_family stays 0.01; WATCH -> RESEARCH allowed with a documented reason"],
        "purpose": "One fair testing machine. Strategies bring frozen rules; the harness gives all of them the same data rules, costs, benchmarks, logging and forward tracking. "
                   "It is built to find out which strategies deserve trust, not to find a winner.",
        "defaults": {"approved_list": "EMPTY at v1", "when_nothing_qualifies": "NO TRADE",
                     "mode": "research and paper only; the harness places no orders and has no exchange credentials"},
        "scope": {
            "strategy_interface": "one common format for old and new strategies",
            "registered_history": [
                {"id": "E001", "name": "fade24", "outcome": "REJECTED: failed money criteria on about 10,000 events", "lifecycle_status": "REJECTED"},
                {"id": "E002", "name": "momentum ladder rungs 1-3",
                 "outcome": "INCONCLUSIVE: primary gate not met; minimum detectable effect about +0.20% per trade, so a null is not a rejection; the original result is preserved as logged",
                 "lifecycle_status": "RESEARCH"},
                {"id": "E003", "name": "carry v2.2 calibration", "outcome": "CALIBRATION FAILED: NO BLOCK QUALIFIES; no inferential claim possible for that design", "lifecycle_status": "none (a calibration, not a strategy)"},
                {"id": "E004", "name": "carry v2.3 historical screen", "outcome": "SCREEN NOT PASSED: criteria 3,4,5,6 unmet; forward collection continues", "lifecycle_status": "WATCH"}],
            "migration_rule": "historical records are copied in as read-only and keep their original ids and hashes. They are never re-run silently. "
                              "A rerun is a new experiment with a new run_id that discloses the data was already examined. Each migrated strategy enters through NONE -> RESEARCH and then its listed status, with reasons logged.",
            "known_flaws_carried_forward": [
                "E004 closest-approach ratio kept updating after liquidation, so the reported minimum (-29.3) is a reporting artifact; event counts and returns do not depend on it",
                "the nine implementation readings in carry_screen.py were not in the frozen text and were not reviewed before E004 ran"]},
        "strategy_interface": {
            "frozen_before_any_run": ["strategy_id", "rule text and parameters", "universe and its selection rule", "data window and global cutoff", "cost model (fees, slippage, funding)",
                                      "benchmark and how it is credited", "mechanism sentence (who pays and why it should persist)", "family",
                                      "effective-sample assumption and how it was justified", "power statement (smallest effect the design could detect)", "pass bar",
                                      "descriptive-only or inferential, with the calibration that licenses inference",
                                      "forward minimum in weeks (default 14, longer allowed, never shorter)",
                                      "health-monitor thresholds with justification (required before PAPER-ACTIVE, may be added after a historical screen)"],
            "signal_is_a_suggestion": "a strategy output never authorizes an order",
            "determinism": "same stored data and same spec give the same result"},
        "database": {
            "file": "harness.db (created by a later script, not by this spec)",
            "ddl": ddl(),
            "rules": ["every row carries strategy_id, spec_hash and a timestamp",
                      "one observation per strategy, time and revision (primary key); duplicates are rejected",
                      "a missing value is stored with missing=1 and no value, never as a zero return",
                      "a correction is a new row with revision+1 and a non-empty reason; the highest revision is current; all revisions are kept",
                      "every table is append-only, enforced by triggers; no row is updated or deleted",
                      "status changes are validated by trigger: allowed pair, matching current status, non-empty reason",
                      "the later schema script must enable PRAGMA foreign_keys=ON, and its self-checks must prove each trigger fires and each CHECK rejects bad rows",
                      "the allowed_transitions seed must equal lifecycle.allowed in this spec; a self-check compares them",
                      "the experiment log stays in experiments.json with its hash chain"]},
        "lifecycle": {
            "statuses": ["RESEARCH", "WATCH", "PAPER-ACTIVE", "SUSPENDED", "REJECTED"],
            "initial": "NONE -> RESEARCH only",
            "allowed": ALLOWED,
            "rules": ["REJECTED is terminal; changing a rule creates a new strategy_id and a new spec hash",
                      "every transition, including WATCH -> RESEARCH, needs a documented reason and is logged with the spec hash; earlier status history is never altered",
                      "PAPER-ACTIVE requires: a frozen spec, qualification under its own frozen pass bar, and frozen justified health thresholds",
                      "an experiment outcome (for example INCONCLUSIVE) is recorded separately from lifecycle status",
                      "no AI model can change a status or override a threshold"]},
        "statistics": {
            "families": "defined by research question, not by calendar year, and written to the families table before the first test in them. Examples of questions, not frozen families: continuation after momentum, reversal after extremes, funding carry.",
            "alpha_family_default": 0.01,
            "correction": "Bonferroni: alpha_individual = alpha_family / m",
            "counting_m": "m counts every hypothesis registered in the family, failures and abandoned ones included; rows cannot be deleted",
            "registration_timing": "a hypothesis is registered before its test runs. Adding hypotheses can only tighten thresholds: an earlier result is re-judged against the tighter alpha and is never upgraded.",
            "no_method_switching": "the correction method is not changed after seeing which one passes",
            "inference_licence": "an inferential gate is allowed only if its false-positive rate was checked on synthetic worlds matching that design's dependence structure, with limits fixed in advance (the fade_calib and carry_calib pattern). Otherwise the strategy is descriptive and forward only.",
            "effective_sample": "each strategy states its own effective-sample assumption. The carry finding (a few independent regimes in 4.7 years) is a limit of that design, not a universal number.",
            "historical_data": "all stored history counts as seen. A historical result is a screen. Only data after a strategy's freeze timestamp is forward."},
        "forward_tracking": {
            "start": "each strategy's own freeze timestamp",
            "minimum": "14 weeks by default; a spec may require longer in advance and may never go shorter. carry-forward-v1 keeps its own frozen 26 weeks.",
            "limit": "14 weeks is a floor for a first review, not confirmation: it cannot show that persistent regimes were sampled, and a favourable stretch can still be inconclusive",
            "review": "at the minimum, review without changing rules; if ambiguous keep collecting; never rescue",
            "collector": "one collector writes per-strategy observations; it verifies every spec hash before collecting and refuses on any mismatch; it never writes into a spec",
            "carry": "carry_forward.db keeps collecting under carry-forward-v1; migration of its rows into harness.db is a later, separate step with its own check"},
        "correlation": {"report": "for every pair of strategies, correlation of daily values on shared observation days, with the number of shared days",
                        "limit": "overlap is stated; a correlation on a short shared period is reported as unstable",
                        "purpose": "to show whether several strategies are really one bet"},
        "health_monitor": {
            "mechanism_now": ["maximum drawdown against the frozen limit", "deterioration against the frozen benchmark over a frozen window", "deterioration in net expectancy",
                              "missing or unreliable data", "cost drift against assumed costs", "unexpected liquidation or risk events"],
            "thresholds": "numerical thresholds are justified and frozen per strategy before its forward evaluation; no strategy without them can be PAPER-ACTIVE",
            "behaviour": "a breach moves the strategy to SUSPENDED by its frozen rule; a few losing trades alone are not a breach"},
        "risk_gate": {"flow": "frozen strategy -> evaluation -> qualification -> paper tracking -> health monitor -> risk gate",
                      "independence": "the gate is separate from every strategy and from every AI model",
                      "relation_to_sentinel": "Sentinel's predict, Groq/Gemini voting and paper trades are untouched until some strategy has qualified and a separate spec connects them"},
        "not_yet_decided": ["family definitions", "the exact observation value stored per strategy (daily net return on capital proposed)",
                            "whether and when to migrate carry_forward.db into harness.db",
                            "real fee tier, H and maintenance margin remain unverified provisional assumptions"],
        "mandatory_wording": "This is a testing framework. It makes no claim that any strategy is profitable, and no strategy has qualified."}


def main(mode):
    if os.path.exists(FILE):
        st = json.load(open(FILE))
        h = hs(spec(st["spec"]["frozen_at_utc"]))
        print(("\033[92mharness spec unchanged: " if h == st["hash"] else "\033[91mHARNESS SPEC CHANGED: ") + h + "\033[0m")
        return
    if mode == "freeze":
        fz = datetime.now(timezone.utc).isoformat()
        s = spec(fz)
        json.dump({"hash": hs(s), "spec": s}, open(FILE, "w"), indent=1)
        print("\033[96mfrozen harness-v1 at %s\nsha256 %s\033[0m" % (fz, hs(s)))
        return
    print(json.dumps(spec("SET AT FREEZE"), indent=1))
    print("\033[93mNothing frozen. Hashes differ at freeze because the timestamp is inside. Freeze with: python3 harness_spec.py freeze\033[0m")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "show")
