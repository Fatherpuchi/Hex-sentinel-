#!/bin/bash
cd "$(dirname "$0")" || exit 1
B=$(git rev-parse --abbrev-ref HEAD)
git fetch origin "$B" 2>&1 | tail -n 1
N=$(git rev-list --count "origin/$B..HEAD")
BEHIND=$(git rev-list --count "HEAD..origin/$B")
BAD=$(git diff --name-only "origin/$B..HEAD" | grep -E '(^|/)\.env|\.db$|\.db-|\.bak|\.broken|_state|\.tmp$')
SECRETS=$(git diff "origin/$B..HEAD" | grep -E '^\+' | grep -cE 'tvly-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|gsk_[0-9A-Za-z]{20,}')
echo "branch $B | unpushed $N | behind $BEHIND | risky files: ${BAD:-none} | secret-like lines: $SECRETS"
if [ "$N" -eq 0 ]; then echo "nothing to push"
elif [ "$BEHIND" -ne 0 ]; then echo "ABORT: remote has $BEHIND commit(s) not in this branch, not pushing"
elif [ -n "$BAD" ] || [ "$SECRETS" -ne 0 ]; then echo "ABORT: risky content found, not pushing"
else git push 2>&1 | tail -n 4
fi
