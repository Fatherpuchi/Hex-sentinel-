from dotenv import load_dotenv
load_dotenv()
import os
import subprocess
import requests
import sqlite3
import re
from difflib import get_close_matches
from difflib import get_close_matches

API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

if not API_KEY:
    print("ERROR: GROQ_API_KEY is not loaded.")
    raise SystemExit(1)


# ============================================================
# RUN STAGE 1
# ============================================================

def run_legacy_pipeline(symbol="BTCUSDT"):
    """Run the Stage 1–4 startup pipeline for a selected symbol."""

    # STAGE 6.12 — NORMALIZE SYMBOL CONTEXT
    symbol = str(symbol).upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"
    global status, signal, final_action, live_execution
    global ai_assessment, risk_status, risk_reason, agent_state
    global sentinel_output

    # ============================================================
    # STAGE 6.11 — AUTOMATIC DECISION EVALUATION
    # ============================================================

    print("\n" + "=" * 60)
    print("🧠 HEX SENTINEL — DECISION FEEDBACK CHECK")
    print("=" * 60)

    try:
        evaluation_results = evaluate_pending_decisions(
            evaluation_limit=20,
            min_age_minutes=60
        )

        print(
            f"Previous decisions evaluated: "
            f"{len(evaluation_results)}"
        )

        for evaluation in evaluation_results:
            print(
                f"  {evaluation['symbol']} | "
                f"{evaluation['signal']} | "
                f"{evaluation['outcome']} | "
                f"{evaluation['price_change_pct']}%"
            )

    except Exception as e:
        print(
            f"⚠️ Decision feedback check skipped: {e}"
        )

    print("=" * 60 + "\n")

    print("🔎 Running HEX SENTINEL Stage 1...\n")

    try:
        stage1_env = os.environ.copy()
        stage1_env["SENTINEL_SYMBOL"] = symbol

        result = subprocess.run(
            ["python", "sentinel_stage1.py"],
            capture_output=True,
            text=True,
            timeout=180,
            env=stage1_env
        )
    except subprocess.TimeoutExpired:
        print("❌ Sentinel timed out.")
        raise SystemExit(1)

    sentinel_output = result.stdout

    if result.returncode != 0 or "❌ MARKET DATA ERROR" in sentinel_output or "❌ Not enough market data." in sentinel_output:
        print("❌ Sentinel Stage 1 failed.")
        if result.stderr:
            print(result.stderr)
        raise SystemExit(1)

    if "✅ Stage 1 run completed." not in sentinel_output:
        print("❌ Sentinel Stage 1 did not complete successfully.")
        raise SystemExit(1)

    print(sentinel_output)


    # ============================================================
    # STAGE 2 — DETERMINISTIC SAFETY CONTROLLER
    # ============================================================

    def extract(pattern, text):
        match = re.search(pattern, text)
        return match.group(1).strip() if match else "UNKNOWN"


    status_raw = extract(
        r"STRATEGY APPROVAL STATUS\s*\n\s*([🟢🟡🔴]?\s*\w+)",
        sentinel_output
    )

    status = (
        "APPROVED" if "APPROVED" in status_raw
        else "WATCH" if "WATCH" in status_raw
        else "REJECTED" if "REJECTED" in status_raw
        else "UNKNOWN"
    )

    signal = extract(
        r"Paper Signal:\s*(\w+)",
        sentinel_output
    )

    # Safety controller is authoritative.
    if status == "REJECTED":
        final_action = "BLOCKED"
    elif status == "WATCH":
        final_action = "PAPER_ONLY"
    elif status == "APPROVED":
        final_action = f"PAPER_{signal}"
    else:
        final_action = "PAPER_ONLY"

    live_execution = "BLOCKED"


    # ============================================================
    # AI AGENT ASSESSMENT
    # ============================================================

    print("\n🤖 Sentinel AI Agent analyzing validated results...\n")


    system_prompt = """
    You are the reasoning layer of Hex Sentinel.

    You analyze results from a deterministic crypto strategy engine.

    STRICT RULES:
    1. Never override the deterministic Sentinel status.
    2. Never recommend live trading.
    3. Never claim future profits.
    4. Be concise.
    5. Return EXACTLY this format:

    ASSESSMENT: <BULLISH/BEARISH/CAUTIOUS/NEUTRAL>
    CONFIDENCE: <LOW/MODERATE/HIGH>
    OOS_EVIDENCE: <STRONG/MIXED/WEAK>
    RISK: <LOW/MODERATE/HIGH>
    REASON: <one short sentence>
    """

    # ============================================================
    # STAGE 6.5 — MEMORY RECALL FOR AI CONTEXT
    # ============================================================

    try:
        past_decisions = get_decision_history(
            symbol="BTCUSDT",
            limit=5
        )

        if past_decisions:
            memory_context = "\n".join(
                f"{timestamp} | {symbol} | {past_signal} | "
                f"{risk_status} | {past_action} | "
                f"importance={importance}"
                for (
                    timestamp,
                    symbol,
                    past_signal,
                    risk_status,
                    past_action,
                    importance
                ) in past_decisions
            )
        else:
            memory_context = "No previous relevant decisions found."

    except Exception as e:
        memory_context = (
            "Memory unavailable. "
            "Do not rely on previous decisions."
        )

    # ============================================================
    # STAGE 6.9 — MEMORY INTELLIGENCE FOR AI CONTEXT
    # ============================================================

    try:
        memory_intelligence = analyze_memory_context(
            "BTCUSDT",
            signal,
            None
        )

        intelligence_context = (
            f"Dominant historical signal: "
            f"{memory_intelligence['dominant_signal']}\n"
            f"Pattern occurrences: "
            f"{memory_intelligence['pattern_count']}\n"
            f"Average importance: "
            f"{memory_intelligence['average_importance']}\n"
            f"Memory conflict: "
            f"{memory_intelligence['conflict']}\n"
            f"Memory confidence: "
            f"{memory_intelligence['confidence']}\n"
            f"Memory summary: "
            f"{memory_intelligence['summary']}"
        )

    except Exception:
        intelligence_context = (
            "Memory intelligence unavailable. "
            "Do not rely on historical memory."
        )

    user_prompt = f"""
    Deterministic strategy status: {status}
    Paper signal: {signal}
    Final allowed action: {final_action}
    Live execution: {live_execution}

    Previous relevant Sentinel decisions:
    {memory_context}

    Memory intelligence:
    {intelligence_context}

    IMPORTANT:
    Previous decisions are historical context only.
    Never override the current deterministic strategy status.
    Never override deterministic safety controls.

    Analyze the following actual Sentinel report:

    {sentinel_output}
    """

    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "max_completion_tokens": 300,
    }

    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
    except requests.RequestException as e:
        print(f"❌ Groq connection error: {e}")
        ai_assessment = ""

    if "ai_assessment" not in locals():
        if response.status_code != 200:
            print(f"❌ Groq API error: {response.status_code}")
            print(response.text)
            ai_assessment = ""
        else:
            try:
                data = response.json()
                ai_assessment = data["choices"][0]["message"].get("content") or ""
            except (ValueError, KeyError, IndexError, TypeError) as e:
                print(f"❌ Invalid AI response: {e}")
                ai_assessment = ""

    if not ai_assessment:
        print("🛑 FAIL-CLOSED: AI assessment unavailable. Defaulting to PAPER_HOLD.")

    # Run deterministic Stage 2.2 risk gate
    stage2_action, risk_status, risk_reason = stage2_risk_gate(
        status,
        signal,
        ai_assessment
    )

    # Live execution remains blocked at Stage 2
    live_execution = "BLOCKED"

    # Stage 2.2 overrides the earlier action
    final_action = stage2_action

    # ============================================================
    # STAGE 6.15 — APPLY ADAPTIVE DECISION SAFETY GUARD
    # ============================================================

    confidence_guard = apply_adaptive_confidence_guard(
        final_action=final_action,
        signal=signal,
        symbol=symbol
    )

    final_action = confidence_guard["final_action"]

    print("\n🧠 Adaptive Memory Safety")
    print("-" * 60)
    print(
        f"Memory Status:     "
        f"{confidence_guard['memory_status']}"
    )
    print(
        f"Memory Confidence: "
        f"{confidence_guard['memory_confidence']}"
    )
    print(
        f"Decision Action:   "
        f"{confidence_guard['original_action']} "
        f"→ {confidence_guard['final_action']}"
    )
    print(
        f"Memory Evidence:   "
        f"{confidence_guard['total_evaluated']} "
        f"evaluated decisions"
    )

    # ============================================================
    # FINAL AGENT DECISION — STAGE 2.2
    # ============================================================

    print("\n" + "=" * 60)
    print("🤖 HEX SENTINEL — STAGE 2.2")
    print("=" * 60)

    print(f"Strategy Status: {status}")
    print(f"Market Signal:   {signal}")

    print("\n🛡️ Risk Gate")
    print("-" * 60)
    print(f"Risk Gate Status: {risk_status}")
    print(f"Risk Reason:      {risk_reason}")

    print("\nAI Assessment")
    print("-" * 60)
    print(ai_assessment)

    print(f"\nFinal Action:    {final_action}")
    print(f"Live Execution:  {live_execution}")

    print("=" * 60)
    print("✅ Stage 2.2 risk gate completed.")
    print(f"Live Execution:  {live_execution}")

    # ============================================================
    # STAGE 3 — AGENT ORCHESTRATION
    # ============================================================

    # STAGE 6.12 — DYNAMIC SYMBOL CONTEXT
    current_symbol = symbol
    current_price = get_current_price(current_symbol)

    agent_state = {
        "agent": "Hex Sentinel",
        "stage": "3",
        "market": {
            "symbol": current_symbol,
            "signal": signal,
            "current_price": current_price
        },
        "validation": {
            "strategy_status": status
        },
        "ai": {
            "assessment": ai_assessment
        },
        "risk": {
            "status": risk_status,
            "reason": risk_reason
        },
        "execution": {
            "action": final_action,
            "live_execution": live_execution
        }
    }

    print("\n" + "=" * 60)
    print("🧠 HEX SENTINEL — STAGE 3 AGENT ORCHESTRATION")
    print("=" * 60)

    print("Agent Pipeline:")
    print("  1. Market Data        ✓")
    print("  2. Strategy Validation ✓")
    print("  3. AI Assessment       ✓")
    print("  4. Risk Gate           ✓")
    print("  5. Paper Action        ✓")
    print("  6. Live Execution      BLOCKED")

    print("\n📋 Agent State")
    print("-" * 60)
    print(f"Symbol:          {agent_state['market']['symbol']}")
    print(f"Signal:          {agent_state['market']['signal']}")
    print(f"Strategy Status: {agent_state['validation']['strategy_status']}")
    print(f"Risk Status:     {agent_state['risk']['status']}")
    print(f"Final Action:    {agent_state['execution']['action']}")
    print(f"Live Execution:  {agent_state['execution']['live_execution']}")

    print("=" * 60)
    print("✅ Stage 3.1 agent orchestration completed.")

    # ============================================================
    # STAGE 3.2 — PERSISTENT AGENT STATE
    # ============================================================

    import sqlite3
    from datetime import datetime, timezone

    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'WATCH',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                UNIQUE(strategy_name, version)
            );

            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal TEXT NOT NULL,
                strategy_status TEXT NOT NULL,
                risk_status TEXT NOT NULL,
                final_action TEXT NOT NULL,
                live_execution TEXT NOT NULL,
                ai_assessment TEXT NOT NULL
            )
        """)

        # ============================================================
        # STAGE 6.6 — CALCULATE MEMORY IMPORTANCE
        # ============================================================

        importance = calculate_memory_importance(
            agent_state["validation"]["strategy_status"],
            agent_state["risk"]["status"],
            agent_state["execution"]["action"],
            agent_state["ai"]["assessment"]
        )

        cursor.execute("""
            INSERT INTO agent_decisions (
                timestamp,
                symbol,
                signal,
                strategy_status,
                risk_status,
                final_action,
                live_execution,
                ai_assessment,
                importance,
                entry_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            agent_state["market"]["symbol"],
            agent_state["market"]["signal"],
            agent_state["validation"]["strategy_status"],
            agent_state["risk"]["status"],
            agent_state["execution"]["action"],
            agent_state["execution"]["live_execution"],
            agent_state["ai"]["assessment"],
            importance,
            agent_state["market"]["current_price"]
        ))

        conn.commit()

        cursor.execute("""
            SELECT COUNT(*) FROM agent_decisions
        """)

        decision_count = cursor.fetchone()[0]
        conn.close()

        print("\n" + "=" * 60)
        print("💾 STAGE 3.2 — PERSISTENT AGENT STATE")
        print("=" * 60)
        print(f"Decision saved:   ✓")
        print(f"Audit records:    {decision_count}")
        print(f"Latest action:    {final_action}")
        print(f"Live execution:   {live_execution}")
        print("=" * 60)
        print("✅ Stage 3.2 persistent state completed.")

    except sqlite3.Error as e:
        print(f"❌ Agent state database error: {e}")
        raise SystemExit(1)

    # ============================================================
    # STAGE 3.3 — AGENT DECISION HISTORY
    # ============================================================

    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, symbol, signal, risk_status, final_action
            FROM agent_decisions
            ORDER BY id DESC
            LIMIT 5
        """)

        history = cursor.fetchall()
        conn.close()

        print("\n" + "=" * 60)
        print("🧠 STAGE 3.3 — AGENT DECISION HISTORY")
        print("=" * 60)

        if history:
            for row in history:
                timestamp, symbol, hist_signal, hist_risk, hist_action = row
                print(
                    f"{timestamp} | {symbol} | "
                    f"{hist_signal} | {hist_risk} | {hist_action}"
                )
        else:
            print("No previous agent decisions found.")

        print("=" * 60)
        print("✅ Stage 3.3 decision history completed.")

    except sqlite3.Error as e:
        print(f"❌ Decision history error: {e}")

    # ============================================================

# ============================================================
# STAGE 6.4 — FAIL-CLOSED AI GATE
# ============================================================

def validate_ai_assessment(ai_assessment):
    """Validate AI output before it can influence the deterministic risk gate."""
    if not isinstance(ai_assessment, str) or not ai_assessment.strip():
        return False, "AI assessment is missing or not text."

    required = {
        "ASSESSMENT": {"BULLISH", "BEARISH", "CAUTIOUS", "NEUTRAL"},
        "CONFIDENCE": {"LOW", "MODERATE", "HIGH"},
        "OOS_EVIDENCE": {"STRONG", "MIXED", "WEAK"},
        "RISK": {"LOW", "MODERATE", "HIGH"},
    }

    values = {}

    for field, allowed in required.items():
        match = re.search(
            rf"(?m)^\s*{field}:\s*([^\n]+)\s*$",
            ai_assessment
        )
        if not match:
            return False, f"AI assessment missing required field: {field}."

        value = match.group(1).strip().upper()

        if value not in allowed:
            return False, f"AI assessment contains invalid {field}: {value}."

        values[field] = value

    reason_match = re.search(
        r"(?m)^\s*REASON:\s*(.+?)\s*$",
        ai_assessment
    )

    if not reason_match or not reason_match.group(1).strip():
        return False, "AI assessment missing a valid REASON."

    return True, "AI assessment passed strict validation."


# ============================================================
# STAGE 2.2 — DETERMINISTIC RISK GATE
# ============================================================

def stage2_risk_gate(status, signal, ai_assessment):

    # Stage 6.4 — AI must pass strict validation before influencing action.
    ai_valid, ai_validation_reason = validate_ai_assessment(ai_assessment)

    if not ai_valid:
        return (
            "PAPER_HOLD",
            "AI_GATE_BLOCKED",
            f"Fail-closed AI gate: {ai_validation_reason}"
        )

    assessment = ai_assessment.upper()

    # Default safety state
    risk_status = "PASS"
    risk_reason = "All deterministic Stage 2.2 checks passed."

    # Strategy must pass Stage 1 approval
    if status != "APPROVED":
        return (
            "BLOCKED",
            "BLOCKED",
            "Strategy is not approved by the Stage 1 validation gate."
        )

    # Invalid or uncertain signals cannot trigger paper actions
    if signal not in ["BUY", "SELL", "HOLD"]:
        return (
            "BLOCKED",
            "BLOCKED",
            "Invalid market signal."
        )

    # AI high-risk assessment blocks the action
    if "RISK: HIGH" in assessment:
        return (
            "BLOCKED",
            "HIGH_RISK",
            "AI assessment identified HIGH risk."
        )

    # Weak out-of-sample evidence blocks directional paper trades
    if "OOS_EVIDENCE: WEAK" in assessment:
        return (
            "PAPER_HOLD",
            "WEAK_OOS",
            "Out-of-sample evidence is weak."
        )

    # Mixed evidence allows paper testing but flags caution
    if "OOS_EVIDENCE: MIXED" in assessment:
        risk_status = "CAUTION"
        risk_reason = (
            "Mixed out-of-sample evidence. "
            "Paper trading allowed with caution."
        )

    # HOLD remains HOLD regardless of approval
    if signal == "HOLD":
        return (
            "PAPER_HOLD",
            risk_status,
            "No actionable market signal."
        )

    # Valid BUY/SELL with Stage 1 approval
    return (
        f"PAPER_{signal}",
        risk_status,
        risk_reason
    )


# STAGE 4.1 — AGENT TOOL REGISTRY
# ============================================================

def get_current_price(symbol):
    """Fetch the latest public Binance spot price."""
    response = requests.get(
        f"{BINANCE_API}/api/v3/ticker/price",
        params={"symbol": symbol},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return float(data["price"])


def get_market_snapshot(symbol="BTCUSDT"):
    """Return current public Binance market price."""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    try:
        current_price = get_current_price(symbol)
        return {
            "symbol": symbol,
            "current_price": current_price,
            "data": "LIVE_BINANCE_SPOT",
            "live_execution": "BLOCKED"
        }
    except Exception as e:
        return {
            "symbol": symbol,
            "error": str(e),
            "live_execution": "BLOCKED"
        }


def analyze_market(symbol=None):
    """Analyze a requested Binance symbol using the full validation engine."""
    if symbol:
        symbol = symbol.upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        result = deep_validate_symbol(symbol)

        if result.get("status") == "ERROR":
            return result

        try:
            current_price = get_current_price(symbol)
        except Exception as e:
            current_price = None
            result["price_error"] = str(e)

        risk_status = "CAUTION" if result.get("status") == "APPROVED" else "BLOCKED"

        if result.get("status") != "APPROVED":
            final_action = "BLOCKED"
        elif result.get("signal") == "BUY":
            final_action = "PAPER_BUY"
        elif result.get("signal") == "SELL":
            final_action = "PAPER_SELL"
        else:
            final_action = "PAPER_HOLD"

        return {
            **result,
            "current_price": current_price,
            "risk_status": risk_status,
            "final_action": final_action,
            "live_execution": "BLOCKED"
        }

    return {
        "symbol": agent_state["market"]["symbol"],
        "signal": agent_state["market"]["signal"],
        "strategy_status": agent_state["validation"]["strategy_status"],
        "risk_status": agent_state["risk"]["status"],
        "final_action": agent_state["execution"]["action"],
        "live_execution": agent_state["execution"]["live_execution"]
    }


# ============================================================
# STAGE 6.6 — SMART MEMORY IMPORTANCE SCORING
# ============================================================


# ============================================================
# STAGE 6.10 — MEMORY FEEDBACK LOOP
# ============================================================


# ============================================================
# STAGE 6.11 — AUTOMATIC DECISION EVALUATION
# ============================================================


# ============================================================
# STAGE 6.13 — DECISION PERFORMANCE ANALYTICS
# ============================================================


# ============================================================
# STAGE 6.14 — ADAPTIVE CONFIDENCE GUARD
# ============================================================


# ============================================================
# STAGE 6.15 — ADAPTIVE DECISION SAFETY GUARD
# ============================================================

def apply_adaptive_confidence_guard(
    final_action,
    signal,
    symbol=None
):
    """
    Apply historical-performance confidence as a safety layer.

    This guard never enables live execution.

    Rules:
    - INSUFFICIENT_DATA: preserve paper decision, low confidence.
    - TRUSTED: preserve decision.
    - CAUTION: preserve decision with caution.
    - AVOID: downgrade actionable paper decisions to PAPER_HOLD.
    """

    confidence_result = (
        get_adaptive_confidence_status()
    )

    memory_status = confidence_result["status"]
    memory_confidence = confidence_result["confidence"]

    original_action = final_action
    guarded_action = final_action
    guard_reason = confidence_result["reason"]

    actionable_actions = {
        "PAPER_BUY",
        "PAPER_SELL"
    }

    if (
        memory_status == "AVOID"
        and final_action in actionable_actions
    ):

        guarded_action = "PAPER_HOLD"

        guard_reason = (
            "Historical decision performance is classified "
            "as AVOID. Actionable paper trade downgraded "
            "to PAPER_HOLD."
        )

    return {
        "symbol": symbol,
        "signal": signal,
        "original_action": original_action,
        "final_action": guarded_action,
        "memory_status": memory_status,
        "memory_confidence": memory_confidence,
        "reason": guard_reason,
        "total_evaluated": (
            confidence_result["total_evaluated"]
        ),
        "accuracy_pct": (
            confidence_result["accuracy_pct"]
        ),
        "live_execution": "BLOCKED"
    }

def get_adaptive_confidence_status(
    min_samples=10,
    trusted_accuracy=60.0,
    avoid_accuracy=40.0
):
    """
    Convert historical decision performance into a confidence status.

    The system deliberately refuses to over-trust small samples.

    Status levels:

    INSUFFICIENT_DATA
        Not enough evaluated decisions.

    TRUSTED
        Enough evaluated decisions and strong historical accuracy.

    CAUTION
        Enough data, but performance is mixed.

    AVOID
        Enough evaluated decisions and weak historical accuracy.
    """

    analytics = (
        get_decision_performance_analytics()
    )

    total = analytics["total_evaluated"]
    accuracy = analytics["accuracy_pct"]
    feedback = analytics["average_feedback"]

    # --------------------------------------------------------
    # SAMPLE SIZE GUARD
    # --------------------------------------------------------

    if total < min_samples:

        status = "INSUFFICIENT_DATA"

        reason = (
            f"Only {total} evaluated decisions available. "
            f"At least {min_samples} are required before "
            f"historical performance can influence trust."
        )

        confidence = "LOW"

    # --------------------------------------------------------
    # STRONG PERFORMANCE
    # --------------------------------------------------------

    elif accuracy >= trusted_accuracy:

        status = "TRUSTED"

        reason = (
            f"Historical accuracy is {accuracy}% across "
            f"{total} evaluated decisions."
        )

        confidence = "HIGH"

    # --------------------------------------------------------
    # WEAK PERFORMANCE
    # --------------------------------------------------------

    elif accuracy <= avoid_accuracy:

        status = "AVOID"

        reason = (
            f"Historical accuracy is only {accuracy}% across "
            f"{total} evaluated decisions."
        )

        confidence = "HIGH"

    # --------------------------------------------------------
    # MIXED PERFORMANCE
    # --------------------------------------------------------

    else:

        status = "CAUTION"

        reason = (
            f"Historical accuracy is {accuracy}% across "
            f"{total} evaluated decisions, indicating "
            f"mixed performance."
        )

        confidence = "MODERATE"


    return {
        "status": status,
        "confidence": confidence,
        "reason": reason,
        "total_evaluated": total,
        "accuracy_pct": accuracy,
        "average_feedback": feedback,
        "min_samples_required": min_samples
    }

def get_decision_performance_analytics():
    """
    Analyze evaluated HEX SENTINEL decisions.

    Returns:
    - overall evaluated decision statistics
    - success/failure/neutral counts
    - overall accuracy
    - average feedback score
    - performance by signal
    - performance by symbol
    """

    import sqlite3

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    try:

        # ----------------------------------------------------
        # OVERALL PERFORMANCE
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                COUNT(*) AS total_evaluated,

                SUM(
                    CASE
                        WHEN outcome = 'SUCCESS'
                        THEN 1
                        ELSE 0
                    END
                ) AS successes,

                SUM(
                    CASE
                        WHEN outcome = 'FAILURE'
                        THEN 1
                        ELSE 0
                    END
                ) AS failures,

                SUM(
                    CASE
                        WHEN outcome = 'NEUTRAL'
                        THEN 1
                        ELSE 0
                    END
                ) AS neutral,

                AVG(feedback_score) AS average_feedback

            FROM agent_decisions

            WHERE outcome IS NOT NULL
              AND outcome != 'UNEVALUATED'
        """)

        row = cursor.fetchone()

        total = row[0] or 0
        successes = row[1] or 0
        failures = row[2] or 0
        neutral = row[3] or 0
        average_feedback = row[4]

        if total > 0:
            accuracy_pct = round(
                successes / total * 100,
                2
            )
        else:
            accuracy_pct = 0.0


        # ----------------------------------------------------
        # PERFORMANCE BY SIGNAL
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                signal,

                COUNT(*) AS total,

                SUM(
                    CASE
                        WHEN outcome = 'SUCCESS'
                        THEN 1
                        ELSE 0
                    END
                ) AS successes,

                SUM(
                    CASE
                        WHEN outcome = 'FAILURE'
                        THEN 1
                        ELSE 0
                    END
                ) AS failures,

                ROUND(
                    AVG(feedback_score),
                    4
                ) AS average_feedback

            FROM agent_decisions

            WHERE outcome IS NOT NULL
              AND outcome != 'UNEVALUATED'

            GROUP BY signal

            ORDER BY total DESC
        """)

        signal_rows = cursor.fetchall()

        by_signal = []

        for (
            signal,
            signal_total,
            signal_successes,
            signal_failures,
            signal_feedback
        ) in signal_rows:

            signal_total = signal_total or 0
            signal_successes = signal_successes or 0
            signal_failures = signal_failures or 0

            signal_accuracy = (
                round(
                    signal_successes
                    / signal_total
                    * 100,
                    2
                )
                if signal_total > 0
                else 0.0
            )

            by_signal.append({
                "signal": signal,
                "total": signal_total,
                "successes": signal_successes,
                "failures": signal_failures,
                "accuracy_pct": signal_accuracy,
                "average_feedback": signal_feedback
            })


        # ----------------------------------------------------
        # PERFORMANCE BY SYMBOL
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                symbol,

                COUNT(*) AS total,

                SUM(
                    CASE
                        WHEN outcome = 'SUCCESS'
                        THEN 1
                        ELSE 0
                    END
                ) AS successes,

                SUM(
                    CASE
                        WHEN outcome = 'FAILURE'
                        THEN 1
                        ELSE 0
                    END
                ) AS failures,

                ROUND(
                    AVG(feedback_score),
                    4
                ) AS average_feedback

            FROM agent_decisions

            WHERE outcome IS NOT NULL
              AND outcome != 'UNEVALUATED'

            GROUP BY symbol

            ORDER BY total DESC
        """)

        symbol_rows = cursor.fetchall()

        by_symbol = []

        for (
            symbol,
            symbol_total,
            symbol_successes,
            symbol_failures,
            symbol_feedback
        ) in symbol_rows:

            symbol_total = symbol_total or 0
            symbol_successes = symbol_successes or 0
            symbol_failures = symbol_failures or 0

            symbol_accuracy = (
                round(
                    symbol_successes
                    / symbol_total
                    * 100,
                    2
                )
                if symbol_total > 0
                else 0.0
            )

            by_symbol.append({
                "symbol": symbol,
                "total": symbol_total,
                "successes": symbol_successes,
                "failures": symbol_failures,
                "accuracy_pct": symbol_accuracy,
                "average_feedback": symbol_feedback
            })


        # ----------------------------------------------------
        # RETURN COMPLETE ANALYTICS
        # ----------------------------------------------------

        return {
            "total_evaluated": total,
            "successes": successes,
            "failures": failures,
            "neutral": neutral,
            "accuracy_pct": accuracy_pct,
            "average_feedback": (
                round(average_feedback, 4)
                if average_feedback is not None
                else None
            ),
            "by_signal": by_signal,
            "by_symbol": by_symbol
        }

    finally:
        conn.close()

