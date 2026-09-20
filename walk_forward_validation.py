import csv
import os
from datetime import datetime, timezone


INPUT_FILE = "historical_data/core/BTCUSDT_1h_core_signals.csv"
OUTPUT_DIR = "historical_data/walk_forward"

INITIAL_BALANCE = 1000.0

TRAIN_END_YEAR = 2024
TEST_YEAR = 2025

BEST_CONFIDENCE = 65
BEST_REGIME_MODE = "BULL_ONLY"
BEST_MTF_MODE = "ANY"
BEST_DIRECTION_MODE = "BOTH"


def ms_to_datetime(ms):
    return datetime.fromtimestamp(
        int(ms) / 1000,
        tz=timezone.utc
    )


def safe_float(value):
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

            try:
                open_time = int(row["open_time"])

                timestamp = ms_to_datetime(
                    open_time
                )

                row["open_time"] = open_time
                row["year"] = timestamp.year

                for column in [
                    "confidence_score",
                    "future_return_24h",
                    "future_return_48h",
                ]:

                    if column in row:
                        row[column] = safe_float(
                            row[column]
                        )

                rows.append(row)

            except (
                ValueError,
                KeyError,
                TypeError,
            ):
                continue

    return rows


def is_long_friendly(regime):

    return regime in [
        "BULL_HIGH_VOL",
        "BULL_LOW_VOL",
    ]


def is_short_friendly(regime):

    return regime in [
        "BEAR_HIGH_VOL",
        "BEAR_LOW_VOL",
    ]


def regime_allowed(row):

    regime = row.get(
        "combined_regime",
        row.get("regime", "")
    )

    mode = BEST_REGIME_MODE

    if mode == "ANY":
        return True

    if mode == "BULL_ONLY":
        return regime.startswith("BULL")

    if mode == "BEAR_ONLY":
        return regime.startswith("BEAR")

    if mode == "TREND_ONLY":
        return (
            regime.startswith("BULL")
            or regime.startswith("BEAR")
        )

    if mode == "LONG_FRIENDLY":
        return is_long_friendly(
            regime
        )

    if mode == "SHORT_FRIENDLY":
        return is_short_friendly(
            regime
        )

    return False


def mtf_allowed(row):

    status = row.get(
        "mtf_status",
        ""
    )

    if BEST_MTF_MODE == "ANY":
        return True

    if BEST_MTF_MODE == "CONFIRMED":
        return status == "CONFIRMED"

    if BEST_MTF_MODE == "NEUTRAL":
        return status == "NEUTRAL"

    return False


def direction_allowed(signal):

    if BEST_DIRECTION_MODE == "BOTH":
        return signal in [
            "LONG",
            "SHORT",
        ]

    if BEST_DIRECTION_MODE == "LONG_ONLY":
        return signal == "LONG"

    if BEST_DIRECTION_MODE == "SHORT_ONLY":
        return signal == "SHORT"

    return False


def row_qualifies(row):

    signal = row.get(
        "final_signal",
        ""
    )

    confidence = safe_float(
        row.get(
            "confidence_score",
            0
        )
    )

    if confidence is None:
        confidence = 0

    if signal not in [
        "LONG",
        "SHORT",
    ]:
        return False

    if confidence < BEST_CONFIDENCE:
        return False

    if not direction_allowed(
        signal
    ):
        return False

    if not regime_allowed(
        row
    ):
        return False

    if not mtf_allowed(
        row
    ):
        return False

    return True


def calculate_trade_return(
    row,
    horizon_column
):

    signal = row.get(
        "final_signal",
        ""
    )

    future_return = safe_float(
        row.get(
            horizon_column
        )
    )

    if future_return is None:
        return None

    if signal == "LONG":
        return future_return

    if signal == "SHORT":
        return -future_return

    return None


def max_drawdown(
    equity_curve
):

    if not equity_curve:
        return 0.0

    peak = equity_curve[0]

    maximum_drawdown = 0.0

    for equity in equity_curve:

        if equity > peak:
            peak = equity

        if peak > 0:

            drawdown = (
                (peak - equity)
                / peak
            ) * 100

            if drawdown > maximum_drawdown:
                maximum_drawdown = drawdown

    return maximum_drawdown


