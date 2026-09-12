import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()
import os
import subprocess
import requests
import sqlite3
import re
from difflib import get_close_matches

API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

if not API_KEY:
    print("ERROR: GROQ_API_KEY is not loaded.")
    raise SystemExit(1)


# ============================================================
# STAGE 7.1 — AI PROVIDER ABSTRACTION
# ============================================================

def call_groq_analysis(system_prompt, user_prompt):
    """Call the existing Groq market-analysis provider."""
    response = requests.post(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "reasoning_effort": "low",
            "include_reasoning": False,
            "max_completion_tokens": 300,
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"].get("content") or ""





def build_trade_plan_market_snapshot(symbol="BTCUSDT"):
    """Build a prediction-time market snapshot using only completed Binance data."""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    original_symbol = sentinel_stage1.SYMBOL

    try:
        sentinel_stage1.SYMBOL = symbol

        server_response = requests.get(
            "https://api.binance.com/api/v3/time",
            timeout=10
        )
        server_response.raise_for_status()
        server_time_ms = int(server_response.json()["serverTime"])

        candles = sentinel_stage1.fetch_binance_data(
            symbol,
            sentinel_stage1.INTERVAL,
            sentinel_stage1.CANDLES
        )

        if len(candles) < 200:
            raise RuntimeError(
                "Insufficient Binance candle data for trade-plan snapshot."
            )

        interval_seconds = 3600
        boundary_ms = server_time_ms - (server_time_ms % (interval_seconds * 1000))

        valid_candles = [
            row for row in candles
            if int(row["open_time"]) < boundary_ms
        ]

        if len(valid_candles) < 200:
            raise RuntimeError(
                "Insufficient completed Binance candles for trade-plan snapshot."
            )

        future_candles = [
            row for row in candles
            if int(row["open_time"]) >= server_time_ms
        ]

        future_data_included = bool(future_candles)

        prepared = sentinel_stage1.prepare_indicators(valid_candles)

        if not prepared:
            raise RuntimeError(
                "Indicator preparation returned no usable completed rows."
            )

        latest = prepared[-1]

        current_price = get_current_price(symbol)

        return {
            "timestamp": latest["datetime"].isoformat(),
            "symbol": symbol,
            "current_price": float(current_price),
            "candle_close": float(latest["close"]),
            "ema_fast": float(latest["ema_fast"]),
            "ema_slow": float(latest["ema_slow"]),
            "rsi": float(latest["rsi"]),
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "volume": float(latest["volume"]),
            "server_time": datetime.fromtimestamp(
                server_time_ms / 1000,
                timezone.utc
            ).isoformat(),
            "data_source": "LIVE_BINANCE_SPOT_KLINES",
            "future_data_included": future_data_included,
            "completed_candle_only": True,
            "live_execution": "BLOCKED"
        }

    finally:
        sentinel_stage1.SYMBOL = original_symbol

def call_groq_trade_plan(system_prompt, user_prompt):
    """Generate an independent 24-hour paper-trade plan with Groq."""
    response = requests.post(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "reasoning_effort": "low",
            "include_reasoning": False,
            "max_completion_tokens": 400,
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"].get("content") or ""


def call_gemini_trade_plan(system_prompt, user_prompt):
    """Generate an independent 24-hour paper-trade plan with Gemini."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY is not loaded")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.6-flash:streamGenerateContent"
    )

    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}]
            }
        ]
    }

    try:
        response = requests.post(
            url,
            params={"alt": "sse"},
            headers={
                "x-goog-api-key": gemini_key,
                "Content-Type": "application/json",
            },
            json=payload,
            stream=True,
            timeout=60,
        )
        response.raise_for_status()

    except requests.exceptions.Timeout as e:
        print("❌ GEMINI PROVIDER FAILURE | Status: TIMEOUT | Type: Timeout")
        raise RuntimeError(
            f"GEMINI_PROVIDER_TIMEOUT: {e}"
        ) from e

    except requests.exceptions.ConnectionError as e:
        print("❌ GEMINI PROVIDER FAILURE | Status: CONNECTION_ERROR | Type: ConnectionError")
        raise RuntimeError(
            f"GEMINI_PROVIDER_CONNECTION_ERROR: {e}"
        ) from e

    except requests.exceptions.HTTPError as e:
        print("❌ GEMINI PROVIDER FAILURE | Status: HTTP_ERROR | Type: HTTPError")
        raise RuntimeError(
            f"GEMINI_PROVIDER_HTTP_ERROR: {e}"
        ) from e

    except requests.exceptions.RequestException as e:
        print("❌ GEMINI PROVIDER FAILURE | Status: REQUEST_ERROR | Type: RequestException")
        raise RuntimeError(
            f"GEMINI_PROVIDER_REQUEST_ERROR: {e}"
        ) from e

    chunks = []

    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue

        if line.startswith("data:"):
            data_line = line[5:].strip()

            if not data_line:
                continue

            try:
                data = requests.models.complexjson.loads(data_line)
            except Exception:
                continue

            for candidate in data.get("candidates", []):
                content = candidate.get("content", {})
                for part in content.get("parts", []):
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)

    result = "".join(chunks).strip()

    if not result:
        raise RuntimeError("Gemini returned no usable trade plan")

    return result


def parse_trade_plan(plan_text):
    """Parse a provider's deterministic 24-hour paper-trade plan."""
    if not isinstance(plan_text, str) or not plan_text.strip():
        return {
            "valid": False,
            "reason": "Trade plan is empty or not text."
        }

    fields = {}
    required = [
        "DIRECTION",
        "ENTRY_LOW",
        "ENTRY_HIGH",
        "STOP_LOSS",
        "TP1",
        "TP2",
        "TP3",
        "CONFIDENCE",
        "REASON",
    ]

    for field in required:
        match = re.search(
            rf"(?m)^\s*{field}:\s*([^\n]+)\s*$",
            plan_text
        )
        if not match:
            return {
                "valid": False,
                "reason": f"Trade plan missing {field}."
            }
        fields[field] = match.group(1).strip()

    fields["DIRECTION"] = fields["DIRECTION"].upper()
    fields["CONFIDENCE"] = fields["CONFIDENCE"].upper()

    if fields["DIRECTION"] not in {"BUY", "SELL"}:
        return {
            "valid": False,
            "reason": f"Invalid DIRECTION: {fields['DIRECTION']}."
        }

    if fields["CONFIDENCE"] not in {"LOW", "MODERATE", "HIGH"}:
        return {
            "valid": False,
            "reason": f"Invalid CONFIDENCE: {fields['CONFIDENCE']}."
        }

    if not fields["REASON"]:
        return {
            "valid": False,
            "reason": "Trade plan REASON is empty."
        }

    numeric_fields = [
        "ENTRY_LOW",
        "ENTRY_HIGH",
        "STOP_LOSS",
        "TP1",
        "TP2",
        "TP3",
    ]

    for field in numeric_fields:
        try:
            value = float(fields[field])
        except (TypeError, ValueError):
            return {
                "valid": False,
                "reason": f"Invalid numeric value for {field}: {fields[field]}."
            }

        if value <= 0:
            return {
                "valid": False,
                "reason": f"{field} must be greater than zero."
            }

        fields[field] = value

    if fields["ENTRY_LOW"] > fields["ENTRY_HIGH"]:
        return {
            "valid": False,
            "reason": "ENTRY_LOW cannot exceed ENTRY_HIGH."
        }

    entry_reference = (fields["ENTRY_LOW"] + fields["ENTRY_HIGH"]) / 2.0

    if fields["DIRECTION"] == "BUY":
        if fields["STOP_LOSS"] >= fields["ENTRY_LOW"]:
            return {
                "valid": False,
                "reason": "BUY stop-loss must be below the entry zone."
            }

        if not (
            fields["TP1"] < fields["TP2"] < fields["TP3"]
        ):
            return {
                "valid": False,
                "reason": "BUY targets must satisfy TP1 < TP2 < TP3."
            }

        risk = entry_reference - fields["STOP_LOSS"]
        reward = fields["TP1"] - entry_reference

    else:
        if fields["STOP_LOSS"] <= fields["ENTRY_HIGH"]:
            return {
                "valid": False,
                "reason": "SELL stop-loss must be above the entry zone."
            }

        if not (
            fields["TP1"] > fields["TP2"] > fields["TP3"]
        ):
            return {
                "valid": False,
                "reason": "SELL targets must satisfy TP1 > TP2 > TP3."
            }

        risk = fields["STOP_LOSS"] - entry_reference
        reward = entry_reference - fields["TP1"]

    if risk <= 0:
        return {
            "valid": False,
            "reason": "Trade-plan risk must be greater than zero."
        }

    if reward <= 0:
        return {
            "valid": False,
            "reason": "TP1 must provide positive reward."
        }

    risk_reward = reward / risk
    # Provider-level TP1 RR rejection removed.
    # Final consensus RR validation remains mandatory.


    fields["entry_reference"] = entry_reference
    fields["risk"] = risk
    fields["risk_reward"] = risk_reward
    fields["valid"] = True
    fields["reason"] = "Trade plan passed structural validation."

    return fields


def validate_trade_plan(plan_text, market_snapshot):
    """Apply deterministic safety validation to a provider trade plan."""
    parsed = parse_trade_plan(plan_text)

    if not parsed["valid"]:
        return parsed

    if not isinstance(market_snapshot, dict):
        return {
            "valid": False,
            "reason": "Market snapshot is unavailable."
        }

    current_price = market_snapshot.get("current_price")

    try:
        current_price = float(current_price)
    except (TypeError, ValueError):
        return {
            "valid": False,
            "reason": "Market snapshot has no valid current price."
        }

    if current_price <= 0:
        return {
            "valid": False,
            "reason": "Market snapshot current price must be greater than zero."
        }

    if market_snapshot.get("future_data_included") is True:
        return {
            "valid": False,
            "reason": "Market snapshot contains future data."
        }

    if market_snapshot.get("completed_candle_only") is not True:
        return {
            "valid": False,
            "reason": "Market snapshot is not explicitly completed-candle-only."
        }

    entry_distance = abs(parsed["entry_reference"] - current_price) / current_price
    stop_distance = abs(parsed["STOP_LOSS"] - current_price) / current_price

    if entry_distance > 0.10:
        return {
            "valid": False,
            "reason": (
                f"Entry zone is too far from current market price "
                f"({entry_distance * 100:.2f}%)."
            )
        }

    if stop_distance > 0.15:
        return {
            "valid": False,
            "reason": (
                f"Stop-loss is too far from current market price "
                f"({stop_distance * 100:.2f}%)."
            )
        }

    parsed["current_price"] = current_price
    parsed["entry_distance_pct"] = entry_distance * 100
    parsed["stop_distance_pct"] = stop_distance * 100
    parsed["valid"] = True
    parsed["reason"] = "Trade plan passed deterministic market-safety validation."

    return parsed


def compare_trade_plans(groq_plan_text, gemini_plan_text):
    """
    Compare independently generated paper-trade plans.

    Safety rules:
    - Both plans must pass deterministic structural validation.
    - Direction must match.
    - Entry zones must overlap.
    - Stop-loss levels must be reasonably close.
    - TP1 must be reasonably close.
    - TP2/TP3 may differ materially because providers can
      estimate different move magnitudes.
    - Final consensus levels must pass deterministic validation.
    - No live execution is permitted.
    """

    groq = parse_trade_plan(groq_plan_text)
    gemini = parse_trade_plan(gemini_plan_text)

    if not groq["valid"] or not gemini["valid"]:
        reasons = []

        if not groq["valid"]:
            reasons.append(f"Groq: {groq['reason']}")

        if not gemini["valid"]:
            reasons.append(f"Gemini: {gemini['reason']}")

        return {
            "status": "INVALID",
            "action": "PAPER_HOLD",
            "reason": " | ".join(reasons),
            "groq": groq,
            "gemini": gemini,
        }

    if groq["DIRECTION"] != gemini["DIRECTION"]:
        return {
            "status": "CONFLICT",
            "action": "PAPER_HOLD",
            "reason": "Groq and Gemini disagree on trade direction.",
            "groq": groq,
            "gemini": gemini,
        }

    direction = groq["DIRECTION"]

    # ------------------------------------------------------------
    # ENTRY CONSENSUS
    # ------------------------------------------------------------

    entry_low = max(
        groq["ENTRY_LOW"],
        gemini["ENTRY_LOW"],
    )

    entry_high = min(
        groq["ENTRY_HIGH"],
        gemini["ENTRY_HIGH"],
    )

    if entry_low > entry_high:
        return {
            "status": "ENTRY_CONFLICT",
            "action": "PAPER_HOLD",
            "reason": "Groq and Gemini entry zones do not overlap.",
            "groq": groq,
            "gemini": gemini,
        }

    reference_entry = (entry_low + entry_high) / 2.0

    # ------------------------------------------------------------
    # RISK / TARGET CONSENSUS TOLERANCES
    # ------------------------------------------------------------

    stop_tolerance = 0.05
    tp1_tolerance = 0.05

    stop_difference = (
        abs(groq["STOP_LOSS"] - gemini["STOP_LOSS"])
        / reference_entry
    )

    if stop_difference > stop_tolerance:
        return {
            "status": "STOP_CONFLICT",
            "action": "PAPER_HOLD",
            "reason": (
                "Groq and Gemini stop-loss levels differ by more "
                f"than {stop_tolerance * 100:.1f}%."
            ),
            "groq": groq,
            "gemini": gemini,
        }

    tp1_difference = (
        abs(groq["TP1"] - gemini["TP1"])
        / reference_entry
    )

    if tp1_difference > tp1_tolerance:
        return {
            "status": "TP1_CONFLICT",
            "action": "PAPER_HOLD",
            "reason": (
                "Groq and Gemini TP1 levels differ by more "
                f"than {tp1_tolerance * 100:.1f}%."
            ),
            "groq": groq,
            "gemini": gemini,
        }

    # ------------------------------------------------------------
    # DETERMINISTIC CONSENSUS LEVELS
    # ------------------------------------------------------------

    consensus_stop = (
        groq["STOP_LOSS"] +
        gemini["STOP_LOSS"]
    ) / 2.0

    consensus_tp1 = (
        groq["TP1"] +
        gemini["TP1"]
    ) / 2.0

    consensus_tp2 = (
        groq["TP2"] +
        gemini["TP2"]
    ) / 2.0

    consensus_tp3 = (
        groq["TP3"] +
        gemini["TP3"]
    ) / 2.0

    # ------------------------------------------------------------
    # STRUCTURAL CONSENSUS VALIDATION
    # ------------------------------------------------------------

    if direction == "BUY":

        if consensus_stop >= entry_low:
            return {
                "status": "INVALID_CONSENSUS",
                "action": "PAPER_HOLD",
                "reason": "Consensus BUY stop-loss is not below entry.",
                "groq": groq,
                "gemini": gemini,
            }

        if not (
            consensus_tp1 <
            consensus_tp2 <
            consensus_tp3
        ):
            return {
                "status": "INVALID_CONSENSUS",
                "action": "PAPER_HOLD",
                "reason": "Consensus BUY targets are not ordered correctly.",
                "groq": groq,
                "gemini": gemini,
            }

        risk = reference_entry - consensus_stop
        reward = consensus_tp1 - reference_entry

    else:

        if consensus_stop <= entry_high:
            return {
                "status": "INVALID_CONSENSUS",
                "action": "PAPER_HOLD",
                "reason": "Consensus SELL stop-loss is not above entry.",
                "groq": groq,
                "gemini": gemini,
            }

        if not (
            consensus_tp1 >
            consensus_tp2 >
            consensus_tp3
        ):
            return {
                "status": "INVALID_CONSENSUS",
                "action": "PAPER_HOLD",
                "reason": "Consensus SELL targets are not ordered correctly.",
                "groq": groq,
                "gemini": gemini,
            }

        risk = consensus_stop - reference_entry
        reward = reference_entry - consensus_tp1

    if risk <= 0:
        return {
            "status": "INVALID_CONSENSUS",
            "action": "PAPER_HOLD",
            "reason": "Consensus risk is not greater than zero.",
            "groq": groq,
            "gemini": gemini,
        }

    if reward <= 0:
        return {
            "status": "INVALID_CONSENSUS",
            "action": "PAPER_HOLD",
            "reason": "Consensus TP1 does not provide positive reward.",
            "groq": groq,
            "gemini": gemini,
        }

    risk_reward = reward / risk

    if risk_reward < 1.0:
        return {
            "status": "INVALID_CONSENSUS",
            "action": "PAPER_HOLD",
            "reason": (
                "Consensus TP1 risk/reward is below 1.0 "
                f"({risk_reward:.2f})."
            ),
            "groq": groq,
            "gemini": gemini,
        }

    return {
        "status": "AGREEMENT",
        "action": (
            "PAPER_BUY"
            if direction == "BUY"
            else "PAPER_SELL"
        ),
        "direction": direction,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_price": reference_entry,
        "stop_loss": consensus_stop,
        "tp1": consensus_tp1,
        "tp2": consensus_tp2,
        "tp3": consensus_tp3,
        "risk": risk,
        "risk_reward": risk_reward,
        "reason": (
            "Groq and Gemini agree on direction and overlapping "
            "entry zone. Stop and TP1 passed consensus tolerances. "
            "TP2/TP3 differences were accepted and consensus levels "
            "passed deterministic ordering and risk/reward validation."
        ),
        "groq": groq,
        "gemini": gemini,
        "live_execution": "BLOCKED",
    }



def call_gemini_analysis(system_prompt, user_prompt):
    """Call Gemini through the streaming REST API with safe retries."""

    gemini_key = os.getenv("GEMINI_API_KEY")

    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY is not loaded")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.6-flash:streamGenerateContent"
    )

    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}]
            }
        ]
    }

    max_attempts = 4
    retry_status_codes = {
        429,
        500,
        502,
        503,
        504,
    }

    last_error = None

    for attempt in range(1, max_attempts + 1):

        response = None

        print(
            f"🌐 GEMINI PROVIDER | "
            f"Attempt {attempt}/{max_attempts}"
        )

        try:
            response = requests.post(
                url,
                params={"alt": "sse"},
                headers={
                    "x-goog-api-key": gemini_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                stream=True,
                timeout=(15, 60),
            )

            if response.status_code >= 400:

                status_code = response.status_code

                if status_code in retry_status_codes:

                    raise RuntimeError(
                        f"RETRYABLE_HTTP_{status_code}"
                    )

                response.raise_for_status()

            chunks = []

            for line in response.iter_lines(
                decode_unicode=True
            ):
                if not line:
                    continue

                if not line.startswith("data:"):
                    continue

                data_line = line[5:].strip()

                if not data_line:
                    continue

                try:
                    data = requests.models.complexjson.loads(
                        data_line
                    )
                except Exception:
                    continue

                for candidate in data.get(
                    "candidates",
                    []
                ):
                    content = candidate.get(
                        "content",
                        {}
                    )

                    for part in content.get(
                        "parts",
                        []
                    ):
                        chunk_text = part.get("text")

                        if isinstance(
                            chunk_text,
                            str
                        ):
                            chunks.append(
                                chunk_text
                            )

            result = "".join(chunks).strip()

            if not result:

                raise RuntimeError(
                    "Gemini returned no usable assessment"
                )

            print(
                f"✅ GEMINI PROVIDER | "
                f"SUCCESS | Attempt {attempt}"
            )

            return result

        except requests.exceptions.Timeout as e:

            last_error = (
                f"TIMEOUT: {e}"
            )

        except requests.exceptions.ConnectionError as e:

            last_error = (
                f"CONNECTION_ERROR: {e}"
            )

        except requests.exceptions.HTTPError as e:

            last_error = (
                f"HTTP_ERROR: {e}"
            )

            print(
                "❌ GEMINI PROVIDER FAILURE | "
                f"{last_error}"
            )

            raise RuntimeError(
                f"GEMINI_PROVIDER_HTTP_ERROR: {e}"
            ) from e

        except RuntimeError as e:

            error_text = str(e)

            if (
                error_text.startswith(
                    "RETRYABLE_HTTP_"
                )
                or error_text
                == "Gemini returned no usable assessment"
            ):
                last_error = error_text
            else:
                raise

        except requests.exceptions.RequestException as e:

            last_error = (
                f"REQUEST_ERROR: {e}"
            )

        finally:

            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        if attempt < max_attempts:

            wait_seconds = 2 ** attempt

            print(
                "⚠️ GEMINI TRANSIENT FAILURE | "
                f"{last_error}"
            )

            print(
                f"🔄 Retrying in "
                f"{wait_seconds}s..."
            )

            time.sleep(wait_seconds)

    print(
        "❌ GEMINI PROVIDER FAILURE | "
        f"EXHAUSTED AFTER {max_attempts} ATTEMPTS"
    )

    raise RuntimeError(
        "GEMINI_PROVIDER_RETRY_EXHAUSTED: "
        f"{last_error}"
    )

def parse_multi_ai_assessment(ai_assessment):
    """Parse and strictly validate one AI assessment for multi-AI comparison."""
    valid, reason = validate_ai_assessment(ai_assessment)

    if not valid:
        return {
            "valid": False,
            "reason": reason,
        }

    fields = {}

    for field in ["ASSESSMENT", "CONFIDENCE", "OOS_EVIDENCE", "RISK"]:
        match = re.search(
            rf"(?m)^\s*{field}:\s*([^\n]+)\s*$",
            ai_assessment
        )
        fields[field] = match.group(1).strip().upper()

    outcome_match = re.search(
        r"(?m)^\s*SIMULATED_OUTCOME:\s*([^\n]+)\s*$",
        ai_assessment
    )

    if not outcome_match:
        return {
            "valid": False,
            "reason": "AI assessment missing SIMULATED_OUTCOME."
        }

    outcome = outcome_match.group(1).strip().upper()

    if outcome not in {"PROFIT", "LOSS", "UNCERTAIN"}:
        return {
            "valid": False,
            "reason": f"Invalid SIMULATED_OUTCOME: {outcome}."
        }

    fields["SIMULATED_OUTCOME"] = outcome

    direction_match = re.search(
        r"(?m)^\s*DIRECTION:\s*([^\n]+)\s*$",
        ai_assessment
    )

    if not direction_match:
        return {
            "valid": False,
            "reason": "AI assessment missing DIRECTION."
        }

    direction = direction_match.group(1).strip().upper()

    if direction not in {"BUY", "SELL"}:
        return {
            "valid": False,
            "reason": f"Invalid DIRECTION: {direction}."
        }

    fields["DIRECTION"] = direction
    fields["valid"] = True
    fields["reason"] = "AI assessment passed multi-AI validation."

    return fields


def compare_multi_ai_assessments(groq_assessment, gemini_assessment):
    """
    Compare Groq and Gemini using explicit BUY/SELL direction as the
    authoritative AI consensus field.

    Both providers must choose the same direction.
    Any directional disagreement fails closed to PAPER_HOLD.
    """

    groq = parse_multi_ai_assessment(groq_assessment)
    gemini = parse_multi_ai_assessment(gemini_assessment)

    # FAIL CLOSED — invalid provider output
    if not groq["valid"] or not gemini["valid"]:
        reasons = []

        if not groq["valid"]:
            reasons.append(f"Groq: {groq['reason']}")

        if not gemini["valid"]:
            reasons.append(f"Gemini: {gemini['reason']}")

        return {
            "status": "INVALID",
            "action": "PAPER_HOLD",
            "direction": None,
            "reason": " | ".join(reasons),
            "agreements": {},
            "groq": groq,
            "gemini": gemini,
        }

    # Advisory fields are recorded but do not veto directional consensus.
    compared_fields = [
        "ASSESSMENT",
        "CONFIDENCE",
        "OOS_EVIDENCE",
        "RISK",
        "SIMULATED_OUTCOME",
    ]

    agreements = {
        field: groq.get(field) == gemini.get(field)
        for field in compared_fields
    }

    # DIRECTION is authoritative for AI consensus.
    groq_direction = groq.get("DIRECTION")
    gemini_direction = gemini.get("DIRECTION")

    valid_directions = {"BUY", "SELL"}

    if (
        groq_direction not in valid_directions
        or gemini_direction not in valid_directions
    ):
        return {
            "status": "INVALID",
            "action": "PAPER_HOLD",
            "direction": None,
            "reason": "One or more providers returned an invalid trade direction.",
            "agreements": agreements,
            "groq": groq,
            "gemini": gemini,
        }

    # Both AI providers independently choose BUY.
    if groq_direction == "BUY" and gemini_direction == "BUY":
        return {
            "status": "AGREEMENT",
            "action": "PAPER_BUY",
            "direction": "BUY",
            "reason": "Groq and Gemini independently agree on BUY direction.",
            "agreements": agreements,
            "groq": groq,
            "gemini": gemini,
        }

    # Both AI providers independently choose SELL.
    if groq_direction == "SELL" and gemini_direction == "SELL":
        return {
            "status": "AGREEMENT",
            "action": "PAPER_SELL",
            "direction": "SELL",
            "reason": "Groq and Gemini independently agree on SELL direction.",
            "agreements": agreements,
            "groq": groq,
            "gemini": gemini,
        }

    # BUY versus SELL disagreement — fail closed.
    return {
        "status": "CONFLICT",
        "action": "PAPER_HOLD",
        "direction": None,
        "reason": (
            f"Directional disagreement: Groq={groq_direction}, "
            f"Gemini={gemini_direction}. Paper trade blocked."
        ),
        "agreements": agreements,
        "groq": groq,
        "gemini": gemini,
    }


# ============================================================
# STAGE 7.4.1 — CONSENSUS HISTORICAL STATISTICS
# ============================================================

def analyze_consensus_statistics():
    """Read historical multi-AI consensus statistics from the audit database."""

    import sqlite3

    statuses = [
        "AGREEMENT",
        "PARTIAL_AGREEMENT",
        "CONFLICT",
        "INVALID",
    ]

    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM ai_consensus_audit
        """)

        total_records = cursor.fetchone()[0]

        counts = {}

        for status in statuses:
            cursor.execute("""
                SELECT COUNT(*)
                FROM ai_consensus_audit
                WHERE consensus_status = ?
            """, (status,))

            counts[status] = cursor.fetchone()[0]

        conn.close()

        percentages = {}

        for status in statuses:
            if total_records > 0:
                percentages[status] = round(
                    (counts[status] / total_records) * 100,
                    2
                )
            else:
                percentages[status] = 0.0

        if total_records == 0:
            trend_status = "INSUFFICIENT_DATA"
        elif counts["CONFLICT"] > counts["AGREEMENT"]:
            trend_status = "HIGH_CONFLICT"
        elif counts["AGREEMENT"] >= counts["PARTIAL_AGREEMENT"]:
            trend_status = "STABLE"
        else:
            trend_status = "MIXED"

        return {
            "total_records": total_records,
            "counts": counts,
            "percentages": percentages,
            "trend_status": trend_status,
        }

    except sqlite3.Error as e:
        return {
            "total_records": 0,
            "counts": {
                status: 0
                for status in statuses
            },
            "percentages": {
                status: 0.0
                for status in statuses
            },
            "trend_status": "DATABASE_ERROR",
            "error": str(e),
        }




# ============================================================
# STAGE 7.6.2 — CONSENSUS OUTCOME EVALUATION
# ============================================================





# ============================================================
# STAGE 7.6.3 — PROVIDER PERFORMANCE ATTRIBUTION
# ============================================================

def extract_provider_direction(assessment):
    """Extract BUY, SELL, or UNKNOWN from a provider assessment."""

    if not assessment:
        return "UNKNOWN"

    text = assessment.upper()

    if "ASSESSMENT: BULLISH" in text:
        return "BUY"

    if "ASSESSMENT: BEARISH" in text:
        return "SELL"

    return "UNKNOWN"


def evaluate_provider_performance():
    """
    Attribute linked decision outcomes to Groq and Gemini.

    Provider direction is compared with the executed paper
    direction. Completed outcomes determine correctness.
    """

    try:

        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                c.id,
                c.symbol,
                c.groq_assessment,
                c.gemini_assessment,
                c.decision_id,
                d.final_action,
                d.outcome
            FROM ai_consensus_audit c
            INNER JOIN agent_decisions d
                ON c.decision_id = d.id
            WHERE c.decision_id IS NOT NULL
            ORDER BY c.id ASC
        """)

        rows = cursor.fetchall()

        conn.close()

        providers = {
            "GROQ": {
                "correct": 0,
                "incorrect": 0,
                "pending": 0,
                "unknown": 0,
                "total_completed": 0,
            },
            "GEMINI": {
                "correct": 0,
                "incorrect": 0,
                "pending": 0,
                "unknown": 0,
                "total_completed": 0,
            }
        }

        evaluations = []

        for row in rows:

            consensus_id = row[0]
            symbol = row[1]
            groq_assessment = row[2]
            gemini_assessment = row[3]
            decision_id = row[4]
            final_action = row[5]
            outcome = row[6]

            groq_direction = extract_provider_direction(
                groq_assessment
            )

            gemini_direction = extract_provider_direction(
                gemini_assessment
            )

            action_direction = "UNKNOWN"

            if final_action == "PAPER_BUY":
                action_direction = "BUY"

            elif final_action == "PAPER_SELL":
                action_direction = "SELL"

            provider_data = {
                "GROQ": groq_direction,
                "GEMINI": gemini_direction,
            }

            row_evaluation = {
                "consensus_id": consensus_id,
                "symbol": symbol,
                "decision_id": decision_id,
                "outcome": outcome,
                "providers": {}
            }

            for provider, direction in provider_data.items():

                if direction == "UNKNOWN":

                    provider_result = "UNKNOWN"

                    providers[provider]["unknown"] += 1

                elif outcome not in (
                    "SUCCESS",
                    "FAILURE"
                ):

                    provider_result = "PENDING"

                    providers[provider]["pending"] += 1

                elif action_direction == "UNKNOWN":

                    provider_result = "UNKNOWN"

                    providers[provider]["unknown"] += 1

                else:

                    aligned = (
                        direction == action_direction
                    )

                    if (
                        aligned
                        and outcome == "SUCCESS"
                    ):

                        provider_result = "CORRECT"

                        providers[provider][
                            "correct"
                        ] += 1

                        providers[provider][
                            "total_completed"
                        ] += 1

                    elif (
                        not aligned
                        and outcome == "FAILURE"
                    ):

                        provider_result = "CORRECT"

                        providers[provider][
                            "correct"
                        ] += 1

                        providers[provider][
                            "total_completed"
                        ] += 1

                    else:

                        provider_result = "INCORRECT"

                        providers[provider][
                            "incorrect"
                        ] += 1

                        providers[provider][
                            "total_completed"
                        ] += 1

                row_evaluation[
                    "providers"
                ][provider] = {
                    "direction": direction,
                    "result": provider_result,
                }

            evaluations.append(
                row_evaluation
            )

        for provider in providers:

            completed = providers[provider][
                "total_completed"
            ]

            correct = providers[provider][
                "correct"
            ]

            if completed > 0:

                accuracy = round(
                    (correct / completed) * 100,
                    2
                )

            else:

                accuracy = None

            providers[provider][
                "accuracy"
            ] = accuracy

        return {
            "providers": providers,
            "evaluations": evaluations,
            "total_linked_records": len(rows),
        }

    except sqlite3.Error as e:

        return {
            "database_error": str(e)
        }





