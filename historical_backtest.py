import csv
import os
from datetime import datetime, timezone


DATA_FILE = "historical_data/features/BTCUSDT_1h_features.csv"
TRADE_LOG_FILE = "historical_data/backtests/BTCUSDT_1h_trade_log.csv"

INITIAL_BALANCE = 1000.0
POSITION_SIZE_USD = 100.0

STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.04

# Backtest assumptions.
# Change these later to match your actual Binance fee tier/execution model.
FEE_RATE = 0.0004
SLIPPAGE_RATE = 0.0002

RSI_LONG_MIN = 50.0
RSI_LONG_MAX = 70.0

RSI_SHORT_MIN = 30.0
RSI_SHORT_MAX = 50.0


def ms_to_datetime(ms):
    return datetime.fromtimestamp(
        int(ms) / 1000,
        tz=timezone.utc
    )


def safe_float(value):
    if value in (None, "", "None"):
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def load_candles(filename):

    candles = []

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            candle = {
                "open_time": int(row["open_time"]),
                "open": safe_float(row["open"]),
                "high": safe_float(row["high"]),
                "low": safe_float(row["low"]),
                "close": safe_float(row["close"]),
                "ema20": safe_float(row["ema20"]),
                "ema50": safe_float(row["ema50"]),
                "rsi14": safe_float(row["rsi14"]),
                "atr14": safe_float(row["atr14"]),
                "momentum12": safe_float(
                    row["momentum12"]
                ),
                "volume_ratio20": safe_float(
                    row["volume_ratio20"]
                ),
                "volatility20": safe_float(
                    row["volatility20"]
                ),
            }

            candles.append(candle)

    return candles


def long_signal(candle):

    required = [
        candle["ema20"],
        candle["ema50"],
        candle["rsi14"],
        candle["momentum12"],
    ]

    if any(value is None for value in required):
        return False

    return (
        candle["ema20"] > candle["ema50"]
        and RSI_LONG_MIN <= candle["rsi14"] <= RSI_LONG_MAX
        and candle["momentum12"] > 0
    )


def short_signal(candle):

    required = [
        candle["ema20"],
        candle["ema50"],
        candle["rsi14"],
        candle["momentum12"],
    ]

    if any(value is None for value in required):
        return False

    return (
        candle["ema20"] < candle["ema50"]
        and RSI_SHORT_MIN <= candle["rsi14"] <= RSI_SHORT_MAX
        and candle["momentum12"] < 0
    )


def apply_entry_slippage(side, price):

    if side == "LONG":
        return price * (
            1 + SLIPPAGE_RATE
        )

    return price * (
        1 - SLIPPAGE_RATE
    )


def apply_exit_slippage(side, price):

    if side == "LONG":
        return price * (
            1 - SLIPPAGE_RATE
        )

    return price * (
        1 + SLIPPAGE_RATE
    )


def calculate_gross_pnl(
    side,
    entry_price,
    exit_price
):

    if side == "LONG":

        price_change = (
            exit_price - entry_price
        ) / entry_price

    else:

        price_change = (
            entry_price - exit_price
        ) / entry_price

    return (
        POSITION_SIZE_USD
        * price_change
    )


def calculate_fees():

    entry_fee = (
        POSITION_SIZE_USD
        * FEE_RATE
    )

    exit_fee = (
        POSITION_SIZE_USD
        * FEE_RATE
    )

    return entry_fee + exit_fee


def calculate_drawdown(
    balance,
    peak_balance
):

    if peak_balance <= 0:
        return 0.0

    return (
        (
            peak_balance - balance
        )
        / peak_balance
    ) * 100