def evaluate_pending_decisions(
    evaluation_limit=20,
    min_age_minutes=60
):
    """
    Automatically evaluate previously saved paper decisions.

    Only decisions with:
    - a valid entry price
    - no previous outcome
    - enough elapsed time

    are evaluated.
    """

    import sqlite3
    from datetime import datetime, timezone

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                id,
                timestamp,
                symbol,
                signal,
                entry_price
            FROM agent_decisions
            WHERE entry_price IS NOT NULL
              AND outcome IS NULL
            ORDER BY id ASC
            LIMIT ?
        """, (evaluation_limit,))

        rows = cursor.fetchall()

        results = []

        now = datetime.now(timezone.utc)

        for decision_id, timestamp, symbol, signal, entry_price in rows:

            try:
                decision_time = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )

                age_minutes = (
                    now - decision_time
                ).total_seconds() / 60

                if age_minutes < min_age_minutes:
                    continue

                evaluation_price = get_current_price(symbol)

                if evaluation_price is None:
                    continue

                outcome, feedback_score, price_change_pct = (
                    evaluate_decision_outcome(
                        signal,
                        entry_price,
                        evaluation_price
                    )
                )

                evaluated_at = now.isoformat()

                cursor.execute("""
                    UPDATE agent_decisions
                    SET
                        evaluation_price = ?,
                        price_change_pct = ?,
                        outcome = ?,
                        feedback_score = ?,
                        evaluated_at = ?
                    WHERE id = ?
                """, (
                    evaluation_price,
                    price_change_pct,
                    outcome,
                    feedback_score,
                    evaluated_at,
                    decision_id
                ))

                results.append({
                    "id": decision_id,
                    "symbol": symbol,
                    "signal": signal,
                    "entry_price": entry_price,
                    "evaluation_price": evaluation_price,
                    "price_change_pct": price_change_pct,
                    "outcome": outcome,
                    "feedback_score": feedback_score
                })

            except Exception as e:
                print(
                    f"⚠️ Evaluation skipped for "
                    f"{symbol}: {e}"
                )

        conn.commit()

        return results

    finally:
        conn.close()

def evaluate_decision_outcome(
    signal,
    entry_price,
    evaluation_price,
    hold_threshold=1.0
):
    """
    Evaluate whether a historical BUY, SELL, or HOLD decision
    was directionally correct.

    Returns outcome, feedback_score, price_change_pct.
    """

    if entry_price is None or evaluation_price is None:
        return "UNEVALUATED", 0.0, None

    if entry_price <= 0:
        return "UNEVALUATED", 0.0, None

    price_change_pct = (
        (evaluation_price - entry_price)
        / entry_price
        * 100
    )

    signal = (signal or "").upper()

    if signal == "BUY":

        if price_change_pct > 0:
            outcome = "SUCCESS"
            feedback_score = 1.0
        elif price_change_pct < 0:
            outcome = "FAILURE"
            feedback_score = -1.0
        else:
            outcome = "NEUTRAL"
            feedback_score = 0.0

    elif signal == "SELL":

        if price_change_pct < 0:
            outcome = "SUCCESS"
            feedback_score = 1.0
        elif price_change_pct > 0:
            outcome = "FAILURE"
            feedback_score = -1.0
        else:
            outcome = "NEUTRAL"
            feedback_score = 0.0

    elif signal == "HOLD":

        if abs(price_change_pct) <= hold_threshold:
            outcome = "SUCCESS"
            feedback_score = 1.0
        else:
            outcome = "FAILURE"
            feedback_score = -1.0

    else:
        outcome = "UNEVALUATED"
        feedback_score = 0.0

    return outcome, feedback_score, round(price_change_pct, 4)


def calculate_memory_importance(
    strategy_status,
    risk_status,
    final_action,
    ai_assessment
):
    """Return a deterministic memory importance score from 0.0 to 1.0."""

    score = 0.5

    strategy_status = str(strategy_status).upper()
    risk_status = str(risk_status).upper()
    final_action = str(final_action).upper()
    ai_assessment = str(ai_assessment).upper()

    if strategy_status in {"REJECTED", "FAILED"}:
        score += 0.30

    if "BLOCKED" in risk_status:
        score += 0.35

    if "HOLD" in final_action:
        score += 0.15

    if risk_status in {"CAUTION", "HIGH_RISK", "MODERATE_RISK"}:
        score += 0.10

    if (
        "OOS_EVIDENCE: MIXED" in ai_assessment
        or "OOS_EVIDENCE: WEAK" in ai_assessment
        or "CONFIDENCE: LOW" in ai_assessment
    ):
        score += 0.10

    return round(min(score, 1.0), 2)


# ============================================================
# STAGE 6.7 — MEMORY CONSOLIDATION
# ============================================================

# ============================================================
# STAGE 6.8 — INTELLIGENT MEMORY RETRIEVAL
# ============================================================

def get_intelligent_memory(symbol=None, limit=5):
    """Retrieve the most relevant historical decisions."""

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    if symbol:
        cursor.execute("""
            SELECT
                timestamp,
                symbol,
                signal,
                risk_status,
                final_action,
                importance
            FROM agent_decisions
            WHERE symbol = ?
            ORDER BY
                importance DESC,
                timestamp DESC
            LIMIT ?
        """, (symbol.upper(), limit))
    else:
        cursor.execute("""
            SELECT
                timestamp,
                symbol,
                signal,
                risk_status,
                final_action,
                importance
            FROM agent_decisions
            ORDER BY
                importance DESC,
                timestamp DESC
            LIMIT ?
        """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return rows



# ============================================================
# STAGE 6.9 — MEMORY INTELLIGENCE
# ============================================================

def analyze_memory_context(symbol, current_signal, current_risk_status=None):
    """Analyze historical memory against the current signal."""

    try:
        patterns = get_memory_patterns(symbol=symbol, limit=10)

        if not patterns:
            return {
                "symbol": symbol.upper(),
                "current_signal": current_signal.upper(),
                "dominant_signal": None,
                "pattern_count": 0,
                "average_importance": 0.0,
                "conflict": False,
                "confidence": "LOW",
                "summary": "No historical memory patterns available."
            }

        dominant = patterns[0]

        (
            pattern_symbol,
            dominant_signal,
            dominant_risk,
            dominant_action,
            pattern_count,
            average_importance,
            latest_timestamp
        ) = dominant

        current_signal = current_signal.upper()

        conflict = (
            current_signal != dominant_signal.upper()
            and pattern_count >= 3
            and float(average_importance) >= 0.5
        )

        if pattern_count >= 10 and float(average_importance) >= 0.7:
            confidence = "HIGH"
        elif pattern_count >= 3:
            confidence = "MODERATE"
        else:
            confidence = "LOW"

        if conflict:
            summary = (
                f"Memory conflict detected. Dominant historical signal: "
                f"{dominant_signal} ({pattern_count} occurrences)."
            )
        else:
            summary = (
                f"Memory is consistent. Dominant historical signal: "
                f"{dominant_signal} ({pattern_count} occurrences)."
            )

        return {
            "symbol": pattern_symbol,
            "current_signal": current_signal,
            "dominant_signal": dominant_signal,
            "dominant_risk_status": dominant_risk,
            "dominant_action": dominant_action,
            "pattern_count": pattern_count,
            "average_importance": round(float(average_importance), 2),
            "latest_timestamp": latest_timestamp,
            "conflict": conflict,
            "confidence": confidence,
            "summary": summary
        }

    except Exception:
        return {
            "symbol": symbol.upper(),
            "current_signal": current_signal.upper(),
            "dominant_signal": None,
            "pattern_count": 0,
            "average_importance": 0.0,
            "conflict": False,
            "confidence": "LOW",
            "summary": "Memory intelligence unavailable."
        }


def get_memory_patterns(symbol=None, limit=5):
    """Consolidate repeated historical decisions into memory patterns."""

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    if symbol:
        cursor.execute("""
            SELECT
                symbol,
                signal,
                risk_status,
                final_action,
                COUNT(*) AS occurrences,
                ROUND(AVG(importance), 2) AS avg_importance,
                MAX(timestamp) AS latest_timestamp
            FROM agent_decisions
            WHERE symbol = ?
            GROUP BY
                symbol,
                signal,
                risk_status,
                final_action
            ORDER BY
                avg_importance DESC,
                occurrences DESC,
                latest_timestamp DESC
            LIMIT ?
        """, (symbol.upper(), limit))
    else:
        cursor.execute("""
            SELECT
                symbol,
                signal,
                risk_status,
                final_action,
                COUNT(*) AS occurrences,
                ROUND(AVG(importance), 2) AS avg_importance,
                MAX(timestamp) AS latest_timestamp
            FROM agent_decisions
            GROUP BY
                symbol,
                signal,
                risk_status,
                final_action
            ORDER BY
                avg_importance DESC,
                occurrences DESC,
                latest_timestamp DESC
            LIMIT ?
        """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_decision_history(symbol=None, limit=5):
    """Recall important recent agent decisions."""

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    if symbol:
        cursor.execute("""
            SELECT
                timestamp,
                symbol,
                signal,
                risk_status,
                final_action,
                importance
            FROM agent_decisions
            WHERE symbol = ?
            ORDER BY importance DESC, id DESC
            LIMIT ?
        """, (symbol.upper(), limit))
    else:
        cursor.execute("""
            SELECT
                timestamp,
                symbol,
                signal,
                risk_status,
                final_action,
                importance
            FROM agent_decisions
            ORDER BY importance DESC, id DESC
            LIMIT ?
        """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return rows

def get_agent_status():
    """Return the current Hex Sentinel safety and execution state."""

    return {
        "agent": "Hex Sentinel",
        "mode": "PAPER/BACKTEST ONLY",
        "strategy_status": "READY",
        "risk_status": "MONITORING",
        "final_action": "NO_LIVE_EXECUTION",
        "live_execution": "BLOCKED",
        "registered_tools": len(agent_tools)
    }

agent_tools = {
    "analyze_market": analyze_market,
    "get_market_snapshot": get_market_snapshot,
    "get_decision_history": get_decision_history,
    "get_agent_status": get_agent_status,
}


# ============================================================
# STAGE 6.1 — HEX SENTINEL AGENT TOOL MANIFEST
# ============================================================

AGENT_TOOL_MANIFEST = {
    "register_strategy_version": {
        "description": "Register a versioned trading strategy in the lifecycle manager.",
        "access": "DECISION_ONLY",
        "execution": "PAPER_OR_BLOCKED",
    },
    "update_strategy_lifecycle": {
        "description": "Promote, demote, watch, reject, retest, or cooldown a strategy version.",
        "access": "DECISION_ONLY",
        "execution": "PAPER_OR_BLOCKED",
    },
    "get_strategy_lifecycle": {
        "description": "Retrieve strategy versions and their current lifecycle states.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "evaluate_strategy_lifecycle": {
        "description": "Evaluate validation evidence and assign a deterministic strategy lifecycle state.",
        "access": "DECISION_ONLY",
        "execution": "PAPER_OR_BLOCKED",
    },

    "analyze_market": {
        "description": "Run deep historical validation and risk-aware market analysis.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "get_market_snapshot": {
        "description": "Fetch the latest public Binance spot price.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "get_decision_history": {
        "description": "Retrieve recent SQLite-audited Sentinel decisions.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "get_agent_status": {
        "description": "Return the current Sentinel safety and execution state.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "get_agent_tools_manifest": {
        "description": "Return the complete Hex Sentinel agent tool manifest and execution safety policy.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "scan_binance": {
        "description": "Scan Binance USDT spot candidates.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "deep_validate_symbol": {
        "description": "Run full historical validation for one symbol.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "scan_and_validate_candidates": {
        "description": "Scan, validate, filter and rank market candidates.",
        "access": "READ_ONLY",
        "execution": "BLOCKED",
    },
    "finalize_candidate_decision": {
        "description": "Apply deterministic risk gates and return a paper-only decision.",
        "access": "DECISION_ONLY",
        "execution": "PAPER_OR_BLOCKED",
    },
}


def get_agent_tools_manifest():
    """Return the registered Hex Sentinel agent capabilities."""

    return {
        "agent": "Hex Sentinel",
        "mode": "PAPER/BACKTEST ONLY",
        "live_execution": "BLOCKED",
        "tools": AGENT_TOOL_MANIFEST,
    }


agent_tools["get_agent_tools_manifest"] = get_agent_tools_manifest

print("Agent tool manifest registered.")


# ============================================================
# STAGE 4.2 — AGENT TOOL EXECUTION
# ============================================================

def execute_tool(tool_name, *args):
    """Safely execute a registered Sentinel agent tool."""

    if tool_name not in agent_tools:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}"
        }

    try:
        result = agent_tools[tool_name](*args)
        return {
            "success": True,
            "tool": tool_name,
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "tool": tool_name,
            "error": str(e)
        }


# ============================================================
# STAGE 4.3 / STAGE 6.2 — MANIFEST-DRIVEN AI TOOL ROUTER
# ============================================================

def route_user_request(user_request):
    """Route a request through AI when available, with safe offline fallback."""

    allowed_tools = [
        tool_name
        for tool_name in AGENT_TOOL_MANIFEST
        if tool_name in agent_tools
    ]

    request_lower = user_request.strip().lower()

    def deterministic_route():
        """Safe local routing used when AI is unavailable or invalid."""

        if any(word in request_lower for word in [
            "scan and validate",
            "validate candidates",
            "best candidates",
            "rank candidates"
        ]):
            return "scan_and_validate_candidates"

        if any(word in request_lower for word in [
            "deep validate",
            "validate symbol",
            "historical validation"
        ]):
            return "deep_validate_symbol"

        if any(word in request_lower for word in [
            "scan",
            "scanner",
            "all crypto",
            "binance market"
        ]):
            return "scan_binance"

        if any(word in request_lower for word in [
            "status",
            "state",
            "safety"
        ]):
            return "get_agent_status"

        if any(word in request_lower for word in [
            "history",
            "decisions",
            "recent"
        ]):
            return "get_decision_history"

        if any(word in request_lower for word in [
            "analyze",
            "analysis"
        ]):
            return "analyze_market"

        if any(word in request_lower for word in [
            "market",
            "price"
        ]):
            return "get_market_snapshot"

        return None

    # Bare commands do not need AI routing.
    if request_lower in ["status", "state", "safety"]:
        return execute_tool("get_agent_status")

    if request_lower in ["history", "decisions", "recent"]:
        return execute_tool("get_decision_history")

    if request_lower in ["market", "price"]:
        return execute_tool("get_market_snapshot")

    routed_tool = None

    try:
        tool_descriptions = "\n".join(
            f"- {tool_name}: {AGENT_TOOL_MANIFEST[tool_name]['description']}"
            for tool_name in allowed_tools
        )

        router_prompt = f"""