# ============================================================
# STAGE 7.6.7.1 — PAPER TRADE PLAN DATABASE
# ============================================================

def ensure_column(cursor, table_name, column_name, column_type):
    """Add a column only if it does not already exist."""

    cursor.execute(
        f"PRAGMA table_info({table_name})"
    )

    existing_columns = {
        row[1]
        for row in cursor.fetchall()
    }

    if column_name not in existing_columns:
        cursor.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {column_type}
            """
        )


def ensure_paper_trade_plans_table():
    """
    Create the persistent paper trade plan table.

    This table stores simulated trade predictions using real
    market prices. No real orders or funds are involved.
    """

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_trade_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,

            symbol TEXT NOT NULL,

            direction TEXT NOT NULL,

            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,

            tp1 REAL,
            tp2 REAL,
            tp3 REAL,

            groq_plan TEXT,
            gemini_plan TEXT,

            consensus_status TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',

            outcome TEXT,
            exit_price REAL,
            resolved_at TEXT,

            decision_id INTEGER,
            consensus_id INTEGER,

            FOREIGN KEY(decision_id)
                REFERENCES agent_decisions(id),

            FOREIGN KEY(consensus_id)
                REFERENCES ai_consensus_audit(id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_paper_trade_plans_status_expiry
        ON paper_trade_plans(status, expires_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_paper_trade_plans_symbol
        ON paper_trade_plans(symbol)
    """)

    # ============================================================
    # STAGE 7.6.7.2 — PAPER TRADE MONITORING MIGRATION
    # ============================================================

    ensure_column(
        cursor,
        "paper_trade_plans",
        "tp1_hit_at",
        "TEXT"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "tp2_hit_at",
        "TEXT"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "tp3_hit_at",
        "TEXT"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "last_checked_at",
        "TEXT"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "last_price",
        "REAL"
    )

    # ============================================================
    # STAGE 7.6.8.7 — 24H PREDICTION EVALUATION MIGRATION
    # ============================================================

    ensure_column(
        cursor,
        "paper_trade_plans",
        "price_change_pct",
        "REAL"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "feedback_score",
        "REAL"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "evaluated_at",
        "TEXT"
    )

    # ============================================================
    # STAGE 7.6.9.0 — SEPARATE TRADE AND PREDICTION OUTCOMES
    # ============================================================

    ensure_column(
        cursor,
        "paper_trade_plans",
        "trade_outcome",
        "TEXT"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "prediction_outcome",
        "TEXT"
    )

    ensure_column(
        cursor,
        "paper_trade_plans",
        "prediction_evaluated_at",
        "TEXT"
    )

    conn.commit()
    conn.close()



# ============================================================
# STAGE 7.6.10 — INDEPENDENT DIRECTIONAL PREDICTION PERSISTENCE
# ============================================================

def persist_directional_prediction(
    symbol,
    direction,
    prediction_price,
    decision_id=None,
    consensus_id=None,
):
    """
    Store an independent 24-hour directional paper prediction.

    This is deliberately separate from detailed trade-plan
    validation. A prediction does not need TP/SL levels or a
    minimum trade-plan risk/reward ratio.

    PAPER/BACKTEST ONLY.
    LIVE EXECUTION IS ALWAYS BLOCKED.
    """

    symbol = str(symbol).upper().strip()
    direction = str(direction).upper().strip()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    if direction not in ("BUY", "SELL"):
        raise ValueError(
            f"Invalid directional prediction: {direction}"
        )

    try:
        prediction_price = float(prediction_price)
    except (TypeError, ValueError):
        raise ValueError(
            f"Invalid prediction price: {prediction_price}"
        )

    if prediction_price <= 0:
        raise ValueError(
            "Prediction price must be greater than zero."
        )

    ensure_paper_trade_plans_table()

    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=24)

    conn = sqlite3.connect("sentinel.db")

    try:
        cursor = conn.cursor()

        # Reuse an existing active prediction instead of creating
        # duplicates when the same command is accidentally repeated.
        cursor.execute("""
            SELECT
                id,
                expires_at,
                entry_price
            FROM paper_trade_plans
            WHERE
                consensus_status = 'DIRECTIONAL_PREDICTION'
                AND symbol = ?
                AND direction = ?
                AND prediction_outcome IS NULL
                AND expires_at > ?
            ORDER BY id DESC
            LIMIT 1
        """, (
            symbol,
            direction,
            created_at.isoformat(),
        ))

        existing = cursor.fetchone()

        if existing:
            return {
                "id": existing[0],
                "symbol": symbol,
                "direction": direction,
                "prediction_price": float(existing[2]),
                "status": "PREDICTION_ACTIVE",
                "created_at": None,
                "expires_at": existing[1],
                "duplicate": True,
                "live_execution": "BLOCKED",
            }

        # Existing schema has NOT NULL trade-plan fields.
        # 0.0 is used to mean "not applicable to prediction".
        cursor.execute("""
            INSERT INTO paper_trade_plans (
                created_at,
                expires_at,
                symbol,
                direction,
                entry_price,
                stop_loss,
                tp1,
                tp2,
                tp3,
                groq_plan,
                gemini_plan,
                consensus_status,
                status,
                decision_id,
                consensus_id
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            created_at.isoformat(),
            expires_at.isoformat(),
            symbol,
            direction,
            prediction_price,
            0.0,
            0.0,
            0.0,
            0.0,
            None,
            None,
            "DIRECTIONAL_PREDICTION",
            "PREDICTION_ACTIVE",
            decision_id,
            consensus_id,
        ))

        prediction_id = cursor.lastrowid

        conn.commit()

        return {
            "id": prediction_id,
            "symbol": symbol,
            "direction": direction,
            "prediction_price": prediction_price,
            "status": "PREDICTION_ACTIVE",
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "duplicate": False,
            "live_execution": "BLOCKED",
        }

    finally:
        conn.close()


# ============================================================
# STAGE 7.6.7.6 — CONSENSUS PAPER-TRADE PERSISTENCE
# ============================================================

def persist_consensus_paper_trade(
    symbol,
    consensus,
    groq_plan_text,
    gemini_plan_text,
    decision_id=None,
    consensus_id=None,
):
    """
    Persist one approved multi-provider consensus as a 24-hour
    paper-only trade plan.

    This function never places orders or interacts with exchange
    execution endpoints.
    """

    if not isinstance(consensus, dict):
        raise ValueError("Consensus result must be a dictionary.")

    if consensus.get("status") != "AGREEMENT":
        raise ValueError(
            "Only AGREEMENT consensus results may create paper trades."
        )

    required = [
        "direction",
        "entry_price",
        "stop_loss",
        "tp1",
        "tp2",
        "tp3",
    ]

    missing = [
        field
        for field in required
        if consensus.get(field) is None
    ]

    if missing:
        raise ValueError(
            "Consensus is missing required fields: "
            + ", ".join(missing)
        )

    symbol = symbol.upper()

    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=24)

    ensure_paper_trade_plans_table()

    conn = sqlite3.connect("sentinel.db")

    try:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO paper_trade_plans (
                created_at,
                expires_at,
                symbol,
                direction,
                entry_price,
                stop_loss,
                tp1,
                tp2,
                tp3,
                groq_plan,
                gemini_plan,
                consensus_status,
                status,
                decision_id,
                consensus_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            created_at.isoformat(),
            expires_at.isoformat(),
            symbol,
            consensus["direction"],
            float(consensus["entry_price"]),
            float(consensus["stop_loss"]),
            float(consensus["tp1"]),
            float(consensus["tp2"]),
            float(consensus["tp3"]),
            groq_plan_text,
            gemini_plan_text,
            consensus["status"],
            "ACTIVE",
            decision_id,
            consensus_id,
        ))

        trade_id = cursor.lastrowid

        conn.commit()

        return {
            "id": trade_id,
            "symbol": symbol,
            "status": "ACTIVE",
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "live_execution": "BLOCKED",
        }

    finally:
        conn.close()




# ============================================================
# STAGE 7.6.9.1 — INDEPENDENT 24H PREDICTION EVALUATOR
# ============================================================

def evaluate_expired_paper_predictions():
    """
    Evaluate paper predictions whose 24-hour horizon has passed.

    This is independent from paper-trade resolution.

    A trade may hit STOP_LOSS or TP3 before 24 hours, but the
    directional prediction is still evaluated separately at the
    prediction horizon.

    No live orders or account actions are performed.
    """

    ensure_paper_trade_plans_table()

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    results = []

    try:
        now = datetime.now(timezone.utc)

        cursor.execute("""
            SELECT
                id,
                symbol,
                direction,
                entry_price,
                expires_at,
                prediction_outcome
            FROM paper_trade_plans
            WHERE
                consensus_status = 'DIRECTIONAL_PREDICTION'
                AND prediction_outcome IS NULL
                AND expires_at <= ?
            ORDER BY id ASC
        """, (
            now.isoformat(),
        ))

        predictions = cursor.fetchall()

        for (
            prediction_id,
            symbol,
            direction,
            entry_price,
            expires_at,
            prediction_outcome
        ) in predictions:

            try:
                evaluation_price = (
                    get_paper_monitor_price(symbol)
                )

                outcome, feedback_score, price_change_pct = (
                    evaluate_decision_outcome(
                        direction,
                        entry_price,
                        evaluation_price
                    )
                )

                cursor.execute("""
                    UPDATE paper_trade_plans
                    SET
                        last_price = ?,
                        price_change_pct = ?,
                        feedback_score = ?,
                        prediction_outcome = ?,
                        prediction_evaluated_at = ?,
                        evaluated_at = ?,
                        status = 'PREDICTION_EVALUATED'
                    WHERE
                        id = ?
                        AND consensus_status = 'DIRECTIONAL_PREDICTION'
                """, (
                    evaluation_price,
                    price_change_pct,
                    feedback_score,
                    outcome,
                    now.isoformat(),
                    now.isoformat(),
                    prediction_id
                ))

                results.append({
                    "id": prediction_id,
                    "symbol": symbol,
                    "event": "PREDICTION_EVALUATED",
                    "prediction_outcome": outcome,
                    "price_change_pct": price_change_pct,
                    "feedback_score": feedback_score,
                    "last_price": evaluation_price
                })

            except Exception as e:

                results.append({
                    "id": prediction_id,
                    "symbol": symbol,
                    "event": "PREDICTION_EVALUATION_ERROR",
                    "error": str(e)
                })

        conn.commit()

        return results

    finally:
        conn.close()


# ============================================================
# STAGE 7.6.7.3 — AUTOMATIC PAPER TRADE MONITOR
# ============================================================


def get_paper_monitor_price(
    symbol,
    retries=3,
    retry_delay=2
):
    """
    Fetch a market price for paper-trade monitoring.

    Retries temporary public API connection failures.
    This function never performs trading or account actions.
    """

    import time

    last_error = None

    for attempt in range(1, retries + 1):

        try:
            return get_current_price(symbol)

        except Exception as e:

            last_error = e

            if attempt < retries:
                time.sleep(retry_delay)

    raise RuntimeError(
        f"Price retrieval failed after {retries} attempts: "
        f"{last_error}"
    )


def monitor_active_paper_trades():
    """
    Monitor all ACTIVE paper trades using live market prices.

    This function is simulation-only.
    It never places exchange orders or accesses account balances.
    """

    ensure_paper_trade_plans_table()

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    results = []

    try:

        cursor.execute("""
            SELECT
                id,
                created_at,
                expires_at,
                symbol,
                direction,
                entry_price,
                stop_loss,
                tp1,
                tp2,
                tp3,
                status,
                tp1_hit_at,
                tp2_hit_at,
                tp3_hit_at
            FROM paper_trade_plans
            WHERE status = 'ACTIVE'
            ORDER BY id ASC
        """)

        trades = cursor.fetchall()

        now = datetime.now(timezone.utc)

        for trade in trades:

            (
                trade_id,
                created_at,
                expires_at,
                symbol,
                direction,
                entry_price,
                stop_loss,
                tp1,
                tp2,
                tp3,
                trade_status,
                tp1_hit_at,
                tp2_hit_at,
                tp3_hit_at
            ) = trade

            try:

                current_price = get_paper_monitor_price(symbol)

                cursor.execute("""
                    UPDATE paper_trade_plans
                    SET
                        last_price = ?,
                        last_checked_at = ?
                    WHERE id = ?
                """, (
                    current_price,
                    now.isoformat(),
                    trade_id
                ))

                # --------------------------------------------
                # EXPIRE OLD PAPER TRADES
                # --------------------------------------------

                expiry_time = datetime.fromisoformat(
                    expires_at.replace("Z", "+00:00")
                )

                if now >= expiry_time:

                    (
                        outcome,
                        feedback_score,
                        price_change_pct
                    ) = evaluate_decision_outcome(
                        direction,
                        entry_price,
                        current_price
                    )

                    cursor.execute("""
                        UPDATE paper_trade_plans
                        SET
                            status = 'RESOLVED',
                            outcome = ?,
                            trade_outcome = ?,
                            exit_price = ?,
                            resolved_at = ?,
                            price_change_pct = ?,
                            feedback_score = ?,
                            evaluated_at = ?
                        WHERE id = ?
                    """, (
                        outcome,
                        outcome,
                        current_price,
                        now.isoformat(),
                        price_change_pct,
                        feedback_score,
                        now.isoformat(),
                        trade_id
                    ))

                    results.append({
                        "id": trade_id,
                        "symbol": symbol,
                        "event": outcome,
                        "price": current_price,
                        "price_change_pct": price_change_pct,
                        "feedback_score": feedback_score
                    })

                    continue


                # --------------------------------------------
                # STOP LOSS DETECTION
                # --------------------------------------------

                stop_hit = False

                if direction == "BUY":
                    stop_hit = current_price <= stop_loss

                elif direction == "SELL":
                    stop_hit = current_price >= stop_loss


                if stop_hit:

                    cursor.execute("""
                        UPDATE paper_trade_plans
                        SET
                            status = 'RESOLVED',
                            outcome = 'STOP_LOSS',
                            trade_outcome = 'STOP_LOSS',
                            exit_price = ?,
                            resolved_at = ?
                        WHERE id = ?
                    """, (
                        current_price,
                        now.isoformat(),
                        trade_id
                    ))

                    results.append({
                        "id": trade_id,
                        "symbol": symbol,
                        "event": "STOP_LOSS",
                        "price": current_price
                    })

                    continue


                # --------------------------------------------
                # TAKE PROFIT DETECTION
                # --------------------------------------------

                if direction == "BUY":

                    tp1_hit = current_price >= tp1
                    tp2_hit = current_price >= tp2
                    tp3_hit = current_price >= tp3

                else:

                    tp1_hit = current_price <= tp1
                    tp2_hit = current_price <= tp2
                    tp3_hit = current_price <= tp3


                if tp1_hit and tp1_hit_at is None:

                    cursor.execute("""
                        UPDATE paper_trade_plans
                        SET tp1_hit_at = ?
                        WHERE id = ?
                    """, (
                        now.isoformat(),
                        trade_id
                    ))

                    results.append({
                        "id": trade_id,
                        "symbol": symbol,
                        "event": "TP1_HIT",
                        "price": current_price
                    })


                if tp2_hit and tp2_hit_at is None:

                    cursor.execute("""
                        UPDATE paper_trade_plans
                        SET tp2_hit_at = ?
                        WHERE id = ?
                    """, (
                        now.isoformat(),
                        trade_id
                    ))

                    results.append({
                        "id": trade_id,
                        "symbol": symbol,
                        "event": "TP2_HIT",
                        "price": current_price
                    })


                if tp3_hit and tp3_hit_at is None:

                    cursor.execute("""
                        UPDATE paper_trade_plans
                        SET
                            tp3_hit_at = ?,
                            status = 'RESOLVED',
                            outcome = 'TP3',
                            trade_outcome = 'TP3',
                            exit_price = ?,
                            resolved_at = ?
                        WHERE id = ?
                    """, (
                        now.isoformat(),
                        current_price,
                        now.isoformat(),
                        trade_id
                    ))

                    results.append({
                        "id": trade_id,
                        "symbol": symbol,
                        "event": "TP3_HIT",
                        "price": current_price
                    })


            except Exception as e:

                results.append({
                    "id": trade_id,
                    "symbol": symbol,
                    "event": "ERROR",
                    "error": str(e)
                })


        conn.commit()

        # ============================================================
        # STAGE 7.6.9.2 — AUTOMATIC 24H PREDICTION EVALUATION
        # ============================================================

        try:
            prediction_results = (
                evaluate_expired_paper_predictions()
            )

            for prediction_result in prediction_results:
                results.append(prediction_result)

        except Exception as prediction_error:

            results.append({
                "event": "PREDICTION_EVALUATION_ERROR",
                "error": str(prediction_error)
            })

        # ============================================================
        # STAGE 7.6.8.1 — AUTOMATIC PAPER-TRADE FEEDBACK HOOK
        # ============================================================
        try:
            learning_results = run_paper_trade_learning_feedback()

            for learning_result in learning_results:
                if learning_result.get("status") == "RECORDED":
                    results.append({
                        "id": learning_result.get("paper_trade_id"),
                        "symbol": learning_result.get("symbol"),
                        "event": "LEARNING_FEEDBACK_RECORDED",
                        "outcome": learning_result.get("outcome"),
                        "feedback_label": learning_result.get("feedback_label")
                    })

        except Exception as learning_error:
            results.append({
                "event": "LEARNING_FEEDBACK_ERROR",
                "error": str(learning_error)
            })

        return results

    finally:
        conn.close()


# ============================================================
# STAGE 7.6.8 — PAPER TRADE OUTCOME ANALYTICS
# ============================================================


# ============================================================
# STAGE 7.6.8.1 — PAPER-TRADE FEEDBACK ENGINE
# ============================================================

def _find_paper_database_path():
    """Locate the SQLite database containing paper_trade_plans."""
    import os
    import sqlite3
    from pathlib import Path

    env_candidates = [
        os.getenv("HEX_SENTINEL_DB"),
        os.getenv("SENTINEL_DB"),
        os.getenv("DATABASE_PATH"),
        os.getenv("DB_PATH"),
    ]

    for candidate in env_candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate).expanduser()
        if candidate_path.exists():
            return str(candidate_path)

    base_dir = Path(__file__).resolve().parent
    candidates = list(base_dir.glob("*.db")) + list(base_dir.glob("*.sqlite")) + list(base_dir.glob("*.sqlite3"))

    for candidate in candidates:
        try:
            conn = sqlite3.connect(str(candidate))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='paper_trade_plans' "
                "LIMIT 1"
            )
            found = cursor.fetchone() is not None
            conn.close()
            if found:
                return str(candidate)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    raise FileNotFoundError(
        "Could not locate the Hex Sentinel SQLite database containing "
        "'paper_trade_plans'."
    )


def ensure_paper_trade_learning_feedback_table():
    """Create the persistent paper-trade learning feedback table."""
    import sqlite3

    db_path = _find_paper_database_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trade_learning_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_trade_id INTEGER NOT NULL UNIQUE,
            decision_id INTEGER,
            consensus_id INTEGER,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            outcome TEXT NOT NULL,
            feedback_label TEXT NOT NULL,
            decision_score REAL NOT NULL,
            consensus_score REAL NOT NULL,
            groq_direction TEXT,
            gemini_direction TEXT,
            groq_score REAL,
            gemini_score REAL,
            learning_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(paper_trade_id) REFERENCES paper_trade_plans(id),
            FOREIGN KEY(decision_id) REFERENCES agent_decisions(id),
            FOREIGN KEY(consensus_id) REFERENCES ai_consensus_audit(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_learning_feedback_symbol
        ON paper_trade_learning_feedback(symbol)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_learning_feedback_outcome
        ON paper_trade_learning_feedback(outcome)
        """
    )

    conn.commit()
    conn.close()


