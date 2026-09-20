import csv
import os


INPUT_FILES = {
    "1h": "historical_data/features/BTCUSDT_1h_features.csv",
    "4h": "historical_data/features/BTCUSDT_4h_features.csv",
}

OUTPUT_DIR = "historical_data/regimes"

TREND_THRESHOLD_PCT = 0.20
VOLATILITY_MULTIPLIER = 1.20


def safe_float(value):

    if value in (None, "", "None"):
        return None

    try:
        return float(value)

    except (ValueError, TypeError):
        return None


def load_features(filename):

    rows = []

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            rows.append(row)

    return rows


def calculate_average_volatility(rows):

    values = []

    for row in rows:

        volatility = safe_float(
            row.get("volatility20")
        )

        if volatility is not None:

            values.append(
                volatility
            )

    if not values:

        return None

    return (
        sum(values)
        / len(values)
    )


def detect_trend_regime(row):

    close = safe_float(
        row.get("close")
    )

    ema20 = safe_float(
        row.get("ema20")
    )

    ema50 = safe_float(
        row.get("ema50")
    )

    if (
        close is None
        or ema20 is None
        or ema50 is None
        or ema50 == 0
    ):

        return "UNKNOWN"

    ema_difference_pct = (
        (
            ema20 - ema50
        )
        / ema50
    ) * 100

    if (
        ema20 > ema50
        and ema_difference_pct
        >= TREND_THRESHOLD_PCT
    ):

        return "BULL"

    if (
        ema20 < ema50
        and ema_difference_pct
        <= -TREND_THRESHOLD_PCT
    ):

        return "BEAR"

    return "SIDEWAYS"


def detect_volatility_regime(
    row,
    average_volatility
):

    volatility = safe_float(
        row.get("volatility20")
    )

    if (
        volatility is None
        or average_volatility is None
        or average_volatility == 0
    ):

        return "UNKNOWN"

    high_volatility_threshold = (
        average_volatility
        * VOLATILITY_MULTIPLIER
    )

    if (
        volatility
        >= high_volatility_threshold
    ):

        return "HIGH_VOL"

    return "LOW_VOL"


def detect_combined_regime(
    trend_regime,
    volatility_regime
):

    if (
        trend_regime == "UNKNOWN"
        or volatility_regime == "UNKNOWN"
    ):

        return "UNKNOWN"

    return (
        f"{trend_regime}_"
        f"{volatility_regime}"
    )


