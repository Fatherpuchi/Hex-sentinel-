"""Hex Sentinel horizon launcher.

Usage:  python hex.py [4h|12h|24h|48h|72h]

Every horizon runs as its own profile: its own database, its own candle
interval, its own history / memory / performance numbers, so the horizons
never mix. The 24h profile is the original setup (sentinel.db, 1h candles).
"""
import os
import sys

# horizon -> (hours, candle interval used by the Stage 1 backtest)
PROFILES = {
    "4h":  {"hours": 4,  "interval": "1h"},
    "12h": {"hours": 12, "interval": "2h"},
    "24h": {"hours": 24, "interval": "1h"},
    "48h": {"hours": 48, "interval": "4h"},
    "72h": {"hours": 72, "interval": "6h"},
}


def main():
    key = (sys.argv[1] if len(sys.argv) > 1 else "24h").lower()

    if key not in PROFILES:
        print(f"Unknown horizon '{key}'. Choose one of: " + ", ".join(PROFILES))
        sys.exit(1)

    profile = PROFILES[key]
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    os.environ["SENTINEL_HORIZON_HOURS"] = str(profile["hours"])
    os.environ["SENTINEL_INTERVAL"] = profile["interval"]

    if key == "24h":
        os.environ.pop("SENTINEL_DB", None)
        db_name = "sentinel.db"
    else:
        db_name = f"sentinel_{key}.db"
        os.environ["SENTINEL_DB"] = db_name

    print("=" * 60)
    print(f"HEX SENTINEL PROFILE: {key.upper()} horizon")
    print(f"  Candles:  {profile['interval']}")
    print(f"  Database: {db_name}")
    print("=" * 60)

    os.execv(sys.executable, [sys.executable, os.path.join(here, "sentinel_ai.py")])


if __name__ == "__main__":
    main()