def _paper_trade_provider_direction(plan_text):
    """Extract a provider direction without inventing one."""
    if not plan_text:
        return None

    try:
        parsed = parse_trade_plan(plan_text)
        if isinstance(parsed, dict) and parsed.get("valid"):
            direction = parsed.get("direction")
            if direction in {"BUY", "SELL"}:
                return direction
    except Exception:
        pass

    return None


def _feedback_score(predicted_direction, actual_outcome):
    """
    Score direction against the terminal 24H paper-trade outcome.

    TP3       = validated direction (+1)
    STOP_LOSS = invalidated direction (-1)
    EXPIRED   = inconclusive (0)

    This is a learning score, NOT a PnL forecast.
    """
    if actual_outcome == "TP3":
        return 1.0
    if actual_outcome == "STOP_LOSS":
        return -1.0
    if actual_outcome == "EXPIRED":
        return 0.0
    return 0.0


def record_paper_trade_feedback(paper_trade_id):
    """
    Convert one resolved 24H paper trade into persistent feedback.

    Existing feedback is never duplicated.
    """
    import sqlite3
    from datetime import datetime, timezone

    ensure_paper_trade_learning_feedback_table()

    db_path = _find_paper_database_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            symbol,
            direction,
            outcome,
            status,
            groq_plan,
            gemini_plan,
            decision_id,
            consensus_id
        FROM paper_trade_plans
        WHERE id = ?
        """,
        (paper_trade_id,),
    )
    trade = cursor.fetchone()

    if not trade:
        conn.close()
        return {
            "status": "SKIPPED",
            "reason": "PAPER_TRADE_NOT_FOUND",
            "paper_trade_id": paper_trade_id,
        }

    (
        trade_id,
        symbol,
        direction,
        outcome,
        status,
        groq_plan,
        gemini_plan,
        decision_id,
        consensus_id,
    ) = trade

    if status != "RESOLVED":
        conn.close()
        return {
            "status": "SKIPPED",
            "reason": "PAPER_TRADE_NOT_RESOLVED",
            "paper_trade_id": paper_trade_id,
        }

    if outcome not in {"TP3", "STOP_LOSS", "EXPIRED"}:
        conn.close()
        return {
            "status": "SKIPPED",
            "reason": "UNSUPPORTED_TERMINAL_OUTCOME",
            "outcome": outcome,
            "paper_trade_id": paper_trade_id,
        }

    cursor.execute(
        """
        SELECT id
        FROM paper_trade_learning_feedback
        WHERE paper_trade_id = ?
        """,
        (paper_trade_id,),
    )
    if cursor.fetchone():
        conn.close()
        return {
            "status": "ALREADY_RECORDED",
            "paper_trade_id": paper_trade_id,
        }

    groq_direction = _paper_trade_provider_direction(groq_plan)
    gemini_direction = _paper_trade_provider_direction(gemini_plan)

    decision_score = _feedback_score(direction, outcome)

    # Provider-specific feedback:
    # If a provider's direction is known, compare it to the same terminal
    # outcome. If it cannot be parsed, leave it neutral rather than guessing.
    groq_score = (
        _feedback_score(groq_direction, outcome)
        if groq_direction in {"BUY", "SELL"}
        else 0.0
    )

    gemini_score = (
        _feedback_score(gemini_direction, outcome)
        if gemini_direction in {"BUY", "SELL"}
        else 0.0
    )

    if outcome == "TP3":
        feedback_label = "VALIDATED"
    elif outcome == "STOP_LOSS":
        feedback_label = "INVALIDATED"
    else:
        feedback_label = "INCONCLUSIVE"

    learning_status = "RECORDED"

    created_at = datetime.now(timezone.utc).isoformat()

    cursor.execute(
        """
        INSERT INTO paper_trade_learning_feedback (
            paper_trade_id,
            decision_id,
            consensus_id,
            symbol,
            direction,
            outcome,
            feedback_label,
            decision_score,
            consensus_score,
            groq_direction,
            gemini_direction,
            groq_score,
            gemini_score,
            learning_status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade_id,
            decision_id,
            consensus_id,
            symbol,
            direction,
            outcome,
            feedback_label,
            decision_score,
            decision_score,
            groq_direction,
            gemini_direction,
            groq_score,
            gemini_score,
            learning_status,
            created_at,
        ),
    )

    # Update the corresponding decision with terminal paper-trade feedback.
    if decision_id is not None:
        cursor.execute(
            """
            UPDATE agent_decisions
            SET
                outcome = ?,
                feedback_score = ?,
                evaluated_at = ?
            WHERE id = ?
            """,
            (
                outcome,
                decision_score,
                created_at,
                decision_id,
            ),
        )

    conn.commit()
    conn.close()

    return {
        "status": "RECORDED",
        "paper_trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "outcome": outcome,
        "feedback_label": feedback_label,
        "decision_score": decision_score,
        "groq_direction": groq_direction,
        "groq_score": groq_score,
        "gemini_direction": gemini_direction,
        "gemini_score": gemini_score,
        "live_execution": "BLOCKED",
    }


def run_paper_trade_learning_feedback():
    """
    Backfill all resolved paper trades that do not yet have feedback.
    Safe to run repeatedly because feedback is unique per paper trade.
    """
    import sqlite3

    ensure_paper_trade_learning_feedback_table()

    db_path = _find_paper_database_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM paper_trade_plans
        WHERE status = 'RESOLVED'
        ORDER BY id ASC
        """
    )
    paper_trade_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    results = []
    for paper_trade_id in paper_trade_ids:
        try:
            results.append(
                record_paper_trade_feedback(paper_trade_id)
            )
        except Exception as exc:
            results.append(
                {
                    "status": "ERROR",
                    "paper_trade_id": paper_trade_id,
                    "error": str(exc),
                }
            )

    return results


def calculate_paper_trade_learning_summary():
    """
    Aggregate resolved paper-trade feedback.

    Learning remains informational/safety-supporting only.
    It does not modify strategy approval or live execution.
    """
    import sqlite3

    ensure_paper_trade_learning_feedback_table()

    db_path = _find_paper_database_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*),
            SUM(CASE WHEN outcome = 'TP3' THEN 1 ELSE 0 END),
            SUM(CASE WHEN outcome = 'STOP_LOSS' THEN 1 ELSE 0 END),
            SUM(CASE WHEN outcome = 'EXPIRED' THEN 1 ELSE 0 END)
        FROM paper_trade_learning_feedback
        """
    )

    total, validated, invalidated, inconclusive = cursor.fetchone()

    total = total or 0
    validated = validated or 0
    invalidated = invalidated or 0
    inconclusive = inconclusive or 0

    decisive = validated + invalidated

    validation_rate_pct = (
        (validated / decisive) * 100.0
        if decisive
        else None
    )

    learning_minimum_sample = 10
    learning_ready = total >= learning_minimum_sample

    if not learning_ready:
        learning_state = "WARMUP"
    elif validation_rate_pct is None:
        learning_state = "INSUFFICIENT_DECISIVE_OUTCOMES"
    elif validation_rate_pct >= 60.0:
        learning_state = "RETAIN_EVIDENCE"
    elif validation_rate_pct >= 50.0:
        learning_state = "MIXED_EVIDENCE"
    else:
        learning_state = "CAUTION"

    cursor.execute(
        """
        SELECT
            provider,
            COUNT(*),
            SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END),
            SUM(CASE WHEN score < 0 THEN 1 ELSE 0 END),
            AVG(score)
        FROM (
            SELECT 'GROQ' AS provider, groq_score AS score
            FROM paper_trade_learning_feedback
            WHERE groq_score IS NOT NULL

            UNION ALL

            SELECT 'GEMINI' AS provider, gemini_score AS score
            FROM paper_trade_learning_feedback
            WHERE gemini_score IS NOT NULL
        )
        GROUP BY provider
        ORDER BY provider
        """
    )

    provider_rows = cursor.fetchall()

    provider_summary = {}

    for provider, count, positive, negative, avg_score in provider_rows:
        provider_summary[provider] = {
            "samples": count,
            "validated": positive,
            "invalidated": negative,
            "average_feedback_score": avg_score,
        }

    cursor.execute(
        """
        SELECT
            symbol,
            direction,
            COUNT(*),
            SUM(CASE WHEN outcome = 'TP3' THEN 1 ELSE 0 END),
            SUM(CASE WHEN outcome = 'STOP_LOSS' THEN 1 ELSE 0 END),
            SUM(CASE WHEN outcome = 'EXPIRED' THEN 1 ELSE 0 END)
        FROM paper_trade_learning_feedback
        GROUP BY symbol, direction
        ORDER BY symbol, direction
        """
    )

    symbol_direction_summary = {}

    for symbol, direction, samples, tp3, stop_loss, expired in cursor.fetchall():
        decisive_count = tp3 + stop_loss

        symbol_direction_summary[
            f"{symbol}:{direction}"
        ] = {
            "samples": samples,
            "tp3": tp3,
            "stop_loss": stop_loss,
            "expired": expired,
            "validation_rate_pct": (
                (tp3 / decisive_count) * 100.0
                if decisive_count
                else None
            ),
        }

    conn.close()

    return {
        "analytics_scope": "PAPER_TRADES_ONLY",
        "learning_scope": "RESOLVED_24H_PAPER_TRADES",
        "total_feedback_records": total,
        "validated": validated,
        "invalidated": invalidated,
        "inconclusive": inconclusive,
        "validation_rate_pct": validation_rate_pct,
        "learning_minimum_sample": learning_minimum_sample,
        "learning_ready": learning_ready,
        "learning_state": learning_state,
        "provider_summary": provider_summary,
        "symbol_direction_summary": symbol_direction_summary,
        "live_execution": "BLOCKED",
    }


def print_paper_trade_learning_summary():
    """Human-readable learning/feedback report."""
    summary = calculate_paper_trade_learning_summary()

    print("\n" + "=" * 60)
    print("🧠 STAGE 7.6.8.1 — PAPER-TRADE LEARNING FEEDBACK")
    print("=" * 60)
    print(f"Feedback records : {summary['total_feedback_records']}")
    print(f"Validated        : {summary['validated']}")
    print(f"Invalidated      : {summary['invalidated']}")
    print(f"Inconclusive     : {summary['inconclusive']}")
    print(f"Learning state   : {summary['learning_state']}")
    print(f"Learning ready   : {summary['learning_ready']}")

    if summary["validation_rate_pct"] is not None:
        print(
            f"Validation rate  : "
            f"{summary['validation_rate_pct']:.2f}%"
        )

    for provider, data in summary["provider_summary"].items():
        print(
            f"{provider:<8} "
            f"samples={data['samples']} "
            f"validated={data['validated']} "
            f"invalidated={data['invalidated']} "
            f"avg_score={data['average_feedback_score']:.3f}"
        )

    print("Learning may inform future analysis only.")
    print("Safety gates remain authoritative.")
    print("🔒 LIVE EXECUTION REMAINS BLOCKED")
    print("=" * 60)

def calculate_paper_trade_analytics():
    """
    Calculate performance analytics for resolved paper trades.

    This function analyzes simulation outcomes only.
    It never performs live trading or exchange execution.
    """

    ensure_paper_trade_plans_table()

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                id,
                symbol,
                direction,
                entry_price,
                exit_price,
                outcome
            FROM paper_trade_plans
            WHERE status = 'RESOLVED'
              AND exit_price IS NOT NULL
            ORDER BY id ASC
        """)

        rows = cursor.fetchall()

        total = len(rows)

        outcomes = {
            "TP3": 0,
            "STOP_LOSS": 0,
            "EXPIRED": 0,
        }

        by_symbol = {}

        directional_successes = 0
        directional_failures = 0

        price_changes = []

        for (
            trade_id,
            symbol,
            direction,
            entry_price,
            exit_price,
            outcome
        ) in rows:

            if outcome in outcomes:
                outcomes[outcome] += 1

            if entry_price and entry_price > 0:

                price_change_pct = (
                    (exit_price - entry_price)
                    / entry_price
                    * 100
                )

                price_changes.append(
                    price_change_pct
                )

                if direction == "BUY":

                    directional_success = (
                        exit_price > entry_price
                    )

                elif direction == "SELL":

                    directional_success = (
                        exit_price < entry_price
                    )

                else:

                    directional_success = False


                if directional_success:
                    directional_successes += 1
                else:
                    directional_failures += 1


                if symbol not in by_symbol:

                    by_symbol[symbol] = {
                        "total": 0,
                        "successes": 0,
                        "failures": 0,
                        "tp3": 0,
                        "stop_loss": 0,
                        "expired": 0,
                    }


                symbol_data = by_symbol[symbol]

                symbol_data["total"] += 1

                if directional_success:
                    symbol_data["successes"] += 1
                else:
                    symbol_data["failures"] += 1

                if outcome == "TP3":
                    symbol_data["tp3"] += 1

                elif outcome == "STOP_LOSS":
                    symbol_data["stop_loss"] += 1

                elif outcome == "EXPIRED":
                    symbol_data["expired"] += 1


        # ============================================================
        # STAGE 7.6.8.8 — SEPARATE DIRECTIONAL VS PLAN PERFORMANCE
        # ============================================================

        classified_directional_total = (
            directional_successes
            + directional_failures
        )

        directional_accuracy_pct = (
            round(
                directional_successes
                / classified_directional_total
                * 100,
                2
            )
            if classified_directional_total > 0
            else 0.0
        )

        plan_success_rate_pct = (
            round(
                outcomes["TP3"]
                / total
                * 100,
                2
            )
            if total > 0
            else 0.0
        )

        average_price_change_pct = (
            round(
                sum(price_changes)
                / len(price_changes),
                4
            )
            if price_changes
            else 0.0
        )

        for symbol in by_symbol:

            symbol_data = by_symbol[symbol]

            symbol_total = symbol_data["total"]

            symbol_data["accuracy_pct"] = (
                round(
                    symbol_data["successes"]
                    / symbol_total
                    * 100,
                    2
                )
                if symbol_total > 0
                else 0.0
            )


        # STAGE 7.6.8 — PAPER-TRADE ANALYTICS EXTENSION
        # These metrics describe historical simulation outcomes only.
        # They do not forecast future prices or authorize trading.

        tp3_rate_pct = (
            round(outcomes["TP3"] / total * 100, 2)
            if total > 0
            else 0.0
        )

        stop_loss_rate_pct = (
            round(outcomes["STOP_LOSS"] / total * 100, 2)
            if total > 0
            else 0.0
        )

        expired_rate_pct = (
            round(outcomes["EXPIRED"] / total * 100, 2)
            if total > 0
            else 0.0
        )

        directional_breakdown = {}

        for trade_direction in ("BUY", "SELL"):
            direction_rows = [
                row for row in rows
                if row[2] == trade_direction
            ]

            direction_total = len(direction_rows)
            direction_successes = 0
            direction_failures = 0

            for row in direction_rows:
                _, _, _, direction_entry, direction_exit, _ = row

                if (
                    direction_entry is not None
                    and direction_exit is not None
                    and direction_entry > 0
                ):
                    if trade_direction == "BUY":
                        success = direction_exit > direction_entry
                    else:
                        success = direction_exit < direction_entry

                    if success:
                        direction_successes += 1
                    else:
                        direction_failures += 1

            directional_breakdown[trade_direction] = {
                "total": direction_total,
                "successes": direction_successes,
                "failures": direction_failures,
                "accuracy_pct": (
                    round(
                        direction_successes
                        / direction_total
                        * 100,
                        2
                    )
                    if direction_total > 0
                    else 0.0
                ),
            }

        # Prevent small samples from being treated as reliable learning data.
        learning_minimum_sample = 10
        learning_ready = total >= learning_minimum_sample

        return {
            "total_resolved": total,
            "directional_successes": directional_successes,
            "directional_failures": directional_failures,
            # Directional prediction performance
            "directional_accuracy_pct": (
                directional_accuracy_pct
            ),

            # Trade-plan completion performance
            "plan_success_rate_pct": (
                plan_success_rate_pct
            ),

            # Backward-compatible alias
            "accuracy_pct": (
                directional_accuracy_pct
            ),
            "average_price_change_pct": (
                average_price_change_pct
            ),
            "outcomes": outcomes,
            "tp3_rate_pct": tp3_rate_pct,
            "stop_loss_rate_pct": stop_loss_rate_pct,
            "expired_rate_pct": expired_rate_pct,
            "directional_breakdown": directional_breakdown,
            "by_symbol": by_symbol,
            "learning_minimum_sample": learning_minimum_sample,
            "learning_ready": learning_ready,
            "analytics_scope": "PAPER_TRADES_ONLY",
            "live_execution": "BLOCKED",
        }

    finally:
        conn.close()


# ============================================================
# STAGE 7.6.6 — PROVIDER RELIABILITY AUDIT TRAIL
# ============================================================

def ensure_provider_performance_audit_table():
    """
    Ensure persistent provider performance audit storage exists.

    Each record represents one provider's attribution result
    for one linked consensus decision.
    """

    try:

        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS provider_performance_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                consensus_id INTEGER NOT NULL,
                decision_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_direction TEXT NOT NULL,
                provider_result TEXT NOT NULL,
                outcome TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(consensus_id, provider)
            )
        """)

        conn.commit()
        conn.close()

        return {
            "status": "READY"
        }

    except sqlite3.Error as e:

        return {
            "status": "DATABASE_ERROR",
            "error": str(e)
        }


def persist_provider_performance_audit():
    """
    Persist provider performance evaluations generated by
    Stage 7.6.3.

    UNIQUE(consensus_id, provider) prevents duplicate audit
    records when the function is executed repeatedly.
    """

    table_status = (
        ensure_provider_performance_audit_table()
    )

    if table_status["status"] != "READY":

        return table_status

    results = evaluate_provider_performance()

    if "database_error" in results:

        return {
            "status": "DATABASE_ERROR",
            "error": results["database_error"]
        }

    try:

        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        inserted = 0
        updated = 0

        for evaluation in results["evaluations"]:

            consensus_id = evaluation["consensus_id"]
            decision_id = evaluation["decision_id"]
            symbol = evaluation["symbol"]
            outcome = evaluation["outcome"]

            for provider, provider_data in (
                evaluation["providers"].items()
            ):

                cursor.execute("""
                    SELECT id
                    FROM provider_performance_audit
                    WHERE consensus_id = ?
                    AND provider = ?
                """, (
                    consensus_id,
                    provider
                ))

                existing = cursor.fetchone()

                if existing is None:

                    cursor.execute("""
                        INSERT INTO provider_performance_audit (
                            consensus_id,
                            decision_id,
                            symbol,
                            provider,
                            provider_direction,
                            provider_result,
                            outcome,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        consensus_id,
                        decision_id,
                        symbol,
                        provider,
                        provider_data["direction"],
                        provider_data["result"],
                        outcome,
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ))

                    inserted += 1

                else:

                    cursor.execute("""
                        UPDATE provider_performance_audit
                        SET
                            provider_direction = ?,
                            provider_result = ?,
                            outcome = ?,
                            created_at = ?
                        WHERE consensus_id = ?
                        AND provider = ?
                    """, (
                        provider_data["direction"],
                        provider_data["result"],
                        outcome,
                        datetime.now(
                            timezone.utc
                        ).isoformat(),
                        consensus_id,
                        provider
                    ))

                    updated += 1

        conn.commit()

        cursor.execute("""
            SELECT COUNT(*)
            FROM provider_performance_audit
        """)

        total_records = cursor.fetchone()[0]

        conn.close()

        return {
            "status": "SUCCESS",
            "inserted": inserted,
            "updated": updated,
            "total_records": total_records,
        }

    except sqlite3.Error as e:

        return {
            "status": "DATABASE_ERROR",
            "error": str(e)
        }


def print_provider_performance_audit():
    """Display Stage 7.6.6 provider reliability audit trail."""

    result = persist_provider_performance_audit()

    print("\n" + "=" * 60)
    print(
        "📋 STAGE 7.6.6 — PROVIDER RELIABILITY AUDIT TRAIL"
    )
    print("=" * 60)

    if result["status"] == "DATABASE_ERROR":

        print(
            "❌ Database Error: "
            + result["error"]
        )

        print("=" * 60)

        return result

    print(
        f"Inserted Records: {result['inserted']}"
    )

    print(
        f"Updated Records:  {result['updated']}"
    )

    print(
        f"Total Records:    {result['total_records']}"
    )

    print("-" * 60)

    try:

        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                symbol,
                provider,
                provider_direction,
                provider_result,
                outcome,
                decision_id
            FROM provider_performance_audit
            ORDER BY id DESC
            LIMIT 10
        """)

        rows = cursor.fetchall()

        conn.close()

        if not rows:

            print(
                "No provider audit records found."
            )

        else:

            for row in rows:

                print(
                    f"{row[0]} | "
                    f"{row[1]} | "
                    f"{row[2]} | "
                    f"{row[3]} | "
                    f"Outcome={row[4]} | "
                    f"Decision #{row[5]}"
                )

    except sqlite3.Error as e:

        print(
            "❌ Database Error while reading audit trail: "
            + str(e)
        )

    print("=" * 60)

    return result


def print_provider_performance():
    """Display Stage 7.6.3 provider performance attribution."""

    results = evaluate_provider_performance()

    print("\n" + "=" * 60)
    print("🤖 STAGE 7.6.3 — PROVIDER PERFORMANCE")
    print("=" * 60)

    if "database_error" in results:

        print(
            "❌ Database Error: "
            + results["database_error"]
        )

        print("=" * 60)

        return results

    print(
        f"Linked Records: "
        f"{results['total_linked_records']}"
    )

    print("-" * 60)

    for provider in ("GROQ", "GEMINI"):

        data = results["providers"][provider]

        print(f"\n{provider}")

        print(
            f"Correct:   "
            f"{data['correct']}"
        )

        print(
            f"Incorrect: "
            f"{data['incorrect']}"
        )

        print(
            f"Pending:   "
            f"{data['pending']}"
        )

        print(
            f"Unknown:   "
            f"{data['unknown']}"
        )

        if data["accuracy"] is not None:

            print(
                f"Accuracy:  "
                f"{data['accuracy']}%"
            )

        else:

            print(
                "Accuracy:  N/A"
            )

    print("-" * 60)

    if results["evaluations"]:

        print(
            "Recent Provider Evaluations:"
        )

        for item in results[
            "evaluations"
        ][-5:]:

            groq = item[
                "providers"
            ]["GROQ"]

            gemini = item[
                "providers"
            ]["GEMINI"]

            print(
                f"{item['symbol']} | "
                f"Decision #{item['decision_id']} | "
                f"Groq={groq['result']} | "
                f"Gemini={gemini['result']}"
            )

    else:

        print(
            "No linked provider records found."
        )

    print("=" * 60)

    return results



