import os, sys, json, copy, hashlib, sqlite3
from datetime import datetime, timezone
from carry_spec import SPEC as V21, spec_hash as h21
from carry_spec22 import spec_hash as h22

HERE = os.path.dirname(os.path.abspath(__file__))
HIST_FILE, FWD_FILE = os.path.join(HERE, "carry_spec_v2_3.json"), os.path.join(HERE, "carry_forward_spec_v1.json")
LOG, FDB, KDB = os.path.join(HERE, "experiments.json"), os.path.join(HERE, "funding.db"), os.path.join(HERE, "carry_klines.db")
V21_HASH = "4f857ebdd3873c27c8c58ca24c0326b9ede5080faac009f731915f4f11fda237"
V22_HASH = "f9bbfb1d1f3d3d485a32ad20cad4fff1d275e38bceb898dcbc0560d68823a1df"
E003_STATUS = "CALIBRATION FAILED: NO BLOCK QUALIFIES"
HOUR, DAY = 3600000, 86400000
PLACEHOLDER = "SET AT FREEZE (one UTC timestamp shared by both specs)"
if h21() != V21_HASH or h22() != V22_HASH:
    raise SystemExit("v2.1 or v2.2 changed since freezing: stop, the record must stay intact.")

WORDING = "This describes what happened historically on seen data. It is not evidence of a long-term edge. No statistical significance is claimed."


