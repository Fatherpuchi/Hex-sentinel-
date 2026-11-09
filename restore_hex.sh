#!/bin/bash
# restore_hex.sh - decrypts a hex_data archive into a NEW folder. Never overwrites anything.
# Usage: bash restore_hex.sh hex_data_DATE.tar.gz.enc TARGET_DIR
set -o pipefail
[ $# -eq 2 ] || { echo "usage: bash restore_hex.sh ARCHIVE.enc TARGET_DIR"; exit 1; }
[ -f "$1" ] || { echo "ABORT: $1 not found"; exit 1; }
[ -e "$2" ] && { echo "ABORT: $2 already exists; choose a new folder"; exit 1; }
mkdir -p "$2" || exit 1
openssl enc -d -aes-256-cbc -pbkdf2 -in "$1" | tar xzf - -C "$2" || { echo "ABORT: decrypt or extract failed (wrong passphrase?)"; rmdir "$2" 2>/dev/null; exit 1; }
echo "restored into $2 (inside: $(ls "$2" | head -n 1)). .env is not in the archive: recreate it from the names in HEX_MANIFEST.md section 3."
echo "Next: cd into the restored folder and run each selftest (HEX_MANIFEST.md section 9)."