You are the tool router for Hex Sentinel.

Select EXACTLY ONE tool from this approved list:

{chr(10).join(allowed_tools)}

Tool meanings:
{tool_descriptions}

User request:
{user_request}

Return ONLY the exact tool name.
"""

        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {
                        "role": "system",
                        "content": "Return only one exact approved tool name."
                    },
                    {
                        "role": "user",
                        "content": router_prompt
                    }
                ],
                "temperature": 0,
                "reasoning_effort": "low",
                "include_reasoning": False,
                "max_completion_tokens": 30
            },
            timeout=30
        )

        response.raise_for_status()

        candidate = (
            response.json()["choices"][0]["message"]
            .get("content", "")
            .strip()
        )

        if candidate in allowed_tools:
            routed_tool = candidate
        else:
            for tool_name in allowed_tools:
                if tool_name in candidate:
                    routed_tool = tool_name
                    break

    except Exception:
        # AI/network failure must not disable safe local routing.
        routed_tool = None

    # Deterministic fallback.
    if routed_tool not in allowed_tools:
        routed_tool = deterministic_route()

    if routed_tool is None:
        return {
            "success": False,
            "error": "No safe manifest-approved tool matched the request."
        }

    # Extract a symbol after explicit price/market keywords.
    if routed_tool == "get_market_snapshot":

        symbol_match = re.search(
            r"\b(?:price|market)\s+(?:price\s+)?([A-Za-z0-9]{2,20})\b",
            user_request,
            re.IGNORECASE,
        )

        if symbol_match:
            requested = symbol_match.group(1).upper()

            if requested not in {"PRICE", "MARKET"}:
                return execute_tool(
                    "get_market_snapshot",
                    requested
                )

        # Handle phrases such as "market price BTC".
        tokens = re.findall(r"[A-Za-z0-9]{2,20}", user_request.upper())

        for token in reversed(tokens):
            if token not in {
                "MARKET",
                "PRICE",
                "CURRENT",
                "THE",
                "OF",
                "FOR"
            }:
                return execute_tool(
                    "get_market_snapshot",
                    token
                )

    # Extract a symbol for market analysis.
    if routed_tool == "analyze_market":

        tokens = re.findall(r"[A-Za-z0-9]{2,20}", user_request.upper())

        for token in reversed(tokens):
            if token not in {
                "ANALYZE",
                "ANALYSIS",
                "MARKET",
                "THE"
            }:
                return execute_tool(
                    "analyze_market",
                    token
                )

    return execute_tool(routed_tool)


# ============================================================
# STAGE 6 — SENTINEL INTERACTIVE DEMO
# ============================================================

def search_binance_crypto(query):
    """Search Binance USDT spot symbols by name or symbol."""

    query = query.strip().lower()
    if not query:
        return []

    try:
        response = requests.get(
            f"{BINANCE_API}/api/v3/exchangeInfo",
            timeout=10
        )
        response.raise_for_status()
        symbols = response.json().get("symbols", [])

        coin_response = requests.get(
            "https://api.coingecko.com/api/v3/coins/list",
            timeout=10
        )
        coin_response.raise_for_status()
        coins = coin_response.json()

    except Exception as e:
        print(f"⚠️ Crypto search error: {e}")
        return []

    # Binance is the source of truth for tradable assets.
    binance_assets = {}

    for item in symbols:
        if (
            item.get("status") != "TRADING"
            or item.get("quoteAsset") != "USDT"
            or item.get("isSpotTradingAllowed") is not True
        ):
            continue

        symbol = item.get("symbol", "")
        base_asset = item.get("baseAsset", "")

        if base_asset.endswith(("UP", "DOWN", "BULL", "BEAR")):
            continue

        binance_assets[base_asset.upper()] = symbol

    results = {}

    # Direct Binance symbol/base-asset matching.
    for base_asset, symbol in binance_assets.items():
        if query in base_asset.lower() or query in symbol.lower():
            results[symbol] = {
                "symbol": symbol,
                "base_asset": base_asset,
                "name": base_asset
            }

    # CoinGecko name/symbol matching.
    for coin in coins:
        name = coin.get("name", "")
        coin_symbol = coin.get("symbol", "").upper()

        if not name or not coin_symbol:
            continue

        if query in name.lower() or query in coin_symbol.lower():
            symbol = binance_assets.get(coin_symbol)

            if symbol:
                candidate = {
                    "symbol": symbol,
                    "base_asset": coin_symbol,
                    "name": name
                }

                existing = results.get(symbol)

                if existing is None:
                    results[symbol] = candidate
                else:
                    # Prefer exact name matches over symbol collisions.
                    existing_exact = existing["name"].lower() == query
                    candidate_exact = name.lower() == query

                    if candidate_exact and not existing_exact:
                        results[symbol] = candidate

    # Rank exact/strong matches first.
    ranked = list(results.values())

    def score(item):
        name = item["name"].lower()
        base = item["base_asset"].lower()
        symbol = item["symbol"].lower()

        if name == query:
            return 0
        if base == query:
            return 1
        if symbol == query:
            return 2
        if name.startswith(query):
            return 3
        if base.startswith(query):
            return 4
        return 5

    ranked.sort(key=lambda x: (score(x), x["name"].lower()))

    return ranked[:20]

def market_menu():
    """Interactive Binance-wide bullish/bearish candidate scanner."""

    print("\n📊 MARKET SCANNER")
    print("1. 🟢 Bullish Candidates")
    print("2. 🔴 Bearish Candidates")
    print("3. 🔎 Search Crypto")
    print("4. Exit")

    choice = input("\nChoose: ").strip()

    if choice == "4":
        return

    if choice == "3":
        query = input("\nSearch crypto: ").strip()

        results = search_binance_crypto(query)

        if not results:
            print("⚠️ No matching Binance USDT spot symbols found.")
            return

        print("\n🔎 SEARCH RESULTS")

        for i, item in enumerate(results, 1):
            print(f"{i}. {item['symbol']} — {item['name']}")

        selection = input("\nSelect coin number (or Enter to return): ").strip()

        if not selection:
            return

        try:
            index = int(selection) - 1
            if index < 0 or index >= len(results):
                print("⚠️ Invalid coin selection.")
                return
        except ValueError:
            print("⚠️ Enter a valid coin number.")
            return

        symbol = results[index]["symbol"]

        print(f"\n🔬 Deep-validating {symbol}...")

        result = analyze_market(symbol)

        print("\n🤖 Tool: analyze_market")
        print("📊 Result:", result)

        if isinstance(result, dict) and result.get("current_price") is not None:
            print(f"💰 Current price: ${result['current_price']:,.2f}")

        print("🔒 Live execution: BLOCKED")
        return

    if choice not in ["1", "2"]:
        print("⚠️ Invalid choice.")
        return

    print("\n🔎 Scanning Binance spot market...")
    scan = scan_binance()

    candidates = scan["top_buys"] if choice == "1" else scan["top_sells"]
    label = "BULLISH" if choice == "1" else "BEARISH"

    print(f"\n{'🟢' if choice == '1' else '🔴'} {label} CANDIDATES")
    print(f"Universe: {scan['universe']} | Scanned: {scan['scanned']}")

    for i, item in enumerate(candidates, 1):
        print(
            f"{i}. {item['symbol']} | "
            f"RSI {item['rsi']:.2f} | "
            f"Trend {item['trend_strength']:.2f}%"
        )

    if not candidates:
        print("⚠️ No candidates found.")
        return

    selection = input("\nSelect coin number (or Enter to return): ").strip()

    if not selection:
        return

    try:
        index = int(selection) - 1
        if index < 0 or index >= len(candidates):
            print("⚠️ Invalid coin selection.")
            return
    except ValueError:
        print("⚠️ Enter a valid coin number.")
        return

    symbol = candidates[index]["symbol"]

    print(f"\n🔬 Deep-validating {symbol}...")

    result = analyze_market(symbol)

    print("\n🤖 Tool: analyze_market")
    print("📊 Result:", result)

    if isinstance(result, dict) and result.get("current_price") is not None:
        print(f"💰 Current price: ${result['current_price']:,.2f}")

    print("🔒 Live execution: BLOCKED")


def normalize_command(user_input):
    """Normalize common command aliases and safely correct minor typos."""
    if not isinstance(user_input, str):
        return None

    command = user_input.strip().lower()
    if not command:
        return None

    aliases = {
        "q": "quit",
        "exit": "quit",
        "analyse": "analyze",
        "analus": "analyze",
        "price": "market",
        "scan": "scan_binance",
    }

    command = aliases.get(command, command)
    commands = ["status", "market", "history", "analyze", "scan_binance", "quit"]

    if command in commands:
        return command

    matches = get_close_matches(command, commands, n=1, cutoff=0.70)
    if matches:
        return matches[0]

    return command


def demo_interface():
    """Interactive terminal interface for the Sentinel agent."""

    print("\n" + "=" * 60)
    print("🛡️ HEX SENTINEL — INTERACTIVE DEMO")
    print("=" * 60)
    print("Mode: PAPER/BACKTEST ONLY")
    print("Live execution: BLOCKED")
    print("\nAvailable commands:")
    print("  status   → Current Sentinel safety state")
    print("  market   → Scan bullish/bearish Binance candidates")
    print("  history  → Recent audited decisions")
    print("  analyze  → Analyze the current market")
    print("  quit     → Exit demo")

    while True:
        try:
            raw_request = input("\nSentinel > ").strip()

            if not raw_request:
                continue

            user_request = normalize_command(raw_request)

            if user_request == "quit":
                print("\n👋 Sentinel demo closed.")
                break

            if user_request != raw_request.lower():
                print(f"🧭 Interpreting '{raw_request}' as '{user_request}'")

            # Deterministic interactive market scanner.
            if user_request == "market":
                market_menu()
                continue

            router_result = route_user_request(user_request)

            if router_result["success"]:
                print("\n🤖 Tool:", router_result["tool"])
                print("📊 Result:", router_result["result"])

                result_data = router_result["result"]
                if isinstance(result_data, dict) and result_data.get("current_price") is not None:
                    print(f"💰 Current price: ${result_data['current_price']:,.2f}")
            else:
                print("\n⚠️ Request blocked:", router_result["error"])

            print("🔒 Live execution: BLOCKED")

        except KeyboardInterrupt:
            print("\n\n👋 Sentinel demo closed.")
            break
        except Exception as e:
            print(f"\n⚠️ Demo error: {e}")




# ============================================================
# STAGE 5 — BINANCE-WIDE MARKET SCANNER
# ============================================================

from concurrent.futures import ThreadPoolExecutor, as_completed

BINANCE_API = "https://api.binance.com"
SCAN_INTERVAL = "1h"
SCAN_CANDLES = 100
SCAN_WORKERS = 8


def scanner_ema(values, span):
    alpha = 2.0 / (span + 1.0)
    ema = values[0]
    for value in values[1:]:
        ema = alpha * value + (1 - alpha) * ema
    return ema


def scanner_rsi(values, period=14):
    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    if len(gains) < period:
        return 50.0

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def discover_binance_usdt_symbols():
    response = requests.get(
        f"{BINANCE_API}/api/v3/exchangeInfo",
        timeout=15
    )
    response.raise_for_status()

    return [
        item["symbol"]
        for item in response.json()["symbols"]
        if (
            item["status"] == "TRADING"
            and item["quoteAsset"] == "USDT"
            and item.get("isSpotTradingAllowed", False)
            and not any(
                item["symbol"].endswith(x)
                for x in ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]
            )
        )
    ]


def get_active_scan_candidates(symbols, limit=50):
    """Use Binance bulk 24h ticker data to reduce the technical scan universe."""

    try:
        response = requests.get(
            f"{BINANCE_API}/api/v3/ticker/24hr",
            timeout=15
        )
        response.raise_for_status()
        tickers = response.json()

        allowed = set(symbols)
        ranked = []

        for ticker in tickers:
            symbol = ticker.get("symbol")

            if symbol not in allowed:
                continue

            try:
                quote_volume = float(ticker.get("quoteVolume", 0))
            except (TypeError, ValueError):
                quote_volume = 0

            ranked.append((quote_volume, symbol))

        ranked.sort(reverse=True)

        return [symbol for _, symbol in ranked[:limit]]

    except Exception as e:
        print(f"⚠️ Bulk ticker filter failed: {e}")
        return symbols


def scan_one_symbol(symbol):
    try:
        response = requests.get(
            f"{BINANCE_API}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": SCAN_INTERVAL,
                "limit": SCAN_CANDLES
            },
            timeout=15
        )
        response.raise_for_status()

        closes = [float(candle[4]) for candle in response.json()]

        if len(closes) < 60:
            return None

        ema20 = scanner_ema(closes, 20)
        ema50 = scanner_ema(closes, 50)
        rsi = scanner_rsi(closes, 14)

        if ema20 > ema50 and 50 <= rsi <= 70:
            signal = "BUY"
        elif ema20 < ema50:
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "symbol": symbol,
            "price": closes[-1],
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "trend_strength": abs(ema20 - ema50) / ema50 * 100,
            "signal": signal
        }

    except Exception:
        return None


def scan_binance():
    """Fast read-only scan of Binance active USDT spot pairs."""

    symbols = discover_binance_usdt_symbols()

    # Fast bulk-volume filter before requesting individual klines.
    scan_symbols = get_active_scan_candidates(symbols, limit=50)

    results = []

    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as executor:
        futures = [executor.submit(scan_one_symbol, s) for s in scan_symbols]

        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    buys = sorted(
        [x for x in results if x["signal"] == "BUY"],
        key=lambda x: x["trend_strength"],
        reverse=True
    )

    sells = sorted(
        [x for x in results if x["signal"] == "SELL"],
        key=lambda x: x["trend_strength"],
        reverse=True
    )

    return {
        "universe": len(symbols),
        "scanned": len(results),
        "top_buys": buys[:10],
        "top_sells": sells[:10]
    }


agent_tools["scan_binance"] = scan_binance

print("Binance-wide scanner registered.")


# ============================================================
# STAGE 5.1 — DEEP VALIDATION
# ============================================================

import io
import contextlib
import sentinel_stage1


def ensure_strategy_versions_table():
    """Create the strategy lifecycle table if it does not already exist."""

    with sqlite3.connect("sentinel.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'WATCH',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                UNIQUE(strategy_name, version)
            )
        """)
        conn.commit()