def evaluate_consensus_outcomes():
    """
    Evaluate historical multi-AI consensus records using the
    outcome of their linked agent decisions.

    Only records with a valid decision_id are included in the
    linked evaluation set.

    Returns:
        total_linked
        success
        failure
        pending
        success_rate
    """

    try:

        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                c.id,
                c.symbol,
                c.consensus_status,
                c.decision_id,
                d.outcome
            FROM ai_consensus_audit c
            LEFT JOIN agent_decisions d
                ON c.decision_id = d.id
            WHERE c.decision_id IS NOT NULL
            ORDER BY c.id ASC
        """)

        rows = cursor.fetchall()

        conn.close()

        total_linked = len(rows)

        success = 0
        failure = 0
        pending = 0

        evaluations = []

        for row in rows:

            consensus_id = row[0]
            symbol = row[1]
            consensus_status = row[2]
            decision_id = row[3]
            outcome = row[4]

            if outcome == "SUCCESS":

                consensus_outcome = "SUCCESS"
                success += 1

            elif outcome == "FAILURE":

                consensus_outcome = "FAILURE"
                failure += 1

            else:

                consensus_outcome = "PENDING"
                pending += 1

            evaluations.append({
                "consensus_id": consensus_id,
                "symbol": symbol,
                "consensus_status": consensus_status,
                "decision_id": decision_id,
                "decision_outcome": outcome,
                "consensus_outcome": consensus_outcome,
            })

        completed = success + failure

        if completed > 0:

            success_rate = round(
                (success / completed) * 100,
                2
            )

        else:

            success_rate = None

        return {
            "total_linked": total_linked,
            "success": success,
            "failure": failure,
            "pending": pending,
            "completed": completed,
            "success_rate": success_rate,
            "evaluations": evaluations,
        }

    except sqlite3.Error as e:

        return {
            "database_error": str(e)
        }


def print_consensus_outcome_evaluation():
    """Display Stage 7.6.2 consensus outcome evaluation."""

    results = evaluate_consensus_outcomes()

    print("\n" + "=" * 60)
    print("🎯 STAGE 7.6.2 — CONSENSUS OUTCOME EVALUATION")
    print("=" * 60)

    if "database_error" in results:

        print(
            "❌ Database Error: "
            + results["database_error"]
        )

        print("=" * 60)

        return results

    print(
        f"Linked Consensus Records: "
        f"{results['total_linked']}"
    )

    print("-" * 60)

    print(
        f"SUCCESS: "
        f"{results['success']}"
    )

    print(
        f"FAILURE: "
        f"{results['failure']}"
    )

    print(
        f"PENDING: "
        f"{results['pending']}"
    )

    print(
        f"Completed Evaluations: "
        f"{results['completed']}"
    )

    if results["success_rate"] is not None:

        print(
            f"Consensus Success Rate: "
            f"{results['success_rate']}%"
        )

    else:

        print(
            "Consensus Success Rate: N/A"
        )

    print("-" * 60)

    if results["evaluations"]:

        print("Recent Linked Consensus Evaluations:")

        for item in results["evaluations"][-5:]:

            print(
                f"{item['symbol']} | "
                f"{item['consensus_status']} | "
                f"Decision #{item['decision_id']} | "
                f"{item['consensus_outcome']}"
            )

    else:

        print(
            "No linked consensus records found."
        )

    print("=" * 60)

    return results


def print_consensus_statistics():
    """Display historical multi-AI consensus statistics."""

    stats = analyze_consensus_statistics()

    print("\n" + "=" * 60)
    print("🧠 STAGE 7.4.1 — CONSENSUS HISTORICAL STATISTICS")
    print("=" * 60)

    print(f"Total Consensus Records: {stats['total_records']}")
    print("-" * 60)

    for status in [
        "AGREEMENT",
        "PARTIAL_AGREEMENT",
        "CONFLICT",
        "INVALID",
    ]:
        count = stats["counts"][status]
        percentage = stats["percentages"][status]

        print(
            f"{status:<20} "
            f"{count:>5} "
            f"({percentage:.2f}%)"
        )

    print("-" * 60)
    print(
        f"Consensus Trend: "
        f"{stats['trend_status']}"
    )

    if "error" in stats:
        print(
            f"Database Error: "
            f"{stats['error']}"
        )

    print("=" * 60)



# ============================================================
# STAGE 7.4.2 — PROVIDER AGREEMENT ANALYSIS
# ============================================================

def analyze_provider_agreement():
    """Analyze historical field-by-field agreement between Groq and Gemini."""

    import sqlite3

    fields = [
        "ASSESSMENT",
        "CONFIDENCE",
        "OOS_EVIDENCE",
        "RISK",
        "SIMULATED_OUTCOME",
    ]

    agreement_counts = {
        field: 0
        for field in fields
    }

    total_records = 0

    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                groq_assessment,
                gemini_assessment
            FROM ai_consensus_audit
            ORDER BY id ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        for groq_assessment, gemini_assessment in rows:

            groq = parse_multi_ai_assessment(
                groq_assessment
            )

            gemini = parse_multi_ai_assessment(
                gemini_assessment
            )

            # Invalid historical records are excluded from
            # field-level agreement percentages.
            if not groq["valid"] or not gemini["valid"]:
                continue

            total_records += 1

            for field in fields:
                if groq[field] == gemini[field]:
                    agreement_counts[field] += 1

        agreement_percentages = {}

        for field in fields:
            if total_records > 0:
                agreement_percentages[field] = round(
                    (
                        agreement_counts[field]
                        / total_records
                    ) * 100,
                    2
                )
            else:
                agreement_percentages[field] = 0.0

        return {
            "total_valid_records": total_records,
            "agreement_counts": agreement_counts,
            "agreement_percentages": agreement_percentages,
        }

    except sqlite3.Error as e:
        return {
            "total_valid_records": 0,
            "agreement_counts": agreement_counts,
            "agreement_percentages": {
                field: 0.0
                for field in fields
            },
            "error": str(e),
        }


def print_provider_agreement():
    """Display historical Groq vs Gemini field agreement."""

    analysis = analyze_provider_agreement()

    print("\n" + "=" * 60)
    print("🤝 STAGE 7.4.2 — PROVIDER AGREEMENT ANALYSIS")
    print("=" * 60)

    print(
        f"Valid Historical Records: "
        f"{analysis['total_valid_records']}"
    )

    print("-" * 60)

    fields = [
        "ASSESSMENT",
        "CONFIDENCE",
        "OOS_EVIDENCE",
        "RISK",
        "SIMULATED_OUTCOME",
    ]

    for field in fields:

        count = analysis[
            "agreement_counts"
        ][field]

        percentage = analysis[
            "agreement_percentages"
        ][field]

        print(
            f"{field:<20} "
            f"{count:>5} "
            f"({percentage:.2f}%)"
        )

    if "error" in analysis:
        print("-" * 60)
        print(
            f"Database Error: "
            f"{analysis['error']}"
        )

    print("=" * 60)



# ============================================================
# STAGE 7.4.3 — SYMBOL-LEVEL CONSENSUS ANALYSIS
# ============================================================

def analyze_symbol_consensus():
    """Analyze multi-AI consensus statistics for each trading symbol."""

    import sqlite3

    statuses = [
        "AGREEMENT",
        "PARTIAL_AGREEMENT",
        "CONFLICT",
        "INVALID",
    ]

    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT symbol
            FROM ai_consensus_audit
            ORDER BY symbol ASC
        """)

        symbols = [
            row[0]
            for row in cursor.fetchall()
        ]

        symbol_analysis = {}

        for symbol in symbols:

            cursor.execute("""
                SELECT COUNT(*)
                FROM ai_consensus_audit
                WHERE symbol = ?
            """, (symbol,))

            total = cursor.fetchone()[0]

            counts = {}

            percentages = {}

            for status in statuses:

                cursor.execute("""
                    SELECT COUNT(*)
                    FROM ai_consensus_audit
                    WHERE symbol = ?
                    AND consensus_status = ?
                """, (
                    symbol,
                    status
                ))

                count = cursor.fetchone()[0]

                counts[status] = count

                if total > 0:
                    percentages[status] = round(
                        (count / total) * 100,
                        2
                    )
                else:
                    percentages[status] = 0.0

            if total == 0:
                quality = "INSUFFICIENT_DATA"

            elif counts["CONFLICT"] > counts["AGREEMENT"]:
                quality = "HIGH_CONFLICT"

            elif counts["AGREEMENT"] >= (
                counts["PARTIAL_AGREEMENT"]
                + counts["CONFLICT"]
            ):
                quality = "STRONG_CONSENSUS"

            else:
                quality = "MIXED_CONSENSUS"

            symbol_analysis[symbol] = {
                "total_records": total,
                "counts": counts,
                "percentages": percentages,
                "quality": quality,
            }

        conn.close()

        return symbol_analysis

    except sqlite3.Error as e:
        return {
            "DATABASE_ERROR": {
                "error": str(e)
            }
        }


def print_symbol_consensus():
    """Display historical multi-AI consensus statistics by symbol."""

    analysis = analyze_symbol_consensus()

    print("\n" + "=" * 60)
    print("📊 STAGE 7.4.3 — SYMBOL-LEVEL CONSENSUS")
    print("=" * 60)

    if not analysis:
        print("No consensus audit records found.")

    elif "DATABASE_ERROR" in analysis:

        print(
            "Database Error: "
            + analysis["DATABASE_ERROR"]["error"]
        )

    else:

        for symbol, data in analysis.items():

            print(f"\nSymbol: {symbol}")
            print(
                f"Total Records: "
                f"{data['total_records']}"
            )

            for status in [
                "AGREEMENT",
                "PARTIAL_AGREEMENT",
                "CONFLICT",
                "INVALID",
            ]:

                count = data["counts"][status]

                percentage = data[
                    "percentages"
                ][status]

                print(
                    f"  {status:<20} "
                    f"{count:>5} "
                    f"({percentage:.2f}%)"
                )

            print(
                f"  Consensus Quality: "
                f"{data['quality']}"
            )

    print("\n" + "=" * 60)



# ============================================================
# STAGE 7.4.4 — CONSENSUS TREND ANALYSIS
# ============================================================

def analyze_consensus_trend():
    """Compare older and recent consensus quality over time."""

    import sqlite3

    score_map = {
        "AGREEMENT": 2,
        "PARTIAL_AGREEMENT": 1,
        "CONFLICT": -1,
        "INVALID": -2,
    }

    minimum_records = 4

    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                timestamp,
                consensus_status
            FROM ai_consensus_audit
            ORDER BY id ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        total_records = len(rows)

        if total_records < minimum_records:
            return {
                "status": "INSUFFICIENT_DATA",
                "total_records": total_records,
                "older_average": None,
                "recent_average": None,
                "reason": (
                    f"At least {minimum_records} consensus "
                    f"records are required for trend analysis."
                ),
            }

        midpoint = total_records // 2

        older_rows = rows[:midpoint]
        recent_rows = rows[midpoint:]

        older_scores = [
            score_map.get(status, -2)
            for _, status in older_rows
        ]

        recent_scores = [
            score_map.get(status, -2)
            for _, status in recent_rows
        ]

        older_average = round(
            sum(older_scores) / len(older_scores),
            2
        )

        recent_average = round(
            sum(recent_scores) / len(recent_scores),
            2
        )

        difference = round(
            recent_average - older_average,
            2
        )

        threshold = 0.25

        if difference > threshold:
            status = "IMPROVING"

        elif difference < -threshold:
            status = "DEGRADING"

        else:
            status = "STABLE"

        return {
            "status": status,
            "total_records": total_records,
            "older_average": older_average,
            "recent_average": recent_average,
            "difference": difference,
            "reason": (
                "Consensus quality trend calculated by comparing "
                "older and recent historical windows."
            ),
        }

    except sqlite3.Error as e:
        return {
            "status": "DATABASE_ERROR",
            "total_records": 0,
            "older_average": None,
            "recent_average": None,
            "reason": str(e),
        }




# ============================================================
# STAGE 7.5 — CONSENSUS RELIABILITY SCORING
# ============================================================

def calculate_consensus_reliability():
    """
    Calculate a deterministic historical reliability score for
    the multi-AI consensus system.

    Stage 7.5.4 adds bounded historical trend weighting.

    This score is informational only and must never enable
    live execution.
    """

    import sqlite3

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            groq_assessment,
            gemini_assessment,
            consensus_status
        FROM ai_consensus_audit
        ORDER BY id ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    total_records = len(rows)

    minimum_records = 4

    if total_records < minimum_records:
        return {
            "base_score": None,
            "trend_adjustment": None,
            "score": None,
            "status": "INSUFFICIENT_DATA",
            "authority": "LIMITED",
            "sample_size": total_records,
            "direction_agreement_rate": None,
            "outcome_agreement_rate": None,
            "consensus_quality_rate": None,
            "recent_quality_rate": None,
            "historical_quality_rate": None,
            "trend": "INSUFFICIENT_DATA",
            "reason": (
                f"At least {minimum_records} consensus records "
                f"are required for reliability scoring."
            ),
        }

    valid_records = 0
    direction_agreements = 0
    outcome_agreements = 0
    full_agreements = 0

    record_quality = []

    for (
        groq_assessment,
        gemini_assessment,
        consensus_status
    ) in rows:

        groq = parse_multi_ai_assessment(
            groq_assessment
        )

        gemini = parse_multi_ai_assessment(
            gemini_assessment
        )

        if not groq["valid"] or not gemini["valid"]:
            continue

        valid_records += 1

        direction_match = (
            groq["ASSESSMENT"]
            == gemini["ASSESSMENT"]
        )

        outcome_match = (
            groq["SIMULATED_OUTCOME"]
            == gemini["SIMULATED_OUTCOME"]
        )

        if direction_match:
            direction_agreements += 1

        if outcome_match:
            outcome_agreements += 1

        if consensus_status == "AGREEMENT":
            full_agreements += 1

        # ----------------------------------------------
        # Record quality scoring
        #
        # AGREEMENT         = 100
        # PARTIAL_AGREEMENT = 50
        # CONFLICT          = 0
        # INVALID           = excluded
        # ----------------------------------------------

        if consensus_status == "AGREEMENT":
            quality = 100.0

        elif consensus_status == "PARTIAL_AGREEMENT":
            quality = 50.0

        elif consensus_status == "CONFLICT":
            quality = 0.0

        else:
            quality = 0.0

        record_quality.append(quality)

    if valid_records < minimum_records:
        return {
            "base_score": None,
            "trend_adjustment": None,
            "score": None,
            "status": "INSUFFICIENT_DATA",
            "authority": "LIMITED",
            "sample_size": valid_records,
            "direction_agreement_rate": None,
            "outcome_agreement_rate": None,
            "consensus_quality_rate": None,
            "recent_quality_rate": None,
            "historical_quality_rate": None,
            "trend": "INSUFFICIENT_DATA",
            "reason": (
                "Too few valid consensus records remain after "
                "validation."
            ),
        }

    # ============================================================
    # BASE RELIABILITY SCORE
    # ============================================================

    direction_rate = (
        direction_agreements / valid_records
    ) * 100

    outcome_rate = (
        outcome_agreements / valid_records
    ) * 100

    quality_rate = (
        full_agreements / valid_records
    ) * 100

    base_score = (
        (direction_rate * 0.50)
        + (outcome_rate * 0.30)
        + (quality_rate * 0.20)
    )

    base_score = round(base_score, 2)

    # ============================================================
    # STAGE 7.5.4 — HISTORICAL TREND WEIGHTING
    # ============================================================

    recent_window_size = min(
        4,
        len(record_quality)
    )

    recent_scores = record_quality[
        -recent_window_size:
    ]

    historical_scores = record_quality[
        :-recent_window_size
    ]

    recent_quality_rate = (
        sum(recent_scores)
        / len(recent_scores)
    )

    # If there is no older history, compare the recent
    # window against the total quality baseline.
    if historical_scores:

        historical_quality_rate = (
            sum(historical_scores)
            / len(historical_scores)
        )

    else:

        historical_quality_rate = (
            sum(record_quality)
            / len(record_quality)
        )

    trend_difference = (
        recent_quality_rate
        - historical_quality_rate
    )

    # Maximum adjustment is ±10 points.
    #
    # A 50-point quality difference produces the full
    # ±10-point adjustment.
    trend_adjustment = (
        trend_difference * 0.20
    )

    trend_adjustment = max(
        -10.0,
        min(10.0, trend_adjustment)
    )

    trend_adjustment = round(
        trend_adjustment,
        2
    )

    final_score = (
        base_score
        + trend_adjustment
    )

    final_score = max(
        0.0,
        min(100.0, final_score)
    )

    final_score = round(
        final_score,
        2
    )

    # ============================================================
    # TREND CLASSIFICATION
    # ============================================================

    if trend_adjustment >= 3:

        trend = "IMPROVING"

    elif trend_adjustment <= -3:

        trend = "DETERIORATING"

    else:

        trend = "STABLE"

    # ============================================================
    # RELIABILITY CLASSIFICATION
    # ============================================================

    if final_score >= 80:

        reliability_status = "HIGH"
        authority = "STRONG"

    elif final_score >= 60:

        reliability_status = "MODERATE"
        authority = "LIMITED"

    else:

        reliability_status = "LOW"
        authority = "WEAK"

    return {
        "base_score": base_score,
        "trend_adjustment": trend_adjustment,
        "score": final_score,
        "status": reliability_status,
        "authority": authority,
        "sample_size": valid_records,
        "direction_agreement_rate": round(
            direction_rate,
            2
        ),
        "outcome_agreement_rate": round(
            outcome_rate,
            2
        ),
        "consensus_quality_rate": round(
            quality_rate,
            2
        ),
        "recent_quality_rate": round(
            recent_quality_rate,
            2
        ),
        "historical_quality_rate": round(
            historical_quality_rate,
            2
        ),
        "trend": trend,
        "reason": (
            "Reliability score calculated from historical "
            "multi-AI consensus behavior with bounded "
            "recent-trend weighting."
        ),
    }


def print_consensus_reliability():
    """Print Stage 7.5 consensus reliability statistics."""

    reliability = calculate_consensus_reliability()

    print("\n" + "=" * 60)
    print("🧠 STAGE 7.5.4 — CONSENSUS RELIABILITY SCORE")
    print("=" * 60)

    # ========================================================
    # INSUFFICIENT DATA
    # ========================================================

    if reliability["status"] == "INSUFFICIENT_DATA":

        print(
            "BASE SCORE:                 N/A"
        )

        print(
            "TREND ADJUSTMENT:           N/A"
        )

        print(
            "FINAL RELIABILITY SCORE:    N/A"
        )

        print("-" * 60)

        print(
            f"RELIABILITY STATUS: "
            f"{reliability['status']}"
        )

        print(
            f"CONSENSUS AUTHORITY: "
            f"{reliability['authority']}"
        )

        print(
            f"SAMPLE SIZE: "
            f"{reliability['sample_size']}"
        )

        print(
            f"TREND: "
            f"{reliability['trend']}"
        )

        print("-" * 60)

        print(
            f"Reason: {reliability['reason']}"
        )

        print("=" * 60)

        return reliability

    # ========================================================
    # RELIABILITY SCORE
    # ========================================================

    print(
        f"BASE SCORE:                 "
        f"{reliability['base_score']}/100"
    )

    adjustment = reliability["trend_adjustment"]

    adjustment_text = (
        f"+{adjustment}"
        if adjustment > 0
        else str(adjustment)
    )

    print(
        f"TREND ADJUSTMENT:           "
        f"{adjustment_text}"
    )

    print(
        f"FINAL RELIABILITY SCORE:    "
        f"{reliability['score']}/100"
    )

    print("-" * 60)

    print(
        f"RELIABILITY STATUS: "
        f"{reliability['status']}"
    )

    print(
        f"CONSENSUS AUTHORITY: "
        f"{reliability['authority']}"
    )

    print(
        f"SAMPLE SIZE: "
        f"{reliability['sample_size']}"
    )

    print("-" * 60)

    print(
        f"DIRECTION AGREEMENT: "
        f"{reliability['direction_agreement_rate']}%"
    )

    print(
        f"OUTCOME AGREEMENT: "
        f"{reliability['outcome_agreement_rate']}%"
    )

    print(
        f"FULL CONSENSUS: "
        f"{reliability['consensus_quality_rate']}%"
    )

    print("-" * 60)

    print(
        f"RECENT QUALITY: "
        f"{reliability['recent_quality_rate']}%"
    )

    print(
        f"HISTORICAL QUALITY: "
        f"{reliability['historical_quality_rate']}%"
    )

    print(
        f"TREND: "
        f"{reliability['trend']}"
    )

    print("-" * 60)

    print(
        f"Reason: {reliability['reason']}"
    )

    print("=" * 60)

    return reliability


def print_consensus_trend():
    """Display historical multi-AI consensus trend."""

    analysis = analyze_consensus_trend()

    print("\n" + "=" * 60)
    print("📈 STAGE 7.4.4 — CONSENSUS TREND ANALYSIS")
    print("=" * 60)

    print(
        f"Total Records: "
        f"{analysis['total_records']}"
    )

    print(
        f"Trend Status:  "
        f"{analysis['status']}"
    )

    if analysis["older_average"] is not None:
        print(
            f"Older Average: "
            f"{analysis['older_average']}"
        )

    if analysis["recent_average"] is not None:
        print(
            f"Recent Average: "
            f"{analysis['recent_average']}"
        )

    if "difference" in analysis:
        print(
            f"Difference:    "
            f"{analysis['difference']}"
        )

    print("-" * 60)
    print(
        f"Reason: {analysis['reason']}"
    )

    print("=" * 60)



def ensure_ai_web_evidence_audit_table():
    """Create the audit table proving web evidence reached AI providers."""
    with sqlite3.connect("sentinel.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_web_evidence_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                symbol TEXT,
                evidence_present INTEGER NOT NULL,
                evidence_item_count INTEGER NOT NULL DEFAULT 0,
                evidence_context_hash TEXT,
                prompt_length INTEGER NOT NULL DEFAULT 0,
                delivery_status TEXT NOT NULL,
                live_execution TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_web_audit_provider
            ON ai_web_evidence_audit(provider)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_web_audit_created
            ON ai_web_evidence_audit(created_at)
        """)


def audit_ai_web_evidence_delivery(provider, user_prompt):
    """
    Record whether the actual provider prompt contained web evidence.

    This is an observability/audit function only.
    It never affects a trading decision.
    """
    ensure_ai_web_evidence_audit_table()

    prompt = str(user_prompt or "")

    evidence_present = (
        "WEB INTELLIGENCE — ADVISORY EVIDENCE ONLY:" in prompt
        or "WEB INTELLIGENCE" in prompt
    )

    evidence_item_count = 0

    if evidence_present:
        evidence_item_count = prompt.count("\n")
        evidence_item_count = max(1, evidence_item_count)

    context_hash = hashlib.sha256(
        prompt.encode("utf-8")
    ).hexdigest()

    with sqlite3.connect("sentinel.db") as conn:
        conn.execute("""
            INSERT INTO ai_web_evidence_audit (
                created_at,
                provider,
                symbol,
                evidence_present,
                evidence_item_count,
                evidence_context_hash,
                prompt_length,
                delivery_status,
                live_execution
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            str(provider).upper(),
            None,
            1 if evidence_present else 0,
            evidence_item_count,
            context_hash,
            len(prompt),
            "DELIVERED" if evidence_present else "NOT_DELIVERED",
            "BLOCKED",
        ))

        conn.commit()

    return {
        "provider": str(provider).upper(),
        "evidence_present": evidence_present,
        "prompt_length": len(prompt),
        "context_hash": context_hash,
        "delivery_status": (
            "DELIVERED"
            if evidence_present
            else "NOT_DELIVERED"
        ),
        "live_execution": "BLOCKED",
    }