def process_interval(
    interval,
    input_file
):

    print(
        "\n"
        + "=" * 60
    )

    print(
        f"ANALYZING MARKET REGIMES: "
        f"BTCUSDT {interval}"
    )

    print(
        "=" * 60
    )

    print(
        f"Loading: "
        f"{input_file}"
    )

    rows = load_features(
        input_file
    )

    print(
        f"Rows loaded: "
        f"{len(rows)}"
    )

    if not rows:

        print(
            "ERROR: No rows loaded."
        )

        return None

    print(
        "\nCalculating baseline volatility..."
    )

    average_volatility = (
        calculate_average_volatility(
            rows
        )
    )

    if average_volatility is None:

        print(
            "ERROR: Could not calculate "
            "average volatility."
        )

        return None

    high_volatility_threshold = (
        average_volatility
        * VOLATILITY_MULTIPLIER
    )

    print(
        f"Average volatility: "
        f"{average_volatility:.6f}%"
    )

    print(
        f"High-vol threshold: "
        f"{high_volatility_threshold:.6f}%"
    )

    trend_counts = {
        "BULL": 0,
        "BEAR": 0,
        "SIDEWAYS": 0,
        "UNKNOWN": 0,
    }

    volatility_counts = {
        "HIGH_VOL": 0,
        "LOW_VOL": 0,
        "UNKNOWN": 0,
    }

    combined_counts = {}

    output_rows = []

    print(
        "\nClassifying regimes..."
    )

    for row in rows:

        trend_regime = (
            detect_trend_regime(
                row
            )
        )

        volatility_regime = (
            detect_volatility_regime(
                row,
                average_volatility
            )
        )

        combined_regime = (
            detect_combined_regime(
                trend_regime,
                volatility_regime
            )
        )

        row["trend_regime"] = (
            trend_regime
        )

        row["volatility_regime"] = (
            volatility_regime
        )

        row["combined_regime"] = (
            combined_regime
        )

        trend_counts[
            trend_regime
        ] += 1

        volatility_counts[
            volatility_regime
        ] += 1

        if (
            combined_regime
            not in combined_counts
        ):

            combined_counts[
                combined_regime
            ] = 0

        combined_counts[
            combined_regime
        ] += 1

        output_rows.append(
            row
        )

    output_file = (
        f"{OUTPUT_DIR}/"
        f"BTCUSDT_"
        f"{interval}_"
        f"regimes.csv"
    )

    fieldnames = list(
        output_rows[0].keys()
    )

    print(
        f"\nWriting/replacing: "
        f"{output_file}"
    )

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

        for row in output_rows:

            writer.writerow(
                row
            )

    print(
        "Regime dataset saved."
    )

    print(
        "\nTREND REGIMES"
    )

    print(
        "-" * 40
    )

    total_rows = len(
        output_rows
    )

    for regime, count in (
        trend_counts.items()
    ):

        percentage = (
            (
                count
                / total_rows
            )
            * 100
        )

        print(
            f"{regime:<10} "
            f"{count:>8} "
            f"{percentage:>7.2f}%"
        )

    print(
        "\nVOLATILITY REGIMES"
    )

    print(
        "-" * 40
    )

    for regime, count in (
        volatility_counts.items()
    ):

        percentage = (
            (
                count
                / total_rows
            )
            * 100
        )

        print(
            f"{regime:<10} "
            f"{count:>8} "
            f"{percentage:>7.2f}%"
        )

    print(
        "\nCOMBINED REGIMES"
    )

    print(
        "-" * 40
    )

    for regime in sorted(
        combined_counts.keys()
    ):

        count = (
            combined_counts[
                regime
            ]
        )

        percentage = (
            (
                count
                / total_rows
            )
            * 100
        )

        print(
            f"{regime:<20} "
            f"{count:>8} "
            f"{percentage:>7.2f}%"
        )

    print(
        "\nSUCCESS"
    )

    print(
        f"Saved: "
        f"{output_file}"
    )

    return {
        "interval": interval,
        "total_rows": total_rows,
        "average_volatility":
            average_volatility,
        "high_volatility_threshold":
            high_volatility_threshold,
        "trend_counts":
            trend_counts,
        "volatility_counts":
            volatility_counts,
        "combined_counts":
            combined_counts,
    }


def write_summary(results):

    summary_file = (
        f"{OUTPUT_DIR}/"
        f"regime_summary.csv"
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "WRITING REGIME SUMMARY"
    )

    print(
        "=" * 60
    )

    print(
        f"Writing/replacing: "
        f"{summary_file}"
    )

    fieldnames = [
        "interval",
        "regime_type",
        "regime",
        "count",
        "percentage",
        "average_volatility",
        "high_volatility_threshold",
    ]

    with open(
        summary_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for result in results:

            if result is None:
                continue

            interval = (
                result[
                    "interval"
                ]
            )

            total_rows = (
                result[
                    "total_rows"
                ]
            )

            average_volatility = (
                result[
                    "average_volatility"
                ]
            )

            high_volatility_threshold = (
                result[
                    "high_volatility_threshold"
                ]
            )

            regime_groups = [

                (
                    "TREND",
                    result[
                        "trend_counts"
                    ]
                ),

                (
                    "VOLATILITY",
                    result[
                        "volatility_counts"
                    ]
                ),

                (
                    "COMBINED",
                    result[
                        "combined_counts"
                    ]
                ),

            ]

            for (
                regime_type,
                counts
            ) in regime_groups:

                for (
                    regime,
                    count
                ) in counts.items():

                    percentage = (
                        (
                            count
                            / total_rows
                        )
                        * 100
                    )

                    writer.writerow({

                        "interval":
                            interval,

                        "regime_type":
                            regime_type,

                        "regime":
                            regime,

                        "count":
                            count,

                        "percentage":
                            percentage,

                        "average_volatility":
                            average_volatility,

                        "high_volatility_threshold":
                            high_volatility_threshold,

                    })

    print(
        "Summary saved."
    )

    print(
        f"File: "
        f"{summary_file}"
    )


def main():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "HEX SENTINEL "
        "MARKET REGIME DETECTION"
    )

    print(
        "=" * 60
    )

    results = []

    for (
        interval,
        input_file
    ) in INPUT_FILES.items():

        result = (
            process_interval(
                interval,
                input_file
            )
        )

        results.append(
            result
        )

    write_summary(
        results
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "REGIME ANALYSIS COMPLETE"
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()
