#!/data/data/com.termux/files/usr/bin/bash
cd "$HOME/binance-sentinel" || exit 1
termux-wake-lock
echo "=== $(date -u +%FT%TZ) scheduled run ===" >> carry_collector.out
python3 carry_collector.py run >> carry_collector.out 2>&1
echo "exit code $?" >> carry_collector.out
termux-wake-unlock