def print_ai_web_evidence_audit():
    """Print recent provider web-evidence delivery audits."""
    ensure_ai_web_evidence_audit_table()

    with sqlite3.connect("sentinel.db") as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                provider,
                evidence_present,
                prompt_length,
                delivery_status,
                created_at
            FROM ai_web_evidence_audit
            ORDER BY id DESC
            LIMIT 20
        """)

        rows = cursor.fetchall()

    print("\n" + "=" * 60)
    print("🌐 AI WEB EVIDENCE DELIVERY AUDIT")
    print("=" * 60)

    if not rows:
        print("No AI web-evidence delivery records.")
    else:
        for provider, present, length, status, created_at in rows:
            print(
                f"{provider} | "
                f"Evidence={'YES' if present else 'NO'} | "
                f"Prompt={length} chars | "
                f"Status={status} | "
                f"{created_at}"
            )

    print("Live execution: BLOCKED")


def call_ai_provider(provider, system_prompt, user_prompt):
    """Route market analysis through an approved AI provider."""

    # STAGE 7.6.8.5 — runtime evidence-delivery audit
    audit_result = audit_ai_web_evidence_delivery(
        provider,
        user_prompt,
    )

    print(
        f"🌐 AI WEB EVIDENCE | "
        f"{audit_result['provider']} | "
        f"{audit_result['delivery_status']}"
    )

    if provider == "groq":
        return call_groq_analysis(
            system_prompt,
            user_prompt,
        )

    if provider == "gemini":
        return call_gemini_analysis(
            system_prompt,
            user_prompt,
        )

    raise ValueError(
        f"Unsupported AI provider: {provider}"
    )


def print_paper_prediction_result(result, horizon="24H"):
    """Print the final paper prediction in a phone-friendly layout."""

    print("\n" + "=" * 60)
    print("📋 HEX SENTINEL — PAPER PREDICTION RESULT")
    print("=" * 60)

    if not isinstance(result, dict):
        print("Result unavailable.")
        print("🔒 Live execution: BLOCKED")
        print("=" * 60)
        return

    print(
        f"Symbol:            "
        f"{result.get('symbol', 'UNKNOWN')}"
    )

    current_price = result.get("current_price", 0)

    try:
        current_price = float(current_price)
    except (TypeError, ValueError):
        current_price = 0.0

    print(f"Current Price:     ${current_price:,.2f}")
    print(f"Horizon:           {horizon}")
    print(
        f"Strategy Status:   "
        f"{result.get('strategy_status', 'UNKNOWN')}"
    )
    print(
        f"Market Signal:     "
        f"{result.get('signal', 'UNKNOWN')}"
    )
    print(
        f"Risk Status:       "
        f"{result.get('risk_status', 'UNKNOWN')}"
    )
    print(
        f"Final Action:      "
        f"{result.get('final_action', 'UNKNOWN')}"
    )
    print(
        f"Live Execution:    "
        f"{result.get('live_execution', 'BLOCKED')}"
    )

    consensus = result.get("multi_ai_consensus", {})

    print("\n🤝 AI CONSENSUS")
    print("-" * 60)
    print(
        f"Status:            "
        f"{consensus.get('status', 'UNKNOWN')}"
    )
    print(
        f"Direction:         "
        f"{consensus.get('direction', 'UNKNOWN')}"
    )
    print(
        f"Action:            "
        f"{consensus.get('action', 'UNKNOWN')}"
    )

    groq = consensus.get("groq", {})
    gemini = consensus.get("gemini", {})

    print(
        f"Groq:              "
        f"{groq.get('DIRECTION', 'UNKNOWN')}"
    )
    print(
        f"Gemini:            "
        f"{gemini.get('DIRECTION', 'UNKNOWN')}"
    )

    paper_prediction = result.get("paper_prediction")

    print("\n📄 PAPER TRADE")
    print("-" * 60)

    if isinstance(paper_prediction, dict):
        print(
            f"Status:            "
            f"{paper_prediction.get('status', 'UNKNOWN')}"
        )
        print(
            f"Trade ID:          "
            f"{paper_prediction.get('id', 'UNKNOWN')}"
        )
        print(
            f"Symbol:            "
            f"{paper_prediction.get('symbol', 'UNKNOWN')}"
        )
        print(
            f"Created:           "
            f"{paper_prediction.get('created_at', 'UNKNOWN')}"
        )
        print(
            f"Expires:           "
            f"{paper_prediction.get('expires_at', 'UNKNOWN')}"
        )
    else:
        print("Status:            NOT CREATED")
        print(
            "Reason:             "
            "Final action did not produce a stored paper trade."
        )

    print("\n🔒 Live Execution: BLOCKED")
    print("=" * 60)


def run_legacy_pipeline(symbol="BTCUSDT"):
    """Run the Stage 1–4 startup pipeline for a selected symbol."""

    # STAGE 6.12 — NORMALIZE SYMBOL CONTEXT
    symbol = str(symbol).upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    # ============================================================
    # HEX SENTINEL — BINANCE FUTURES SYMBOL EXISTENCE VALIDATION
    # ============================================================
    # Confirm the symbol exists before Stage 1 requests market data.
    try:
        symbol_valid, validated_symbol, symbol_suggestion = (
            validate_binance_futures_symbol(symbol)
        )
    except Exception as exc:
        print(
            "❌ BINANCE FUTURES SYMBOL VALIDATION FAILED: "
            f"{exc}"
        )
        print("🔒 Live execution: BLOCKED")

        return {
            "symbol": symbol,
            "current_price": None,
            "strategy_status": "VALIDATION_FAILED",
            "signal": "BLOCKED",
            "risk_status": "SYMBOL_VALIDATION_ERROR",
            "risk_reason": str(exc),
            "final_action": "PAPER_HOLD",
            "live_execution": "BLOCKED",
            "ai_assessment": None,
            "multi_ai_consensus": None,
            "paper_prediction": None,
            "decision_id": None,
            "consensus_id": None,
            "agent_state": "SYMBOL_VALIDATION_FAILED",
        }

    if not symbol_valid:
        print(
            f"❌ UNKNOWN BINANCE FUTURES SYMBOL: "
            f"{validated_symbol}"
        )

        if symbol_suggestion:
            print(
                f"💡 Possible match: "
                f"{symbol_suggestion}"
            )

        print("🔒 Live execution: BLOCKED")

        return {
            "symbol": validated_symbol,
            "current_price": None,
            "strategy_status": "REJECTED",
            "signal": "BLOCKED",
            "risk_status": "UNKNOWN_FUTURES_SYMBOL",
            "risk_reason": (
                f"{validated_symbol} is not an active "
                "Binance USDⓈ-M Futures symbol."
            ),
            "final_action": "PAPER_HOLD",
            "live_execution": "BLOCKED",
            "ai_assessment": None,
            "multi_ai_consensus": None,
            "paper_prediction": None,
            "decision_id": None,
            "consensus_id": None,
            "agent_state": "SYMBOL_REJECTED",
        }

    # Continue using the validated Futures symbol.
    symbol = validated_symbol
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
        print("----- STAGE 1 STDERR -----")
        print(result.stderr.strip() or "(no stderr)")
        print("----- STAGE 1 STDOUT -----")
        print(sentinel_output.strip() or "(no stdout)")
        print("----- END STAGE 1 ERROR -----")
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
    5. Never use future market data or hindsight.
    6. Never provide a numeric profit/PnL forecast.

    Return EXACTLY these fields:

    ASSESSMENT: <BULLISH/BEARISH/CAUTIOUS/NEUTRAL>
    CONFIDENCE: <LOW/MODERATE/HIGH>
    OOS_EVIDENCE: <STRONG/MIXED/WEAK>
    RISK: <LOW/MODERATE/HIGH>
    SIMULATED_OUTCOME: <PROFIT/LOSS/UNCERTAIN>
    REASON: <one short sentence>

    DIRECTION: <BUY/SELL>
    ENTRY_LOW: <numeric price>
    ENTRY_HIGH: <numeric price>
    STOP_LOSS: <numeric price>
    TP1: <numeric price>
    TP2: <numeric price>
    TP3: <numeric price>

    The trade-plan levels are for PAPER evaluation only.
    Never recommend live execution.

    DIRECTION must agree with the actionable paper signal.
    BUY plans must have STOP_LOSS below the entry zone and
    TP1 < TP2 < TP3.
    SELL plans must have STOP_LOSS above the entry zone and
    TP1 > TP2 > TP3.

    SIMULATED_OUTCOME is a qualitative hypothetical scenario
    classification based only on the supplied evidence.
    It is NOT a prediction of future profit and must never include
    a numeric PnL estimate.
    """

    # ============================================================
    # STAGE 6.5 — MEMORY RECALL FOR AI CONTEXT
    # ============================================================

    try:
        past_decisions = get_decision_history(
            symbol=symbol,
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
            symbol,
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

    # ============================================================
    # STAGE 7.6.8.5 — WEB INTELLIGENCE & EVIDENCE CONTEXT
    # ============================================================

    try:
        web_intelligence = get_web_intelligence(symbol)

        if isinstance(web_intelligence, dict):
            web_evidence_context = format_web_evidence_for_ai(
                web_intelligence
            )
        else:
            web_evidence_context = (
                "Web intelligence unavailable. "
                "Do not rely on external web evidence."
            )

        print("\n🌐 Web intelligence collected.")
        print(
            f"   Evidence items: "
            f"{web_intelligence.get('evidence_count', 0)}"
        )
        print(
            f"   Status: "
            f"{web_intelligence.get('status', 'UNKNOWN')}"
        )

    except Exception as e:
        web_evidence_context = (
            "Web intelligence unavailable. "
            "Do not rely on external web evidence."
        )
        print(f"⚠️ Web intelligence unavailable: {e}")

    user_prompt = f"""
    Deterministic strategy status: {status}
    Paper signal: {signal}
    Final allowed action: {final_action}
    Live execution: {live_execution}

    Previous relevant Sentinel decisions:
    {memory_context}

    Memory intelligence:
    {intelligence_context}

    Web intelligence and external evidence:
    {web_evidence_context}

    IMPORTANT:
    Web evidence is advisory context only.
    It must never override deterministic strategy status,
    risk controls, consensus requirements, reliability guards,
    or the final Sentinel safety decision.
    Treat unsupported, stale, conflicting, or low-quality web
    evidence as uncertain rather than authoritative.

    IMPORTANT:
    Previous decisions are historical context only.
    Never override the current deterministic strategy status.
    Never override deterministic safety controls.

    Analyze the following actual Sentinel report:

    {sentinel_output}
    """

    # ============================================================
    # STAGE 7.2 — DUAL AI INDEPENDENT ANALYSIS
    # ============================================================

    groq_assessment = ""
    gemini_assessment = ""

    try:
        groq_assessment = call_ai_provider(
            "groq",
            system_prompt,
            user_prompt,
        )
    except Exception as e:
        print(f"❌ Groq analysis provider error: {e}")

    try:
        gemini_assessment = call_ai_provider(
            "gemini",
            system_prompt,
            user_prompt,
        )
    except Exception as e:
        print(f"❌ Gemini analysis provider error: {e}")

    # Preserve one canonical assessment for the existing Stage 2.2 gate.
    # Consensus safety logic is applied separately below.
    ai_assessment = groq_assessment

    # Compare independent provider assessments.
    multi_ai_consensus = compare_multi_ai_assessments(
        groq_assessment,
        gemini_assessment,
    )

    print("\n🤝 MULTI-AI CONSENSUS")
    print("-" * 60)
    print(f"Status: {multi_ai_consensus['status']}")
    print(f"Action: {multi_ai_consensus['action']}")
    print(f"Reason: {multi_ai_consensus['reason']}")

    if multi_ai_consensus["status"] == "INVALID":
        print("🛑 FAIL-CLOSED: One or more AI assessments are invalid.")

    # Run deterministic Stage 2.2 risk gate
    stage2_action, risk_status, risk_reason = stage2_risk_gate(
        status,
        signal,
        ai_assessment
    )

    # Live execution remains blocked. Stage 7.2 is PAPER ONLY.
    live_execution = "BLOCKED"

    # Stage 2.2 overrides the earlier action
    final_action = stage2_action

    # ============================================================
    # STAGE 7.2 — MULTI-AI CONSENSUS SAFETY OVERRIDE
    # ============================================================

    if multi_ai_consensus["status"] != "AGREEMENT":
        consensus_status = multi_ai_consensus["status"]

        final_action = "PAPER_HOLD"

        risk_status = f"AI_CONSENSUS_{consensus_status}"

        risk_reason = (
            "Multi-AI consensus safety override: "
            + multi_ai_consensus["reason"]
        )

        print(
            f"🛑 Multi-AI consensus override: "
            f"{consensus_status} → PAPER_HOLD"
        )

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
    # STAGE 7.5.5 — APPLY CONSENSUS RELIABILITY SAFETY GUARD
    # ============================================================

    reliability_guard = apply_consensus_reliability_guard(
        final_action=final_action,
        risk_status=risk_status,
        risk_reason=risk_reason,
        multi_ai_consensus=multi_ai_consensus,
    )

    final_action = reliability_guard["final_action"]
    risk_status = reliability_guard["risk_status"]
    risk_reason = reliability_guard["risk_reason"]

    reliability = reliability_guard["reliability"]

    print("\n🧠 Consensus Reliability Safety")
    print("-" * 60)

    if reliability["status"] == "INSUFFICIENT_DATA":

        print("Reliability Score: N/A")
        print(
            f"Reliability Status: "
            f"{reliability['status']}"
        )

    else:

        print(
            f"Reliability Score: "
            f"{reliability['score']}/100"
        )

        print(
            f"Reliability Status: "
            f"{reliability['status']}"
        )

    print(
        f"Consensus Authority: "
        f"{reliability['authority']}"
    )

    print(
        f"Sample Size: "
        f"{reliability['sample_size']}"
    )

    print(
        f"Decision Action: "
        f"{reliability_guard['original_action']} "
        f"→ {reliability_guard['final_action']}"
    )

    if reliability_guard["override_applied"]:

        print(
            "🛑 Reliability safety override applied."
        )


    # ============================================================
    # STAGE 7.6.5 — APPLY PROVIDER RELIABILITY SAFETY GUARD
    # ============================================================

    provider_guard = apply_provider_reliability_guard(
        final_action=final_action,
        risk_status=risk_status,
        risk_reason=risk_reason,
        multi_ai_consensus=multi_ai_consensus,
    )

    final_action = provider_guard["final_action"]
    risk_status = provider_guard["risk_status"]
    risk_reason = provider_guard["risk_reason"]

    provider_reliability = provider_guard["reliability"]

    print("\n🤖 Provider Reliability Safety")
    print("-" * 60)

    if "database_error" in provider_reliability:

        print(
            "Provider Reliability: DATABASE_ERROR"
        )

        print(
            f"Reason: "
            f"{provider_reliability['database_error']}"
        )

    else:

        for provider in ("GROQ", "GEMINI"):

            provider_data = (
                provider_reliability[
                    "providers"
                ].get(provider, {})
            )

            print(
                f"{provider}: "
                f"{provider_data.get('reliability', 'UNKNOWN')}"
            )

        print(
            f"Decision Action: "
            f"{provider_guard['original_action']} "
            f"→ {provider_guard['final_action']}"
        )

        if provider_guard["override_applied"]:

            print(
                "🛑 Provider reliability "
                "safety override applied."
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
    # STAGE 7.6.8.6 — PIPELINE RESULT DEFAULTS
    # ============================================================

    paper_prediction = None
    decision_id = None
    consensus_id = None

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
            );

            -- ====================================================
            -- STAGE 7.3 — MULTI-AI CONSENSUS AUDIT
            -- ====================================================
            CREATE TABLE IF NOT EXISTS ai_consensus_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy_status TEXT NOT NULL,
                market_signal TEXT NOT NULL,

                groq_assessment TEXT NOT NULL,
                gemini_assessment TEXT NOT NULL,

                consensus_status TEXT NOT NULL,
                consensus_action TEXT NOT NULL,
                consensus_reason TEXT NOT NULL,

                final_action TEXT NOT NULL,
                risk_status TEXT NOT NULL,
                live_execution TEXT NOT NULL
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

        # ============================================================
        # STAGE 7.6.1 — CAPTURE LINKED DECISION ID
        # ============================================================

        decision_id = cursor.lastrowid

        # ============================================================
        # STAGE 7.3 — PERSIST MULTI-AI CONSENSUS AUDIT
        # ============================================================

        cursor.execute("""
            INSERT INTO ai_consensus_audit (
                timestamp,
                symbol,
                strategy_status,
                market_signal,
                groq_assessment,
                gemini_assessment,
                consensus_status,
                consensus_action,
                consensus_reason,
                final_action,
                risk_status,
                live_execution,
                decision_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            agent_state["market"]["symbol"],
            agent_state["validation"]["strategy_status"],
            agent_state["market"]["signal"],
            groq_assessment,
            gemini_assessment,
            multi_ai_consensus["status"],
            multi_ai_consensus["action"],
            multi_ai_consensus["reason"],
            final_action,
            risk_status,
            live_execution,
            decision_id
        ))

        consensus_id = cursor.lastrowid
        conn.commit()

        cursor.execute("""
            SELECT COUNT(*) FROM agent_decisions
        """)

        decision_count = cursor.fetchone()[0]
        conn.close()

        # STAGE 7.6.7.4 — VALIDATED 24H PAPER TRADE ACTIVATION
        # Only the FINAL guarded action may activate a paper trade.
        # No live execution is permitted.

        if final_action in {"PAPER_BUY", "PAPER_SELL"}:
            try:
                plan_snapshot = {
                    "symbol": symbol,
                    "current_price": current_price,
                    "completed_candle_only": True,
                    "future_data_included": False,
                    "live_execution": "BLOCKED",
                }

                groq_plan_check = validate_trade_plan(
                    groq_assessment,
                    plan_snapshot,
                )
                gemini_plan_check = validate_trade_plan(
                    gemini_assessment,
                    plan_snapshot,
                )

                if (
                    groq_plan_check.get("valid")
                    and gemini_plan_check.get("valid")
                ):
                    trade_plan_consensus = compare_trade_plans(
                        groq_assessment,
                        gemini_assessment,
                    )

                    expected_direction = (
                        "BUY"
                        if final_action == "PAPER_BUY"
                        else "SELL"
                    )

                    # ====================================================
                    # STAGE 7.6.10.1 — DIRECTIONAL PREDICTION PERSISTENCE
                    # ====================================================
                    #
                    # Persist the 24-hour directional prediction BEFORE
                    # detailed TP/SL plan consensus validation.
                    #
                    # This means a valid BUY/SELL prediction can be
                    # evaluated independently even when the detailed
                    # paper trade plan fails consensus validation.
                    #
                    # PAPER ONLY.
                    # LIVE EXECUTION REMAINS BLOCKED.
                    directional_prediction = (
                        persist_directional_prediction(
                            symbol=symbol,
                            direction=expected_direction,
                            prediction_price=current_price,
                            decision_id=decision_id,
                            consensus_id=consensus_id,
                        )
                    )

                    print(
                        "STAGE 7.6.10.1 DIRECTIONAL PREDICTION: "
                        f"{directional_prediction.get('status')} | "
                        f"ID={directional_prediction.get('id')} | "
                        f"{symbol} | "
                        f"{expected_direction} | "
                        f"PRICE={directional_prediction.get('prediction_price')} | "
                        f"EXPIRES={directional_prediction.get('expires_at')} | "
                        "LIVE_EXECUTION=BLOCKED"
                    )

                    if directional_prediction.get("duplicate"):
                        print(
                            "  Existing active directional prediction reused."
                        )

                    if (
                        trade_plan_consensus.get("status") == "AGREEMENT"
                        and trade_plan_consensus.get("direction")
                        == expected_direction
                    ):
                        paper_prediction = persist_consensus_paper_trade(
                            symbol=symbol,
                            consensus=trade_plan_consensus,
                            groq_plan_text=groq_assessment,
                            gemini_plan_text=gemini_assessment,
                            decision_id=decision_id,
                            consensus_id=consensus_id,
                        )

                        print(
                            "STAGE 7.6.7.4 PAPER TRADE: "
                            f"ACTIVE | ID={paper_prediction.get('id')} | "
                            f"{symbol} | "
                            f"{expected_direction} | "
                            f"EXPIRES={paper_prediction.get('expires_at')} | "
                            "LIVE_EXECUTION=BLOCKED"
                        )
                    else:
                        print(
                            "STAGE 7.6.7.4 PAPER TRADE: "
                            "NOT ACTIVATED — PLAN CONSENSUS FAILED"
                        )

                        print(
                            f"  CONSENSUS STATUS: "
                            f"{trade_plan_consensus.get('status')}"
                        )

                        print(
                            f"  CONSENSUS REASON: "
                            f"{trade_plan_consensus.get('reason')}"
                        )

                        groq_debug = trade_plan_consensus.get(
                            "groq", {}
                        )
                        gemini_debug = trade_plan_consensus.get(
                            "gemini", {}
                        )

                        print("\n  GROQ PLAN:")
                        print(
                            f"    Direction: "
                            f"{groq_debug.get('DIRECTION')}"
                        )
                        print(
                            f"    Entry: "
                            f"{groq_debug.get('ENTRY_LOW')} - "
                            f"{groq_debug.get('ENTRY_HIGH')}"
                        )
                        print(
                            f"    Stop: "
                            f"{groq_debug.get('STOP_LOSS')}"
                        )
                        print(
                            f"    TP1: "
                            f"{groq_debug.get('TP1')}"
                        )
                        print(
                            f"    TP2: "
                            f"{groq_debug.get('TP2')}"
                        )
                        print(
                            f"    TP3: "
                            f"{groq_debug.get('TP3')}"
                        )

                        print("\n  GEMINI PLAN:")
                        print(
                            f"    Direction: "
                            f"{gemini_debug.get('DIRECTION')}"
                        )
                        print(
                            f"    Entry: "
                            f"{gemini_debug.get('ENTRY_LOW')} - "
                            f"{gemini_debug.get('ENTRY_HIGH')}"
                        )
                        print(
                            f"    Stop: "
                            f"{gemini_debug.get('STOP_LOSS')}"
                        )
                        print(
                            f"    TP1: "
                            f"{gemini_debug.get('TP1')}"
                        )
                        print(
                            f"    TP2: "
                            f"{gemini_debug.get('TP2')}"
                        )
                        print(
                            f"    TP3: "
                            f"{gemini_debug.get('TP3')}"
                        )
                else:
                    print(
                        "STAGE 7.6.7.4 PAPER TRADE: "
                        "NOT ACTIVATED — PROVIDER PLAN VALIDATION FAILED"
                    )

                    if not groq_plan_check.get("valid"):
                        print(
                            "  GROQ PLAN ERROR: "
                            f"{groq_plan_check.get('reason')}"
                        )

                    if not gemini_plan_check.get("valid"):
                        print(
                            "  GEMINI PLAN ERROR: "
                            f"{gemini_plan_check.get('reason')}"
                        )

            except Exception as paper_plan_error:
                print(
                    "STAGE 7.6.7.4 PAPER TRADE ERROR: "
                    f"{paper_plan_error}"
                )


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
                timestamp, hist_symbol, hist_signal, hist_risk, hist_action = row
                print(
                    f"{timestamp} | {hist_symbol} | "
                    f"{hist_signal} | {hist_risk} | {hist_action}"
                )
        else:
            print("No previous agent decisions found.")

        print("=" * 60)
        print("✅ Stage 3.3 decision history completed.")

    except sqlite3.Error as e:
        print(f"❌ Decision history error: {e}")

    # ============================================================
    # STAGE 7.6.8.7 — STRUCTURED PIPELINE RESULT
    # ============================================================

    return {
        "symbol": symbol,
        "current_price": current_price,
        "strategy_status": status,
        "signal": signal,
        "risk_status": risk_status,
        "risk_reason": risk_reason,
        "final_action": final_action,
        "live_execution": live_execution,
        "ai_assessment": ai_assessment,
        "multi_ai_consensus": multi_ai_consensus,
        "paper_prediction": paper_prediction,
        "decision_id": decision_id,
        "consensus_id": consensus_id,
        "agent_state": agent_state,
    }


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

    # Weak out-of-sample evidence allows experimental PAPER testing
    # but is explicitly flagged for caution. Live execution remains blocked.
    if "OOS_EVIDENCE: WEAK" in assessment:
        risk_status = "WEAK_OOS"
        risk_reason = (
            "Out-of-sample evidence is weak. "
            "Paper trading allowed for experimental validation only."
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
    """Fetch the latest public Binance USDⓈ-M Futures price."""
    import requests

    symbol = str(symbol).strip().upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    response = requests.get(
        "https://fapi.binance.com/fapi/v1/ticker/price",
        params={"symbol": symbol},
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()
    return float(data["price"])




# ============================================================
# STAGE 7.6.8.5 — WEB INTELLIGENCE & EVIDENCE LAYER
# ============================================================
#
# Web evidence is ADVISORY ONLY.
# It can inform AI analysis but can never authorize execution,
# override deterministic strategy validation, risk gates,
# consensus guards, reliability guards, or live-execution policy.
#

import hashlib
import time
import urllib.parse
import xml.etree.ElementTree as ET


WEB_INFORMATION_CLASSES = {
    "MARKET_STRUCTURE",
    "DERIVATIVES",
    "ON_CHAIN",
    "NEWS_EVENTS",
    "MACRO",
    "REGULATORY",
    "PROJECT_FUNDAMENTALS",
    "EXCHANGE_INTELLIGENCE",
    "SOCIAL_SENTIMENT",
    "SECURITY_RISK",
    "TOKENOMICS",
    "CROSS_ASSET",
    "TECHNICAL",
    "HISTORICAL_EVIDENCE",
}


WEB_SOURCE_QUALITY = {
    "official": 1.00,
    "exchange": 0.95,
    "government": 0.95,
    "major_news": 0.85,
    "financial_news": 0.80,
    "aggregator": 0.65,
    "unknown": 0.40,
}


def ensure_web_evidence_table():
    """Create the persistent advisory web-evidence store."""

    with sqlite3.connect("sentinel.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS web_intelligence_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                information_class TEXT NOT NULL,
                source TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_quality REAL NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence REAL NOT NULL,
                importance REAL NOT NULL,
                freshness REAL NOT NULL,
                corroboration_count INTEGER NOT NULL DEFAULT 1,
                published_at TEXT,
                retrieved_at TEXT NOT NULL,
                evidence_hash TEXT NOT NULL UNIQUE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_evidence_symbol
            ON web_intelligence_evidence(symbol)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_evidence_class
            ON web_intelligence_evidence(information_class)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_evidence_retrieved
            ON web_intelligence_evidence(retrieved_at)
        """)



def _web_event_key(title, summary, information_class):
    """
    Build a deterministic topic/event fingerprint.

    Corroboration must compare substantially equivalent evidence,
    not merely symbol + direction + information class.
    """
    text = " ".join([
        str(title or ""),
        str(summary or ""),
        str(information_class or ""),
    ]).lower()

    # Remove URLs and punctuation.
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Conservative stop-word removal.
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from",
        "after", "before", "into", "over", "about", "will",
        "have", "has", "its", "are", "was", "were", "been",
        "being", "than", "then", "they", "their", "there",
        "what", "when", "where", "which", "while", "also",
        "just", "more", "most", "some", "could", "would",
        "should", "crypto", "cryptocurrency", "bitcoin",
    }

    tokens = [
        token
        for token in text.split()
        if len(token) >= 4 and token not in stopwords
    ]

    # Keep the strongest lexical signal while remaining deterministic.
    tokens = sorted(set(tokens))[:18]

    if not tokens:
        return hashlib.sha256(
            f"{information_class}|unknown".encode()
        ).hexdigest()[:24]

    canonical = (
        str(information_class or "UNKNOWN").upper()
        + "|"
        + "|".join(tokens)
    )

    return hashlib.sha256(
        canonical.encode()
    ).hexdigest()[:24]


