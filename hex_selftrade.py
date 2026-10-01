#!/usr/bin/env python3
"""
Hex Sentinel self-trade scheduler.

Runs ONE cycle -- pick candidates for a category, run predict on each,
log the results -- then exits. Designed to be fired repeatedly by cron,
not to loop forever itself: if one cycle crashes, the next scheduled
run still fires instead of the whole thing silently dying.

Usage:
    python3 hex_selftrade.py [--category gainers] [--count 5] [--dry-run]

    --dry-run   List which symbols would be predicted, with NO AI calls
                and no predictions run. Use this to test the scheduling
                mechanic (cron + lockfile + pause file) for free, before
                spending any AI quota on it.

Files this script uses (created next to this script, not in sentinel.db):
    hex_selftrade.lock    Prevents two cycles overlapping. Auto-cleared
                          if the owning process is gone or the lock is
                          older than LOCK_STALE_SECONDS.
    SELF_TRADE_PAUSE      If this file exists, the cycle logs "paused"
                          and exits immediately. Delete it to resume.
                          This is the kill switch -- no cron edits needed.
    hex_selftrade.log     One clear, appended block per cycle: start
                          time, category, symbols tried, each result,
                          and any errors. This is the log meant for
                          actually reviewing what happened; sentinel_ai's
                          own console output (manifest registration,
                          Stage 1 reports, etc.) still goes to stdout as
                          usual -- redirect that separately in cron if
                          you want the full transcript too.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(HERE, "hex_selftrade.lock")
PAUSE_PATH = os.path.join(HERE, "SELF_TRADE_PAUSE")
LOG_PATH = os.path.join(HERE, "hex_selftrade.log")
LOCK_STALE_SECONDS = 30 * 60  # 30 minutes


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(message):
    line = f"[{now_iso()}] {message}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def pid_is_alive(pid):
    """Best-effort liveness check. Works on Linux/Android (Termux)."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned by someone else -- still "alive".
        return True
    except Exception:
        # Unknown platform quirk -- don't block on it either way.
        return True


def acquire_lock():
    """
    Returns True if the lock was acquired (safe to proceed), False if
    another cycle genuinely appears to still be running.
    """
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            lock_pid = data.get("pid")
            lock_time = data.get("started_at_epoch", 0)
        except Exception:
            lock_pid = None
            lock_time = 0

        age = time.time() - lock_time
        stale = age > LOCK_STALE_SECONDS
        alive = lock_pid is not None and pid_is_alive(lock_pid)

        if alive and not stale:
            log(
                f"⏭️  SKIPPED: previous cycle (pid {lock_pid}) still "
                f"running or lock not yet stale ({age:.0f}s old). "
                "Not starting a new cycle."
            )
            return False

        reason = "process no longer running" if not alive else "lock is stale"
        log(f"🔓 Clearing old lock ({reason}, {age:.0f}s old, pid {lock_pid}).")

    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "started_at_epoch": time.time()}, f)

    return True


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass


def main():
    parser = argparse.ArgumentParser(description="Hex Sentinel self-trade cycle (one run, then exit).")
    parser.add_argument(
        "--category",
        default="gainers",
        choices=["bullish", "bearish", "gainers", "losers"],
        help="Which market-scan category to pull candidates from (default: gainers).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="How many symbols to predict this cycle (default: 5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates only. No AI calls, no predictions run.",
    )
    args = parser.parse_args()

    if os.path.exists(PAUSE_PATH):
        log(
            "⏸️  PAUSED: SELF_TRADE_PAUSE file present. Doing nothing "
            "this cycle. Delete that file to resume."
        )
        return

    if not acquire_lock():
        return

    try:
        log(
            f"▶️  CYCLE START | category={args.category} "
            f"count={args.count} dry_run={args.dry_run}"
        )

        # Imported here, after the pause/lock checks, so a dry-run test
        # of the scheduling mechanic itself never even touches Binance
        # or the AI keys -- exactly the point of --dry-run.
        import sentinel_ai

        if args.dry_run:
            try:
                candidates = sentinel_ai.get_batch_prediction_candidates(
                    args.category, args.count
                )
            except Exception as exc:
                log(f"❌ DRY RUN: could not load candidates: {exc}")
                return

            log(f"🔎 DRY RUN candidates ({len(candidates)}): {', '.join(candidates) or '(none found)'}")
            log("✅ CYCLE END (dry run, no predictions made)")
            return

        results = sentinel_ai.run_batch_predictions(args.category, args.count)

        ok_count = sum(1 for r in results if r.get("ok"))
        fail_count = sum(1 for r in results if not r.get("ok"))

        log(f"📋 CYCLE RESULTS | {ok_count} completed, {fail_count} failed")
        for r in results:
            if r.get("ok"):
                log(
                    f"   {r['symbol']:<12} signal={r.get('signal')} "
                    f"final_action={r.get('final_action')} "
                    f"risk_status={r.get('risk_status')}"
                )
            else:
                log(f"   {r['symbol']:<12} ❌ FAILED: {r.get('error')}")

        log("✅ CYCLE END")

    except Exception as exc:
        log(f"❌ CYCLE CRASHED: {type(exc).__name__}: {exc}")
        raise

    finally:
        release_lock()


if __name__ == "__main__":
    main()
