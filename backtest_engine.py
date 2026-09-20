import csv
from datetime import datetime, timezone


DATA_FILE = "historical_data/processed/BTCUSDT_1h_2023_2025.csv"

INITIAL_BALANCE = 1000.0
POSITION_SIZE_USD = 100.0

STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.04


def ms_to_datetime(ms):
    return datetime.fromtimestamp(
        int(ms) / 1000,
        tz=timezone.utc
    )


def load_candles(filename):

    candles = []

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            candles.append({
                "open_time": int(row["open_time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })

    return candles


def calculate_pnl(side, entry_price, exit_price):

    if side == "LONG":
        price_change = (
            exit_price - entry_price
        ) / entry_price

    else:
        price_change = (
            entry_price - exit_price
        ) / entry_price

    return POSITION_SIZE_USD * price_change


def run_backtest(candles):

    balance = INITIAL_BALANCE

    total_trades = 0
    wins = 0
    losses = 0

    trade_results = []

    position = None

    for candle in candles:

        if position is None:
            continue

        side = position["side"]

        entry_price = position["entry_price"]
        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]

        exit_price = None
        exit_reason = None

        if side == "LONG":

            if candle["low"] <= stop_loss:
                exit_price = stop_loss
                exit_reason = "STOP_LOSS"

            elif candle["high"] >= take_profit:
                exit_price = take_profit
                exit_reason = "TAKE_PROFIT"

        elif side == "SHORT":

            if candle["high"] >= stop_loss:
                exit_price = stop_loss
                exit_reason = "STOP_LOSS"

            elif candle["low"] <= take_profit:
                exit_price = take_profit
                exit_reason = "TAKE_PROFIT"

        if exit_price is not None:

            pnl = calculate_pnl(
                side,
                entry_price,
                exit_price
            )

            balance += pnl
            total_trades += 1

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            trade_results.append({
                "side": side,
                "entry_time": position["entry_time"],
                "exit_time": candle["open_time"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "reason": exit_reason,
                "pnl": pnl,
                "balance": balance,
            })

            position = None

    return {
        "balance": balance,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "trades": trade_results,
    }


def print_summary(results):

    total_trades = results["total_trades"]
    wins = results["wins"]
    losses = results["losses"]

    win_rate = (
        (wins / total_trades) * 100
        if total_trades > 0
        else 0
    )

    net_pnl = (
        results["balance"]
        - INITIAL_BALANCE
    )

    print("\n" + "=" * 60)
    print("HEX SENTINEL BACKTEST ENGINE")
    print("=" * 60)

    print(f"Starting balance: ${INITIAL_BALANCE:.2f}")
    print(f"Final balance:    ${results['balance']:.2f}")
    print(f"Net P&L:          ${net_pnl:.2f}")

    print("-" * 60)

    print(f"Total trades:     {total_trades}")
    print(f"Wins:             {wins}")
    print(f"Losses:           {losses}")
    print(f"Win rate:         {win_rate:.2f}%")

    print("=" * 60)

    if results["trades"]:

        print("\nLAST 5 TRADES")

        for trade in results["trades"][-5:]:

            print(
                f"{trade['side']} | "
                f"{trade['reason']} | "
                f"PnL: ${trade['pnl']:.2f} | "
                f"Balance: ${trade['balance']:.2f}"
            )


def main():

    print("\nLOADING DATA...")
    print(f"File: {DATA_FILE}")

    candles = load_candles(DATA_FILE)

    print(f"Candles loaded: {len(candles)}")

    print("\nRUNNING BACKTEST...")

    results = run_backtest(candles)

    print_summary(results)


if __name__ == "__main__":
    main()