def _web_effective_evidence_weight(item):
    """
    Calculate an advisory evidence weight.

    This is NOT a trading score and cannot authorize execution.
    """
    quality = float(item.get("source_quality", 0.0) or 0.0)
    freshness = float(item.get("freshness", 0.0) or 0.0)
    confidence = float(item.get("confidence", 0.0) or 0.0)
    importance = float(item.get("importance", 0.0) or 0.0)

    corroboration = int(
        item.get("corroboration_count", 1) or 1
    )

    # Diminishing returns prevent ten duplicate sources
    # from overpowering one high-quality source.
    corroboration_factor = min(
        1.0,
        0.55 + (0.15 * min(corroboration, 3))
    )

    return round(
        quality
        * freshness
        * confidence
        * importance
        * corroboration_factor,
        6,
    )


def _web_direction_conflict(directions):
    """
    Detect meaningful opposing directional evidence.

    NEUTRAL is ignored when determining directional conflict.
    """
    normalized = {
        str(direction or "").upper()
        for direction in directions
        if str(direction or "").upper() in {
            "BULLISH",
            "BEARISH",
        }
    }

    return "CONFLICT" if len(normalized) >= 2 else "CONSISTENT"


def ensure_web_evidence_corroboration_columns():
    """Migrate the web evidence table for publisher-level corroboration."""

    with sqlite3.connect("sentinel.db") as conn:
        cursor = conn.cursor()

        ensure_column(
            cursor,
            "web_intelligence_evidence",
            "publisher",
            "TEXT"
        )

        ensure_column(
            cursor,
            "web_intelligence_evidence",
            "source_domain",
            "TEXT"
        )

        ensure_column(
            cursor,
            "web_intelligence_evidence",
            "corroboration_strength",
            "TEXT"
        )

        ensure_column(
            cursor,
            "web_intelligence_evidence",
            "event_key",
            "TEXT"
        )

        ensure_column(
            cursor,
            "web_intelligence_evidence",
            "conflict_status",
            "TEXT"
        )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_evidence_domain
            ON web_intelligence_evidence(source_domain)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_evidence_publisher
            ON web_intelligence_evidence(publisher)
        """)

        conn.commit()


def _web_normalize_symbol(symbol):
    """Normalize a crypto symbol for web searches."""
    symbol = str(symbol or "").upper().strip()

    if symbol.endswith("USDT"):
        base = symbol[:-4]
    else:
        base = symbol

    return base


def _web_classify_information(title, summary):
    """Assign one of the controlled information classes."""

    text = f"{title} {summary}".lower()

    if any(x in text for x in (
        "hack", "exploit", "attack", "breach", "stolen",
        "vulnerability", "security", "drain"
    )):
        return "SECURITY_RISK"

    if any(x in text for x in (
        "sec", "regulator", "regulation", "lawsuit", "court",
        "legal", "compliance", "ban", "sanction"
    )):
        return "REGULATORY"

    if any(x in text for x in (
        "binance", "listing", "delisting", "exchange",
        "deposit", "withdrawal", "trading halt"
    )):
        return "EXCHANGE_INTELLIGENCE"

    if any(x in text for x in (
        "token unlock", "unlock", "vesting", "supply",
        "inflation", "emission", "burn", "tokenomics"
    )):
        return "TOKENOMICS"

    if any(x in text for x in (
        "fed", "federal reserve", "interest rate", "inflation",
        "cpi", "ppi", "jobs report", "unemployment", "treasury",
        "recession", "gdp"
    )):
        return "MACRO"

    if any(x in text for x in (
        "bitcoin dominance", "btc dominance", "ethereum",
        "correlation", "risk-on", "risk-off", "nasdaq",
        "s&p 500", "gold", "dollar"
    )):
        return "CROSS_ASSET"

    if any(x in text for x in (
        "futures", "perpetual", "funding rate", "open interest",
        "liquidation", "leverage", "basis"
    )):
        return "DERIVATIVES"

    if any(x in text for x in (
        "on-chain", "onchain", "wallet", "whale", "address",
        "exchange inflow", "exchange outflow", "holders"
    )):
        return "ON_CHAIN"

    if any(x in text for x in (
        "upgrade", "mainnet", "testnet", "roadmap", "protocol",
        "developer", "development", "partnership"
    )):
        return "PROJECT_FUNDAMENTALS"

    if any(x in text for x in (
        "price", "rsi", "ema", "moving average", "breakout",
        "support", "resistance", "technical"
    )):
        return "TECHNICAL"

    if any(x in text for x in (
        "sentiment", "social", "community", "twitter", "reddit"
    )):
        return "SOCIAL_SENTIMENT"

    return "NEWS_EVENTS"


def _web_classify_direction(title, summary):
    """Classify evidence direction without making a trading decision."""

    text = f"{title} {summary}".lower()

    bullish_terms = (
        "surge", "rally", "bullish", "breakout", "approval",
        "approved", "partnership", "adoption", "inflow",
        "launch", "growth", "record high", "positive",
        "integration", "upgrade", "expands", "gains"
    )

    bearish_terms = (
        "fall", "drop", "crash", "bearish", "breakdown",
        "hack", "exploit", "lawsuit", "ban", "outflow",
        "liquidation", "loss", "negative", "delist",
        "shutdown", "decline", "vulnerability"
    )

    bullish = sum(1 for term in bullish_terms if term in text)
    bearish = sum(1 for term in bearish_terms if term in text)

    if bullish > bearish:
        return "BULLISH"

    if bearish > bullish:
        return "BEARISH"

    return "NEUTRAL"


def _web_freshness(published_at):
    """Return a 0-1 freshness score."""

    if not published_at:
        return 0.50

    try:
        value = published_at.replace("Z", "+00:00")

        published = datetime.fromisoformat(value)

        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        age_hours = max(
            0.0,
            (
                datetime.now(timezone.utc) - published.astimezone(timezone.utc)
            ).total_seconds() / 3600.0
        )

        if age_hours <= 6:
            return 1.00
        if age_hours <= 24:
            return 0.90
        if age_hours <= 72:
            return 0.70
        if age_hours <= 168:
            return 0.50

        return 0.25

    except Exception:
        return 0.50


def _web_source_type(source_url):
    """
    Classify a web source using its actual publisher domain.

    This registry is deliberately conservative. Source classification
    affects evidence quality only; it never authorizes execution.
    """
    try:
        parsed = urllib.parse.urlparse(str(source_url or ""))

        host = parsed.netloc.lower()
        host = host.split("@")[-1].split(":")[0]

        if host.startswith("www."):
            host = host[4:]

        if not host:
            return "unknown"

        # --------------------------------------------------------
        # Official project / protocol sources
        # --------------------------------------------------------
        official_domains = {
            "ethereum.org",
            "ethereum.foundation",
            "solana.com",
            "cardano.org",
            "bnbchain.org",
            "binance.com",
            "ripple.com",
            "xrpl.org",
            "avalanche.com",
            "avax.network",
            "chain.link",
            "polygon.technology",
            "arbitrum.io",
            "optimism.io",
            "near.org",
            "aptosfoundation.org",
            "sui.io",
        }

        if host in official_domains or any(
            host.endswith("." + domain)
            for domain in official_domains
        ):
            return "official"

        # --------------------------------------------------------
        # Exchanges
        # --------------------------------------------------------
        exchange_domains = {
            "binance.com",
            "coinbase.com",
            "kraken.com",
            "okx.com",
            "bybit.com",
            "kucoin.com",
            "bitget.com",
            "gate.io",
            "mexc.com",
            "crypto.com",
        }

        if host in exchange_domains or any(
            host.endswith("." + domain)
            for domain in exchange_domains
        ):
            return "exchange"

        # --------------------------------------------------------
        # Government / regulatory
        # --------------------------------------------------------
        government_domains = {
            "sec.gov",
            "cftc.gov",
            "federalreserve.gov",
            "treasury.gov",
            "justice.gov",
            "ftc.gov",
            "gov.uk",
            "europa.eu",
        }

        if host in government_domains or any(
            host.endswith("." + domain)
            for domain in government_domains
        ):
            return "government"

        if host.endswith(".gov") or host.endswith(".gov.uk"):
            return "government"

        # --------------------------------------------------------
        # Major news
        # --------------------------------------------------------
        major_news_domains = {
            "reuters.com",
            "bloomberg.com",
            "coindesk.com",
            "cointelegraph.com",
            "theblock.co",
            "wsj.com",
            "ft.com",
            "forbes.com",
            "fortune.com",
        }

        if host in major_news_domains or any(
            host.endswith("." + domain)
            for domain in major_news_domains
        ):
            return "major_news"

        # --------------------------------------------------------
        # Financial / business news
        # --------------------------------------------------------
        financial_news_domains = {
            "cnbc.com",
            "marketwatch.com",
            "finance.yahoo.com",
            "yahoo.com",
            "businessinsider.com",
            "barrons.com",
            "investopedia.com",
        }

        if host in financial_news_domains or any(
            host.endswith("." + domain)
            for domain in financial_news_domains
        ):
            return "financial_news"

        # --------------------------------------------------------
        # Crypto / specialist publications
        # --------------------------------------------------------
        crypto_news_domains = {
            "cryptoslate.com",
            "decrypt.co",
            "bitcoin.com",
            "blockworks.co",
            "cryptonews.com",
            "beincrypto.com",
            "thedefiant.io",
            "dlnews.com",
        }

        if host in crypto_news_domains or any(
            host.endswith("." + domain)
            for domain in crypto_news_domains
        ):
            return "major_news"

        # --------------------------------------------------------
        # Research / data aggregators
        # --------------------------------------------------------
        aggregator_domains = {
            "coinmarketcap.com",
            "coingecko.com",
            "messari.io",
            "glassnode.com",
            "defillama.com",
            "tradingview.com",
        }

        if host in aggregator_domains or any(
            host.endswith("." + domain)
            for domain in aggregator_domains
        ):
            return "aggregator"

        return "unknown"

    except Exception:
        return "unknown"


def _web_evidence_hash(symbol, title, source, published_at):
    raw = "|".join([
        symbol,
        title.strip().lower(),
        source.strip().lower(),
        str(published_at or "")
    ])

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _web_google_news_url(symbol):
    """Build a Google News RSS search URL."""

    base = _web_normalize_symbol(symbol)

    query = urllib.parse.quote(
        f'"{base}" crypto'
    )

    return (
        "https://news.google.com/rss/search"
        f"?q={query}"
        "&hl=en-US"
        "&gl=US"
        "&ceid=US:en"
    )


def _web_extract_publisher(source_url, publisher=None):
    """Normalize the publisher name for advisory evidence records."""
    publisher_text = str(publisher or "").strip()

    if publisher_text:
        publisher_text = re.sub(r"\s+", " ", publisher_text)
        return publisher_text[:200]

    try:
        host = urllib.parse.urlparse(
            str(source_url or "")
        ).netloc.lower()

        host = host.split("@")[-1].split(":")[0]

        if host.startswith("www."):
            host = host[4:]

        return host[:200] if host else "unknown"

    except Exception:
        return "unknown"


def _web_extract_source_domain(source_url, source_domain=None):
    """Extract and normalize the actual publisher domain."""
    if source_domain:
        domain = str(source_domain).lower().strip()
    else:
        try:
            domain = urllib.parse.urlparse(
                str(source_url or "")
            ).netloc.lower()
        except Exception:
            domain = ""

    domain = domain.split("@")[-1].split(":")[0]

    if domain.startswith("www."):
        domain = domain[4:]

    if domain == "news.google.com":
        return "unknown"

    return domain[:200] if domain else "unknown"


def fetch_web_news(symbol, limit=12):
    """
    Fetch recent public crypto-news evidence through Google News RSS.

    This is collection only. No trading decision is made here.
    """

    symbol = _web_normalize_symbol(symbol)

    if not symbol:
        return []

    url = _web_google_news_url(symbol)

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Hex-Sentinel/7.6.8.5"
            },
            timeout=15,
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)

    except requests.exceptions.Timeout:
        print("⚠️ WEB INTELLIGENCE | Google News timeout")
        return []

    except requests.exceptions.RequestException as e:
        print(f"⚠️ WEB INTELLIGENCE | Google News request failure: {e}")
        return []

    except ET.ParseError as e:
        print(f"⚠️ WEB INTELLIGENCE | RSS parse failure: {e}")
        return []

    evidence = []

    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        published_at = (item.findtext("pubDate") or "").strip()

        if not title or not link:
            continue

        # RSS publication timestamps are not always ISO formatted.
        normalized_published = None

        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(published_at)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            normalized_published = parsed.astimezone(
                timezone.utc
            ).isoformat()

        except Exception:
            normalized_published = None

        # Google News RSS exposes the actual publisher separately
        # from the Google News redirect URL.
        source_element = item.find("source")

        publisher = ""
        publisher_url = ""

        if source_element is not None:
            publisher = (source_element.text or "").strip()
            publisher_url = (
                source_element.attrib.get("url", "") or ""
            ).strip()

        # Fallback when the RSS source element is missing.
        if not publisher:
            parts = title.rsplit(" - ", 1)
            if len(parts) == 2 and parts[1].strip():
                publisher = parts[1].strip()

        source_domain = _web_extract_source_domain(
            publisher_url or link
        )

        publisher = _web_extract_publisher(
            publisher_url or link,
            publisher
        )

        # Classify the actual publisher, not news.google.com.
        source_type = _web_source_type(
            publisher_url or link
        )
        source_quality = WEB_SOURCE_QUALITY.get(
            source_type,
            WEB_SOURCE_QUALITY["unknown"]
        )

        information_class = _web_classify_information(
            title,
            description
        )

        direction = _web_classify_direction(
            title,
            description
        )

        freshness = _web_freshness(normalized_published)

        confidence = min(
            0.95,
            max(
                0.25,
                (source_quality * 0.55) +
                (freshness * 0.45)
            )
        )

        importance = min(
            1.00,
            max(
                0.25,
                confidence
            )
        )

        clean_summary = re.sub(
            r"<[^>]+>",
            " ",
            description
        )

        clean_summary = re.sub(
            r"\s+",
            " ",
            clean_summary
        ).strip()

        evidence.append({
            "symbol": symbol,
            "information_class": information_class,
            "source": link,
            "source_type": source_type,
            "source_quality": source_quality,
            "publisher": publisher,
            "source_domain": source_domain,
            "title": title,
            "summary": clean_summary[:1000],
            "direction": direction,
            "confidence": round(confidence, 4),
            "importance": round(importance, 4),
            "freshness": round(freshness, 4),
            "published_at": normalized_published,
        })

    return evidence


def persist_web_evidence(evidence):
    """Persist normalized advisory evidence with event fingerprints."""
    ensure_web_evidence_table()
    ensure_web_evidence_corroboration_columns()

    if not evidence:
        return {
            "status": "NO_EVIDENCE",
            "records_added": 0,
            "live_execution": "BLOCKED",
        }

    added = 0

    with sqlite3.connect("sentinel.db") as conn:
        cursor = conn.cursor()

        for item in evidence:
            evidence_hash = _web_evidence_hash(
                item["symbol"],
                item["title"],
                item["source"],
                item.get("published_at"),
            )

            event_key = _web_event_key(
                item.get("title"),
                item.get("summary"),
                item.get("information_class"),
            )

            try:
                cursor.execute("""
                    INSERT INTO web_intelligence_evidence (
                        symbol,
                        information_class,
                        source,
                        source_type,
                        source_quality,
                        title,
                        summary,
                        direction,
                        confidence,
                        importance,
                        freshness,
                        corroboration_count,
                        publisher,
                        source_domain,
                        corroboration_strength,
                        event_key,
                        conflict_status,
                        published_at,
                        retrieved_at,
                        evidence_hash
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        1, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, (
                    item["symbol"],
                    item["information_class"],
                    item["source"],
                    item["source_type"],
                    item["source_quality"],
                    item["title"],
                    item["summary"],
                    item["direction"],
                    item["confidence"],
                    item["importance"],
                    item["freshness"],
                    item.get("publisher", "unknown"),
                    item.get("source_domain", "unknown"),
                    "LOW",
                    event_key,
                    "CONSISTENT",
                    item.get("published_at"),
                    datetime.now(timezone.utc).isoformat(),
                    evidence_hash,
                ))

                added += 1

            except sqlite3.IntegrityError:
                pass

        conn.commit()

    return {
        "status": "RECORDED",
        "records_added": added,
        "records_seen": len(evidence),
        "live_execution": "BLOCKED",
    }



def update_web_corroboration(symbol):
    """
    Calculate corroboration for equivalent events only.

    Independent publisher domains support the SAME event/topic.
    Unrelated articles must never inflate corroboration.

    Corroboration is advisory evidence only.
    """
    symbol = _web_normalize_symbol(symbol)

    ensure_web_evidence_table()
    ensure_web_evidence_corroboration_columns()

    with sqlite3.connect("sentinel.db") as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                information_class,
                title,
                summary,
                direction,
                source_domain
            FROM web_intelligence_evidence
            WHERE symbol = ?
              AND retrieved_at >= datetime('now', '-7 days')
        """, (symbol,))

        rows = cursor.fetchall()

        # Backfill event keys for historical rows.
        for (
            row_id,
            information_class,
            title,
            summary,
            direction,
            source_domain,
        ) in rows:
            event_key = _web_event_key(
                title,
                summary,
                information_class,
            )

            cursor.execute("""
                UPDATE web_intelligence_evidence
                SET event_key = ?
                WHERE id = ?
            """, (
                event_key,
                row_id,
            ))

        # Group equivalent evidence by event and information class.
        cursor.execute("""
            SELECT
                id,
                information_class,
                direction,
                event_key
            FROM web_intelligence_evidence
            WHERE symbol = ?
              AND retrieved_at >= datetime('now', '-7 days')
              AND event_key IS NOT NULL
        """, (symbol,))

        grouped_rows = cursor.fetchall()

        for (
            row_id,
            information_class,
            direction,
            event_key,
        ) in grouped_rows:

            cursor.execute("""
                SELECT
                    COUNT(DISTINCT source_domain)
                FROM web_intelligence_evidence
                WHERE symbol = ?
                  AND information_class = ?
                  AND event_key = ?
                  AND source_domain IS NOT NULL
                  AND source_domain != ''
                  AND source_domain != 'unknown'
                  AND retrieved_at >= datetime('now', '-7 days')
            """, (
                symbol,
                information_class,
                event_key,
            ))

            count = cursor.fetchone()[0] or 1

            cursor.execute("""
                SELECT direction
                FROM web_intelligence_evidence
                WHERE symbol = ?
                  AND information_class = ?
                  AND event_key = ?
                  AND retrieved_at >= datetime('now', '-7 days')
            """, (
                symbol,
                information_class,
                event_key,
            ))

            directions = [
                row[0]
                for row in cursor.fetchall()
            ]

            conflict_status = _web_direction_conflict(
                directions
            )

            if conflict_status == "CONFLICT":
                strength = "CONFLICT"
            elif count >= 3:
                strength = "STRONG"
            elif count == 2:
                strength = "MODERATE"
            else:
                strength = "LOW"

            cursor.execute("""
                UPDATE web_intelligence_evidence
                SET
                    corroboration_count = ?,
                    corroboration_strength = ?,
                    conflict_status = ?
                WHERE id = ?
            """, (
                count,
                strength,
                conflict_status,
                row_id,
            ))

        conn.commit()



def build_web_evidence_package(symbol, limit=10):
    """
    Build an advisory evidence package.

    Evidence is grouped conceptually by event_key. Freshness,
    source quality and conflicts are explicitly exposed to AI.
    """
    symbol = _web_normalize_symbol(symbol)

    ensure_web_evidence_table()
    ensure_web_evidence_corroboration_columns()

    update_web_corroboration(symbol)

    with sqlite3.connect("sentinel.db") as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                information_class,
                source_type,
                publisher,
                source_domain,
                title,
                summary,
                direction,
                confidence,
                importance,
                freshness,
                corroboration_count,
                corroboration_strength,
                event_key,
                conflict_status,
                published_at,
                retrieved_at,
                source_quality
            FROM web_intelligence_evidence
            WHERE symbol = ?
              AND retrieved_at >= datetime('now', '-72 hours')
            ORDER BY
                (
                    source_quality
                    * freshness
                    * confidence
                    * importance
                ) DESC,
                corroboration_count DESC,
                freshness DESC
            LIMIT ?
        """, (
            symbol,
            limit,
        ))

        rows = cursor.fetchall()

    if not rows:
        return {
            "symbol": symbol,
            "status": "NO_RECENT_EVIDENCE",
            "evidence": [],
            "evidence_count": 0,
            "live_execution": "BLOCKED",
        }

    package = []

    for row in rows:
        (
            information_class,
            source_type,
            publisher,
            source_domain,
            title,
            summary,
            direction,
            confidence,
            importance,
            freshness,
            corroboration_count,
            corroboration_strength,
            event_key,
            conflict_status,
            published_at,
            retrieved_at,
            source_quality,
        ) = row

        item = {
            "information_class": information_class,
            "source_type": source_type,
            "publisher": publisher or "unknown",
            "source_domain": source_domain or "unknown",
            "title": title,
            "summary": summary,
            "direction": direction,
            "confidence": float(confidence or 0.0),
            "importance": float(importance or 0.0),
            "freshness": float(freshness or 0.0),
            "source_quality": float(source_quality or 0.0),
            "corroboration_count": int(
                corroboration_count or 1
            ),
            "corroboration_strength": (
                corroboration_strength or "LOW"
            ),
            "event_key": event_key or "unknown",
            "conflict_status": (
                conflict_status or "CONSISTENT"
            ),
            "published_at": published_at,
            "retrieved_at": retrieved_at,
        }

        item["effective_weight"] = (
            _web_effective_evidence_weight(item)
        )

        package.append(item)

    conflict_count = sum(
        1
        for item in package
        if item["conflict_status"] == "CONFLICT"
    )

    return {
        "symbol": symbol,
        "status": (
            "AVAILABLE"
            if package
            else "NO_RECENT_EVIDENCE"
        ),
        "evidence": package,
        "evidence_count": len(package),
        "conflict_count": conflict_count,
        "analytics_scope": "WEB_ADVISORY_ONLY",
        "live_execution": "BLOCKED",
    }



def collect_web_intelligence(symbol, limit=12):
    """
    Collect, persist and package recent web intelligence.

    Failure of this layer never creates a trading signal.
    """

    symbol = _web_normalize_symbol(symbol)

    try:
        evidence = fetch_web_news(symbol, limit=limit)

        persisted = persist_web_evidence(evidence)

        if evidence:
            update_web_corroboration(symbol)

        package = build_web_evidence_package(
            symbol,
            limit=min(limit, 10)
        )

        return {
            "status": package["status"],
            "symbol": symbol,
            "fetched": len(evidence),
            "persisted": persisted.get("records_added", 0),
            "package": package,
            "live_execution": "BLOCKED",
        }

    except Exception as e:
        print(f"⚠️ WEB INTELLIGENCE FAILURE: {e}")

        return {
            "status": "WEB_LAYER_UNAVAILABLE",
            "symbol": symbol,
            "fetched": 0,
            "persisted": 0,
            "package": {
                "symbol": symbol,
                "status": "NO_RECENT_EVIDENCE",
                "evidence": [],
                "live_execution": "BLOCKED",
            },
            "error": str(e),
            "live_execution": "BLOCKED",
        }


