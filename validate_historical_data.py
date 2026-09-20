import csv
import os
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
DATA_DIR = "historical_data/processed"

EXPECTED_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]

INTERVALS = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}


def ms_to_datetime(ms):
    return datetime.fromtimestamp(
        int(ms) / 1000,
        tz=timezone.utc
    )


def validate_interval(interval):

    print("\n" + "=" * 60)
    print(f"VALIDATING: {SYMBOL} {interval}")
    print("=" * 60)

    filename = f"{SYMBOL}_{interval}_2023_2025.csv"
    path = os.path.join(DATA_DIR, filename)

    if not os.path.isfile(path):
        print(f"ERROR: File not found: {path}")
        return False

    print(f"File: {path}")
    print(f"Size: {os.path.getsize(path):,} bytes")

    expected_gap = INTERVALS[interval]

    total_rows = 0
    bad_columns = 0
    bad_timestamps = 0
    duplicates = 0
    gaps = 0
    bad_ohlc = 0
    bad_volume = 0

    previous_time = None
    first_time = None
    last_time = None

    with open(
        path,
        "r",
        newline="",
        encoding="utf-8"
    ) as file:

        reader = csv.reader(file)

        header = next(reader, None)

        if header != EXPECTED_COLUMNS:
            print("WARNING: Header does not exactly match expected columns.")
            print("Found:", header)
        else:
            print("Header: OK")

        for row in reader:

            total_rows += 1

            if len(row) != 12:
                bad_columns += 1
                continue

            try:
                open_time = int(row[0])

                open_price = float(row[1])
                high_price = float(row[2])
                low_price = float(row[3])
                close_price = float(row[4])
                volume = float(row[5])

            except (ValueError, IndexError):
                bad_timestamps += 1
                continue

            if first_time is None:
                first_time = open_time

            last_time = open_time

            if previous_time is not None:

                difference = open_time - previous_time

                if difference == 0:
                    duplicates += 1

                elif difference != expected_gap:
                    gaps += 1

            previous_time = open_time

            # OHLC validation
            if (
                high_price < open_price
                or high_price < close_price
                or high_price < low_price
                or low_price > open_price
                or low_price > close_price
            ):
                bad_ohlc += 1

            # Volume validation
            if volume < 0:
                bad_volume += 1

    print("\nVALIDATION RESULTS")
    print("-" * 60)

    print(f"Total candles:        {total_rows}")
    print(f"Bad column rows:      {bad_columns}")
    print(f"Bad timestamp rows:   {bad_timestamps}")
    print(f"Duplicate timestamps: {duplicates}")
    print(f"Time gaps:            {gaps}")
    print(f"Invalid OHLC rows:    {bad_ohlc}")
    print(f"Negative volumes:     {bad_volume}")

    if first_time is not None:
        print(
            f"First candle:         "
            f"{ms_to_datetime(first_time)}"
        )

        print(
            f"Last candle:          "
            f"{ms_to_datetime(last_time)}"
        )

    success = (
        total_rows > 0
        and bad_columns == 0
        and bad_timestamps == 0
        and duplicates == 0
        and gaps == 0
        and bad_ohlc == 0
        and bad_volume == 0
    )

    print("\nSTATUS:", "PASS" if success else "FAIL")

    return success


results = []

for interval in ["1h", "4h"]:
    results.append(validate_interval(interval))


print("\n" + "=" * 60)

if all(results):
    print("ALL DATASETS PASSED VALIDATION")
else:
    print("VALIDATION FAILED")

print("=" * 60)