def register_strategy_version(strategy_name="EMA_RSI", version="v1", status="WATCH", reason="Initial registration"):
    """Register or update a strategy version in the lifecycle registry."""

    ensure_strategy_versions_table()

    with sqlite3.connect("sentinel.db") as conn:
        conn.execute("""
            INSERT INTO strategy_versions
            (strategy_name, version, status, reason)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(strategy_name, version) DO UPDATE SET
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP,
                reason=excluded.reason
        """, (strategy_name, version, status, reason))
        conn.commit()

    return {
        "strategy_name": strategy_name,
        "version": version,
        "status": status,
        "reason": reason
    }



def get_previous_lifecycle_state(strategy_name, version):
    """Return the current persisted lifecycle state before a new evaluation."""
    ensure_strategy_versions_table()

    with sqlite3.connect("sentinel.db") as conn:
        row = conn.execute("""
            SELECT status
            FROM strategy_versions
            WHERE strategy_name = ? AND version = ?
        """, (strategy_name, version)).fetchone()

    return row[0] if row else None


def apply_lifecycle_transition(previous_state, proposed_state, validation):
    """Apply deterministic lifecycle transition rules."""

    if previous_state == "COOLDOWN":
        return "COOLDOWN", "Strategy remains in cooldown until a fresh retest is completed."

    if proposed_state == "RETEST":
        return "RETEST", "Fresh validation is required before the strategy can return to an active lifecycle state."

    if proposed_state == "REJECT":
        return "REJECT", "Strategy failed the approval gate."

    if previous_state == "PROMOTE" and proposed_state == "WATCH":
        return "DEMOTE", "Previously promoted strategy no longer meets promotion criteria."

    if previous_state == "DEMOTE" and proposed_state == "WATCH":
        return "WATCH", "Strategy shows sufficient evidence to leave demotion status but not enough for promotion."

    return proposed_state, None


