import csv
import os
from collections import defaultdict


INPUT_FILE = (
    "historical_data/core/"
    "BTCUSDT_1h_core_signals.csv"
)

OUTPUT_DIR = (
    "historical_data/core_performance"
)

DETAIL_OUTPUT = (
    f"{OUTPUT_DIR}/"
    "BTCUSDT_1h_core_performance.csv"
)

SUMMARY_OUTPUT = (
    f"{OUTPUT_DIR}/"
    "core_performance_summary.csv"
)


HORIZONS = [
    "4h",
    "12h",
    "24h",
    "48h",
]


def safe_float(value):

    if value is None or value == "":
        return None

    try:
        return float(value)

    except ValueError:
        return None


def load_rows(filename):

    rows = []

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            row["confidence_score"] = (
                safe_float(
                    row.get(
                        "confidence_score"
                    )
                )
            )

            for horizon in HORIZONS:

                key = (
                    f"future_return_"
                    f"{horizon}"
                )

                row[key] = (
                    safe_float(
                        row.get(key)
                    )
                )

            rows.append(row)

    return rows


def evaluate_prediction(
    signal,
    future_return
):

    if signal not in (
        "LONG",
        "SHORT",
    ):
        return None

    if future_return is None:
        return None

    if signal == "LONG":

        return future_return > 0

    if signal == "SHORT":

        return future_return < 0


def calculate_adjusted_return(
    signal,
    future_return
):

    if (
        signal not in (
            "LONG",
            "SHORT",
        )
        or future_return is None
    ):

        return None

    if signal == "LONG":

        return future_return

    return -future_return


def create_statistics():

    return {

        "total":
            0,

        "correct":
            0,

        "wrong":
            0,

        "total_return":
            0.0,

        "positive_return":
            0.0,

        "negative_return":
            0.0,
    }


def add_result(
    stats,
    signal,
    future_return
):

    result = (
        evaluate_prediction(
            signal,
            future_return,
        )
    )

    adjusted_return = (
        calculate_adjusted_return(
            signal,
            future_return,
        )
    )

    if result is None:

        return

    stats["total"] += 1

    if result:

        stats["correct"] += 1

    else:

        stats["wrong"] += 1

    stats["total_return"] += (
        adjusted_return
    )

    if adjusted_return > 0:

        stats["positive_return"] += (
            adjusted_return
        )

    elif adjusted_return < 0:

        stats["negative_return"] += (
            abs(adjusted_return)
        )


def finalize_statistics(
    stats
):

    total = stats["total"]

    if total == 0:

        return {

            "predictions":
                0,

            "correct":
                0,

            "wrong":
                0,

            "accuracy":
                0.0,

            "average_return":
                0.0,

            "profit_factor":
                0.0,
        }

    accuracy = (
        stats["correct"]
        / total
        * 100
    )

    average_return = (
        stats["total_return"]
        / total
    )

    if stats["negative_return"] > 0:

        profit_factor = (
            stats["positive_return"]
            / stats[
                "negative_return"
            ]
        )

    elif (
        stats["positive_return"]
        > 0
    ):

        profit_factor = (
            999.0
        )

    else:

        profit_factor = 0.0

    return {

        "predictions":
            total,

        "correct":
            stats["correct"],

        "wrong":
            stats["wrong"],

        "accuracy":
            accuracy,

        "average_return":
            average_return,

        "profit_factor":
            profit_factor,
    }


def analyze_rows(rows):

    results = []

    categories = {

        "FINAL_SIGNAL":
            lambda row: row.get(
                "final_signal",
                "UNKNOWN"
            ),

        "CONFIDENCE":
            lambda row: row.get(
                "confidence_level",
                "UNKNOWN"
            ),

        "SIGNAL_QUALITY":
            lambda row: row.get(
                "signal_quality",
                "UNKNOWN"
            ),

        "MTF_STATUS":
            lambda row: row.get(
                "mtf_status",
                "UNKNOWN"
            ),

        "REGIME":
            lambda row: row.get(
                "regime",
                "UNKNOWN"
            ),
    }

    for horizon in HORIZONS:

        future_key = (
            f"future_return_"
            f"{horizon}"
        )

        print(
            "\n"
            + "=" * 60
        )

        print(
            f"EVALUATING "
            f"CORE PERFORMANCE: "
            f"{horizon}"
        )

        print(
            "=" * 60
        )

        for category, getter in (
            categories.items()
        ):

            grouped = defaultdict(
                create_statistics
            )

            for row in rows:

                signal = row.get(
                    "final_signal"
                )

                # NO_TRADE does not
                # count as a directional
                # prediction.
                if signal == "NO_TRADE":

                    continue

                future_return = (
                    row.get(
                        future_key
                    )
                )

                group = getter(
                    row
                )

                add_result(
                    grouped[group],
                    signal,
                    future_return,
                )

            print(
                f"\n{category}"
            )

            print(
                "-" * 60
            )

            for name in sorted(
                grouped.keys()
            ):

                stats = (
                    finalize_statistics(
                        grouped[name]
                    )
                )

                print(
                    f"{name:<20} "
                    f"Accuracy: "
                    f"{stats['accuracy']:>6.2f}% "
                    f"| Avg Return: "
                    f"{stats['average_return']:>7.3f}% "
                    f"| PF: "
                    f"{stats['profit_factor']:>6.2f}"
                )

                results.append({

                    "horizon":
                        horizon,

                    "category":
                        category,

                    "group":
                        name,

                    "predictions":
                        stats[
                            "predictions"
                        ],

                    "correct":
                        stats[
                            "correct"
                        ],

                    "wrong":
                        stats[
                            "wrong"
                        ],

                    "accuracy":
                        f"{stats['accuracy']:.4f}",

                    "average_return":
                        f"{stats['average_return']:.6f}",

                    "profit_factor":
                        f"{stats['profit_factor']:.6f}",
                })

    return results


