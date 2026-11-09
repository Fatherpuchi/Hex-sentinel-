#!/bin/bash
# backup_hex.sh - encrypted backup of the project (databases, state, code, git) WITHOUT .env.
# Usage: bash backup_hex.sh   (asks for a passphrase twice; the passphrase is never stored)
set -o pipefail
cd "$(dirname "$0")" || exit 1
command -v openssl >/dev/null 2>&1 || { echo "openssl not found (try: pkg install openssl-tool)"; exit 1; }
D=$(date -u +%F)
OUT="$HOME/hex_data_$D.tar.gz.enc"
[ -e "$OUT" ] && { echo "ABORT: $OUT exists"; exit 1; }
tar czf - --exclude=.env --exclude='*.bak*' --exclude=__pycache__ --exclude='*.tmp' -C .. "$(basename "$PWD")" \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -out "$OUT" || { rm -f "$OUT"; echo "ABORT: backup failed"; exit 1; }
sha256sum "$OUT" | cut -c1-64 > "$OUT.sha256"
ls -l "$OUT"
echo "sha256 saved in $OUT.sha256. The passphrase is NOT stored anywhere. .env is NOT in the archive."
echo "Verify: openssl enc -d -aes-256-cbc -pbkdf2 -in $OUT | tar tzf - | wc -l"