def evaluate_strategy_lifecycle(validation, strategy_name="EMA_RSI", version="v1"):
    """Automatically assign a lifecycle state from deterministic validation evidence."""

    if not isinstance(validation, dict):
        return {
            "success": False,
            "status": "REJECT",
            "reason": "Invalid validation result."
        }

    if validation.get("status") == "ERROR":
        lifecycle = "RETEST"
        reason = "Validation failed to produce reliable evidence."

    else:
        pf = float(validation.get("profit_factor", 0) or 0)
        drawdown = float(validation.get("max_drawdown_pct", 100) or 100)
        trades = int(validation.get("trades", 0) or 0)
        expectancy = float(validation.get("expectancy", 0) or 0)
        status = validation.get("status")
        signal = validation.get("signal")

        if status != "APPROVED":
            lifecycle = "REJECT"
            reason = "Strategy failed the existing approval gate."

        elif signal not in ("BUY", "SELL"):
            lifecycle = "WATCH"
            reason = "Strategy is approved but has no actionable signal."

        elif trades < 30 or pf < 1.10 or drawdown > 20 or expectancy <= 0:
            lifecycle = "WATCH"
            reason = "Strategy passes basic approval but lacks sufficient risk-adjusted evidence for promotion."

        elif pf >= 1.50 and drawdown <= 15 and trades >= 50 and expectancy > 0:
            lifecycle = "PROMOTE"
            reason = "Strong deterministic validation evidence supports promotion."

        else:
            lifecycle = "WATCH"
            reason = "Strategy passes validation but evidence is not strong enough for promotion."

    previous_state = get_previous_lifecycle_state(strategy_name, version)

    lifecycle, transition_reason = apply_lifecycle_transition(
        previous_state,
        lifecycle,
        validation
    )

    if transition_reason:
        reason = transition_reason

    lifecycle_result = update_strategy_lifecycle(
        strategy_name,
        version,
        lifecycle,
        reason
    )

    return {
        "success": lifecycle_result.get("success", True),
        "strategy_name": strategy_name,
        "version": version,
        "lifecycle": lifecycle,
        "reason": reason,
        "validation": validation
    }