def create_detail_dataset(
    rows
):

    output = []

    for row in rows:

        signal = row.get(
            "final_signal"
        )

        for horizon in HORIZONS:

            future_key = (
                f"future_return_"
                f"{horizon}"
            )

            future_return = (
                row.get(
                    future_key
                )
            )

            correct = (
                evaluate_prediction(
                    signal,
                    future_return,
                )
            )

            adjusted_return = (
                calculate_adjusted_return(
                    signal,
                    future_return,
                )
            )

            output.append({

                "open_time":
                    row.get(
                        "open_time"
                    ),

                "horizon":
                    horizon,

                "final_signal":
                    signal,

                "confidence_level":
                    row.get(
                        "confidence_level"
                    ),

                "confidence_score":
                    row.get(
                        "confidence_score"
                    ),

                "signal_quality":
                    row.get(
                        "signal_quality"
                    ),

                "regime":
                    row.get(
                        "regime"
                    ),

                "regime_quality":
                    row.get(
                        "regime_quality"
                    ),

                "mtf_status":
                    row.get(
                        "mtf_status"
                    ),

                "future_return":
                    future_return,

                "correct":
                    correct,

                "adjusted_return":
                    adjusted_return,
            })

    return output


def write_detail_dataset(
    rows,
    filename
):

    fieldnames = [

        "open_time",

        "horizon",

        "final_signal",

        "confidence_level",

        "confidence_score",

        "signal_quality",

        "regime",

        "regime_quality",

        "mtf_status",

        "future_return",

        "correct",

        "adjusted_return",
    ]

    print(
        f"\nWriting/replacing: "
        f"{filename}"
    )

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in rows:

            writer.writerow(
                row
            )


def write_summary(
    rows,
    filename
):

    fieldnames = [

        "horizon",

        "category",

        "group",

        "predictions",

        "correct",

        "wrong",

        "accuracy",

        "average_return",

        "profit_factor",
    ]

    print(
        f"\nWriting/replacing: "
        f"{filename}"
    )

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in rows:

            writer.writerow(
                row
            )


def print_final_summary(
    results
):

    print(
        "\n"
        + "=" * 60
    )

    print(
        "HEX SENTINEL CORE "
        "PERFORMANCE SUMMARY"
    )

    print(
        "=" * 60
    )

    for horizon in HORIZONS:

        print(
            f"\nHORIZON: "
            f"{horizon}"
        )

        signal_rows = [

            row
            for row in results
            if (
                row["horizon"]
                == horizon
                and row["category"]
                == "FINAL_SIGNAL"
            )
        ]

        print(
            "-" * 50
        )

        for row in signal_rows:

            print(
                f"{row['group']:<12} "
                f"Predictions: "
                f"{int(row['predictions']):>6} "
                f"| Accuracy: "
                f"{float(row['accuracy']):>6.2f}% "
                f"| Avg Return: "
                f"{float(row['average_return']):>7.3f}%"
            )


def main():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True,
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "HEX SENTINEL CORE "
        "PERFORMANCE VALIDATION"
    )

    print(
        "=" * 60
    )

    print(
        f"\nLoading: "
        f"{INPUT_FILE}"
    )

    rows = (
        load_rows(
            INPUT_FILE
        )
    )

    print(
        f"Rows loaded: "
        f"{len(rows)}"
    )

    print(
        "\nANALYZING "
        "HISTORICAL PERFORMANCE..."
    )

    results = (
        analyze_rows(
            rows
        )
    )

    detail_rows = (
        create_detail_dataset(
            rows
        )
    )

    write_detail_dataset(
        detail_rows,
        DETAIL_OUTPUT,
    )

    write_summary(
        results,
        SUMMARY_OUTPUT,
    )

    print_final_summary(
        results
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "CORE PERFORMANCE "
        "VALIDATION COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nDetail dataset:"
        f"\n{DETAIL_OUTPUT}"
    )

    print(
        f"\nSummary:"
        f"\n{SUMMARY_OUTPUT}"
    )


if __name__ == "__main__":
    main()