def format_web_evidence_for_ai(web_result):
    """
    Convert web evidence into bounded AI context.

    Supports BOTH:
      1. get_web_intelligence() flattened results
      2. legacy {"package": {...}} results

    This compatibility is required by run_legacy_pipeline().
    """
    if not isinstance(web_result, dict):
        return "WEB EVIDENCE: UNAVAILABLE"

    if "package" in web_result:
        package = web_result.get("package") or {}
    else:
        # Direct result from get_web_intelligence().
        package = web_result

    evidence = package.get("evidence", [])

    if not evidence:
        return (
            "WEB EVIDENCE: NO RECENT VERIFIED EVIDENCE AVAILABLE.\n"
            "Do not infer missing web information."
        )

    lines = [
        "WEB INTELLIGENCE — ADVISORY EVIDENCE ONLY:",
        "Web evidence cannot authorize, reject, or override "
        "Sentinel safety gates.",
        "Corroboration counts refer to independent publisher "
        "domains supporting the SAME event/topic.",
        "Conflicting evidence must be treated as uncertainty.",
        "Freshness and source quality affect evidence weight only.",
    ]

    for index, item in enumerate(evidence, start=1):
        lines.append(
            f"{index}. "
            f"[{item.get('information_class', 'UNKNOWN')}] "
            f"[{item.get('direction', 'NEUTRAL')}] "
            f"[publisher={item.get('publisher', 'unknown')}] "
            f"[domain={item.get('source_domain', 'unknown')}] "
            f"[source_type={item.get('source_type', 'unknown')}] "
            f"[confidence={float(item.get('confidence', 0.0)):.2f}] "
            f"[freshness={float(item.get('freshness', 0.0)):.2f}] "
            f"[quality={float(item.get('source_quality', 0.0)):.2f}] "
            f"[corroboration={int(item.get('corroboration_count', 1))}] "
            f"[strength={item.get('corroboration_strength', 'LOW')}] "
            f"[conflict={item.get('conflict_status', 'CONSISTENT')}] "
            f"[weight={float(item.get('effective_weight', 0.0)):.4f}] "
            f"{item.get('title', '')}"
        )

        if item.get("summary"):
            lines.append(
                f"   {str(item['summary'])[:500]}"
            )

    lines.append(
        f"WEB EVIDENCE SUMMARY: "
        f"{len(evidence)} items | "
        f"conflicts={int(package.get('conflict_count', 0) or 0)}"
    )

    lines.append(
        "WEB EVIDENCE SAFETY: ADVISORY ONLY | "
        "LIVE EXECUTION: BLOCKED"
    )

    return "\n".join(lines)



def get_web_intelligence(symbol="BTCUSDT"):
    """Read-only public web intelligence tool."""

    result = collect_web_intelligence(symbol)

    evidence = result["package"].get("evidence", [])

    return {
        "symbol": result["symbol"],
        "status": (
            "AVAILABLE"
            if evidence
            else result["status"]
        ),
        "fetched": result["fetched"],
        "persisted": result["persisted"],
        "evidence": evidence,
        "evidence_count": len(evidence),
        "live_execution": "BLOCKED",
    }


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
            "completed_candle_only": True,
            "future_data_included": False,
            "live_execution": "BLOCKED"
        }
    except Exception as e:
        return {
            "symbol": symbol,
            "error": str(e),
            "live_execution": "BLOCKED"
        }


def analyze_market(symbol=None):
    """Analyze a requested Binance USDⓈ-M Futures symbol."""

    if not symbol:
        return {
            "symbol": None,
            "status": "NO_SYMBOL",
            "signal": "HOLD",
            "risk_status": "BLOCKED",
            "final_action": "PAPER_HOLD",
            "reason": "Specify a symbol: analyze <coin>",
            "live_execution": "BLOCKED",
        }

    symbol = str(symbol).strip().upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    result = deep_validate_symbol(symbol)

    if result.get("status") == "ERROR":
        return {
            **result,
            "live_execution": "BLOCKED",
        }

    try:
        current_price = get_current_price(symbol)
    except Exception as exc:
        current_price = None
        result["price_error"] = str(exc)

    if result.get("status") != "APPROVED":
        risk_status = "BLOCKED"
        final_action = "PAPER_HOLD"
    else:
        risk_status = "CAUTION"

        if result.get("signal") == "BUY":
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
        "live_execution": "BLOCKED",
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
    """Return the current Hex Sentinel safety and execution state.

    Pulls live values from the strategy lifecycle table, the paper
    trade table, and the API cache instead of returning fixed
    placeholder text.
    """

    status_payload = {
        "agent": "Hex Sentinel",
        "mode": "PAPER/BACKTEST ONLY",
        "final_action": "NO_LIVE_EXECUTION",
        "live_execution": "BLOCKED",
        "registered_tools": len(agent_tools),
    }

    # Strategy status — latest row in the lifecycle table, if any.
    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT strategy_name, version, status FROM strategy_versions "
            "ORDER BY updated_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            status_payload["strategy_status"] = row[2]
            status_payload["strategy_name"] = f"{row[0]} {row[1]}"
        else:
            status_payload["strategy_status"] = "NO_STRATEGY_REGISTERED"
    except Exception as status_error:
        status_payload["strategy_status"] = f"UNKNOWN ({status_error})"

    # Risk status — how many paper predictions are still being tracked.
    try:
        conn = sqlite3.connect("sentinel.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM paper_trade_plans "
            "WHERE status = 'PREDICTION_ACTIVE'"
        )
        active_count = cursor.fetchone()[0] or 0
        conn.close()

        status_payload["active_predictions"] = active_count
        status_payload["risk_status"] = "MONITORING" if active_count else "IDLE"
    except Exception:
        status_payload["active_predictions"] = "UNKNOWN"
        status_payload["risk_status"] = "UNKNOWN"

    # API cache / rate-limit protection health.
    try:
        status_payload["api_cache"] = hex_api_cache_status()
    except Exception:
        status_payload["api_cache"] = "UNAVAILABLE"

    return status_payload

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
    "get_web_intelligence": {
        "description": "Collect recent public web evidence and classify it into controlled information classes.",
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
agent_tools["get_web_intelligence"] = get_web_intelligence

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

    # "scan" already had a full deterministic match in deterministic_route()
    # below, but it still had to go through a Groq round-trip first because
    # it wasn't in this bare-command list. Note: normalize_command() rewrites
    # a bare "scan" into "scan_binance" via its alias table before this
    # function ever sees it, so both forms are matched here. Same fix
    # applied to the new cache commands so they never leave the machine.
    if request_lower in ["scan", "scanner", "futures scan", "scan_binance"]:
        return execute_tool("scan_binance")

    if request_lower in ["cache", "cache status"]:
        return execute_tool("cache_status")

    if request_lower in ["cache clear", "clear cache"]:
        return execute_tool("cache_clear")

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
    """Search Binance USDT symbols across both Spot and USDⓈ-M Futures."""

    query = str(query).strip().upper()

    if not query:
        return []

    spot_api = "https://api.binance.com"
    futures_api = "https://fapi.binance.com"

    results = {}

    # --------------------------------------------------------
    # SPOT SEARCH
    # --------------------------------------------------------

    try:
        response = requests.get(
            f"{spot_api}/api/v3/exchangeInfo",
            timeout=10,
        )

        response.raise_for_status()

        symbols = response.json().get(
            "symbols",
            [],
        )

        for item in symbols:

            if (
                item.get("status") != "TRADING"
                or item.get("quoteAsset") != "USDT"
                or item.get("isSpotTradingAllowed") is not True
            ):
                continue

            symbol = item.get("symbol", "").upper()
            base_asset = item.get(
                "baseAsset",
                "",
            ).upper()

            if (
                query in symbol
                or query in base_asset
            ):
                key = symbol

                results.setdefault(
                    key,
                    {
                        "symbol": symbol,
                        "base_asset": base_asset,
                        "spot": False,
                        "futures": False,
                    },
                )

                results[key]["spot"] = True

    except Exception as exc:
        print(
            f"⚠️ Spot search unavailable: {exc}"
        )

    # --------------------------------------------------------
    # FUTURES SEARCH
    # --------------------------------------------------------

    try:
        response = requests.get(
            f"{futures_api}/fapi/v1/exchangeInfo",
            timeout=10,
        )

        response.raise_for_status()

        symbols = response.json().get(
            "symbols",
            [],
        )

        for item in symbols:

            if (
                item.get("status") != "TRADING"
                or item.get("quoteAsset") != "USDT"
            ):
                continue

            symbol = item.get("symbol", "").upper()
            base_asset = item.get(
                "baseAsset",
                "",
            ).upper()

            if (
                query in symbol
                or query in base_asset
            ):
                key = symbol

                results.setdefault(
                    key,
                    {
                        "symbol": symbol,
                        "base_asset": base_asset,
                        "spot": False,
                        "futures": False,
                    },
                )

                results[key]["futures"] = True

    except Exception as exc:
        print(
            f"⚠️ Futures search unavailable: {exc}"
        )

    ranked = list(results.values())

    ranked.sort(
        key=lambda item: (
            item["base_asset"] != query,
            item["symbol"] != query + "USDT",
            item["symbol"],
        )
    )

    return ranked[:30]



# ============================================================
# HEX SENTINEL — BINANCE SPOT MARKET SCANNER
# ============================================================

HEX_SPOT_API = "https://api.binance.com"






# ============================================================
# FUTURES 24H GAINERS / LOSERS
# ============================================================





# ============================================================
# HEX SENTINEL — BINANCE SPOT MARKET SCANNER
# ============================================================

HEX_SPOT_API = "https://api.binance.com"


def scan_spot_one_symbol(symbol):
    """Read-only Spot technical scan for one USDT symbol."""

    try:

        response = requests.get(
            f"{HEX_SPOT_API}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": "1h",
                "limit": 100,
            },
            timeout=10,
        )

        response.raise_for_status()

        candles = response.json()

        closes = [
            float(candle[4])
            for candle in candles
        ]

        if len(closes) < 50:
            return None

        def ema(values, period):

            multiplier = 2 / (period + 1)

            value = sum(values[:period]) / period

            for price in values[period:]:
                value = (
                    price * multiplier
                    + value * (1 - multiplier)
                )

            return value

        ema20 = ema(closes[-60:], 20)
        ema50 = ema(closes[-60:], 50)

        gains = []
        losses = []

        for i in range(
            len(closes) - 14,
            len(closes),
        ):

            change = closes[i] - closes[i - 1]

            if change >= 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (
                100 / (1 + rs)
            )

        trend_strength = (
            abs(ema20 - ema50)
            / ema50
            * 100
        ) if ema50 else 0.0

        signal = (
            "BUY"
            if ema20 > ema50 and rsi >= 50
            else "SELL"
        )

        return {
            "symbol": symbol,
            "price": closes[-1],
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "trend_strength": trend_strength,
            "signal": signal,
            "market_type": "SPOT",
        }

    except Exception:
        return None


def scan_spot_market(limit=50):
    """Scan active Binance Spot USDT markets."""

    try:

        response = requests.get(
            f"{HEX_SPOT_API}/api/v3/exchangeInfo",
            timeout=10,
        )

        response.raise_for_status()

        symbols = []

        for item in response.json().get(
            "symbols",
            [],
        ):

            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get(
                    "isSpotTradingAllowed"
                ) is True
            ):

                symbol = item.get(
                    "symbol",
                    "",
                )

                base_asset = item.get(
                    "baseAsset",
                    "",
                ).upper()

                excluded_base_assets = {
                    "USDT",
                    "USDC",
                    "USDP",
                    "TUSD",
                    "FDUSD",
                    "DAI",
                    "BUSD",
                    "RLUSD",
                    "USD1",
                    "PYUSD",
                    "USDD",
                    "EURI",
                }

                if (
                    symbol.endswith("USDT")
                    and base_asset not in excluded_base_assets
                ):
                    symbols.append(symbol)

    except Exception as exc:
        return {
            "error": str(exc),
            "universe": 0,
            "scanned": 0,
            "top_buys": [],
            "top_sells": [],
            "market_type": "SPOT",
        }

    # ============================================================
    # ACTIVE / LIQUID MARKET SELECTION
    # ============================================================

    try:
        ticker_response = requests.get(
            f"{HEX_SPOT_API}/api/v3/ticker/24hr",
            timeout=10,
        )

        ticker_response.raise_for_status()

        ticker_data = ticker_response.json()

        allowed_symbols = set(symbols)
        ranked_symbols = []

        for ticker in ticker_data:
            symbol = ticker.get("symbol", "")

            if symbol not in allowed_symbols:
                continue

            try:
                quote_volume = float(
                    ticker.get("quoteVolume", 0)
                )
            except (
                TypeError,
                ValueError,
            ):
                quote_volume = 0

            ranked_symbols.append(
                (
                    quote_volume,
                    symbol,
                )
            )

        ranked_symbols.sort(reverse=True)

        scan_symbols = [
            symbol
            for _volume, symbol
            in ranked_symbols[:limit]
        ]

    except Exception:
        # Safe fallback if bulk ticker data fails.
        scan_symbols = symbols[:limit]

    results = []

    with ThreadPoolExecutor(
        max_workers=min(
            SCAN_WORKERS,
            8,
        )
    ) as executor:

        futures = [
            executor.submit(
                scan_spot_one_symbol,
                symbol,
            )
            for symbol in scan_symbols
        ]

        for future in as_completed(futures):

            try:
                result = future.result()
            except Exception:
                result = None

            if result:
                results.append(result)

    buys = sorted(
        [
            item
            for item in results
            if item["signal"] == "BUY"
        ],
        key=lambda item: item[
            "trend_strength"
        ],
        reverse=True,
    )

    sells = sorted(
        [
            item
            for item in results
            if item["signal"] == "SELL"
        ],
        key=lambda item: item[
            "trend_strength"
        ],
        reverse=True,
    )

    return {
        "universe": len(symbols),
        "scanned": len(results),
        "top_buys": buys[:10],
        "top_sells": sells[:10],
        "market_type": "BINANCE_SPOT",
        "live_execution": "BLOCKED",
    }


# ============================================================
# FUTURES 24H GAINERS / LOSERS
# ============================================================

