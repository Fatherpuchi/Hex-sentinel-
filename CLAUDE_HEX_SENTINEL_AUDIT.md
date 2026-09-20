# HEX SENTINEL — FULL REPOSITORY AUDIT, BUG DISCOVERY AND REPAIR

You are the senior software engineer responsible for auditing and repairing this entire HEX SENTINEL repository.

DO NOT assume the existing architecture is correct.

Your job is to inspect the REAL repository, identify bugs, reproduce them where possible, repair them, and verify every repair with tests/runtime evidence.

============================================================
0. ABSOLUTE SAFETY RULES
============================================================

1. PAPER/BACKTEST ONLY.
2. NEVER place a real Binance order.
3. NEVER enable live trading.
4. NEVER remove, weaken, bypass, or rename a deterministic safety gate merely to make tests pass.
5. Do not modify API credentials, .env secrets, authentication, or account settings.
6. Do not expose API keys, secrets, tokens, cookies, or private credentials in reports.
7. Do not delete backups.
8. Do not blindly rewrite large files.
9. Before modifying a file:
   - inspect it
   - understand its role
   - identify the exact defect
   - create a timestamped backup if appropriate
10. Never claim a bug is fixed without running a relevant verification.
11. If a proposed change could affect live execution, STOP and report it instead of making the change.
12. Historical data must remain local and must not be committed to Git.

============================================================
1. PRIMARY OBJECTIVE
============================================================

Perform a FULL repository-level engineering audit.

Find and fix bugs involving:

- incorrect data schemas
- broken imports
- stale modules
- duplicated logic
- dead code
- incorrect assumptions about CSV columns
- incorrect file paths
- incorrect database schemas
- lookahead bias
- data leakage
- future-data contamination
- overlapping trades
- invalid walk-forward validation
- incorrect train/validation/holdout separation
- incorrect position accounting
- incorrect P&L
- incorrect fees
- incorrect slippage
- incorrect equity calculations
- incorrect drawdown calculations
- incorrect profit factor
- incorrect win-rate calculations
- incorrect trade duration
- signal/entry timing errors
- regime classification errors
- multi-timeframe alignment errors
- confidence calibration errors
- optimizer leakage
- optimizer overfitting
- duplicated signal generation
- inconsistent direction conventions
- LONG/SHORT inversion
- incorrect TP/SL calculations
- incorrect risk/reward calculations
- paper-trade lifecycle bugs
- prediction lifecycle bugs
- database persistence bugs
- provider/AI consensus bugs
- reliability scoring bugs
- risk-gate bugs
- Binance symbol handling bugs
- Futures/spot symbol confusion
- stale configuration
- exception handling that hides failures
- silent fallback behavior
- impossible states
- broken command-line interfaces
- tests that pass while the underlying calculation is wrong

Do not restrict yourself to the currently known bug.

============================================================
2. CURRENTLY KNOWN PROBLEM
============================================================

There is a known failure in:

    portfolio_walk_forward_validation.py

A previous run produced:

    Decision: INSUFFICIENT_DATA
    Development trades: 0
    Holdout trades: 0

The historical core CSV schema is known to contain:

    open_time
    close
    base_direction
    base_score
    regime
    regime_quality
    regime_bonus
    mtf_status
    four_h_regime
    mtf_bonus
    confidence_score
    confidence_level
    signal_quality
    final_signal
    reasons
    future_return_4h
    future_return_12h
    future_return_24h
    future_return_48h

The important field is:

    regime

Previous code was suspected of using:

    combined_regime

This may be one bug, but DO NOT assume it is the only bug.

Trace the complete execution path and prove why trades are or are not generated.

============================================================
3. AUTHORITATIVE DATA PIPELINE
============================================================

Determine the actual authoritative pipeline.

Trace:

RAW BINANCE DATA
        |
        v
process_historical_data.py
        |
        v
processed OHLCV CSV
        |
        v
build_historical_features.py
        |
        v
feature CSV
        |
        v
