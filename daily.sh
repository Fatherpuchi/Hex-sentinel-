#!/bin/bash
# daily.sh - runs the shell steps of the daily routine, in order.
#   bash daily.sh               run the steps not yet done today (UTC)
#   bash daily.sh --redo NAME   run step NAME again (for example levels_log)
#   bash daily.sh --force       run every step again
# Does NOT run sp or pw (typed inside Hex). Writes only .daily_state_<date>.
cd "$(dirname "$0")" || exit 1
DAY=$(date -u +%Y-%m-%d)
STATE=".daily_state_$DAY"
touch "$STATE"
if [ "$1" = "--force" ]; then : > "$STATE"; fi
if [ "$1" = "--redo" ] && [ -n "$2" ]; then grep -vx "$2" "$STATE" > "$STATE.tmp"; mv "$STATE.tmp" "$STATE"; fi
FAILS=""
echo "daily routine $DAY $(date -u +%H:%M) UTC"
if [ "$(date -u +%H)" -ge 6 ]; then echo "note: past 06:00 UTC, shadow_log rows are marked late (expected)"; fi

step() {
  name="$1"; n="$2"; shift 2
  if grep -qx "$name" "$STATE"; then echo "[skip] $name (done today)"; return; fi
  if [ ! -f "$1" ]; then echo "FAIL: $name: $1 not found"; FAILS="$FAILS $name"; return; fi
  echo "-- $name ..."
  out=$(python3 "$@" 2>&1); rc=$?
  if [ $rc -ne 0 ] || echo "$out" | grep -q "Traceback"; then
    echo "FAIL: $name (exit $rc)"; echo "$out" | tail -n 8; FAILS="$FAILS $name"
  else
    echo "$out" | tail -n "$n"; echo "$name" >> "$STATE"
  fi
}

step shadow_log 3 shadow_log.py run
step carry_collector 3 carry_collector.py run
step carry_forward_obs 6 carry_forward_obs.py run
step counterfactual_grade 4 counterfactual_grade.py grade
step held_plan_grade 4 held_plan_grade.py run
step levels_log 3 levels_log.py run
step market_ctx_log 3 market_ctx_log.py run
if [ -f codeplan_log.py ]; then
  if python3 codeplan_log.py selftest >/dev/null 2>&1; then step codeplan_log 4 codeplan_log.py run
  else echo "FAIL: codeplan_log selftest"; FAILS="$FAILS codeplan_selftest"; fi
fi

if [ -f webdir_log.py ]; then
  if python3 webdir_log.py selftest >/dev/null 2>&1; then step webdir_log 4 webdir_log.py run
  else echo "FAIL: webdir_log selftest"; FAILS="$FAILS webdir_selftest"; fi
fi

if [ -f levelcmp_log.py ]; then
  if python3 levelcmp_log.py selftest >/dev/null 2>&1; then step levelcmp_log 4 levelcmp_log.py run
  else echo "FAIL: levelcmp_log selftest"; FAILS="$FAILS levelcmp_selftest"; fi
fi

if [ -f noiseband_log.py ]; then
  if python3 noiseband_log.py selftest >/dev/null 2>&1; then step noiseband_log 4 noiseband_log.py run
  else echo "FAIL: noiseband_log selftest"; FAILS="$FAILS noiseband_selftest"; fi
fi

if [ -f breakout19_log.py ]; then
  if python3 breakout19_log.py selftest >/dev/null 2>&1; then step breakout19_log 4 breakout19_log.py run
  else echo "FAIL: breakout19_log selftest"; FAILS="$FAILS breakout19_selftest"; fi
fi

B=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
U=$(git rev-list --count "origin/$B..HEAD" 2>/dev/null)
echo "== summary: failed:${FAILS:- none} | unpushed local commits: ${U:-?}"
echo "next, inside Hex: sp resume (or sp 5), then pw."
