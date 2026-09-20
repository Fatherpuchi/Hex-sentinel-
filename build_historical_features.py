import csv
import os
from statistics import mean


INPUT_FILES = {
    "1h": "historical_data/processed/BTCUSDT_1h_2023_2025.csv",
    "4h": "historical_data/processed/BTCUSDT_4h_2023_2025.csv",
}

OUTPUT_DIR = "historical_data/features"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_candles(filename):
    candles = []

    with open(filename, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            candles.append({
                "open_time": int(row["open_time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })

    return candles


def calculate_ema(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    multiplier = 2 / (period + 1)

    first_ema = mean(values[:period])
    result[period - 1] = first_ema

    previous_ema = first_ema

    for i in range(period, len(values)):
        current_value = values[i]

        ema = (
            current_value * multiplier
            + previous_ema * (1 - multiplier)
        )

        result[i] = ema
        previous_ema = ema

    return result


def calculate_rsi(closes, period=14):
    result = [None] * len(closes)

    if len(closes) <= period:
        return result

    gains = []
    losses = []

    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    if average_loss == 0:
        result[period] = 100.0
    else:
        rs = average_gain / average_loss

        result[period] = (
            100 - (100 / (1 + rs))
        )

    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]

        gain = max(change, 0)
        loss = max(-change, 0)

        average_gain = (
            (average_gain * (period - 1) + gain)
            / period
        )

        average_loss = (
            (average_loss * (period - 1) + loss)
            / period
        )

        if average_loss == 0:
            result[i] = 100.0
        else:
            rs = average_gain / average_loss

            result[i] = (
                100 - (100 / (1 + rs))
            )

    return result


def calculate_atr(candles, period=14):
    result = [None] * len(candles)

    if len(candles) <= period:
        return result

    true_ranges = [None] * len(candles)

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        true_ranges[i] = true_range

    first_atr = mean(
        true_ranges[1:period + 1]
    )

    result[period] = first_atr

    previous_atr = first_atr

    for i in range(period + 1, len(candles)):
        current_tr = true_ranges[i]

        atr = (
            (
                previous_atr * (period - 1)
                + current_tr
            )
            / period
        )

        result[i] = atr
        previous_atr = atr

    return result


def calculate_momentum(closes, period=12):
    result = [None] * len(closes)

    for i in range(period, len(closes)):
        previous_close = closes[i - period]

        if previous_close != 0:
            result[i] = (
                (
                    closes[i] - previous_close
                )
                / previous_close
            ) * 100

    return result


def calculate_volume_ratio(volumes, period=20):
    result = [None] * len(volumes)

    for i in range(period, len(volumes)):
        average_volume = mean(
            volumes[i - period:i]
        )

        if average_volume > 0:
            result[i] = (
                volumes[i] / average_volume
            )

    return result


def calculate_volatility(closes, period=20):
    result = [None] * len(closes)

    for i in range(period, len(closes)):
        returns = []

        for j in range(
            i - period + 1,
            i + 1
        ):
            previous_close = closes[j - 1]

            if previous_close != 0:
                percentage_return = (
                    (
                        closes[j] - previous_close
                    )
                    / previous_close
                )

                returns.append(
                    percentage_return
                )

        if returns:
            average_return = mean(returns)

            variance = mean(
                [
                    (
                        value - average_return
                    ) ** 2
                    for value in returns
                ]
            )

            result[i] = (
                variance ** 0.5
            ) * 100

    return result


def future_return(
    closes,
    index,
    periods_ahead
):
    future_index = (
        index + periods_ahead
    )

    if future_index >= len(closes):
        return None

    current_price = closes[index]
    future_price = closes[future_index]

    if current_price == 0:
        return None

    return (
        (
            future_price - current_price
        )
        / current_price
    ) * 100


def build_features(candles, interval):
    closes = [
        candle["close"]
        for candle in candles
    ]

    volumes = [
        candle["volume"]
        for candle in candles
    ]

    print("Calculating EMA 20...")
    ema20 = calculate_ema(closes, 20)

    print("Calculating EMA 50...")
    ema50 = calculate_ema(closes, 50)

    print("Calculating RSI 14...")
    rsi14 = calculate_rsi(closes, 14)

    print("Calculating ATR 14...")
    atr14 = calculate_atr(candles, 14)

    print("Calculating momentum...")
    momentum12 = calculate_momentum(closes, 12)

    print("Calculating volume ratio...")
    volume_ratio20 = calculate_volume_ratio(
        volumes,
        20
    )

    print("Calculating volatility...")
    volatility20 = calculate_volatility(
        closes,
        20
    )

    if interval == "1h":
        future_periods = {
            "future_return_4h": 4,
            "future_return_12h": 12,
            "future_return_24h": 24,
            "future_return_48h": 48,
        }
    else:
        future_periods = {
            "future_return_4h": 1,
            "future_return_12h": 3,
            "future_return_24h": 6,
            "future_return_48h": 12,
        }

    features = []

    for i, candle in enumerate(candles):
        row = dict(candle)

        row["ema20"] = ema20[i]
        row["ema50"] = ema50[i]
        row["rsi14"] = rsi14[i]
        row["atr14"] = atr14[i]
        row["momentum12"] = momentum12[i]
        row["volume_ratio20"] = volume_ratio20[i]
        row["volatility20"] = volatility20[i]

        for name, periods in future_periods.items():
            row[name] = future_return(
                closes,
                i,
                periods
            )

        features.append(row)

    return features


def write_features(features, output_file):
    fieldnames = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ema20",
        "ema50",
        "rsi14",
        "atr14",
        "momentum12",
        "volume_ratio20",
        "volatility20",
        "future_return_4h",
        "future_return_12h",
        "future_return_24h",
        "future_return_48h",
    ]

    # Automatic replacement of existing dataset
    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(features)


def process_interval(interval, input_file):
    print("\n" + "=" * 60)
    print(
        f"BUILDING FEATURES: "
        f"BTCUSDT {interval}"
    )
    print("=" * 60)

    candles = load_candles(input_file)

    print(
        f"Candles loaded: {len(candles)}"
    )

    features = build_features(
        candles,
        interval
    )

    output_file = (
        f"{OUTPUT_DIR}/"
        f"BTCUSDT_{interval}_features.csv"
    )

    if os.path.exists(output_file):
        print(
            f"Replacing existing dataset: "
            f"{output_file}"
        )
    else:
        print(
            f"Creating dataset: "
            f"{output_file}"
        )

    write_features(
        features,
        output_file
    )

    print("SUCCESS")
    print(f"Saved: {output_file}")
    print(f"Feature rows: {len(features)}")


def main():
    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    for interval, input_file in INPUT_FILES.items():
        process_interval(
            interval,
            input_file
        )

    print("\n" + "=" * 60)
    print("FEATURE BUILD COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