def hs(d): return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
def iso(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def e003_entry():
    try:
        for e in json.load(open(LOG)):
            if e.get("spec_hash") == V22_HASH and e.get("status") == E003_STATUS:
                return e.get("id")
    except Exception:
        pass
    return None


def data_end():
    """Timestamps only: earliest last candle close / last funding record across coins, floored to UTC midnight."""
    k, f = sqlite3.connect(KDB), sqlite3.connect(FDB)
    ends = [k.execute(f"SELECT MIN(m) FROM (SELECT MAX(t) m FROM {t} GROUP BY sym)").fetchone()[0] + HOUR for t in ("sp", "pp", "mk")]
    ends.append(f.execute("SELECT MIN(m) FROM (SELECT MAX(t) m FROM f GROUP BY sym)").fetchone()[0])
    return min(ends) // DAY * DAY


def historical(end_ms, frozen_at):
    return {
        "version": "carry-v2.3-historical-screen",
        "frozen_at_utc": frozen_at,
        "mechanism": V21["mechanism"],
        "universe": V21["universe"],
        "window_start": "each coin is eligible from its first settlement hour with spot, perp, mark and funding all present (Rule B)",
        "global_cutoff": {"window_end_utc_ms": end_ms, "window_end": iso(end_ms) + " (exclusive)",
                          "rule": "only data strictly before the cutoff is used; the cutoff is fixed from timestamps only and never moves for any coin",
                          "coverage_reporting": "per coin, report the first and last valid observation actually used and any gaps; a coin with data ending before "
                                                "the cutoff is reported as such, not extended and not allowed to shorten the window"},
        "disclosures": ["funding used as a direction signal in an earlier replay on 14 coins", "historical screen on seen data",
                        "survivorship: today's listed coins", "dataset hashes recorded at the real run"],
        "portfolio_accounting": {
            "capital": "100 units of total portfolio capital at the first rebalance; this is total capital, not per coin",
            "allocation": "on the first 00:00 UTC of each month (the monthly rebalance), total equity at that moment is split equally across coins eligible that day; "
                          "each coin's slice is 50% spot long and 50% perp margin, equal notional (1x)",
            "new_coins": "a coin that becomes eligible mid-month is not added until the next monthly rebalance. A coin eligible before the portfolio's first rebalance "
                         "enters at that rebalance. There is no mid-month entry. Each coin's entry date and days waited are reported.",
            "coin_data_ends": "if a coin's data ends or it is delisted before the cutoff, its position is closed at the last valid price with full costs; "
                              "the proceeds stay in cash until the next monthly rebalance, then are redistributed equally",
            "liquidation": "the perp leg is closed per the liquidation model; the spot leg stays open; the slice stays with that coin during the 7-day wait and is not "
                           "redistributed mid-month; the coin rejoins at the next monthly rebalance if still eligible",
            "idle_cash": "earns 0, not H. The output must report the average idle share of equity",
            "equity_curve": "a single portfolio equity curve (all slices plus cash), daily at 00:00 UTC. Every weekly, monthly, drawdown, annual and rolling-window figure "
                            "is computed from it. Daily return = change in total equity / previous day's equity. Per-coin figures use each coin's own slice-equity curve."},
        "benchmark": "H is a descriptive comparison only: annualized net return of the whole portfolio equity curve, idle cash included, against H_annual. "
                     "No H is credited to any position or to idle cash.",
        "H_annual": 0.04, "H_status": V21["H_status"],
        "fees": copy.deepcopy(V21["fees"]), "funding": V21["funding"],
        "rebalance": "first 00:00 UTC of each month; restore equal notional and the 50/50 split inside each slice; costs on traded notional; no drift-triggered rebalance; "
                     "no mid-month entry (see portfolio_accounting.new_coins)",
        "price_pnl": V21["price_pnl"],
        "liquidation": copy.deepcopy(V21["liquidation"]),
        "liquidity_rank": V21["liquidity_rank"],
        "liquidity_limitation": "the ranking period ends 2026-10-08, two days before the historical cutoff, and starts 2023-11-11, after many coin windows begin; stated limitation, not a gate",
        "definitions": {
            "positive_net_return": "total return on capital after fees, slippage, funding and liquidation costs is strictly > 0, with no H credit",
            "zero_return": "neither positive nor negative",
            "annualization": "(1 + total return) ** (365 / calendar days) - 1",
            "above_H": "annualized net return strictly greater than H_annual",
            "full_calendar_year": "a calendar year is full-year if, on every day of that year inside the window, at least 80% of the eligible universe was active; "
                                  "the fraction per year is printed so no year is silently classified; thresholds apply to full years only; other years are labelled partial",
            "rolling_windows": "26 consecutive weeks ending on a Sunday at 24:00 UTC, stepping one week, so windows overlap and are not independent; only windows fully inside "
                               "the equity curve count; incomplete windows are excluded and their number reported; a window is positive if end equity is strictly greater "
                               "than start equity; a missing day is carried at the previous equity and the count reported; share = positive windows / counted windows"},
        "supersedes": {"version": "carry-v2.2", "hash": V22_HASH,
                       "reason": "v2.2 calibration failed (NO BLOCK QUALIFIES): block-bootstrap intervals were unreliable under persistent funding regimes. "
                                 "All inference was removed; the screen is descriptive only. Accounting rules are unchanged from v2.1 except the portfolio rules above."},
        "mandatory_wording": WORDING,
        "prohibited": ["p-values", "confidence intervals", "bootstrap", "significance gates", "any claim of historical profitability or edge"],
        "outputs_descriptive_only": [
            "net yield on total portfolio capital, total and by calendar year",
            "worst week, worst month, max drawdown on the equity curve",
            "average idle share of equity, and each coin's entry date and days waited",
            "liquidation events and closest approach at maintenance 1%, 2.5% and 5%",
            "sensitivity: slippage 0.15%; without the 5 least-liquid coins; with and without 2023-03-24",
            "share of coins with positive net return and share of rolling 26-week windows positive, as plain numbers",
            "annualized net yield compared with H, at base and at stress slippage, descriptive only",
            "per-coin coverage and the survivorship limitation",
            "realised daily sd and funding persistence of the data, for the record"],
        "original_eight_criteria_mapping": [
            {"n": 1, "original": "99.5% one-sided lower bound of annualized net return > H", "v2.3": "REMOVED: no inferential claims"},
            {"n": 2, "original": "mean > H at stress costs (slippage 0.15%, maintenance 5%)", "v2.3": "descriptive comparison with H only, not a gate"},
            {"n": 3, "original": "net return > 0 in every full calendar year", "v2.3": "screening threshold"},
            {"n": 4, "original": "zero liquidation events in the base model", "v2.3": "screening threshold"},
            {"n": 5, "original": "max drawdown <= 10% of capital", "v2.3": "screening threshold"},
            {"n": 6, "original": ">= 80% of rolling 26-week windows positive", "v2.3": "screening threshold"},
            {"n": 7, "original": ">= 55% of coins net positive", "v2.3": "screening threshold"},
            {"n": 8, "original": "same result without the 5 least-liquid coins", "v2.3": "robustness threshold: criteria 3 to 7 recomputed without those coins must still be met"}],
        "thresholds_status": "not loosened; meeting them is a descriptive screen, not evidence of an edge",
        "rung2": "NOT TESTED: its power gate was never computed. Logged as not tested, not as failed.",
        "real_data_rule": "the screening script reads funding.db and carry_klines.db only after this spec is frozen and the script passes its synthetic accounting self-checks"}


def forward(hist_hash, frozen_at, H):
    return {
        "version": "carry-forward-v1", "mode": "PAPER ONLY. No exchange orders are placed.", "mandatory_wording": WORDING,
        "historical_spec_hash": hist_hash,
        "frozen_at_utc": frozen_at, "forward_start_utc": frozen_at,
        "forward_start_rule": "the forward clock starts at the single freeze timestamp shared with the historical spec. Data between the historical cutoff "
                              "and the freeze timestamp was available while the spec was being written and counts as seen, not forward.",
        "collector_must_verify": ["recompute SHA-256 of the stored historical spec with the same canonical JSON function as the freeze script and compare with its stored hash",
                                  "forward spec's historical_spec_hash equals the historical file's hash",
                                  "recompute and compare the forward spec's own hash",
                                  "refuse to collect or evaluate if either file or experiments.json is missing or any check fails; never write into a spec file"],
        "accounting": {"portfolio_accounting": copy.deepcopy(H["portfolio_accounting"]), "funding": H["funding"], "rebalance": H["rebalance"],
                       "price_pnl": H["price_pnl"], "fees": copy.deepcopy(H["fees"]), "H_annual": H["H_annual"],
                       "benchmark": H["benchmark"], "liquidation": copy.deepcopy(H["liquidation"]),
                       "definitions": copy.deepcopy(H["definitions"]), "universe": H["universe"],
                       "status": "fees, H and maintenance are unverified provisional assumptions"},
        "missing_data": "a missing candle or funding record is logged with its timestamp; the last price is carried only for spot candles and only with a log entry; "
                        "a missing funding record is never imputed",
        "weekly_record": ["funding actually settled, with timestamps", "spot and perp prices", "cost assumptions", "net performance and annualized comparison with H",
                          "drawdown", "liquidation proximity", "average idle share", "missing data", "operational failures (collector errors, API failures)"],
        "minimum_weeks": 26,
        "review": "at 26 weeks, review without changing rules; if disappointing or ambiguous, keep collecting; never rescue",
        "rule_change": "any substantive change makes a new version with a new hash and restarts the clock",
        "limit": "26 weeks is a minimum, not proof that persistent regimes were sampled; a favourable stretch can still be inconclusive",
        "collector": "the weekly collector script is not written yet; it needs review before use"}


def build(end_ms, frozen_at):
    H = historical(end_ms, frozen_at)
    return H, forward(hs(H), frozen_at, H)


def main(mode):
    if os.path.exists(HIST_FILE):
        st = json.load(open(HIST_FILE))
        end, fz = st["spec"]["global_cutoff"]["window_end_utc_ms"], st["spec"]["frozen_at_utc"]
        H, F = build(end, fz)
        print(("\033[92mhistorical spec unchanged: " if hs(H) == st["hash"] else "\033[91mHISTORICAL SPEC CHANGED: ") + hs(H) + "\033[0m")
        if os.path.exists(FWD_FILE):
            fs = json.load(open(FWD_FILE))
            print(("\033[92mforward spec unchanged: " if hs(F) == fs["hash"] else "\033[91mFORWARD SPEC CHANGED: ") + hs(F) + "\033[0m")
        return
    end = data_end()
    if mode == "freeze":
        eid = e003_entry()
        if not eid:
            raise SystemExit(f"\033[91mNo experiments.json entry with spec_hash = v2.2 hash and status '{E003_STATUS}'. Run carry_log_e003.py first. Nothing frozen.\033[0m")
        print(f"\033[96mE003 check passed: entry {eid}\033[0m")
        fz = datetime.now(timezone.utc).isoformat()
        H, F = build(end, fz)
        json.dump({"hash": hs(H), "spec": H}, open(HIST_FILE, "w"), indent=1)
        json.dump({"hash": hs(F), "spec": F}, open(FWD_FILE, "w"), indent=1)
        print(f"\033[96mfrozen at {fz}\ncarry-v2.3 {hs(H)}\ncarry-forward-v1 {hs(F)}\033[0m")
        return
    H, F = build(end, PLACEHOLDER)
    print(f"\033[96mhistorical cutoff (exclusive): {iso(end)}   [timestamps only were read]\033[0m")
    print(f"\033[96mE003 entry: {e003_entry() or 'NOT FOUND (freeze will refuse)'}\033[0m")
    if mode in ("show", "hist"):
        print("=== HISTORICAL SPEC ===\n" + json.dumps(H, indent=1))
    if mode in ("show", "fwd"):
        print("=== FORWARD SPEC ===\n" + json.dumps(F, indent=1))
    print("\033[93mNothing frozen. Hashes differ at freeze because the timestamp is inside them. Freeze with: python3 carry_spec23.py freeze\033[0m")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "show")