def run_backtest(candles):

    balance = INITIAL_BALANCE
    peak_balance = INITIAL_BALANCE
    max_drawdown = 0.0

    total_trades = 0
    wins = 0
    losses = 0

    gross_profit = 0.0
    gross_loss = 0.0

    long_trades = 0
    short_trades = 0

    trade_results = []

    position = None

    pending_signal = None

    skipped_warmup = 0

    for index, candle in enumerate(candles):

        # ==========================================
        # ENTER PENDING SIGNAL AT CURRENT OPEN
        # ==========================================

        if (
            position is None
            and pending_signal is not None
        ):

            side = pending_signal

            entry_price = apply_entry_slippage(
                side,
                candle["open"]
            )

            if side == "LONG":

                stop_loss = (
                    entry_price
                    * (
                        1
                        - STOP_LOSS_PCT
                    )
                )

                take_profit = (
                    entry_price
                    * (
                        1
                        + TAKE_PROFIT_PCT
                    )
                )

                long_trades += 1

            else:

                stop_loss = (
                    entry_price
                    * (
                        1
                        + STOP_LOSS_PCT
                    )
                )

                take_profit = (
                    entry_price
                    * (
                        1
                        - TAKE_PROFIT_PCT
                    )
                )

                short_trades += 1

            position = {
                "side": side,
                "entry_time": candle[
                    "open_time"
                ],
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }

            pending_signal = None

        # ==========================================
        # CHECK OPEN POSITION
        # ==========================================

        if position is not None:

            side = position["side"]

            entry_price = position[
                "entry_price"
            ]

            stop_loss = position[
                "stop_loss"
            ]

            take_profit = position[
                "take_profit"
            ]

            exit_price = None
            exit_reason = None

            # Conservative assumption:
            # if both SL and TP are touched
            # inside the same candle,
            # STOP LOSS is assumed first.

            if side == "LONG":

                if candle["low"] <= stop_loss:

                    exit_price = stop_loss
                    exit_reason = "STOP_LOSS"

                elif (
                    candle["high"]
                    >= take_profit
                ):

                    exit_price = take_profit
                    exit_reason = "TAKE_PROFIT"

            elif side == "SHORT":

                if candle["high"] >= stop_loss:

                    exit_price = stop_loss
                    exit_reason = "STOP_LOSS"

                elif (
                    candle["low"]
                    <= take_profit
                ):

                    exit_price = take_profit
                    exit_reason = "TAKE_PROFIT"

            if exit_price is not None:

                exit_price = apply_exit_slippage(
                    side,
                    exit_price
                )

                gross_pnl = (
                    calculate_gross_pnl(
                        side,
                        entry_price,
                        exit_price
                    )
                )

                fees = calculate_fees()

                net_pnl = (
                    gross_pnl
                    - fees
                )

                balance += net_pnl

                total_trades += 1

                if net_pnl > 0:

                    wins += 1
                    gross_profit += net_pnl

                else:

                    losses += 1
                    gross_loss += abs(
                        net_pnl
                    )

                if balance > peak_balance:

                    peak_balance = balance

                drawdown = (
                    calculate_drawdown(
                        balance,
                        peak_balance
                    )
                )

                if drawdown > max_drawdown:

                    max_drawdown = drawdown

                trade_results.append({

                    "side": side,

                    "entry_time": position[
                        "entry_time"
                    ],

                    "exit_time": candle[
                        "open_time"
                    ],

                    "entry_datetime":
                        ms_to_datetime(
                            position[
                                "entry_time"
                            ]
                        ),

                    "exit_datetime":
                        ms_to_datetime(
                            candle[
                                "open_time"
                            ]
                        ),

                    "entry_price":
                        entry_price,

                    "exit_price":
                        exit_price,

                    "stop_loss":
                        stop_loss,

                    "take_profit":
                        take_profit,

                    "reason":
                        exit_reason,

                    "gross_pnl":
                        gross_pnl,

                    "fees":
                        fees,

                    "net_pnl":
                        net_pnl,

                    "balance":
                        balance,

                    "drawdown_pct":
                        drawdown,

                })

                position = None

        # ==========================================
        # GENERATE NEW SIGNAL
        #
        # Signal uses completed candle.
        # Entry happens on next candle open.
        # ==========================================

        if position is None:

            if index < 50:

                skipped_warmup += 1
                continue

            if long_signal(candle):

                pending_signal = "LONG"

            elif short_signal(candle):

                pending_signal = "SHORT"

    # ==========================================
    # CLOSE ANY OPEN POSITION AT FINAL CLOSE
    # ==========================================

    if (
        position is not None
        and candles
    ):

        final_candle = candles[-1]

        side = position["side"]

        exit_price = apply_exit_slippage(
            side,
            final_candle["close"]
        )

        gross_pnl = (
            calculate_gross_pnl(
                side,
                position["entry_price"],
                exit_price
            )
        )

        fees = calculate_fees()

        net_pnl = (
            gross_pnl
            - fees
        )

        balance += net_pnl

        total_trades += 1

        if net_pnl > 0:

            wins += 1
            gross_profit += net_pnl

        else:

            losses += 1
            gross_loss += abs(
                net_pnl
            )

        if balance > peak_balance:

            peak_balance = balance

        drawdown = (
            calculate_drawdown(
                balance,
                peak_balance
            )
        )

        if drawdown > max_drawdown:

            max_drawdown = drawdown

        trade_results.append({

            "side": side,

            "entry_time":
                position[
                    "entry_time"
                ],

            "exit_time":
                final_candle[
                    "open_time"
                ],

            "entry_datetime":
                ms_to_datetime(
                    position[
                        "entry_time"
                    ]
                ),

            "exit_datetime":
                ms_to_datetime(
                    final_candle[
                        "open_time"
                    ]
                ),

            "entry_price":
                position[
                    "entry_price"
                ],

            "exit_price":
                exit_price,

            "stop_loss":
                position[
                    "stop_loss"
                ],

            "take_profit":
                position[
                    "take_profit"
                ],

            "reason":
                "END_OF_DATA",

            "gross_pnl":
                gross_pnl,

            "fees":
                fees,

            "net_pnl":
                net_pnl,

            "balance":
                balance,

            "drawdown_pct":
                drawdown,

        })

    profit_factor = (

        gross_profit
        / gross_loss

        if gross_loss > 0

        else (
            float("inf")
            if gross_profit > 0
            else 0.0
        )
    )

    return {

        "balance": balance,

        "total_trades":
            total_trades,

        "wins":
            wins,

        "losses":
            losses,

        "gross_profit":
            gross_profit,

        "gross_loss":
            gross_loss,

        "profit_factor":
            profit_factor,

        "max_drawdown":
            max_drawdown,

        "long_trades":
            long_trades,

        "short_trades":
            short_trades,

        "warmup_candles":
            skipped_warmup,

        "trades":
            trade_results,

    }


