import csv
import os


INPUT_FILE = (
    "historical_data/core/"
    "BTCUSDT_1h_core_signals.csv"
)

OUTPUT_DIR = (
    "historical_data/optimization"
)

RESULTS_FILE = (
    f"{OUTPUT_DIR}/"
    "strategy_optimization_results.csv"
)

TOP_FILE = (
    f"{OUTPUT_DIR}/"
    "strategy_optimization_top10.csv"
)

BEST_FILE = (
    f"{OUTPUT_DIR}/"
    "best_strategy_config.txt"
)


# ------------------------------------------------------------
# OPTIMIZATION DESIGN
# ------------------------------------------------------------
#
# 2023-2024 = development/training period
# 2025      = untouched holdout period
#
# The optimizer NEVER uses 2025 to select parameters.
# ------------------------------------------------------------

TRAIN_END = "2024-12-31T23:59:59"

MIN_TRAIN_TRADES = 200

HORIZON = "24h"


def safe_float(value):

    if value in (
        None,
        "",
        "None",
    ):
        return None

    try:
        return float(value)

    except (
        ValueError,
        TypeError,
    ):
        return None


def load_rows(filename):

    rows = []

    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            row["open_time"] = int(
                row["open_time"]
            )

            row["close"] = safe_float(
                row["close"]
            )

            row["base_score"] = safe_float(
                row["base_score"]
            )

            row["confidence_score"] = (
                safe_float(
                    row[
                        "confidence_score"
                    ]
                )
            )

            row["future_return_24h"] = (
                safe_float(
                    row[
                        "future_return_24h"
                    ]
                )
            )

            rows.append(row)

    rows.sort(
        key=lambda row: row[
            "open_time"
        ]
    )

    return rows


def timestamp_to_date_string(
    timestamp_ms
):

    from datetime import datetime, timezone

    return (
        datetime.fromtimestamp(
            timestamp_ms / 1000,
            timezone.utc,
        ).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    )


def is_train_row(row):

    timestamp = row.get(
        "open_time"
    )

    if timestamp is None:
        return False

    date_string = (
        timestamp_to_date_string(
            timestamp
        )
    )

    return (
        date_string
        <= TRAIN_END
    )


def calculate_stats(
    rows
):

    total = 0
    correct = 0

    gross_profit = 0.0
    gross_loss = 0.0

    returns = []

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for row in rows:

        signal = row.get(
            "selected_signal"
        )

        future_return = (
            row.get(
                "future_return_24h"
            )
        )

        if signal not in (
            "LONG",
            "SHORT",
        ):

            continue

        if future_return is None:

            continue

        total += 1

        if signal == "LONG":

            adjusted_return = (
                future_return
            )

        else:

            adjusted_return = (
                -future_return
            )

        returns.append(
            adjusted_return
        )

        cumulative += (
            adjusted_return
        )

        if cumulative > peak:

            peak = cumulative

        drawdown = (
            peak
            - cumulative
        )

        if drawdown > max_drawdown:

            max_drawdown = drawdown

        if adjusted_return > 0:

            correct += 1
            gross_profit += (
                adjusted_return
            )

        elif adjusted_return < 0:

            gross_loss += (
                abs(adjusted_return)
            )

    if total == 0:

        return {
            "trades": 0,
            "accuracy": 0.0,
            "average_return": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
        }

    accuracy = (
        correct
        / total
        * 100
    )

    average_return = (
        sum(returns)
        / total
    )

    if gross_loss > 0:

        profit_factor = (
            gross_profit
            / gross_loss
        )

    elif gross_profit > 0:

        profit_factor = 999.0

    else:

        profit_factor = 0.0

    return {
        "trades": total,
        "accuracy": accuracy,
        "average_return":
            average_return,
        "profit_factor":
            profit_factor,
        "max_drawdown":
            max_drawdown,
        "total_return":
            sum(returns),
    }


def regime_allowed(
    regime,
    regime_mode
):

    if regime_mode == "ALL":
        return True

    if regime_mode == "BULL_ONLY":

        return regime.startswith(
            "BULL"
        )

    if regime_mode == "BEAR_ONLY":

        return regime.startswith(
            "BEAR"
        )

    if regime_mode == "TREND_ONLY":

        return (
            regime.startswith(
                "BULL"
            )
            or regime.startswith(
                "BEAR"
            )
        )

    if regime_mode == "EXCLUDE_HIGH_RISK":

        return regime not in {
            "BEAR_HIGH_VOL",
            "SIDEWAYS_HIGH_VOL",
        }

    if regime_mode == "LONG_FRIENDLY":

        return regime in {
            "BULL_HIGH_VOL",
            "BULL_LOW_VOL",
            "BEAR_LOW_VOL",
        }

    if regime_mode == "SHORT_FRIENDLY":

        return regime in {
            "BEAR_LOW_VOL",
            "BULL_LOW_VOL",
        }

    return True