def update_strategy_lifecycle(strategy_name, version, status, reason):
    """Update a strategy lifecycle state with an explicit reason."""

    ensure_strategy_versions_table()

    allowed_states = {"PROMOTE", "DEMOTE", "WATCH", "REJECT", "RETEST", "COOLDOWN"}

    if status not in allowed_states:
        return {
            "success": False,
            "error": f"Invalid lifecycle state: {status}"
        }

    with sqlite3.connect("sentinel.db") as conn:
        conn.execute("""
            INSERT INTO strategy_versions
            (strategy_name, version, status, reason)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(strategy_name, version) DO UPDATE SET
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP,
                reason=excluded.reason
        """, (strategy_name, version, status, reason))
        conn.commit()

    return {
        "success": True,
        "strategy_name": strategy_name,
        "version": version,
        "status": status,
        "reason": reason
    }


def get_strategy_lifecycle(strategy_name=None):
    """Return current strategy lifecycle records."""

    ensure_strategy_versions_table()

    query = """
        SELECT strategy_name, version, status, created_at, updated_at, reason
        FROM strategy_versions
    """
    params = ()

    if strategy_name:
        query += " WHERE strategy_name = ?"
        params = (strategy_name,)

    query += " ORDER BY updated_at DESC"

    with sqlite3.connect("sentinel.db") as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "strategy_name": row[0],
            "version": row[1],
            "status": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "reason": row[5]
        }
        for row in rows
    ]


