import os
import subprocess
import requests
import sqlite3
import re

API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

if not API_KEY:
    print("ERROR: GROQ_API_KEY is not loaded.")
    raise SystemExit(1)


# ============================================================
# RUN STAGE 1
# ============================================================

def run_legacy_pipeline():
    """Run the original Stage 1–4 startup pipeline."""
    global status, signal, final_action, live_execution
    global ai_assessment, risk_status, risk_reason, agent_state
    global sentinel_output
    print("🔎 Running Binance Sentinel Stage 1...\n")

    try:
        result = subprocess.run(
            ["python", "sentinel_stage1.py"],
            capture_output=True,
            text=True,
            timeout=180
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

    user_prompt = f"""
    Deterministic strategy status: {status}
    Paper signal: {signal}
    Final allowed action: {final_action}
    Live execution: {live_execution}

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
        raise SystemExit(1)

    if response.status_code != 200:
        print(f"❌ Groq API error: {response.status_code}")
        print(response.text)
        raise SystemExit(1)

    data = response.json()

    ai_assessment = data["choices"][0]["message"].get("content") or (
        "ASSESSMENT: CAUTIOUS\n"
        "CONFIDENCE: LOW\n"
        "OOS_EVIDENCE: UNKNOWN\n"
        "RISK: MODERATE\n"
        "REASON: AI response was unavailable; deterministic safety controls remain active."
    )

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

    agent_state = {
        "agent": "Hex Sentinel",
        "stage": "3",
        "market": {
            "symbol": "BTCUSDT",
            "signal": signal
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

        cursor.execute("""
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

        cursor.execute("""
            INSERT INTO agent_decisions (
                timestamp,
                symbol,
                signal,
                strategy_status,
                risk_status,
                final_action,
                live_execution,
                ai_assessment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            agent_state["market"]["symbol"],
            agent_state["market"]["signal"],
            agent_state["validation"]["strategy_status"],
            agent_state["risk"]["status"],
            agent_state["execution"]["action"],
            agent_state["execution"]["live_execution"],
            agent_state["ai"]["assessment"]
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
# STAGE 2.2 — DETERMINISTIC RISK GATE
# ============================================================

def stage2_risk_gate(status, signal, ai_assessment):

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

def analyze_market():
    """Run the Sentinel market-analysis pipeline."""
    return {
        "symbol": agent_state["market"]["symbol"],
        "signal": agent_state["market"]["signal"],
        "strategy_status": agent_state["validation"]["strategy_status"],
        "risk_status": agent_state["risk"]["status"],
        "final_action": agent_state["execution"]["action"],
        "live_execution": agent_state["execution"]["live_execution"]
    }


def get_decision_history():
    """Return the latest five audited agent decisions."""
    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT timestamp, symbol, signal, risk_status, final_action
        FROM agent_decisions
        ORDER BY id DESC
        LIMIT 5
    """)

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_agent_status():
    """Return the current Sentinel safety state."""
    return {
        "agent": "Hex Sentinel",
        "mode": "PAPER/BACKTEST ONLY",
        "strategy_status": status,
        "risk_status": risk_status,
        "final_action": final_action,
        "live_execution": "BLOCKED"
    }


agent_tools = {
    "analyze_market": analyze_market,
    "get_decision_history": get_decision_history,
    "get_agent_status": get_agent_status
}

# ============================================================
# STAGE 4.2 — AGENT TOOL EXECUTION
# ============================================================

def execute_tool(tool_name):
    """Safely execute a registered Sentinel agent tool."""

    if tool_name not in agent_tools:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}"
        }

    try:
        result = agent_tools[tool_name]()
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
# STAGE 4.3 — AI TOOL ROUTER
# ============================================================

def route_user_request(user_request):
    """Use the AI layer to select one safe Sentinel read-only tool."""

    router_prompt = f"""
You are the tool router for Hex Sentinel.

Select EXACTLY ONE tool from this list:

analyze_market
get_decision_history
get_agent_status
scan_binance
scan_and_validate_candidates

Tool meanings:
- analyze_market = analyze the current validated market result
- get_decision_history = show recent audited decisions
- get_agent_status = show current Sentinel safety/status state
- scan_binance = scan all active Binance USDT spot pairs
- scan_and_validate_candidates = scan Binance, deep-validate candidates, filter and rank approved candidates

User request:
{user_request}

Return ONLY the tool name.
"""

    try:
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
                        "content": "Return only one valid tool name."
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
        routed_tool = response.json()["choices"][0]["message"].get("content", "").strip()

        # Normalize AI output and allow only registered safe tools.
        for allowed_tool in agent_tools:
            if allowed_tool in routed_tool:
                routed_tool = allowed_tool
                break
        else:
            # Safe deterministic fallback when AI returns empty/invalid output.
            request_lower = user_request.lower()

            if any(word in request_lower for word in ["scan", "scanner", "all crypto", "binance market"]):
                routed_tool = "scan_binance"
            elif any(word in request_lower for word in ["status", "state", "safety"]):
                routed_tool = "get_agent_status"
            elif any(word in request_lower for word in ["history", "decisions", "recent"]):
                routed_tool = "get_decision_history"
            elif any(word in request_lower for word in ["analyze", "analysis", "market"]):
                routed_tool = "analyze_market"
            else:
                return {
                    "success": False,
                    "error": "AI selected an invalid or unsafe tool."
                }

        return execute_tool(routed_tool)

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# STAGE 6 — SENTINEL INTERACTIVE DEMO
# ============================================================

def demo_interface():
    """Interactive terminal interface for the Sentinel agent."""

    print("\n" + "=" * 60)
    print("🛡️ HEX SENTINEL — INTERACTIVE DEMO")
    print("=" * 60)
    print("Mode: PAPER/BACKTEST ONLY")
    print("Live execution: BLOCKED")
    print("\nAvailable commands:")
    print("  status   → Current Sentinel safety state")
    print("  market   → Current validated market analysis")
    print("  history  → Recent audited decisions")
    print("  analyze  → Analyze the current market")
    print("  quit     → Exit demo")

    while True:
        try:
            user_request = input("\nSentinel > ").strip()

            if user_request.lower() in ["quit", "exit", "q"]:
                print("\n👋 Sentinel demo closed.")
                break

            if not user_request:
                continue

            router_result = route_user_request(user_request)

            if router_result["success"]:
                print("\n🤖 Tool:", router_result["tool"])
                print("📊 Result:", router_result["result"])
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
    """Read-only fast scan of Binance active USDT spot pairs."""

    symbols = discover_binance_usdt_symbols()
    results = []

    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as executor:
        futures = [executor.submit(scan_one_symbol, s) for s in symbols]

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
    run_legacy_pipeline()
    demo_interface()
