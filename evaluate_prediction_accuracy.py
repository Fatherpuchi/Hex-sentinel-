import csv
import os


INPUT_FILES = {
    "1h": "historical_data/regimes/BTCUSDT_1h_regimes.csv",
    "4h": "historical_data/regimes/BTCUSDT_4h_regimes.csv",
}

OUTPUT_DIR = "historical_data/accuracy"

PREDICTION_THRESHOLD_PCT = 0.20


def safe_float(value):

    if value in (None, "", "None"):
        return None

    try:
        return float(value)

    except (ValueError, TypeError):
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
            rows.append(row)

    return rows


def generate_prediction(row):

    ema20 = safe_float(
        row.get("ema20")
    )

    ema50 = safe_float(
        row.get("ema50")
    )

    rsi14 = safe_float(
        row.get("rsi14")
    )

    momentum12 = safe_float(
        row.get("momentum12")
    )

    volume_ratio20 = safe_float(
        row.get("volume_ratio20")
    )

    if (
        ema20 is None
        or ema50 is None
        or rsi14 is None
        or momentum12 is None
    ):
        return None, None

    long_score = 0
    short_score = 0

    if ema20 > ema50:
        long_score += 1

    elif ema20 < ema50:
        short_score += 1

    if rsi14 >= 55:
        long_score += 1

    elif rsi14 <= 45:
        short_score += 1

    if momentum12 > 0:
        long_score += 1

    elif momentum12 < 0:
        short_score += 1

    if (
        volume_ratio20 is not None
        and volume_ratio20 >= 1.0
    ):

        if long_score > short_score:
            long_score += 1

        elif short_score > long_score:
            short_score += 1

    if long_score > short_score:

        confidence = (
            long_score / 4
        ) * 100

        return "LONG", confidence

    if short_score > long_score:

        confidence = (
            short_score / 4
        ) * 100

        return "SHORT", confidence

    return None, None


def evaluate_outcome(
    prediction,
    future_return
):

    if (
        prediction is None
        or future_return is None
    ):
        return None

    if prediction == "LONG":

        if (
            future_return
            >= PREDICTION_THRESHOLD_PCT
        ):
            return "CORRECT"

        return "WRONG"

    if prediction == "SHORT":

        if (
            future_return
            <= -PREDICTION_THRESHOLD_PCT
        ):
            return "CORRECT"

        return "WRONG"

    return None


def confidence_bucket(confidence):

    if confidence is None:
        return "NO_SIGNAL"

    if confidence >= 100:
        return "100"

    if confidence >= 75:
        return "75"

    if confidence >= 50:
        return "50"

    if confidence >= 25:
        return "25"

    return "LOW"


def process_horizon(
    rows,
    horizon
):

    future_column = (
        f"future_return_{horizon}"
    )

    total_predictions = 0
    correct = 0
    wrong = 0

    long_predictions = 0
    long_correct = 0

    short_predictions = 0
    short_correct = 0

    regime_stats = {}
    confidence_stats = {}

    results = []

    for row in rows:

        prediction, confidence = (
            generate_prediction(
                row
            )
        )

        future_return = safe_float(
            row.get(
                future_column
            )
        )

        outcome = evaluate_outcome(
            prediction,
            future_return
        )

        # NOTE: trend_regime and volatility_regime were previously
        # fetched here but never used -- only combined_regime feeds
        # regime_stats below, so the breakdown was silently dropped.
        # Removed the dead reads; if a per-trend/per-volatility
        # breakdown is wanted later, bucket on these the same way
        # combined_regime is bucketed below.
        combined_regime = (
            row.get(
                "combined_regime",
                "UNKNOWN"
            )
        )

        bucket = (
            confidence_bucket(
                confidence
            )
        )

        output_row = dict(
            row
        )

        output_row[
            "prediction"
        ] = prediction or ""

        output_row[
            "confidence"
        ] = (
            f"{confidence:.2f}"
            if confidence is not None
            else ""
        )

        output_row[
            "confidence_bucket"
        ] = bucket

        output_row[
            "evaluated_future_return"
        ] = (
            future_return
            if future_return is not None
            else ""
        )

        output_row[
            "prediction_outcome"
        ] = outcome or ""

        results.append(
            output_row
        )

        if outcome is None:
            continue

        total_predictions += 1

        if prediction == "LONG":

            long_predictions += 1

        elif prediction == "SHORT":

            short_predictions += 1

        if outcome == "CORRECT":

            correct += 1

            if prediction == "LONG":
                long_correct += 1

            elif prediction == "SHORT":
                short_correct += 1

        else:
            wrong += 1

        if combined_regime not in regime_stats:

            regime_stats[
                combined_regime
            ] = {
                "total": 0,
                "correct": 0,
            }

        regime_stats[
            combined_regime
        ]["total"] += 1

        if outcome == "CORRECT":

            regime_stats[
                combined_regime
            ]["correct"] += 1

        if bucket not in confidence_stats:

            confidence_stats[
                bucket
            ] = {
                "total": 0,
                "correct": 0,
            }

        confidence_stats[
            bucket
        ]["total"] += 1

        if outcome == "CORRECT":

            confidence_stats[
                bucket
            ]["correct"] += 1

    accuracy = (
        (correct / total_predictions) * 100
        if total_predictions > 0
        else 0
    )

    long_accuracy = (
        (
            long_correct
            / long_predictions
        )
        * 100
        if long_predictions > 0
        else 0
    )

    short_accuracy = (
        (
            short_correct
            / short_predictions
        )
        * 100
        if short_predictions > 0
        else 0
    )

    return {
        "horizon": horizon,
        "total_predictions":
            total_predictions,
        "correct": correct,
        "wrong": wrong,
        "accuracy": accuracy,
        "long_predictions":
            long_predictions,
        "long_correct":
            long_correct,
        "long_accuracy":
            long_accuracy,
        "short_predictions":
            short_predictions,
        "short_correct":
            short_correct,
        "short_accuracy":
            short_accuracy,
        "regime_stats":
            regime_stats,
        "confidence_stats":
            confidence_stats,
        "results":
            results,
    }