def mtf_allowed(
    mtf_status,
    mtf_mode
):

    if mtf_mode == "ANY":

        return True

    if mtf_mode == "CONFIRMED":

        return (
            mtf_status
            == "CONFIRMED"
        )

    if mtf_mode == "NOT_CONFLICT":

        return (
            mtf_status
            != "CONFLICT"
        )

    return True


def generate_signal(
    row,
    confidence_threshold,
    regime_mode,
    mtf_mode,
    direction_mode,
):

    base_direction = (
        row.get(
            "base_direction"
        )
    )

    base_score = (
        row.get(
            "base_score"
        )
    )

    confidence_score = (
        row.get(
            "confidence_score"
        )
    )

    regime = (
        row.get(
            "regime",
            "UNKNOWN"
        )
    )

    mtf_status = (
        row.get(
            "mtf_status",
            "UNKNOWN"
        )
    )

    if base_direction not in (
        "LONG",
        "SHORT",
    ):

        return "NO_TRADE"

    if base_score is None:

        return "NO_TRADE"

    if confidence_score is None:

        return "NO_TRADE"

    if (
        confidence_score
        < confidence_threshold
    ):

        return "NO_TRADE"

    if not regime_allowed(
        regime,
        regime_mode,
    ):

        return "NO_TRADE"

    if not mtf_allowed(
        mtf_status,
        mtf_mode,
    ):

        return "NO_TRADE"

    if (
        direction_mode == "LONG_ONLY"
        and base_direction != "LONG"
    ):

        return "NO_TRADE"

    if (
        direction_mode == "SHORT_ONLY"
        and base_direction != "SHORT"
    ):

        return "NO_TRADE"

    if (
        direction_mode
        == "TREND_AGREEMENT"
    ):

        if mtf_status != "CONFIRMED":

            return "NO_TRADE"

    return base_direction


def evaluate_configuration(
    rows,
    confidence_threshold,
    regime_mode,
    mtf_mode,
    direction_mode,
):

    selected_rows = []

    for row in rows:

        signal = generate_signal(

            row,

            confidence_threshold,

            regime_mode,

            mtf_mode,

            direction_mode,
        )

        if signal == "NO_TRADE":

            continue

        selected = dict(row)

        selected[
            "selected_signal"
        ] = signal

        selected_rows.append(
            selected
        )

    stats = calculate_stats(
        selected_rows
    )

    stats.update({

        "confidence_threshold":
            confidence_threshold,

        "regime_mode":
            regime_mode,

        "mtf_mode":
            mtf_mode,

        "direction_mode":
            direction_mode,

    })

    return stats


def optimization_score(
    stats
):

    trades = stats["trades"]

    if trades < MIN_TRAIN_TRADES:

        return -999999.0

    accuracy = (
        stats["accuracy"]
    )

    profit_factor = (
        stats["profit_factor"]
    )

    average_return = (
        stats["average_return"]
    )

    max_drawdown = (
        stats["max_drawdown"]
    )

    # We deliberately do not optimize
    # accuracy alone. Doing so can select
    # tiny samples and encourage overfitting.
    #
    # Score rewards:
    # - positive average return
    # - profit factor above 1
    # - accuracy
    #
    # and penalizes drawdown.

    score = (

        average_return * 40.0

        + (
            profit_factor
            - 1.0
        ) * 20.0

        + (
            accuracy
            - 50.0
        ) * 0.20

        - max_drawdown * 0.05

    )

    return score


def build_parameter_grid():

    confidence_thresholds = [
        55,
        60,
        65,
        70,
        75,
        80,
        85,
    ]

    regime_modes = [
        "ALL",
        "BULL_ONLY",
        "BEAR_ONLY",
        "TREND_ONLY",
        "EXCLUDE_HIGH_RISK",
        "LONG_FRIENDLY",
        "SHORT_FRIENDLY",
    ]

    mtf_modes = [
        "ANY",
        "NOT_CONFLICT",
        "CONFIRMED",
    ]

    direction_modes = [
        "BOTH",
        "LONG_ONLY",
        "SHORT_ONLY",
        "TREND_AGREEMENT",
    ]

    configurations = []

    for confidence_threshold in (
        confidence_thresholds
    ):

        for regime_mode in (
            regime_modes
        ):

            for mtf_mode in (
                mtf_modes
            ):

                for direction_mode in (
                    direction_modes
                ):

                    configurations.append({

                        "confidence_threshold":
                            confidence_threshold,

                        "regime_mode":
                            regime_mode,

                        "mtf_mode":
                            mtf_mode,

                        "direction_mode":
                            direction_mode,

                    })

    return configurations