def evaluate_period(
    rows,
    horizon_column,
    label
):

    qualifying_rows = []

    for row in rows:

        if not row_qualifies(
            row
        ):
            continue

        trade_return = (
            calculate_trade_return(
                row,
                horizon_column
            )
        )

        if trade_return is None:
            continue

        qualifying_rows.append(
            (
                row,
                trade_return
            )
        )

    trades = len(
        qualifying_rows
    )

    wins = 0
    losses = 0

    gross_profit = 0.0
    gross_loss = 0.0

    total_return = 0.0

    balance = INITIAL_BALANCE

    equity_curve = [
        balance
    ]

    results = []

    for row, trade_return in qualifying_rows:

        total_return += (
            trade_return
        )

        pnl = (
            balance
            * trade_return
            / 100
        )

        balance += pnl

        equity_curve.append(
            balance
        )

        if trade_return > 0:

            wins += 1
            gross_profit += (
                trade_return
            )

        elif trade_return < 0:

            losses += 1
            gross_loss += abs(
                trade_return
            )

        results.append({

            "period": label,

            "open_time": row[
                "open_time"
            ],

            "datetime": ms_to_datetime(
                row[
                    "open_time"
                ]
            ).isoformat(),

            "signal": row.get(
                "final_signal"
            ),

            "confidence": row.get(
                "confidence_score"
            ),

            "regime": row.get(
                "combined_regime",
                row.get(
                    "regime",
                    ""
                )
            ),

            "mtf_status": row.get(
                "mtf_status",
                ""
            ),

            "future_return": trade_return,

            "balance": balance,

        })

    accuracy = (
        wins
        / trades
        * 100
        if trades > 0
        else 0.0
    )

    average_return = (
        total_return
        / trades
        if trades > 0
        else 0.0
    )

    profit_factor = (
        gross_profit
        / gross_loss
        if gross_loss > 0
        else 0.0
    )

    drawdown = max_drawdown(
        equity_curve
    )

    net_return = (
        (
            balance
            - INITIAL_BALANCE
        )
        / INITIAL_BALANCE
    ) * 100

    return {

        "label": label,

        "trades": trades,

        "wins": wins,

        "losses": losses,

        "accuracy": accuracy,

        "average_return": average_return,

        "gross_profit": gross_profit,

        "gross_loss": gross_loss,

        "profit_factor": profit_factor,

        "starting_balance": (
            INITIAL_BALANCE
        ),

        "final_balance": balance,

        "net_return": net_return,

        "max_drawdown": drawdown,

        "results": results,

    }


def print_metrics(
    metrics
):

    print(
        f"\n{metrics['label']}"
    )

    print(
        "-" * 60
    )

    print(
        f"Trades:          "
        f"{metrics['trades']}"
    )

    print(
        f"Wins:            "
        f"{metrics['wins']}"
    )

    print(
        f"Losses:          "
        f"{metrics['losses']}"
    )

    print(
        f"Accuracy:        "
        f"{metrics['accuracy']:.2f}%"
    )

    print(
        f"Avg return:      "
        f"{metrics['average_return']:.4f}%"
    )

    print(
        f"Profit factor:   "
        f"{metrics['profit_factor']:.2f}"
    )

    print(
        f"Net return:      "
        f"{metrics['net_return']:.2f}%"
    )

    print(
        f"Max drawdown:    "
        f"{metrics['max_drawdown']:.2f}%"
    )

    print(
        f"Final balance:   "
        f"${metrics['final_balance']:.2f}"
    )


def determine_decision(
    development,
    holdout
):

    if holdout["trades"] < 100:

        return (
            "INSUFFICIENT_HOLDOUT_SAMPLE"
        )

    if holdout[
        "profit_factor"
    ] < 1.0:

        return (
            "REJECTED"
        )

    if holdout[
        "average_return"
    ] <= 0:

        return (
            "REJECTED"
        )

    if holdout[
        "max_drawdown"
    ] > 50:

        return (
            "RISK_WARNING"
        )

    development_pf = (
        development[
            "profit_factor"
        ]
    )

    holdout_pf = (
        holdout[
            "profit_factor"
        ]
    )

    if development_pf > 0:

        retention = (
            holdout_pf
            / development_pf
        )

    else:
        retention = 0

    if retention < 0.60:

        return (
            "OVERFITTING_WARNING"
        )

    return (
        "PASS_TO_NEXT_VALIDATION"
    )


