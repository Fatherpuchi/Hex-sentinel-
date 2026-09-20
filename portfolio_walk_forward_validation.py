import csv
import os
from datetime import datetime, timezone


DATA_FILE = "historical_data/core/BTCUSDT_1h_core_signals.csv"

OUTPUT_DIR = "historical_data/portfolio_walk_forward"

INITIAL_BALANCE = 1000.0

# Position sizing
RISK_FRACTION = 0.10
MAX_POSITION_USD = 100.0

# Trading costs
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0003

# Strategy configuration from optimizer
CONFIDENCE_THRESHOLD = 65
REGIME_MODE = "BULL_ONLY"
MTF_MODE = "ANY"
DIRECTION_MODE = "BOTH"

# Maximum holding period
HOLDING_HOURS = 48


def ms_to_datetime(ms):
    return datetime.fromtimestamp(
        int(ms) / 1000,
        tz=timezone.utc
    )


def safe_float(value):

    try:

        if value is None:
            return None

        value = str(value).strip()

        if value == "":
            return None

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

            open_time = row.get("open_time")

            if not open_time:
                continue

            try:
                open_time = int(open_time)

            except ValueError:
                continue

            rows.append({
                "open_time": open_time,

                "open": safe_float(
                    row.get("open")
                ),

                "high": safe_float(
                    row.get("high")
                ),

                "low": safe_float(
                    row.get("low")
                ),

                "close": safe_float(
                    row.get("close")
                ),

                "final_signal": (
                    row.get(
                        "final_signal",
                        "NO_TRADE"
                    )
                    .strip()
                    .upper()
                ),

                "confidence_score": safe_float(
                    row.get(
                        "confidence_score"
                    )
                ),

                "combined_regime": (
                    row.get(
                        "combined_regime",
                        row.get(
                            "regime",
                            ""
                        )
                    )
                    .strip()
                    .upper()
                ),

                "mtf_status": (
                    row.get(
                        "mtf_status",
                        ""
                    )
                    .strip()
                    .upper()
                ),
            })

    return rows


def get_year(open_time):

    return datetime.fromtimestamp(
        open_time / 1000,
        tz=timezone.utc
    ).year


def confidence_passes(row):

    score = row["confidence_score"]

    if score is None:
        return False

    return (
        score
        >= CONFIDENCE_THRESHOLD
    )


def regime_passes(row):

    regime = (
        row["combined_regime"]
        or ""
    )

    if REGIME_MODE == "ANY":
        return True

    if REGIME_MODE == "BULL_ONLY":
        return (
            regime.startswith("BULL")
        )

    if REGIME_MODE == "BEAR_ONLY":
        return (
            regime.startswith("BEAR")
        )

    if REGIME_MODE == "TREND_ONLY":
        return (
            regime.startswith("BULL")
            or regime.startswith("BEAR")
        )

    if REGIME_MODE == "LONG_FRIENDLY":
        return (
            regime.startswith("BULL")
        )

    if REGIME_MODE == "SHORT_FRIENDLY":
        return (
            regime.startswith("BEAR")
        )

    return True


def mtf_passes(row):

    status = (
        row["mtf_status"]
        or ""
    )

    if MTF_MODE == "ANY":
        return True

    if MTF_MODE == "CONFIRMED":
        return (
            status == "CONFIRMED"
        )

    if MTF_MODE == "NOT_CONFLICT":
        return (
            status
            != "CONFLICT"
        )

    return True


def direction_passes(signal):

    if DIRECTION_MODE == "BOTH":
        return signal in (
            "LONG",
            "SHORT"
        )

    if DIRECTION_MODE == "LONG_ONLY":
        return signal == "LONG"

    if DIRECTION_MODE == "SHORT_ONLY":
        return signal == "SHORT"

    return False


def signal_passes(row):

    signal = (
        row["final_signal"]
        or ""
    )

    if signal not in (
        "LONG",
        "SHORT"
    ):
        return False

    if not direction_passes(
        signal
    ):
        return False

    if not confidence_passes(
        row
    ):
        return False

    if not regime_passes(
        row
    ):
        return False

    if not mtf_passes(
        row
    ):
        return False

    return True


def calculate_position_size(
    balance
):

    position_size = (
        balance
        * RISK_FRACTION
    )

    position_size = min(
        position_size,
        MAX_POSITION_USD
    )

    return max(
        0.0,
        position_size
    )