def write_results(
    results
):

    fieldnames = [

        "rank",

        "optimization_score",

        "confidence_threshold",

        "regime_mode",

        "mtf_mode",

        "direction_mode",

        "trades",

        "accuracy",

        "average_return",

        "profit_factor",

        "max_drawdown",

        "total_return",

    ]

    print(
        f"\nWriting/replacing: "
        f"{RESULTS_FILE}"
    )

    with open(
        RESULTS_FILE,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for rank, result in enumerate(
            results,
            start=1
        ):

            writer.writerow({

                "rank":
                    rank,

                "optimization_score":
                    f"{result['optimization_score']:.6f}",

                "confidence_threshold":
                    result[
                        "confidence_threshold"
                    ],

                "regime_mode":
                    result[
                        "regime_mode"
                    ],

                "mtf_mode":
                    result[
                        "mtf_mode"
                    ],

                "direction_mode":
                    result[
                        "direction_mode"
                    ],

                "trades":
                    result[
                        "trades"
                    ],

                "accuracy":
                    f"{result['accuracy']:.4f}",

                "average_return":
                    f"{result['average_return']:.6f}",

                "profit_factor":
                    f"{result['profit_factor']:.6f}",

                "max_drawdown":
                    f"{result['max_drawdown']:.6f}",

                "total_return":
                    f"{result['total_return']:.6f}",
            })


def write_top10(
    results
):

    fieldnames = [

        "rank",

        "optimization_score",

        "confidence_threshold",

        "regime_mode",

        "mtf_mode",

        "direction_mode",

        "trades",

        "accuracy",

        "average_return",

        "profit_factor",

        "max_drawdown",

        "total_return",

    ]

    print(
        f"Writing/replacing: "
        f"{TOP_FILE}"
    )

    with open(
        TOP_FILE,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for rank, result in enumerate(
            results[:10],
            start=1
        ):

            writer.writerow({

                "rank":
                    rank,

                "optimization_score":
                    f"{result['optimization_score']:.6f}",

                "confidence_threshold":
                    result[
                        "confidence_threshold"
                    ],

                "regime_mode":
                    result[
                        "regime_mode"
                    ],

                "mtf_mode":
                    result[
                        "mtf_mode"
                    ],

                "direction_mode":
                    result[
                        "direction_mode"
                    ],

                "trades":
                    result[
                        "trades"
                    ],

                "accuracy":
                    f"{result['accuracy']:.4f}",

                "average_return":
                    f"{result['average_return']:.6f}",

                "profit_factor":
                    f"{result['profit_factor']:.6f}",

                "max_drawdown":
                    f"{result['max_drawdown']:.6f}",

                "total_return":
                    f"{result['total_return']:.6f}",
            })


def write_best_config(
    best
):

    print(
        f"Writing/replacing: "
        f"{BEST_FILE}"
    )

    with open(
        BEST_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            "HEX SENTINEL "
            "OPTIMIZED STRATEGY\n"
        )

        file.write(
            "================================\n"
        )

        file.write(
            "DEVELOPMENT PERIOD: "
            "2023-01-01 -> 2024-12-31\n"
        )

        file.write(
            "HOLDOUT PERIOD: "
            "2025-01-01 -> 2025-12-31\n"
        )

        file.write(
            "HOLDOUT WAS NOT USED "
            "FOR OPTIMIZATION.\n\n"
        )

        file.write(
            f"Confidence threshold: "
            f"{best['confidence_threshold']}\n"
        )

        file.write(
            f"Regime mode: "
            f"{best['regime_mode']}\n"
        )

        file.write(
            f"MTF mode: "
            f"{best['mtf_mode']}\n"
        )

        file.write(
            f"Direction mode: "
            f"{best['direction_mode']}\n"
        )

        file.write(
            f"Training trades: "
            f"{best['trades']}\n"
        )

        file.write(
            f"Training accuracy: "
            f"{best['accuracy']:.2f}%\n"
        )

        file.write(
            f"Training average return: "
            f"{best['average_return']:.6f}%\n"
        )

        file.write(
            f"Training profit factor: "
            f"{best['profit_factor']:.4f}\n"
        )

        file.write(
            f"Training max drawdown: "
            f"{best['max_drawdown']:.4f}%\n"
        )

        file.write(
            f"Training total return: "
            f"{best['total_return']:.4f}%\n"
        )

        file.write(
            "\nIMPORTANT:\n"
            "This configuration must be "
            "validated on the untouched "
            "2025 holdout before adoption.\n"
        )


def print_top_results(
    results
):

    print(
        "\n"
        + "=" * 60
    )

    print(
        "TOP 10 STRATEGY CONFIGURATIONS"
    )

    print(
        "=" * 60
    )

    for rank, result in enumerate(
        results[:10],
        start=1
    ):

        print(

            f"#{rank:02d} "

            f"Score="
            f"{result['optimization_score']:.3f} | "

            f"Conf>="
            f"{result['confidence_threshold']} | "

            f"Regime="
            f"{result['regime_mode']} | "

            f"MTF="
            f"{result['mtf_mode']} | "

            f"Dir="
            f"{result['direction_mode']} | "

            f"Trades="
            f"{result['trades']} | "

            f"Acc="
            f"{result['accuracy']:.2f}% | "

            f"Avg="
            f"{result['average_return']:.3f}% | "

            f"PF="
            f"{result['profit_factor']:.2f}"
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
        "STRATEGY OPTIMIZATION ENGINE"
    )

    print(
        "=" * 60
    )

    print(
        "\nLoading historical core signals..."
    )

    rows = load_rows(
        INPUT_FILE
    )

    print(
        f"Total rows: "
        f"{len(rows)}"
    )

    train_rows = [
        row
        for row in rows
        if is_train_row(row)
    ]

    holdout_rows = [
        row
        for row in rows
        if not is_train_row(row)
    ]

    print(
        f"Development rows "
        f"(2023-2024): "
        f"{len(train_rows)}"
    )

    print(
        f"Untouched holdout rows "
        f"(2025): "
        f"{len(holdout_rows)}"
    )

    if not train_rows:

        raise RuntimeError(
            "No training rows available."
        )

    if not holdout_rows:

        raise RuntimeError(
            "No 2025 holdout rows available."
        )

    baseline_rows = []

    for row in train_rows:

        selected = dict(row)

        selected[
            "selected_signal"
        ] = row.get(
            "final_signal"
        )

        baseline_rows.append(
            selected
        )

    baseline = calculate_stats(
        baseline_rows
    )

    print(
        "\nBASELINE "
        "(existing Core signal)"
    )

    print(
        f"Trades:        "
        f"{baseline['trades']}"
    )

    print(
        f"Accuracy:      "
        f"{baseline['accuracy']:.2f}%"
    )

    print(
        f"Avg return:    "
        f"{baseline['average_return']:.4f}%"
    )

    print(
        f"Profit factor: "
        f"{baseline['profit_factor']:.2f}"
    )

    configurations = (
        build_parameter_grid()
    )

    print(
        f"\nConfigurations to test: "
        f"{len(configurations)}"
    )

    results = []

    for index, config in enumerate(
        configurations,
        start=1
    ):

        if index % 100 == 0:

            print(
                f"Testing configuration "
                f"{index}/"
                f"{len(configurations)}"
            )

        stats = (
            evaluate_configuration(
                train_rows,

                config[
                    "confidence_threshold"
                ],

                config[
                    "regime_mode"
                ],

                config[
                    "mtf_mode"
                ],

                config[
                    "direction_mode"
                ],
            )
        )

        stats[
            "optimization_score"
        ] = optimization_score(
            stats
        )

        results.append(
            stats
        )

    results.sort(
        key=lambda result:
            result[
                "optimization_score"
            ],
        reverse=True,
    )

    write_results(
        results
    )

    write_top10(
        results
    )

    eligible = [
        result
        for result in results
        if result[
            "trades"
        ] >= MIN_TRAIN_TRADES
    ]

    if not eligible:

        raise RuntimeError(
            "No configuration met "
            "the minimum training "
            "sample requirement."
        )

    best = eligible[0]

    write_best_config(
        best
    )

    print_top_results(
        eligible
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "BEST DEVELOPMENT CONFIGURATION"
    )

    print(
        "=" * 60
    )

    print(
        f"Confidence threshold: "
        f"{best['confidence_threshold']}"
    )

    print(
        f"Regime mode: "
        f"{best['regime_mode']}"
    )

    print(
        f"MTF mode: "
        f"{best['mtf_mode']}"
    )

    print(
        f"Direction mode: "
        f"{best['direction_mode']}"
    )

    print(
        f"Trades: "
        f"{best['trades']}"
    )

    print(
        f"Accuracy: "
        f"{best['accuracy']:.2f}%"
    )

    print(
        f"Average return: "
        f"{best['average_return']:.4f}%"
    )

    print(
        f"Profit factor: "
        f"{best['profit_factor']:.2f}"
    )

    print(
        f"Max drawdown: "
        f"{best['max_drawdown']:.2f}%"
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "OPTIMIZATION COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        "\nIMPORTANT:"
    )

    print(
        "The best configuration "
        "has NOT been approved."
    )

    print(
        "2025 remains untouched and "
        "must be tested next."
    )


if __name__ == "__main__":
    main()