def write_results(
    results,
    output_file
):

    fieldnames = [

        "period",

        "open_time",

        "datetime",

        "signal",

        "confidence",

        "regime",

        "mtf_status",

        "future_return",

        "balance",

    ]

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

        for row in results:

            writer.writerow(
                row
            )


def write_summary(
    development,
    holdout,
    decision,
    output_file
):

    fieldnames = [

        "period",

        "trades",

        "wins",

        "losses",

        "accuracy",

        "average_return",

        "gross_profit",

        "gross_loss",

        "profit_factor",

        "starting_balance",

        "final_balance",

        "net_return",

        "max_drawdown",

    ]

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

        for metrics in [

            development,

            holdout,

        ]:

            writer.writerow({

                key: metrics.get(
                    key,
                    ""
                )

                for key in fieldnames

            })

        writer.writerow({

            "period": (
                "DECISION: "
                + decision
            )

        })


def main():

    print(
        "\n"
        + "=" * 60
    )

    print(
        "HEX SENTINEL WALK-FORWARD VALIDATION"
    )

    print(
        "=" * 60
    )

    print(
        "\nLoading core signals..."
    )

    print(
        f"File: {INPUT_FILE}"
    )

    rows = load_rows(
        INPUT_FILE
    )

    print(
        f"Rows loaded: "
        f"{len(rows)}"
    )

    development_rows = [

        row

        for row in rows

        if row["year"]
        <= TRAIN_END_YEAR

    ]

    holdout_rows = [

        row

        for row in rows

        if row["year"]
        == TEST_YEAR

    ]

    print(
        f"\nDevelopment rows "
        f"(2023-{TRAIN_END_YEAR}): "
        f"{len(development_rows)}"
    )

    print(
        f"Holdout rows "
        f"({TEST_YEAR}): "
        f"{len(holdout_rows)}"
    )

    horizon_column = (
        "future_return_48h"
    )

    print(
        "\nUsing horizon: 48h"
    )

    print(
        "\nStrategy configuration:"
    )

    print(
        f"Confidence >= "
        f"{BEST_CONFIDENCE}"
    )

    print(
        f"Regime: "
        f"{BEST_REGIME_MODE}"
    )

    print(
        f"MTF: "
        f"{BEST_MTF_MODE}"
    )

    print(
        f"Direction: "
        f"{BEST_DIRECTION_MODE}"
    )

    print(
        "\nRUNNING DEVELOPMENT "
        "EVALUATION..."
    )

    development = (
        evaluate_period(
            development_rows,
            horizon_column,
            (
                "DEVELOPMENT_"
                "2023_2024"
            ),
        )
    )

    print(
        "\nRUNNING UNTOUCHED "
        "HOLDOUT EVALUATION..."
    )

    holdout = (
        evaluate_period(
            holdout_rows,
            horizon_column,
            (
                "HOLDOOUT_2025"
            ),
        )
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "WALK-FORWARD RESULTS"
    )

    print(
        "=" * 60
    )

    print_metrics(
        development
    )

    print_metrics(
        holdout
    )

    decision = (
        determine_decision(
            development,
            holdout
        )
    )

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    detail_file = (
        f"{OUTPUT_DIR}/"
        f"walk_forward_trade_results.csv"
    )

    summary_file = (
        f"{OUTPUT_DIR}/"
        f"walk_forward_summary.csv"
    )

    print(
        "\nWriting/replacing: "
        f"{detail_file}"
    )

    write_results(

        development[
            "results"
        ]

        + holdout[
            "results"
        ],

        detail_file

    )

    print(
        "Writing/replacing: "
        f"{summary_file}"
    )

    write_summary(

        development,

        holdout,

        decision,

        summary_file,

    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "WALK-FORWARD DECISION"
    )

    print(
        "=" * 60
    )

    print(
        f"\nDECISION: "
        f"{decision}"
    )

    print(
        "\nDetail results:"
    )

    print(
        detail_file
    )

    print(
        "\nSummary:"
    )

    print(
        summary_file
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "WALK-FORWARD VALIDATION COMPLETE"
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()