def apply_entry_slippage(
    price,
    side
):

    if side == "LONG":

        return (
            price
            * (
                1
                + SLIPPAGE_RATE
            )
        )

    return (
        price
        * (
            1
            - SLIPPAGE_RATE
        )
    )


def apply_exit_slippage(
    price,
    side
):

    if side == "LONG":

        return (
            price
            * (
                1
                - SLIPPAGE_RATE
            )
        )

    return (
        price
        * (
            1
            + SLIPPAGE_RATE
        )
    )


def calculate_return_pct(
    side,
    entry_price,
    exit_price
):

    if entry_price <= 0:
        return 0.0

    if side == "LONG":

        return (
            (
                exit_price
                - entry_price
            )
            / entry_price
        )

    return (
        (
            entry_price
            - exit_price
        )
        / entry_price
    )


def calculate_max_drawdown(
    equity_curve
):

    if not equity_curve:
        return 0.0

    peak = (
        equity_curve[0]
    )

    max_drawdown = 0.0

    for equity in equity_curve:

        if equity > peak:
            peak = equity

        if peak <= 0:
            continue

        drawdown = (
            (
                peak
                - equity
            )
            / peak
        ) * 100

        if (
            drawdown
            > max_drawdown
        ):
            max_drawdown = drawdown

    return max_drawdown


def evaluate_period(
    rows,
    label
):

    print(
        "\n"
        + "=" * 60
    )

    print(
        f"RUNNING: {label}"
    )

    print(
        "=" * 60
    )

    balance = (
        INITIAL_BALANCE
    )

    equity_curve = [
        balance
    ]

    trades = []

    wins = 0
    losses = 0

    gross_profit = 0.0
    gross_loss = 0.0

    index = 0

    total_rows = (
        len(rows)
    )

    while (
        index
        < total_rows - 1
    ):

        row = rows[index]

        if not signal_passes(
            row
        ):

            index += 1
            continue

        side = (
            row["final_signal"]
        )

        entry_index = (
            index + 1
        )

        if (
            entry_index
            >= total_rows
        ):
            break

        exit_index = min(
            entry_index
            + HOLDING_HOURS,
            total_rows - 1
        )

        entry_row = (
            rows[entry_index]
        )

        exit_row = (
            rows[exit_index]
        )

        raw_entry_price = (
            entry_row["open"]
        )

        raw_exit_price = (
            exit_row["close"]
        )

        if (
            raw_entry_price is None
            or raw_exit_price is None
        ):

            index += 1
            continue

        if (
            raw_entry_price <= 0
            or raw_exit_price <= 0
        ):

            index += 1
            continue

        position_size = (
            calculate_position_size(
                balance
            )
        )

        if position_size <= 0:
            break

        entry_price = (
            apply_entry_slippage(
                raw_entry_price,
                side
            )
        )

        exit_price = (
            apply_exit_slippage(
                raw_exit_price,
                side
            )
        )

        gross_return = (
            calculate_return_pct(
                side,
                entry_price,
                exit_price
            )
        )

        gross_pnl = (
            position_size
            * gross_return
        )

        entry_fee = (
            position_size
            * FEE_RATE
        )

        exit_notional = (
            position_size
            * (
                exit_price
                / entry_price
            )
        )

        exit_fee = (
            exit_notional
            * FEE_RATE
        )

        total_fees = (
            entry_fee
            + exit_fee
        )

        net_pnl = (
            gross_pnl
            - total_fees
        )

        balance += (
            net_pnl
        )

        if balance < 0:
            balance = 0.0

        equity_curve.append(
            balance
        )

        if net_pnl > 0:

            wins += 1

            gross_profit += (
                net_pnl
            )

        else:

            losses += 1

            gross_loss += abs(
                net_pnl
            )

        trades.append({
            "period": label,

            "signal_time": (
                row["open_time"]
            ),

            "entry_time": (
                entry_row["open_time"]
            ),

            "exit_time": (
                exit_row["open_time"]
            ),

            "side": side,

            "confidence_score": (
                row[
                    "confidence_score"
                ]
            ),

            "combined_regime": (
                row[
                    "combined_regime"
                ]
            ),

            "mtf_status": (
                row[
                    "mtf_status"
                ]
            ),

            "entry_price": (
                entry_price
            ),

            "exit_price": (
                exit_price
            ),

            "position_size": (
                position_size
            ),

            "gross_return_pct": (
                gross_return
                * 100
            ),

            "gross_pnl": (
                gross_pnl
            ),

            "fees": (
                total_fees
            ),

            "net_pnl": (
                net_pnl
            ),

            "balance": (
                balance
            ),
        })

        # IMPORTANT:
        # Move directly past the position.
        # This prevents overlapping trades.
        index = (
            exit_index + 1
        )

    total_trades = (
        len(trades)
    )

    win_rate = 0.0

    if total_trades > 0:

        win_rate = (
            wins
            / total_trades
        ) * 100

    profit_factor = 0.0

    if gross_loss > 0:

        profit_factor = (
            gross_profit
            / gross_loss
        )

    elif gross_profit > 0:

        profit_factor = float(
            "inf"
        )

    average_return = 0.0

    if total_trades > 0:

        average_return = (
            sum(
                trade[
                    "gross_return_pct"
                ]
                for trade in trades
            )
            / total_trades
        )

    net_return = (
        (
            balance
            - INITIAL_BALANCE
        )
        / INITIAL_BALANCE
    ) * 100

    max_drawdown = (
        calculate_max_drawdown(
            equity_curve
        )
    )

    return {
        "label": label,

        "trades": trades,

        "balance": balance,

        "total_trades": (
            total_trades
        ),

        "wins": wins,

        "losses": losses,

        "win_rate": (
            win_rate
        ),

        "gross_profit": (
            gross_profit
        ),

        "gross_loss": (
            gross_loss
        ),

        "profit_factor": (
            profit_factor
        ),

        "average_return": (
            average_return
        ),

        "net_return": (
            net_return
        ),

        "max_drawdown": (
            max_drawdown
        ),
    }