def get_futures_movers(limit=10):

    response = requests.get(
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    items = []

    for item in data:

        symbol = item.get(
            "symbol",
            "",
        )

        if not symbol.endswith("USDT"):
            continue

        try:

            change = float(
                item.get(
                    "priceChangePercent",
                    0,
                )
            )

            last_price = float(
                item.get(
                    "lastPrice",
                    0,
                )
            )

            quote_volume = float(
                item.get(
                    "quoteVolume",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        items.append(
            {
                "symbol": symbol,
                "price": last_price,
                "change_pct": change,
                "quote_volume": quote_volume,
                "market_type": "BINANCE_USDS_M_FUTURES",
            }
        )

    gainers = sorted(
        items,
        key=lambda item: item[
            "change_pct"
        ],
        reverse=True,
    )[:limit]

    losers = sorted(
        items,
        key=lambda item: item[
            "change_pct"
        ],
    )[:limit]

    return {
        "universe": len(items),
        "gainers": gainers,
        "losers": losers,
        "market_type": "BINANCE_USDS_M_FUTURES",
        "live_execution": "BLOCKED",
    }


def market_menu():
    """Interactive Spot + Futures market browser."""

    print("\n" + "=" * 60)
    print("📊 HEX SENTINEL — MARKET")
    print("=" * 60)

    print("\n1. 🟢 Bullish Candidates")
    print("   Spot bullish candidates")

    print("\n2. 🔴 Bearish Candidates")
    print("   Spot bearish candidates")

    print("\n3. 📈 Future Gainers")
    print("   USDⓈ-M Futures gaining strongly")

    print("\n4. 📉 Future Losers")
    print("   USDⓈ-M Futures losing strongly")

    print("\n5. 🔎 Search Crypto")
    print("   Search both Spot + Futures")

    print("\n6. Exit")

    choice = input("\nChoose: ").strip()

    # Result count for market scans.
    result_limit = 10

    if choice in {"1", "2", "3", "4"}:
        raw_limit = input(
            "\nHow many results? [1-50, default 10]: "
        ).strip()

        if raw_limit:
            try:
                result_limit = int(raw_limit)
            except ValueError:
                print(
                    "⚠️ Invalid number. Using default: 10"
                )
                result_limit = 10

        result_limit = max(
            1,
            min(result_limit, 50),
        )

    # ========================================================
    # EXIT
    # ========================================================

    if choice == "6":
        return

    # ========================================================
    # SPOT BULLISH / BEARISH
    # ========================================================

    if choice in {"1", "2"}:

        scan_limit = 50
        seen_symbols = set()

        while True:

            print(
                f"\n🔎 Scanning top {scan_limit} "
                f"liquid Binance Spot markets..."
            )

            scan = scan_spot_market(
                limit=scan_limit
            )

            if scan.get("error"):
                print(
                    f"⚠️ Spot scan failed: "
                    f"{scan['error']}"
                )
                return

            all_candidates = (
                scan["top_buys"]
                if choice == "1"
                else scan["top_sells"]
            )

            # Remove candidates already shown.
            candidates = [
                item
                for item in all_candidates
                if item["symbol"] not in seen_symbols
            ][:result_limit]

            label = (
                "BULLISH"
                if choice == "1"
                else "BEARISH"
            )

            icon = (
                "🟢"
                if choice == "1"
                else "🔴"
            )

            print(
                f"\n{icon} SPOT {label} CANDIDATES"
            )
            print("-" * 60)

            print(
                f"Universe: {scan['universe']}"
            )
            print(
                f"Scanned: {scan['scanned']}"
            )

            if not candidates:
                print(
                    "\n⚠️ No new candidates found "
                    "at this scan level."
                )

            for item in candidates:

                display_number = (
                    len(seen_symbols) + 1
                )

                print(
                    f"\n{display_number}. "
                    f"{item['symbol']}"
                )

                print(
                    f"   Price: "
                    f"${item['price']:,.8f}"
                    .rstrip("0")
                    .rstrip(".")
                )

                print(
                    f"   RSI: "
                    f"{item['rsi']:.2f}"
                )

                print(
                    f"   Trend: "
                    f"{item['trend_strength']:.2f}%"
                )

                seen_symbols.add(
                    item["symbol"]
                )

            print("\n" + "-" * 60)

            if scan_limit < 200:
                print(
                    "more → Scan a larger Spot universe"
                )

            print(
                "menu → Return to market menu"
            )

            action = input(
                "\nMarket > "
            ).strip().lower()

            if action == "more":

                if scan_limit == 50:
                    scan_limit = 100

                elif scan_limit == 100:
                    scan_limit = 200

                else:
                    print(
                        "\n⚠️ Maximum Spot scan "
                        "level reached."
                    )

                continue

            return

    # ========================================================
    # FUTURES GAINERS / LOSERS
    # ========================================================

    if choice in {"3", "4"}:

        try:

            print("\n🔎 Checking Binance USDⓈ-M Futures...")

            # Load the full ranked Futures list once.
            # "more" uses this same snapshot without another API request.
            movers = get_futures_movers(limit=10000)

        except Exception as exc:

            print(f"⚠️ Futures data failed: {exc}")
            return

        candidates = (
            movers["gainers"]
            if choice == "3"
            else movers["losers"]
        )

        label = (
            "FUTURE GAINERS"
            if choice == "3"
            else "FUTURE LOSERS"
        )

        icon = (
            "📈"
            if choice == "3"
            else "📉"
        )

        print(f"\n{icon} {label}")
        print("-" * 60)

        print(
            f"Futures Universe: "
            f"{movers['universe']}"
        )

        shown = 0
        batch_size = result_limit

        while shown < len(candidates):

            batch = candidates[
                shown:shown + batch_size
            ]

            if not batch:
                break

            for i, item in enumerate(
                batch,
                shown + 1,
            ):

                print(
                    f"\n{i}. "
                    f"{item['symbol']}"
                )

                print(
                    f"   Price: "
                    f"${item['price']:,.8f}"
                    .rstrip("0")
                    .rstrip(".")
                )

                print(
                    f"   24h Change: "
                    f"{item['change_pct']:.2f}%"
                )

            shown += len(batch)

            print("\n" + "-" * 60)

            if shown < len(candidates):

                print(
                    "more → Show next Futures results"
                )

            else:

                print(
                    "No more Futures results."
                )

            print(
                "menu → Return to market menu"
            )

            action = input(
                "\nMarket > "
            ).strip().lower()

            if action == "more":

                if shown >= len(candidates):

                    print(
                        "\n⚠️ No more Futures results."
                    )

                continue

            if action == "menu":

                return

            print(
                "\n⚠️ Invalid option. "
                "Use: more or menu"
            )

        return

    # ========================================================
    # SEARCH — SPOT + FUTURES
    # ========================================================

    if choice == "5":

        query = input(
            "\n🔎 Search crypto: "
        ).strip()

        if not query:
            print("⚠️ Search cancelled.")
            return

        print(
            f"\n🔎 Searching Spot + "
            f"USDⓈ-M Futures for: {query.upper()}"
        )

        results = search_binance_crypto(query)

        if not results:
            print(
                "\n⚠️ No matching symbols found."
            )
            return

        print("\n📋 SEARCH RESULTS")
        print("-" * 60)

        for i, item in enumerate(results, 1):

            markets = []

            if item.get("spot"):
                markets.append("🟢 Spot")

            if item.get("futures"):
                markets.append("📈 USDⓈ-M Futures")

            market_text = (
                " | ".join(markets)
                if markets
                else "⚠️ Market status unavailable"
            )

            print(
                f"\n{i}. {item['symbol']}"
            )

            print(
                f"   Base asset: "
                f"{item.get('base_asset', '-')}"
            )

            print(
                f"   Markets: "
                f"{market_text}"
            )

        print("\n0. Exit")

        selection = input(
            "\nSelect symbol number: "
        ).strip()

        if selection == "0" or not selection:
            return

        try:
            selected_index = int(selection) - 1
        except ValueError:
            print("\n⚠️ Invalid selection.")
            return

        if (
            selected_index < 0
            or selected_index >= len(results)
        ):
            print("\n⚠️ Invalid selection.")
            return

        selected = results[selected_index]

        print("\n" + "=" * 60)
        print("🎯 SELECTED SYMBOL")
        print("=" * 60)

        print(
            f"Symbol: {selected['symbol']}"
        )

        print(
            f"Base asset: "
            f"{selected.get('base_asset', '-')}"
        )

        if selected.get("spot"):
            print("🟢 Spot: AVAILABLE")
        else:
            print("🟢 Spot: NOT AVAILABLE")

        if selected.get("futures"):
            print("📈 USDⓈ-M Futures: AVAILABLE")
        else:
            print("📈 USDⓈ-M Futures: NOT AVAILABLE")

        print(
            "\n🔒 Live execution: BLOCKED"
        )

        return

    print("\n⚠️ Invalid market option.")

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

# ============================================================
# STAGE 7.6.8.9 — 24H PREDICTION PERFORMANCE REPORT
# ============================================================

def get_prediction_performance_report():
    """
    Report performance for genuine 24-hour directional predictions.

    IMPORTANT:
    Only rows explicitly marked as DIRECTIONAL_PREDICTION are counted.
    Full paper-trade records, legacy TEST records, and resolved trade
    plans are excluded.

    PAPER/BACKTEST ONLY.
    LIVE EXECUTION REMAINS BLOCKED.
    """

    ensure_paper_trade_plans_table()

    conn = sqlite3.connect("sentinel.db")
    cursor = conn.cursor()

    try:
        prediction_filter = """
            consensus_status = 'DIRECTIONAL_PREDICTION'
        """

        # --------------------------------------------------------
        # Total predictions
        # --------------------------------------------------------
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE {prediction_filter}
        """)
        total_predictions = cursor.fetchone()[0] or 0

        # --------------------------------------------------------
        # Active predictions
        # --------------------------------------------------------
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND prediction_outcome IS NULL
                AND status = 'PREDICTION_ACTIVE'
        """)
        active_predictions = cursor.fetchone()[0] or 0

        # --------------------------------------------------------
        # Evaluated predictions
        # --------------------------------------------------------
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND prediction_outcome IS NOT NULL
        """)
        evaluated_predictions = cursor.fetchone()[0] or 0

        # --------------------------------------------------------
        # Outcome counts
        # --------------------------------------------------------
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND prediction_outcome = 'SUCCESS'
        """)
        successes = cursor.fetchone()[0] or 0

        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND prediction_outcome = 'FAILURE'
        """)
        failures = cursor.fetchone()[0] or 0

        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND prediction_outcome = 'NEUTRAL'
        """)
        neutral = cursor.fetchone()[0] or 0

        # --------------------------------------------------------
        # Direction counts
        # --------------------------------------------------------
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND direction = 'BUY'
                AND prediction_outcome IS NOT NULL
        """)
        buy_evaluated = cursor.fetchone()[0] or 0

        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND direction = 'BUY'
                AND prediction_outcome = 'SUCCESS'
        """)
        buy_successes = cursor.fetchone()[0] or 0

        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND direction = 'SELL'
                AND prediction_outcome IS NOT NULL
        """)
        sell_evaluated = cursor.fetchone()[0] or 0

        cursor.execute(f"""
            SELECT COUNT(*)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND direction = 'SELL'
                AND prediction_outcome = 'SUCCESS'
        """)
        sell_successes = cursor.fetchone()[0] or 0

        # --------------------------------------------------------
        # Aggregate metrics
        # --------------------------------------------------------
        cursor.execute(f"""
            SELECT
                AVG(price_change_pct),
                AVG(feedback_score)
            FROM paper_trade_plans
            WHERE
                {prediction_filter}
                AND prediction_outcome IS NOT NULL
        """)

        aggregate = cursor.fetchone()

        avg_price_change = (
            float(aggregate[0])
            if aggregate and aggregate[0] is not None
            else 0.0
        )

        avg_feedback_score = (
            float(aggregate[1])
            if aggregate and aggregate[1] is not None
            else 0.0
        )

        accuracy = (
            (successes / evaluated_predictions) * 100.0
            if evaluated_predictions
            else 0.0
        )

        buy_accuracy = (
            (buy_successes / buy_evaluated) * 100.0
            if buy_evaluated
            else 0.0
        )

        sell_accuracy = (
            (sell_successes / sell_evaluated) * 100.0
            if sell_evaluated
            else 0.0
        )

        return {
            "total_predictions": total_predictions,
            "active_predictions": active_predictions,
            "evaluated_predictions": evaluated_predictions,
            "successes": successes,
            "failures": failures,
            "neutral": neutral,
            "accuracy": accuracy,
            "buy_accuracy": buy_accuracy,
            "sell_accuracy": sell_accuracy,
            "avg_price_change_pct": avg_price_change,
            "avg_feedback_score": avg_feedback_score,
            "live_execution": "BLOCKED",
        }

    finally:
        conn.close()


def print_prediction_performance_report():
    """
    Print the 24-hour directional prediction performance report.

    PAPER/BACKTEST ONLY.
    LIVE EXECUTION REMAINS BLOCKED.
    """

    report = get_prediction_performance_report()

    print("\n" + "=" * 60)
    print("📊 HEX SENTINEL — 24H PREDICTION PERFORMANCE")
    print("=" * 60)

    print(
        f"Total Predictions:      "
        f"{report['total_predictions']}"
    )

    print(
        f"Active Predictions:     "
        f"{report['active_predictions']}"
    )

    print(
        f"Evaluated Predictions:  "
        f"{report['evaluated_predictions']}"
    )

    print("-" * 60)

    print(
        f"✅ Successes:           "
        f"{report['successes']}"
    )

    print(
        f"❌ Failures:            "
        f"{report['failures']}"
    )

    print(
        f"➖ Neutral:             "
        f"{report['neutral']}"
    )

    print(
        f"🎯 Accuracy:            "
        f"{report['accuracy']:.2f}%"
    )

    print("-" * 60)

    print(
        f"📈 BUY Accuracy:        "
        f"{report['buy_accuracy']:.2f}%"
    )

    print(
        f"📉 SELL Accuracy:       "
        f"{report['sell_accuracy']:.2f}%"
    )

    print("-" * 60)

    print(
        f"Avg Price Change:       "
        f"{report['avg_price_change_pct']:+.4f}%"
    )

    print(
        f"Avg Feedback Score:     "
        f"{report['avg_feedback_score']:+.4f}"
    )

    print("🔒 Live execution: BLOCKED")
    print("=" * 60)



# ============================================================
# HEX SENTINEL — BINANCE USDⓈ-M FUTURES SYMBOL VALIDATOR
# ============================================================

_HEX_FUTURES_SYMBOL_CACHE = {
    "expires_at": 0,
    "symbols": set(),
}

def validate_binance_futures_symbol(symbol):
    import time
    import difflib
    import requests

    normalized = str(symbol).strip().upper()

    if not normalized.endswith("USDT"):
        normalized += "USDT"

    now = time.time()

    if (
        not _HEX_FUTURES_SYMBOL_CACHE["symbols"]
        or now >= _HEX_FUTURES_SYMBOL_CACHE["expires_at"]
    ):
        response = requests.get(
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
            timeout=15,
        )
        response.raise_for_status()

        data = response.json()

        symbols = {
            item["symbol"]
            for item in data.get("symbols", [])
            if item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
        }

        _HEX_FUTURES_SYMBOL_CACHE["symbols"] = symbols
        _HEX_FUTURES_SYMBOL_CACHE["expires_at"] = now + 300

    if normalized in _HEX_FUTURES_SYMBOL_CACHE["symbols"]:
        return True, normalized, None

    candidates = sorted(_HEX_FUTURES_SYMBOL_CACHE["symbols"])

    base = normalized[:-4]

    close = difflib.get_close_matches(
        normalized,
        candidates,
        n=1,
        cutoff=0.40,
    )

    if close:
        suggestion = close[0]
    else:
        prefix = [
            item for item in candidates
            if item.startswith(base[:3])
        ]
        suggestion = prefix[0] if prefix else None

    return False, normalized, suggestion



def demo_interface():
    """Interactive terminal interface for the Sentinel agent."""

    # ============================================================
    # STAGE 7.6.8.8 — AUTOMATIC 24H PREDICTION EVALUATION
    # ============================================================

    try:
        prediction_events = monitor_active_paper_trades()

        if prediction_events:
            print("\n📊 CHECKING 24H PAPER PREDICTIONS...")
            print("-" * 60)

            for event in prediction_events:

                if event.get("event") in {
                    "SUCCESS",
                    "FAILURE",
                    "NEUTRAL"
                }:
                    change = event.get("price_change_pct")

                    change_text = (
                        f"{change:+.2f}%"
                        if isinstance(change, (int, float))
                        else "N/A"
                    )

                    print(
                        f"{event.get('symbol', 'UNKNOWN')} | "
                        f"{event.get('event')} | "
                        f"{change_text}"
                    )

            print("-" * 60)

    except Exception as prediction_monitor_error:
        print(
            "\n⚠️ Prediction evaluation check skipped: "
            f"{prediction_monitor_error}"
        )

    print("\n" + "=" * 60)
    print("🛡️ HEX SENTINEL — INTERACTIVE DEMO")
    print("=" * 60)
    print("Mode: PAPER/BACKTEST ONLY")
    print("Live execution: BLOCKED")
    print("\nAvailable commands:")
    print("  status   → Current Sentinel safety state (now live, not fixed text)")
    print("  market   → Scan bullish/bearish Binance candidates")
    print("  scan     → Binance-wide futures scanner")
    print("  history  → Recent audited decisions")
    print("  analyze  → Analyze the current market")
    print("  predict <coin> [horizon] → 24H paper prediction")
    print("  performance → 24H prediction performance report")
    print("  cache    → API cache / rate-limit protection status")
    print("  cache clear → Clear the API response cache")
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

            # ========================================================
            # STAGE 7.6.8.10 — PREDICTION PERFORMANCE COMMAND
            # ========================================================

            if user_request in {
                "performance",
                "prediction performance",
                "prediction stats"
            }:
                try:
                    print_prediction_performance_report()
                except Exception as performance_error:
                    print(
                        "\n⚠️ Performance report failed: "
                        f"{performance_error}"
                    )

                print("🔒 Live execution: BLOCKED")
                continue

            # ========================================================
            # STAGE 7.6.8.2 — 24H PAPER PREDICTION COMMAND
            # ========================================================
            # Usage:
            #   predict ETH
            #   predict ETHUSDT
            #   predict ETH 24h
            #
            # Default horizon is 24H.
            # This always uses the existing Sentinel pipeline.
            # No real exchange order can be created.
            if user_request.startswith("predict "):
                import re

                parts = user_request.split()

                if len(parts) < 2 or len(parts) > 3:
                    print("\n⚠️ Usage: predict <coin> [horizon]")
                    print("   Example: predict ETH")
                    print("   Example: predict ETH 24h")
                    print("🔒 Live execution: BLOCKED")
                    continue

                raw_symbol = parts[1].upper()

                if raw_symbol.endswith("USDT"):
                    symbol = raw_symbol
                else:
                    symbol = raw_symbol + "USDT"

                horizon = parts[2].lower() if len(parts) == 3 else "24h"

                # 24H is the only horizon currently enabled.
                if horizon != "24h":
                    print(f"\n⚠️ Horizon '{horizon}' is not enabled yet.")
                    print("Currently enabled: 24h")
                    print("Future horizons require horizon-specific evidence.")
                    print("🔒 Live execution: BLOCKED")
                    continue

                if not re.fullmatch(r"[A-Z0-9]{2,20}USDT", symbol):
                    print(f"\n⚠️ Invalid prediction symbol: {symbol}")
                    print("Example: predict ETH")
                    print("🔒 Live execution: BLOCKED")
                    continue

                print("\n" + "=" * 60)
                print("🔮 HEX SENTINEL — 24H PAPER PREDICTION")
                print("=" * 60)
                print(f"Symbol: {symbol}")
                print("Horizon: 24H")
                print("Market data: LIVE BINANCE MARKET")
                print("Execution: PAPER ONLY")
                print("Live execution: BLOCKED")
                print("=" * 60)

                try:
                    prediction_result = run_legacy_pipeline(symbol)

                    print("\n" + "=" * 60)
                    print("📋 24H PAPER PREDICTION PIPELINE COMPLETE")
                    print("=" * 60)
                    print(f"Symbol: {symbol}")
                    print("Horizon: 24H")
                    print_paper_prediction_result(
                        prediction_result,
                        horizon="24H"
                    )
                    print("🔒 Live execution: BLOCKED")
                    print("=" * 60)

                except Exception as e:
                    print(f"\n⚠️ Prediction pipeline error: {e}")
                    print("🔒 Live execution: BLOCKED")

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
        # Routed through hex_cached_request so the 8 concurrent scan
        # workers share one rate-limit/backoff budget for this endpoint
        # instead of each hammering Binance independently.
        klines = hex_cached_request(
            f"{BINANCE_API}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": SCAN_INTERVAL,
                "limit": SCAN_CANDLES
            },
            cache_ttl=30,
            min_interval=0.1,
            timeout=15,
        )

        closes = [float(candle[4]) for candle in klines]

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

    except Exception as scan_error:
        # Previously this returned None on every failure, so a Binance
        # rate-limit/ban (HTTP 429/418) looked identical to "no signal"
        # in the scan results. Now it is reported separately.
        return {"symbol": symbol, "error": str(scan_error)}


def scan_binance():
    """
    Fast read-only scan of active Binance USDⓈ-M Futures
    USDT perpetual markets.

    PAPER / BACKTEST ONLY.
    """

    symbols = discover_binance_usdt_symbols()

    # Fast bulk-volume filter before requesting individual klines.
    scan_symbols = get_active_scan_candidates(
        symbols,
        limit=50
    )

    results = []
    scan_errors = []

    with ThreadPoolExecutor(
        max_workers=SCAN_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_one_symbol,
                symbol
            )
            for symbol in scan_symbols
        ]

        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as future_error:
                result = {"error": str(future_error)}

            if not result:
                continue

            if "error" in result:
                scan_errors.append(result)
            else:
                results.append(result)

    buys = sorted(
        [
            item
            for item in results
            if item["signal"] == "BUY"
        ],
        key=lambda item: item["trend_strength"],
        reverse=True
    )

    sells = sorted(
        [
            item
            for item in results
            if item["signal"] == "SELL"
        ],
        key=lambda item: item["trend_strength"],
        reverse=True
    )

    return {
        "universe": len(symbols),
        "scanned": len(results),
        "scan_errors": len(scan_errors),
        "sample_errors": [e["error"] for e in scan_errors[:3]],
        "top_buys": buys[:10],
        "top_sells": sells[:10],
        "market_type": "BINANCE_USDS_M_FUTURES",
        "live_execution": "BLOCKED"
    }


agent_tools["scan_binance"] = scan_binance

print("Binance-wide Futures scanner registered.")


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


def run_full_futures_scan(limit=6):
    """
    Complete read-only Binance USDⓈ-M Futures candidate pipeline.

    Flow:
        Futures scanner
        -> deep validation
        -> deterministic risk ranking
        -> final decision gate

    PAPER / BACKTEST ONLY.
    LIVE EXECUTION REMAINS BLOCKED.
    """

    pipeline = scan_and_validate_candidates(limit=limit)

    ranked = pipeline.get("ranked", [])

    decision = finalize_candidate_decision(ranked)

    return {
        "market_type": "BINANCE_USDS_M_FUTURES",
        "universe": pipeline.get("universe", 0),
        "scanned": pipeline.get("scanned", 0),
        "candidates": pipeline.get("candidates", []),
        "ranked": ranked,
        "decision": decision,
        "live_execution": "BLOCKED",
    }


agent_tools["run_full_futures_scan"] = run_full_futures_scan

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



# ============================================================
# STAGE 7.5.5 — CONSENSUS RELIABILITY SAFETY GUARD
# ============================================================

def apply_consensus_reliability_guard(
    final_action,
    risk_status,
    risk_reason,
    multi_ai_consensus,
):
    """
    Apply deterministic safety controls based on historical
    multi-AI consensus reliability.

    This guard may restrict paper actions but must never enable
    live execution or override existing deterministic blocks.
    """

    reliability = calculate_consensus_reliability()

    original_action = final_action

    # --------------------------------------------------------
    # Existing consensus failures are already fail-closed.
    # --------------------------------------------------------
    if multi_ai_consensus["status"] != "AGREEMENT":

        return {
            "final_action": final_action,
            "risk_status": risk_status,
            "risk_reason": risk_reason,
            "reliability": reliability,
            "override_applied": False,
            "original_action": original_action,
        }

    # --------------------------------------------------------
    # LOW historical reliability:
    # Agreement alone is insufficient.
    # --------------------------------------------------------
    if reliability["status"] == "LOW":

        final_action = "PAPER_HOLD"

        risk_status = (
            "AI_CONSENSUS_LOW_RELIABILITY"
        )

        risk_reason = (
            "Consensus reliability safety override: "
            "historical multi-AI reliability is LOW."
        )

        return {
            "final_action": final_action,
            "risk_status": risk_status,
            "risk_reason": risk_reason,
            "reliability": reliability,
            "override_applied": True,
            "original_action": original_action,
        }

    # --------------------------------------------------------
    # HIGH / MODERATE / INSUFFICIENT_DATA:
    #
    # No reliability override.
    #
    # Insufficient data does NOT manufacture confidence, but
    # it also does not independently block the deterministic
    # paper workflow while history is accumulating.
    # --------------------------------------------------------
    return {
        "final_action": final_action,
        "risk_status": risk_status,
        "risk_reason": risk_reason,
        "reliability": reliability,
        "override_applied": False,
        "original_action": original_action,
    }



# ============================================================
# STAGE 7.6.4 — PROVIDER RELIABILITY RANKING
# ============================================================

def calculate_provider_reliability():
    """
    Convert provider performance history into deterministic
    reliability classifications.

    This ranking is informational and safety-oriented.
    It must never enable live execution.
    """

    performance = evaluate_provider_performance()

    if "database_error" in performance:

        return {
            "database_error": (
                performance["database_error"]
            )
        }

    provider_results = {}

    for provider, data in performance[
        "providers"
    ].items():

        completed = data["total_completed"]
        accuracy = data["accuracy"]

        if completed < 4:

            reliability = (
                "INSUFFICIENT_DATA"
            )

            authority = "LIMITED"

            reason = (
                "At least 4 completed provider "
                "evaluations are required."
            )

        elif accuracy >= 75:

            reliability = "HIGH"

            authority = "STRONG"

            reason = (
                "Provider accuracy is at least "
                "75% across completed evaluations."
            )

        elif accuracy >= 50:

            reliability = "MODERATE"

            authority = "STANDARD"

            reason = (
                "Provider accuracy is between "
                "50% and 74.99%."
            )

        else:

            reliability = "LOW"

            authority = "RESTRICTED"

            reason = (
                "Provider accuracy is below "
                "50%."
            )

        provider_results[provider] = {
            "accuracy": accuracy,
            "completed_evaluations": completed,
            "correct": data["correct"],
            "incorrect": data["incorrect"],
            "pending": data["pending"],
            "unknown": data["unknown"],
            "reliability": reliability,
            "authority": authority,
            "reason": reason,
        }

    return {
        "providers": provider_results,
        "total_linked_records": (
            performance["total_linked_records"]
        )
    }


def print_provider_reliability():
    """
    Display Stage 7.6.4 provider reliability ranking.
    """

    results = (
        calculate_provider_reliability()
    )

    print("\n" + "=" * 60)
    print(
        "🏆 STAGE 7.6.4 — PROVIDER RELIABILITY RANKING"
    )
    print("=" * 60)

    if "database_error" in results:

        print(
            "❌ Database Error: "
            + results["database_error"]
        )

        print("=" * 60)

        return results

    print(
        f"Linked Records: "
        f"{results['total_linked_records']}"
    )

    print("-" * 60)

    for provider in ("GROQ", "GEMINI"):

        data = results["providers"][provider]

        print(f"\n{provider}")

        print(
            f"Completed Evaluations: "
            f"{data['completed_evaluations']}"
        )

        print(
            f"Correct:               "
            f"{data['correct']}"
        )

        print(
            f"Incorrect:             "
            f"{data['incorrect']}"
        )

        if data["accuracy"] is None:

            accuracy_text = "N/A"

        else:

            accuracy_text = (
                f"{data['accuracy']}%"
            )

        print(
            f"Accuracy:              "
            f"{accuracy_text}"
        )

        print(
            f"Reliability:           "
            f"{data['reliability']}"
        )

        print(
            f"Authority:             "
            f"{data['authority']}"
        )

        print(
            f"Reason:                "
            f"{data['reason']}"
        )

    print("\n" + "=" * 60)

    return results



# ============================================================
# STAGE 7.6.5 — PROVIDER RELIABILITY SAFETY GUARD
# ============================================================

def apply_provider_reliability_guard(
    final_action,
    risk_status,
    risk_reason,
    multi_ai_consensus,
):
    """
    Apply deterministic safety controls based on historical
    Groq and Gemini provider reliability.

    This guard may restrict paper actions but must never enable
    live execution or override an existing deterministic block.
    """

    reliability = calculate_provider_reliability()

    original_action = final_action

    # --------------------------------------------------------
    # Consensus failures are already fail-closed.
    # --------------------------------------------------------

    if multi_ai_consensus["status"] != "AGREEMENT":

        return {
            "final_action": final_action,
            "risk_status": risk_status,
            "risk_reason": risk_reason,
            "reliability": reliability,
            "override_applied": False,
            "original_action": original_action,
        }

    # --------------------------------------------------------
    # Check all providers with sufficient historical evidence.
    # Any LOW-reliability agreeing provider restricts action.
    # --------------------------------------------------------

    low_reliability_providers = []

    for provider in ("GROQ", "GEMINI"):

        provider_data = reliability["providers"].get(
            provider,
            {}
        )

        if provider_data.get("reliability") == "LOW":

            low_reliability_providers.append(
                provider
            )

    # --------------------------------------------------------
    # Fail-safe restriction.
    # --------------------------------------------------------

    if low_reliability_providers:

        final_action = "PAPER_HOLD"

        risk_status = (
            "AI_PROVIDER_LOW_RELIABILITY"
        )

        provider_names = ", ".join(
            low_reliability_providers
        )

        risk_reason = (
            "Provider reliability safety override: "
            f"LOW historical reliability detected for "
            f"{provider_names}."
        )

        return {
            "final_action": final_action,
            "risk_status": risk_status,
            "risk_reason": risk_reason,
            "reliability": reliability,
            "override_applied": True,
            "original_action": original_action,
        }

    # --------------------------------------------------------
    # HIGH / MODERATE / INSUFFICIENT_DATA:
    # No independent provider reliability override.
    # --------------------------------------------------------

    return {
        "final_action": final_action,
        "risk_status": risk_status,
        "risk_reason": risk_reason,
        "reliability": reliability,
        "override_applied": False,
        "original_action": original_action,
    }


if __name__ == "__main__":
    demo_interface()

# ============================================================
# HEX SENTINEL — API RATE LIMIT / REQUEST PROTECTION
# ============================================================

import time
import threading

_HEX_API_CACHE = {}
_HEX_API_CACHE_LOCK = threading.Lock()
_HEX_API_LAST_REQUEST = {}
_HEX_API_REQUEST_LOCK = threading.Lock()


def hex_cached_request(
    url,
    params=None,
    cache_ttl=15,
    min_interval=0.15,
    timeout=10,
    retries=2,
):
    """
    Safe read-only HTTP GET helper.

    Features:
    - Short-lived response cache
    - Per-endpoint request spacing
    - Retry handling for temporary failures
    - No trading or order execution
    """

    import requests

    params = params or {}

    cache_key = (
        url,
        tuple(sorted(
            (str(key), str(value))
            for key, value in params.items()
        )),
    )

    now = time.time()

    # --------------------------------------------------------
    # CACHE CHECK
    # --------------------------------------------------------
    with _HEX_API_CACHE_LOCK:
        cached = _HEX_API_CACHE.get(cache_key)

        if cached:
            cached_at, cached_data = cached

            if now - cached_at < cache_ttl:
                return cached_data

    # --------------------------------------------------------
    # REQUEST SPACING
    # --------------------------------------------------------
    endpoint_key = url

    with _HEX_API_REQUEST_LOCK:
        last_request = _HEX_API_LAST_REQUEST.get(
            endpoint_key,
            0.0,
        )

        elapsed = time.time() - last_request

        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        _HEX_API_LAST_REQUEST[endpoint_key] = time.time()

    # --------------------------------------------------------
    # RETRY LOOP
    # --------------------------------------------------------
    last_error = None

    for attempt in range(retries + 1):

        try:
            response = requests.get(
                url,
                params=params,
                timeout=timeout,
            )

            # Rate limit / temporary server errors.
            if response.status_code in (
                429,
                418,
                500,
                502,
                503,
                504,
            ):
                raise RuntimeError(
                    f"HTTP {response.status_code}"
                )

            response.raise_for_status()

            data = response.json()

            # ------------------------------------------------
            # SAVE CACHE
            # ------------------------------------------------
            with _HEX_API_CACHE_LOCK:
                _HEX_API_CACHE[cache_key] = (
                    time.time(),
                    data,
                )

            return data

        except Exception as exc:

            last_error = exc

            if attempt < retries:

                backoff = 1.0 * (attempt + 1)

                time.sleep(backoff)

    raise RuntimeError(
        f"HEX API request failed after "
        f"{retries + 1} attempts: {last_error}"
    )


def hex_clear_api_cache():
    """Clear Sentinel's temporary API response cache."""

    with _HEX_API_CACHE_LOCK:
        _HEX_API_CACHE.clear()

    return {
        "status": "CLEARED",
        "live_execution": "BLOCKED",
    }


def hex_api_cache_status():
    """Return temporary API cache statistics."""

    with _HEX_API_CACHE_LOCK:

        entries = len(_HEX_API_CACHE)

    return {
        "cache_entries": entries,
        "request_protection": "ACTIVE",
        "live_execution": "BLOCKED",
    }


# Expose the rate-limit tools as real commands. Previously these three
# functions existed but were never registered or called anywhere, so
# the caching/spacing logic above never actually protected a live call.
agent_tools["cache_status"] = hex_api_cache_status
agent_tools["cache_clear"] = hex_clear_api_cache

AGENT_TOOL_MANIFEST["cache_status"] = {
    "description": "Report API response cache size and rate-limit protection status.",
    "access": "READ_ONLY",
    "execution": "BLOCKED",
}
AGENT_TOOL_MANIFEST["cache_clear"] = {
    "description": "Clear Sentinel's temporary API response cache.",
    "access": "READ_ONLY",
    "execution": "BLOCKED",
}

print("API rate-limit protection registered.")

