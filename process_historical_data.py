import os
import glob
import csv
import zipfile
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
BASE_DIR = f"historical_data/raw/futures_um/{SYMBOL}"
OUTPUT_DIR = "historical_data/processed"

os.makedirs(OUTPUT_DIR, exist_ok=True)

COLUMNS = [
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


def ms_to_datetime(ms):
    return datetime.fromtimestamp(
        int(ms) / 1000,
        tz=timezone.utc
    )


def process_interval(interval):
    print("\n" + "=" * 60)
    print(f"PROCESSING: {SYMBOL} {interval}")
    print("=" * 60)

    pattern = f"{BASE_DIR}/{interval}/*.zip"
    zip_files = sorted(glob.glob(pattern))

    print(f"ZIP files found: {len(zip_files)}")

    if not zip_files:
        print("ERROR: No ZIP files found.")
        return

    candles = []
    invalid_rows = 0

    for zip_path in zip_files:
        filename = os.path.basename(zip_path)
        print(f"Reading: {filename}")

        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                csv_files = [
                    name for name in z.namelist()
                    if name.endswith(".csv")
                ]

                if not csv_files:
                    print(f"WARNING: No CSV inside {filename}")
                    continue

                with z.open(csv_files[0]) as binary_file:
                    text_file = (
                        binary_file.read()
                        .decode("utf-8")
                        .splitlines()
                    )

                    reader = csv.reader(text_file)

                    for row in reader:
                        if len(row) < 12:
                            invalid_rows += 1
                            continue

                        try:
                            open_time = int(row[0])

                            candle = [
                                open_time,
                                row[1],
                                row[2],
                                row[3],
                                row[4],
                                row[5],
                                row[6],
                                row[7],
                                row[8],
                                row[9],
                                row[10],
                                row[11],
                            ]

                            candles.append(candle)

                        except (ValueError, IndexError):
                            invalid_rows += 1

        except zipfile.BadZipFile:
            print(f"BAD ZIP: {filename}")

    print(f"\nRows read: {len(candles)}")
    print(f"Invalid rows: {invalid_rows}")

    candles.sort(key=lambda x: x[0])

    cleaned = []
    seen_times = set()
    duplicates = 0

    for candle in candles:
        open_time = candle[0]

        if open_time in seen_times:
            duplicates += 1
            continue

        seen_times.add(open_time)
        cleaned.append(candle)

    candles = cleaned

    print(f"Duplicate candles removed: {duplicates}")
    print(f"Final candle count: {len(candles)}")

    expected_gap_ms = (
        60 * 60 * 1000
        if interval == "1h"
        else 4 * 60 * 60 * 1000
    )

    gaps = []

    for i in range(1, len(candles)):
        previous_time = candles[i - 1][0]
        current_time = candles[i][0]
        difference = current_time - previous_time

        if difference != expected_gap_ms:
            gaps.append(
                (
                    previous_time,
                    current_time,
                    difference
                )
            )

    print(f"Time gaps / irregular intervals: {len(gaps)}")

    if gaps:
        print("\nFirst 10 gaps:")

        for previous_time, current_time, difference in gaps[:10]:
            print(
                f"{ms_to_datetime(previous_time)}"
                f" -> "
                f"{ms_to_datetime(current_time)}"
                f" | gap_ms={difference}"
            )

    output_file = (
        f"{OUTPUT_DIR}/"
        f"{SYMBOL}_{interval}_2023_2025.csv"
    )

    print(f"\nWriting/replacing: {output_file}")

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as output:
        writer = csv.writer(output)
        writer.writerow(COLUMNS)

        for candle in candles:
            writer.writerow(candle)

    print("SUCCESS")
    print(f"Saved: {output_file}")

    if candles:
        first_time = ms_to_datetime(candles[0][0])
        last_time = ms_to_datetime(candles[-1][0])

        print(f"First candle: {first_time}")
        print(f"Last candle:  {last_time}")

    print(f"Final rows: {len(candles)}")

    print("\nFirst 3 candles:")

    for candle in candles[:3]:
        print(
            ms_to_datetime(candle[0]),
            candle[1],
            candle[2],
            candle[3],
            candle[4]
        )


for interval in ["1h", "4h"]:
    process_interval(interval)


print("\n" + "=" * 60)
print("ALL PROCESSING COMPLETE")
print("=" * 60)
