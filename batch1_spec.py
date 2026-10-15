import os, sys, json, hashlib, sqlite3
from datetime import datetime, timezone
import harness_spec as H

HERE = os.path.dirname(os.path.abspath(__file__))
FILE, FDB = os.path.join(HERE, "batch1_spec_v1.json"), os.path.join(HERE, "fade.db")
HOUR, DAY = 3600000, 86400000
PH = "SET AT FREEZE"
WORDING = "This is a historical screen on seen data. It is not evidence of a long-term edge. Nothing here is approved, and inference is allowed only if the calibration addendum passes."


def hs(d): return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
def iso(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def read_data():
    c = sqlite3.connect("file:%s?mode=ro" % FDB, uri=True)
    last = c.execute("SELECT MIN(m) FROM (SELECT MAX(t) m FROM k GROUP BY sym)").fetchone()[0]
    syms = [r[0] for r in c.execute("SELECT DISTINCT sym FROM k ORDER BY sym")]
    return (last + HOUR) // DAY * DAY, syms


def spec(end_ms, syms, frozen_at):
    return {
        "version": "batch1-daily-v1", "frozen_at_utc": frozen_at, "mandatory_wording": WORDING,
        "purpose": "Screen five daily-bar strategies through one shared engine and cost model, with every hypothesis counted, so we learn which (if any) deserve forward weeks.",
        "disclosures": ["fade.db was already used for E001 and E002, so all of it is seen data; this is a screen, not confirmation",
                        "none of these five rules has been computed on this data by the author or the user before this spec",
                        "the 40 coins are today's listed survivors, which flatters buy-and-hold, trend and momentum rules",
                        "funding on perpetual shorts is NOT modelled (weekly_mom is the only strategy that shorts); this favours weekly_mom",
                        "parameters are conventional, chosen before looking at results, and frozen at approval"],
        "data": {"source": "fade.db table k (sym, t, o, h, l, c, v), hourly spot-then-futures candles, read only",
                 "universe": syms, "universe_rule": "the coins present in fade.db at freeze; none added or removed afterwards",
                 "daily_bar": "UTC day d: open = open of the 00:00 candle, close = close of the 23:00 candle, built only from days with all 24 hourly candles; a day with any missing hour is invalid for that coin, indicators are not interpolated, and the count of invalid coin-days is reported",
                 "window_end_utc_ms": end_ms, "window_end": iso(end_ms) + " (exclusive)",
                 "window_end_rule": "earliest last candle across coins, floored to UTC midnight, from timestamps only",
                 "coin_start": "each coin from its first valid day; a strategy's own warm-up (below) delays its first position"},
        "timing": {"decision": "after the close of day d, using only closes up to and including day d",
                   "execution": "position changes happen at the open of day d+1; the day's return is close(d+1)/open(d+1) - 1 per unit weight",
                   "start_state": "flat; weights are zero until a strategy's warm-up is complete"},
        "cost_model": {"per_side": 0.0010, "stress_per_side": 0.0015, "rule": "cost = per_side x sum over coins of |weight_today - weight_yesterday_after_drift|, charged on the day of the change; round trip is 0.20% base, 0.30% stress",
                       "status": "provisional, covers fees and slippage; the actual fee tier is unverified, as in the carry work",
                       "benchmark_costs": "the benchmark is charged no costs, which is conservative against each strategy"},
        "weights_drift": "weights are reset to the target at each open, so turnover counts only target changes plus drift back to target",
        "strategies": [
            {"id": "bh_equal_weight", "role": "benchmark only; not a hypothesis and not counted in m",
             "rule": "long, equal weight across coins with a valid bar that day, summing to 1, rebalanced daily",
             "mechanism": "holds the crypto market's own return, so other strategies are judged against what simply holding would have earned"},
            {"id": "ema50_200", "family": "trend following on daily bars",
             "rule": "per coin, EMA(50) and EMA(200) of daily closes, alpha 2/(n+1), seeded with the coin's first valid close; long if EMA50 > EMA200 after the close of day d, else flat; a coin counts as warmed up after 200 valid closes; weights equal across coins that are long, total long weight 1/N_active per long coin where N_active is the number of coins with a valid bar, so cash is held when few coins qualify",
             "mechanism": "slow-moving capital reallocates gradually, so trends persist; staying long while the fast average leads and flat otherwise should avoid part of drawdowns. The market pays this strategy only if trends outlast costs.",
             "direction": "long or flat"},
            {"id": "breakout20", "family": "trend following on daily bars",
             "rule": "per coin, enter long when the day's close exceeds the highest close of the previous 20 days; exit to flat when the close falls below the lowest close of the previous 10 days; otherwise keep the current state; weights as for ema50_200; warm-up 20 valid closes",
             "mechanism": "a new multi-week high triggers trend-follower buying and stop orders, so continuation follows; the 10-day exit limits give-back",
             "direction": "long or flat"},
            {"id": "weekly_mom", "family": "continuation after momentum",
             "rule": "every Monday after the Sunday close, rank coins with a valid bar by close(d) / close(d-7) - 1; long the top floor(N/5) coins and short the bottom floor(N/5), with weights +0.5/k and -0.5/k (k = floor(N/5)), held 7 days, no intra-week rebalance; N must be at least 20 or no position is taken; warm-up 7 valid closes",
             "mechanism": "coins that led over the past week keep attracting flow relative to laggards for the next week; the long and short legs offset market direction, so this tests relative continuation only",
             "direction": "long and short, dollar neutral, gross exposure 1"},
            {"id": "meanrev_short", "family": "reversal after extremes",
             "rule": "per coin, r3 = close(d) / close(d-3) - 1 and s = standard deviation of daily returns over the previous 60 valid days; z = r3 / (s x sqrt(3)); long if z <= -1.5, else flat, re-evaluated every day; weights as for ema50_200; warm-up 63 valid closes",
             "mechanism": "over-extended 3-day drops are partly reversed as liquidity providers are paid to hold the other side. This is the daily, long-only cousin of fade24, so it is correlated with an already rejected hypothesis.",
             "direction": "long or flat"}],
        "benchmark_for_tests": {"definition": "for strategy s, active return on day t = net return of s - E_t x r_bh_t, where E_t is s's net exposure (sum of weights) held on day t and r_bh_t is the day's benchmark return; for weekly_mom E_t is 0, so the comparison is with zero",
                                "question": "does the strategy's timing or selection add return beyond holding the market at the same exposure"},
        "primary_statistic": "mean daily active return, after costs, over the strategy's evaluable days (from its warm-up end to the window end)",
        "reported_always": ["mean daily net return and annualized (1+r)^365-1", "mean daily active return", "maximum drawdown on the compounded net curve", "average exposure and turnover", "yearly breakdown with a partial-year label",
                            "first-half and second-half active return", "result at stress costs", "number of invalid coin-days", "pairwise correlation of daily net returns across all five, with the number of shared days",
                            "realised daily sd of active return and the minimum detectable effect computed from it"],
        "families": {"trend following on daily bars": {"question": "does staying long while a daily trend signal is on add return beyond the market at equal exposure", "new": True, "m_after": 2},
                     "continuation after momentum": {"question": "existing family (E002 registered); weekly_mom is a second hypothesis", "new": False, "m_after": 2},
                     "reversal after extremes": {"question": "existing family (E001 registered); meanrev_short is a second hypothesis", "new": False, "m_after": 2}},
        "alpha": {"alpha_family": 0.01, "rule": "Bonferroni inside each family, alpha_individual = 0.01 / m, so 0.005 for each of the four hypotheses",
                  "earlier_results": "adding hypotheses to the two existing families tightens E001 and E002 to 0.005 as well; they are re-judged, never upgraded",
                  "across_families": "families are not corrected against each other, so the chance that at least one of the four passes by luck alone can approach 2%; the batch-wide alternative alpha 0.0025 is listed under open decisions",
                  "bootstrap": "one-sided lower bound of the mean daily active return, resampling blocks of days, at confidence 1 - alpha_individual"},
        "inference_licence": {"rule": "no p-value, interval or pass may be reported until a calibration addendum passes: block bootstrap on synthetic worlds that match this design (daily returns with volatility clustering, cross-coin correlation, weak autocorrelation, and the strategies' own warm-up lengths), false-positive counts and limits fixed in advance, two seeds, precision rule, stop on failure",
                              "if_not_licensed": "the screen is descriptive only and the strategies can only advance through forward weeks, as with carry",
                              "numeric_limits": "NOT in this spec; they go in the calibration addendum, frozen before the calibration runs"},
        "effective_sample": "each strategy has roughly 860 to 1,060 daily observations, but they are dependent across days (volatility regimes) and across coins; the number of independent observations is unknown and is exactly what the calibration must estimate. The carry result (a handful of independent regimes) shows how badly that can go wrong, but that figure belongs to the carry design and is not assumed here.",
        "power_statement": {"formula": "minimum detectable mean daily active return, one-sided alpha 0.005, 80% power = (2.576 + 0.842) x sd_daily_active / sqrt(n_effective)",
                            "arithmetic": "with n_effective equal to the number of days (about 860, the best case) this is about 0.117 x sd_daily_active per day",
                            "illustration_not_a_measurement": "if the daily sd of active return were 1%, the minimum detectable effect would be about 0.12% per day, roughly 43% a year; the real sd is measured from the data and reported before any pass/fail",
                            "consequence": "unless active returns are far less volatile than that, only very large effects are detectable, so a null is reported as 'no effect larger than X detectable', never 'rejected'"},
        "pass_bar": {"applies_only_if": "the inference licence passes",
                     "all_required": ["the one-sided lower bound of mean daily active return at base costs is above 0 at alpha_individual",
                                      "the mean daily active return at stress costs is above 0",
                                      "active return is positive in the first half and in the second half of the evaluable window",
                                      "active return is positive in every full calendar year inside the window (2024 and 2025; 2023 and 2026 are partial)"],
                     "meaning_of_pass": "a candidate for a separate forward spec, never an approved strategy; harness status moves at most to WATCH"},
        "harness_registration": {"before_run": "strategies and hypotheses are registered by a separate, reviewed script before the real run; the run refuses to start unless all four hypotheses exist in harness.db",
                                 "strategy_ids": ["ema50_200", "breakout20", "weekly_mom_b1", "meanrev_short_b1"],
                                 "note": "weekly_mom_b1 and meanrev_short_b1 are new ids; they are not edits of E002 or fade24"},
        "health_monitor": "thresholds are frozen per strategy only if a strategy ever reaches a forward stage; none is needed for this screen",
        "forward": "a passing strategy needs its own forward spec, frozen before any forward data, with at least 14 weeks and likely 26",
        "order_of_work": ["approve and freeze this spec", "write and freeze the calibration addendum with numeric limits", "write the engine with synthetic accounting self-checks",
                          "run the calibration on synthetic data only", "register the hypotheses in the harness", "one real run, logged in experiments.json with observation and interpretation separate"],
        "open_decisions": ["long/flat only for the trend and reversal rules (proposed) versus allowing shorts", "per-family alpha 0.005 (proposed) versus batch-wide 0.0025",
                           "all five now (proposed) versus start with bh_equal_weight and ema50_200",
                           "cost 0.10% per side, provisional", "block lengths to calibrate (candidates 7, 14, 28 days)",
                           "whether the 200-day warm-up for ema50_200 (about a fifth of the data) makes it too weak to run"]}


def main(mode):
    if os.path.exists(FILE):
        st = json.load(open(FILE))
        s = st["spec"]
        ok = hs(spec(s["data"]["window_end_utc_ms"], s["data"]["universe"], s["frozen_at_utc"])) == st["hash"] == hs(s)
        print(("\033[92mbatch1 spec unchanged: " if ok else "\033[91mBATCH1 SPEC CHANGED: ") + st["hash"] + "\033[0m")
        return
    end, syms = read_data()
    if mode == "freeze":
        hst = json.load(open(H.FILE))
        if H.hs(H.spec(hst["spec"]["frozen_at_utc"])) != hst["hash"]:
            raise SystemExit("\033[91mharness spec does not match its hash: nothing frozen\033[0m")
        fz = datetime.now(timezone.utc).isoformat()
        s = spec(end, syms, fz)
        json.dump({"hash": hs(s), "spec": s}, open(FILE, "w"), indent=1)
        print("\033[96mfrozen batch1-daily-v1 at %s\nsha256 %s\033[0m" % (fz, hs(s)))
        return
    print("\033[96mwindow end (exclusive): %s   coins: %d   [timestamps and symbols only were read]\033[0m" % (iso(end), len(syms)))
    print(json.dumps(spec(end, syms, PH), indent=1))
    print("\033[93mNothing frozen. Hashes differ at freeze because the timestamp is inside. Freeze with: python3 batch1_spec.py freeze\033[0m")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "show")