def print_horizon_results(results):

    print(
        "\n"
        + "-" * 60
    )

    print(
        f"PREDICTION HORIZON: "
        f"{results['horizon']}"
    )

    print(
        "-" * 60
    )

    print(
        f"Predictions: "
        f"{results['total_predictions']}"
    )

    print(
        f"Correct:     "
        f"{results['correct']}"
    )

    print(
        f"Wrong:       "
        f"{results['wrong']}"
    )

    print(
        f"Accuracy:    "
        f"{results['accuracy']:.2f}%"
    )

    print()

    print(
        f"LONG accuracy:  "
        f"{results['long_accuracy']:.2f}% "
        f"({results['long_correct']}/"
        f"{results['long_predictions']})"
    )

    print(
        f"SHORT accuracy: "
        f"{results['short_accuracy']:.2f}% "
        f"({results['short_correct']}/"
        f"{results['short_predictions']})"
    )


def write_prediction_results(
    interval,
    horizon_results
):

    output_file = (
        f"{OUTPUT_DIR}/"
        f"BTCUSDT_"
        f"{interval}_"
        f"prediction_accuracy.csv"
    )

    all_rows = []

    for result in horizon_results:

        horizon = result[
            "horizon"
        ]

        for row in result[
            "results"
        ]:

            output_row = dict(
                row
            )

            output_row[
                "prediction_horizon"
            ] = horizon

            all_rows.append(
                output_row
            )

    if not all_rows:
        return

    fieldnames = list(
        all_rows[0].keys()
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

        for row in all_rows:

            writer.writerow(
                row
            )

    print(
        "Prediction dataset saved."
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
        f"EVALUATING PREDICTION "
        f"ACCURACY: BTCUSDT {interval}"
    )

    print(
        "=" * 60
    )

    print(
        f"Loading: "
        f"{input_file}"
    )

    rows = load_rows(
        input_file
    )

    print(
        f"Rows loaded: "
        f"{len(rows)}"
    )

    horizons = [
        "4h",
        "12h",
        "24h",
        "48h",
    ]

    horizon_results = []

    for horizon in horizons:

        result = (
            process_horizon(
                rows,
                horizon
            )
        )

        print_horizon_results(
            result
        )

        horizon_results.append(
            result
        )

    write_prediction_results(
        interval,
        horizon_results
    )

    return {
        "interval": interval,
        "horizons":
            horizon_results,
    }


def write_summary(all_results):

    summary_file = (
        f"{OUTPUT_DIR}/"
        f"prediction_accuracy_summary.csv"
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "WRITING ACCURACY SUMMARY"
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
        "horizon",
        "total_predictions",
        "correct",
        "wrong",
        "accuracy",
        "long_predictions",
        "long_correct",
        "long_accuracy",
        "short_predictions",
        "short_correct",
        "short_accuracy",
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

        for interval_result in all_results:

            interval = (
                interval_result[
                    "interval"
                ]
            )

            for result in (
                interval_result[
                    "horizons"
                ]
            ):

                writer.writerow({

                    "interval":
                        interval,

                    "horizon":
                        result[
                            "horizon"
                        ],

                    "total_predictions":
                        result[
                            "total_predictions"
                        ],

                    "correct":
                        result[
                            "correct"
                        ],

                    "wrong":
                        result[
                            "wrong"
                        ],

                    "accuracy":
                        result[
                            "accuracy"
                        ],

                    "long_predictions":
                        result[
                            "long_predictions"
                        ],

                    "long_correct":
                        result[
                            "long_correct"
                        ],

                    "long_accuracy":
                        result[
                            "long_accuracy"
                        ],

                    "short_predictions":
                        result[
                            "short_predictions"
                        ],

                    "short_correct":
                        result[
                            "short_correct"
                        ],

                    "short_accuracy":
                        result[
                            "short_accuracy"
                        ],

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
        "PREDICTION ACCURACY ENGINE"
    )

    print(
        "=" * 60
    )

    all_results = []

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

        all_results.append(
            result
        )

    write_summary(
        all_results
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "PREDICTION ACCURACY "
        "ANALYSIS COMPLETE"
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()