analyze_market_regimes.py
        |
        v
regime information
        |
        v
hex_sentinel_core.py
        |
        v
core signals CSV
        |
        +----------------------+
        |                      |
        v                      v
strategy_optimizer.py    walk_forward_validation.py
        |                      |
        v                      v
optimized strategy      portfolio validation
                               |
                               v
                         performance metrics

Also trace:

sentinel_stage1.py
        |
        v
sentinel_ai.py
        |
        v
AI consensus / risk / paper trading / prediction lifecycle

Do not assume filenames are authoritative.

Use imports, function calls, CLI entry points, file reads/writes, database access, and runtime behavior to determine the actual architecture.

============================================================
4. BACKUP/SNAPSHOT AUDIT
============================================================

There are many files resembling:

sentinel_ai.py.before_*
sentinel_ai_*_backup.py
sentinel_stage1_*_backup.py
backups/*
*.save

Do NOT delete them.

Determine:

- which files are active
- which files are historical snapshots
- which files are imported by active code
- which files are never imported
- whether stale backup code is accidentally executed
- whether multiple versions contain different logic
- whether any script references a backup module

Report obsolete/duplicate modules separately.

============================================================
5. SCHEMA CONTRACT AUDIT
============================================================

For every important CSV/DB interface:

1. Identify producer.
2. Identify consumer.
3. Extract actual schema.
4. Compare producer fields with consumer fields.
5. Detect:
   - renamed columns
   - missing columns
   - fallback inconsistencies
   - type mismatches
   - capitalization mismatches
   - stale field names
   - default-value bugs

Pay particular attention to:

    regime
    combined_regime
    final_signal
    base_direction
    confidence_score
    confidence_level
    mtf_status
    four_h_regime

Also inspect SQLite schemas and SQL queries.

============================================================
6. TIME-SERIES / LEAKAGE AUDIT
============================================================

This is critical.

For every model/strategy/optimizer/validator:

Determine exactly what information is available at signal time.

Look for:

- future candles used in features
- future returns accidentally used as inputs
- current candle close used when entry occurs at its open
- future regime information
- future higher-timeframe candles
- overlapping future-return observations treated as independent trades
- training/holdout contamination
- normalization fitted on future data
- thresholds tuned using holdout data
- optimizer seeing 2025 before final validation
- timestamp alignment errors
- 1h/4h lookahead
- incomplete higher-timeframe candles

Document every confirmed leakage with:

FILE
FUNCTION
LINE
WHY IT LEAKS
HOW TO FIX
TEST THAT PROVES THE FIX

============================================================
7. WALK-FORWARD VALIDATION AUDIT
============================================================

Inspect:

    strategy_optimizer.py
    walk_forward_validation.py
    portfolio_walk_forward_validation.py

Verify:

- training period
- validation period
- untouched holdout period
- chronological ordering
- no future information
- no overlapping positions unless explicitly intended
- one position lifecycle is represented correctly
- entry timestamp
- entry price
- exit timestamp
- exit price
- holding period
- fees
- slippage
- position sizing
- equity
- drawdown

The validator MUST NOT compound overlapping future returns as though they were separate sequential trades.

A 48h prediction cannot automatically become four independent trades simply because four rows contain 48h future returns.

============================================================
8. PERFORMANCE-METRIC AUDIT
============================================================

Verify formulas independently.

For each trade calculate:

gross P&L
fees
slippage
net P&L
return
equity after trade

Then calculate:

total trades
winning trades
losing trades
win rate
average trade
profit factor
net return
maximum drawdown
final equity

Maximum drawdown MUST be based on the actual equity curve:

peak equity
current equity
drawdown = (peak - current) / peak

Do NOT use a simple sum of returns as a substitute for equity drawdown.

Profit factor MUST be:

gross winning P&L / absolute gross losing P&L

unless the code explicitly documents another definition.

============================================================
9. SIGNAL/ENTRY TIMING AUDIT
============================================================

For every signal:

Determine:

signal candle
signal timestamp
entry candle
entry timestamp
entry price
exit logic

Prevent accidental same-candle lookahead.

If a signal uses candle close information, entry should normally occur no earlier than the next executable candle unless the system explicitly models another execution mechanism.

Verify this mathematically and with tests.

============================================================
10. MULTI-TIMEFRAME AUDIT
============================================================

Inspect 1h + 4h interaction.

Verify that when processing a 1h candle:

ONLY THE LATEST COMPLETED 4h CANDLE is available.

Never use an incomplete future 4h candle.

Check:

- timestamp alignment
- timezone
- candle boundaries
- missing 4h context
- first-candle behavior
- regime propagation

Create a test specifically proving that future 4h information cannot affect an earlier 1h signal.

============================================================
11. OPTIMIZER AUDIT
============================================================

Inspect:

    strategy_optimizer.py

Verify:

- parameter search
- train period
- validation period
- holdout period
- minimum sample size
- objective function
- confidence thresholds
- regime selection
- MTF selection
- direction selection

Look for:

- overfitting
- duplicate configurations
- invalid metrics
- incorrect max drawdown
- selection based on holdout
- overlapping future returns
- unrealistic compounding

If the optimizer's current results are mathematically invalid, correct the optimizer rather than simply accepting the highest result.

============================================================
12. CORE SIGNAL AUDIT
============================================================

Inspect:

    hex_sentinel_core.py

Determine:

- exact signal-generation rules
- LONG rules
- SHORT rules
- NO_TRADE rules
- confidence calculation
- regime bonus
- MTF bonus
- final signal
- signal quality

Check whether:

VERY_HIGH
HIGH
MEDIUM
LOW
VERY_LOW

are actually calibrated to empirical probabilities.

Do not assume confidence labels represent true probabilities.

============================================================
13. AI / CONSENSUS AUDIT
============================================================

Inspect:

    sentinel_ai.py
    signal_intelligence_engine.py
    sentinel_stage1.py

Trace:

market data
web intelligence
provider outputs
directional consensus
trade-plan consensus
memory
reliability
risk gate
paper trade
prediction persistence
prediction evaluation

Verify that:

- directional prediction is distinct from trade-plan approval
- rejected trade plans do not become paper trades
- failed AI calls cannot silently become fake agreement
- provider reliability is updated correctly
- consensus is deterministic where required
- risk gates override AI recommendations
- no AI output can bypass deterministic safety
- prediction expiry/evaluation uses correct timestamps and prices

============================================================
14. BINANCE SAFETY AUDIT
============================================================

Search the entire repository for:

order
create_order
futures_create_order
new_order
place_order
POST /order
client.order
futures_order
market_order
limit_order

Determine whether any actual Binance order-placement path exists.

If actual order placement exists:

DO NOT execute it.

Trace it and report exactly how it could be reached.

Ensure live execution remains BLOCKED.

Do not weaken the block.

============================================================
15. DATABASE AUDIT
============================================================

Inspect:

    sentinel.db
    database access code
    SQL CREATE TABLE statements
    INSERT statements
    UPDATE statements
    SELECT statements

Check:

- schema mismatch
- missing columns
- wrong column names
- incorrect NULL handling
- duplicate records
- incorrect timestamps
- stale rows
- prediction lifecycle
- paper trade lifecycle
- outcome persistence

Verify that persisted results can be reconstructed correctly.

============================================================
16. ERROR-HANDLING AUDIT
============================================================

Search for:

except:
except Exception
pass
return None
fallback
default
silent
ignore

Determine whether exceptions are being swallowed.

A failure must not silently become:

- agreement
- successful prediction
- profitable result
- valid trade
- approved risk
- valid market data

Where appropriate, replace silent failures with explicit safe failure states.

============================================================
17. TESTING REQUIREMENTS
============================================================

Do not only run:

    python -m py_compile

Create focused tests for confirmed bugs.

At minimum test:

1. Core CSV schema compatibility.
2. Portfolio validator generates trades when valid BULL_ONLY data exists.
3. Portfolio validator generates zero trades when no qualifying signals exist.
4. No future 4h candle leakage.
5. No overlapping positions.
6. Correct entry timing.
7. Correct fees.
8. Correct slippage.
9. Correct equity curve.
10. Correct maximum drawdown.
11. Correct profit factor.
12. Correct holdout isolation.
13. LONG/SHORT P&L direction.
14. Live order execution remains blocked.
15. Paper trade persistence.
16. Prediction persistence/evaluation.

Use deterministic synthetic fixtures where possible.

Do not rely solely on historical BTC data to prove a calculation.

============================================================
18. REPAIR POLICY
============================================================

For every confirmed bug:

1. Explain root cause.
2. Make the smallest safe repair.
3. Preserve existing intended behavior.
4. Add a regression test.
5. Run the test.
6. Run compile checks.
7. Run the affected pipeline.
8. Compare before/after behavior.
9. Record evidence.

Do not make speculative "improvements" that are unrelated to confirmed bugs.

Do not optimize trading performance before correctness is established.

CORRECTNESS FIRST.
VALIDATION SECOND.
OPTIMIZATION THIRD.

============================================================
19. REQUIRED FINAL VERIFICATION
============================================================

After repairs run:

- Python compile check
- focused regression tests
- historical data validation
- core signal generation
- portfolio walk-forward validation
- optimizer validation if affected
- Stage 1 validation if affected
- Sentinel AI smoke test if affected
- repository safety scan

Do not claim success if any relevant test fails.

============================================================
20. REQUIRED REPORT
============================================================

Create:

    CLAUDE_HEX_SENTINEL_AUDIT_REPORT.md

The report must contain:

# Executive Summary

# Repository Architecture

# Authoritative Pipeline

# Active vs Backup Files

# Confirmed Bugs

For each bug:

- Severity
- File
- Function
- Line
- Root cause
- Evidence
- Fix
- Regression test
- Verification result

# Data Schema Findings

# Time-Series Leakage Findings

# Walk-Forward Findings

# Portfolio Accounting Findings

# Optimizer Findings

# Core Signal Findings

# AI/Consensus Findings

# Database Findings

# Binance Safety Findings

# Dead/Duplicate Code

# Tests Added

# Tests Passed

# Tests Failed

# Remaining Risks

# Recommended Next Stage

============================================================
21. IMPORTANT DECISION RULE
============================================================

Do NOT stop after fixing the known:

    regime vs combined_regime

issue.

That is only the starting point.

Continue auditing the entire pipeline for additional bugs.

However, do NOT endlessly rewrite the project.

Once a subsystem is:

- understood
- corrected
- regression-tested
- verified

mark it as COMPLETE and move to the next subsystem.

============================================================
22. GIT SAFETY
============================================================

Before substantial modifications:

    git status
    git branch --show-current
    git log --oneline -10

Never commit:

.env
API keys
credentials
historical_data/
large generated datasets
private databases unless explicitly required

Do not push automatically.

At the end report:

- files modified
- files created
- tests added
- git diff summary
- whether working tree is clean/dirty

============================================================
23. FINAL RESPONSE FORMAT
============================================================

When finished, report exactly:

AUDIT COMPLETE

Repository:
<path>

Confirmed bugs:
<number>

Fixed bugs:
<number>

Regression tests:
<number>

Tests passed:
<number>

Tests failed:
<number>

Live execution:
BLOCKED

Then give:

1. Most serious bugs found
2. What was fixed
3. What remains
4. Exact commands used for verification
5. Whether the repository is safe to continue to the next development stage

Do not claim the trading strategy is profitable merely because a backtest improved.

Do not claim production readiness without sufficient forward paper validation.

START NOW.

First inspect the repository and build the dependency/data-flow map.

Do not begin by rewriting code.

Find the bugs first.
Reproduce them.
Then repair them.
Then test them.