def print_results(
    results
):

    print(
        f"\n{results['label']}"
    )

    print(
        "-" * 60
    )

    print(
        f"Trades:          "
        f"{results['total_trades']}"
    )

    print(
        f"Wins:            "
        f"{results['wins']}"
    )

    print(
        f"Losses:          "
        f"{results['losses']}"
    )

    print(
        f"Accuracy:        "
        f"{results['win_rate']:.2f}%"
    )

    print(
        f"Avg return:      "
        f"{results['average_return']:.4f}%"
    )

    print(
        f"Profit factor:   "
        f"{results['profit_factor']:.2f}"
    )

    print(
        f"Net return:      "
        f"{results['net_return']:.2f}%"
    )

    print(
        f"Max drawdown:    "
        f"{results['max_drawdown']:.2f}%"
    )

    print(
        f"Final balance:   "
        f"${results['balance']:.2f}"
    )


def write_trade_results(
    results_list
):

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    output_file = (
        f"{OUTPUT_DIR}/"
        "portfolio_walk_forward_trades.csv"
    )

    print(
        "\nWriting/replacing: "
        f"{output_file}"
    )

    fieldnames = [
        "period",
        "signal_time",
        "entry_time",
        "exit_time",
        "side",
        "confidence_score",
        "combined_regime",
        "mtf_status",
        "entry_price",
        "exit_price",
        "position_size",
        "gross_return_pct",
        "gross_pnl",
        "fees",
        "net_pnl",
        "balance",
    ]

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = (
            csv.DictWriter(
                file,
                fieldnames=fieldnames
            )
        )

        writer.writeheader()

        for results in results_list:

            for trade in (
                results["trades"]
            ):

                writer.writerow(
                    trade
                )

    print(
        "Trade results saved."
    )

    return output_file


def write_summary(
    results_list
):

    output_file = (
        f"{OUTPUT_DIR}/"
        "portfolio_walk_forward_summary.csv"
    )

    print(
        "Writing/replacing: "
        f"{output_file}"
    )

    fieldnames = [
        "period",
        "total_trades",
        "wins",
        "losses",
        "win_rate",
        "average_return",
        "profit_factor",
        "net_return",
        "max_drawdown",
        "final_balance",
    ]

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = (
            csv.DictWriter(
                file,
                fieldnames=fieldnames
            )
        )

        writer.writeheader()

        for results in results_list:

            writer.writerow({
                "period": (
                    results["label"]
                ),

                "total_trades": (
                    results[
                        "total_trades"
                    ]
                ),

                "wins": (
                    results["wins"]
                ),

                "losses": (
                    results["losses"]
                ),

                "win_rate": (
                    results[
                        "win_rate"
                    ]
                ),

                "average_return": (
                    results[
                        "average_return"
                    ]
                ),

                "profit_factor": (
                    results[
                        "profit_factor"
                    ]
                ),

                "net_return": (
                    results[
                        "net_return"
                    ]
                ),

                "max_drawdown": (
                    results[
                        "max_drawdown"
                    ]
                ),

                "final_balance": (
                    results[
                        "balance"
                    ]
                ),
            })

    print(
        "Summary saved."
    )

    return output_file