agent_tools["register_strategy_version"] = register_strategy_version
agent_tools["update_strategy_lifecycle"] = update_strategy_lifecycle
agent_tools["get_strategy_lifecycle"] = get_strategy_lifecycle
agent_tools["evaluate_strategy_lifecycle"] = evaluate_strategy_lifecycle

def deep_validate_symbol(symbol):
    """Run the full Stage 1 validation engine for one scanner candidate."""
    original_symbol = sentinel_stage1.SYMBOL

    try:
        sentinel_stage1.SYMBOL = symbol.upper()

        with contextlib.redirect_stdout(io.StringIO()):
            result = sentinel_stage1.main()

        if not result or "metrics" not in result:
            return {
                "symbol": symbol.upper(),
                "status": "ERROR",
                "signal": "HOLD",
                "error": "Stage 1 returned no validation data."
            }

        metrics = result["metrics"]

        return {
            "symbol": result["symbol"],
            "status": result["status"],
            "signal": result["signal"],
            "return_pct": metrics["total_return"] * 100,
            "profit_factor": metrics["profit_factor"],
            "max_drawdown_pct": metrics["max_drawdown"] * 100,
            "trades": metrics["total_trades"],
            "expectancy": metrics["expectancy"]
        }

    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "status": "ERROR",
            "signal": "HOLD",
            "error": str(e)
        }

    finally:
        sentinel_stage1.SYMBOL = original_symbol