def write_trade_log(trades):

    directory = os.path.dirname(
        TRADE_LOG_FILE
    )

    os.makedirs(
        directory,
        exist_ok=True
    )

    fieldnames = [

        "side",

        "entry_time",

        "exit_time",

        "entry_datetime",

        "exit_datetime",

        "entry_price",

        "exit_price",

        "stop_loss",

        "take_profit",

        "reason",

        "gross_pnl",

        "fees",

        "net_pnl",

        "balance",

        "drawdown_pct",

    ]

    print(
        f"\nWriting/replacing: "
        f"{TRADE_LOG_FILE}"
    )

    with open(
        TRADE_LOG_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for trade in trades:

            writer.writerow(
                trade
            )

    print(
        "Trade log saved."
    )


def print_summary(results):

    total_trades = (
        results[
            "total_trades"
        ]
    )

    wins = (
        results[
            "wins"
        ]
    )

    losses = (
        results[
            "losses"
        ]
    )

    win_rate = (

        (
            wins
            / total_trades
        )
        * 100

        if total_trades > 0

        else 0.0
    )

    net_pnl = (

        results[
            "balance"
        ]

        - INITIAL_BALANCE

    )

    average_pnl = (

        net_pnl
        / total_trades

        if total_trades > 0

        else 0.0
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "HEX SENTINEL LARGE-SCALE BACKTEST"
    )

    print(
        "=" * 60
    )

    print(
        f"Starting balance: "
        f"${INITIAL_BALANCE:.2f}"
    )

    print(
        f"Final balance:    "
        f"${results['balance']:.2f}"
    )

    print(
        f"Net P&L:          "
        f"${net_pnl:.2f}"
    )

    print(
        f"Max drawdown:     "
        f"{results['max_drawdown']:.2f}%"
    )

    print(
        "-" * 60
    )

    print(
        f"Total trades:     "
        f"{total_trades}"
    )

    print(
        f"LONG trades:      "
        f"{results['long_trades']}"
    )

    print(
        f"SHORT trades:     "
        f"{results['short_trades']}"
    )

    print(
        f"Wins:             "
        f"{wins}"
    )

    print(
        f"Losses:           "
        f"{losses}"
    )

    print(
        f"Win rate:         "
        f"{win_rate:.2f}%"
    )

    print(
        f"Profit factor:    "
        f"{results['profit_factor']:.2f}"
    )

    print(
        f"Average P&L:      "
        f"${average_pnl:.2f}"
    )

    print(
        f"Gross profit:     "
        f"${results['gross_profit']:.2f}"
    )

    print(
        f"Gross loss:       "
        f"${results['gross_loss']:.2f}"
    )

    print(
        "=" * 60
    )

    if results["trades"]:

        print(
            "\nLAST 5 TRADES"
        )

        for trade in (
            results[
                "trades"
            ][-5:]
        ):

            print(

                f"{trade['side']} | "

                f"{trade['reason']} | "

                f"PnL: "
                f"${trade['net_pnl']:.2f} | "

                f"Balance: "
                f"${trade['balance']:.2f}"

            )


def main():

    print(
        "\nLOADING FEATURE DATA..."
    )

    print(
        f"File: "
        f"{DATA_FILE}"
    )

    candles = load_candles(
        DATA_FILE
    )

    print(
        f"Candles loaded: "
        f"{len(candles)}"
    )

    print(
        "\nRUNNING LARGE-SCALE BACKTEST..."
    )

    results = run_backtest(
        candles
    )

    write_trade_log(
        results[
            "trades"
        ]
    )

    print_summary(
        results
    )


if __name__ == "__main__":
    main()