def make_decision(
    development,
    holdout
):

    if (
        holdout[
            "total_trades"
        ]
        < 10
    ):

        return (
            "INSUFFICIENT_DATA"
        )

    if (
        holdout[
            "profit_factor"
        ]
        < 1.05
    ):

        return (
            "REJECT"
        )

    if (
        holdout[
            "max_drawdown"
        ]
        > 25
    ):

        return (
            "RISK_WARNING"
        )

    if (
        holdout[
            "net_return"
        ]
        <= 0
    ):

        return (
            "REJECT"
        )

    if (
        holdout[
            "profit_factor"
        ]
        >= 1.15
        and holdout[
            "max_drawdown"
        ]
        <= 20
    ):

        return (
            "PAPER_TRADING_CANDIDATE"
        )

    return (
        "NEEDS_MORE_VALIDATION"
    )


def main():

    print(
        "=" * 60
    )

    print(
        "HEX SENTINEL PORTFOLIO "
        "WALK-FORWARD VALIDATION"
    )

    print(
        "=" * 60
    )

    print(
        "\nLoading core signals..."
    )

    print(
        f"File: {DATA_FILE}"
    )

    rows = load_rows(
        DATA_FILE
    )

    print(
        f"Rows loaded: "
        f"{len(rows)}"
    )

    development_rows = [
        row
        for row in rows
        if get_year(
            row["open_time"]
        )
        in (
            2023,
            2024
        )
    ]

    holdout_rows = [
        row
        for row in rows
        if get_year(
            row["open_time"]
        )
        == 2025
    ]

    print(
        f"\nDevelopment rows "
        f"(2023-2024): "
        f"{len(development_rows)}"
    )

    print(
        f"Holdout rows "
        f"(2025): "
        f"{len(holdout_rows)}"
    )

    print(
        "\nStrategy configuration:"
    )

    print(
        f"Confidence >= "
        f"{CONFIDENCE_THRESHOLD}"
    )

    print(
        f"Regime: "
        f"{REGIME_MODE}"
    )

    print(
        f"MTF: "
        f"{MTF_MODE}"
    )

    print(
        f"Direction: "
        f"{DIRECTION_MODE}"
    )

    print(
        f"Holding period: "
        f"{HOLDING_HOURS}h"
    )

    print(
        f"Position fraction: "
        f"{RISK_FRACTION * 100:.1f}%"
    )

    print(
        f"Maximum position: "
        f"${MAX_POSITION_USD:.2f}"
    )

    print(
        "\nRUNNING DEVELOPMENT "
        "EVALUATION..."
    )

    development = (
        evaluate_period(
            development_rows,
            "DEVELOPMENT_2023_2024"
        )
    )

    print(
        "\nRUNNING UNTOUCHED "
        "HOLDOUT EVALUATION..."
    )

    holdout = (
        evaluate_period(
            holdout_rows,
            "HOLDOUT_2025"
        )
    )

    results_list = [
        development,
        holdout,
    ]

    print(
        "\n"
        + "=" * 60
    )

    print(
        "PORTFOLIO WALK-FORWARD "
        "RESULTS"
    )

    print(
        "=" * 60
    )

    print_results(
        development
    )

    print_results(
        holdout
    )

    trade_file = (
        write_trade_results(
            results_list
        )
    )

    summary_file = (
        write_summary(
            results_list
        )
    )

    decision = (
        make_decision(
            development,
            holdout
        )
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
        "\nIMPORTANT:"
    )

    print(
        "This validation now "
        "prevents overlapping "
        "48-hour positions."
    )

    print(
        "A strategy must pass "
        "the untouched holdout "
        "before moving toward "
        "paper trading."
    )

    print(
        "\nDetail results:"
    )

    print(
        trade_file
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
        "PORTFOLIO WALK-FORWARD "
        "VALIDATION COMPLETE"
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()