agent_tools["deep_validate_symbol"] = deep_validate_symbol

print("Deep validation tool registered.")

# ============================================================
# STAGE 5.2 — CANDIDATE RISK FILTER & RANKING
# ============================================================

def rank_validated_candidates(results):
    """Rank deeply validated candidates using deterministic risk rules."""

    ranked = []

    for result in results:
        if result.get("status") != "APPROVED":
            continue

        if result.get("signal") not in ["BUY", "SELL"]:
            continue

        pf = result.get("profit_factor", 0)
        drawdown = result.get("max_drawdown_pct", 100)
        trades = result.get("trades", 0)
        return_pct = result.get("return_pct", 0)

        # Deterministic safety filters.
        if pf < 1.10:
            continue

        if trades < 30:
            continue

        if drawdown > 20:
            continue

        score = (
            (return_pct * 0.35)
            + (pf * 10 * 0.35)
            - (drawdown * 0.20)
            + (min(trades, 100) * 0.10)
        )

        ranked.append({
            **result,
            "score": round(score, 2)
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return ranked


def scan_and_validate_candidates(limit=6):
    """Scan Binance, deeply validate candidates, then apply risk ranking."""

    scan = scan_binance()

    candidates = (
        scan["top_buys"][:limit // 2]
        + scan["top_sells"][:limit // 2]
    )

    validated = []

    for candidate in candidates:
        validated.append(
            deep_validate_symbol(candidate["symbol"])
        )

    ranked = rank_validated_candidates(validated)

    return {
        "universe": scan["universe"],
        "scanned": scan["scanned"],
        "candidates": validated,
        "ranked": ranked
    }


agent_tools["scan_and_validate_candidates"] = scan_and_validate_candidates

print("Candidate risk filter registered.")


# ============================================================
# STAGE 5.4 — FINAL DECISION GATE
# ============================================================


def audit_final_decision(decision):
    """Persist the Stage 5 final candidate decision for auditability."""
    import sqlite3
    from datetime import datetime, timezone

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS final_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT,
            signal TEXT NOT NULL,
            decision TEXT NOT NULL,
            score REAL,
            reason TEXT NOT NULL,
            live_execution TEXT NOT NULL
        )
    """)

    cursor.execute("""
        INSERT INTO final_decisions
        (timestamp, symbol, signal, decision, score, reason, live_execution)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        decision.get("symbol"),
        decision.get("signal", "HOLD"),
        decision.get("decision", "NO_ACTION"),
        decision.get("score"),
        decision.get("reason", ""),
        decision.get("live_execution", "BLOCKED")
    ))

    conn.commit()
    conn.close()
    return decision


def finalize_candidate_decision(ranked_results):
    """Apply the final deterministic paper-trading safety gate."""

    if not ranked_results:
        return {
            "decision": "NO_ACTION",
            "symbol": None,
            "signal": "HOLD",
            "reason": "No candidate passed all deterministic validation filters.",
            "live_execution": "BLOCKED"
        }

    winner = ranked_results[0]

    if winner.get("status") != "APPROVED":
        return {
            "decision": "NO_ACTION",
            "symbol": winner.get("symbol"),
            "signal": "HOLD",
            "reason": "Top candidate is not approved.",
            "live_execution": "BLOCKED"
        }

    if winner.get("signal") not in ["BUY", "SELL"]:
        return {
            "decision": "NO_ACTION",
            "symbol": winner.get("symbol"),
            "signal": "HOLD",
            "reason": "Top candidate has no actionable signal.",
            "live_execution": "BLOCKED"
        }

    decision = {
        "decision": f"PAPER_{winner['signal']}",
        "symbol": winner["symbol"],
        "signal": winner["signal"],
        "score": winner["score"],
        "reason": "Candidate passed Binance-wide scan, deep validation, risk filtering, and ranking.",
        "live_execution": "BLOCKED"
    }

    return audit_final_decision(decision)


agent_tools["finalize_candidate_decision"] = finalize_candidate_decision

print("Final decision gate registered.")

if __name__ == "__main__":
    import sys

    # STAGE 6.12 — COMMAND-LINE SYMBOL SELECTION
    selected_symbol = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "BTCUSDT"
    )

    print(
        f"📌 Selected symbol: "
        f"{selected_symbol.upper()}"
    )

    run_legacy_pipeline(selected_symbol)
    demo_interface()
