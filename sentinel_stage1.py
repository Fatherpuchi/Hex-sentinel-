import sqlite3
import time
import math
import requests
import numpy as np
import os
from datetime import datetime, timezone

# ============================================================
# BINANCE SENTINEL AI
# STAGE 1 — PROOF OF EDGE ENGINE
#
# IMPORTANT:
# This program DOES NOT place real trades.
# It only downloads public market data, backtests,
# evaluates the strategy, and records paper signals.
# ============================================================

DB_FILE = "sentinel.db"

SYMBOL = os.getenv("SENTINEL_SYMBOL", "BTCUSDT").upper()
INTERVAL = "1h"

# Number of historical candles to download
CANDLES = 5000

# Trading assumptions
STARTING_BALANCE = 100.0
FEE_RATE = 0.001          # 0.10% per side
SLIPPAGE_RATE = 0.0005   # 0.05%

# Strategy parameters
FAST_EMA = 20
SLOW_EMA = 50
RSI_PERIOD = 14

# Risk assumptions
RISK_PER_TRADE = 0.01
STOP_LOSS_PERCENT = 0.02

# Approval thresholds
MIN_TRADES = 30
MIN_PROFIT_FACTOR = 1.10
MIN_EXPECTANCY = 0.0
MAX_DRAWDOWN = 0.20


# ============================================================
# DATABASE
# ============================================================

def initialize_database():
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_validation TEXT,
            notes TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            version TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            candles INTEGER,
            starting_balance REAL,
            ending_balance REAL,
            total_return REAL,
            win_rate REAL,
            profit_factor REAL,
            expectancy REAL,
            max_drawdown REAL,
            total_trades INTEGER,
            fees_paid REAL,
            slippage_cost REAL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            version TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal TEXT NOT NULL,
            price REAL,
            created_at TEXT NOT NULL,
            outcome TEXT DEFAULT 'PENDING'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS walk_forward_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            version TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            fold INTEGER NOT NULL,
            trades INTEGER,
            total_return REAL,
            profit_factor REAL,
            max_drawdown REAL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# BINANCE PUBLIC MARKET DATA
# ============================================================

def fetch_binance_data(symbol, interval, limit):
    print(f"\n📡 Downloading {limit} candles...")
    print(f"   Symbol: {symbol}")
    print(f"   Interval: {interval}")

    url = "https://api.binance.com/api/v3/klines"

    all_data = []
    end_time = None

    while len(all_data) < limit:
        batch_limit = min(1000, limit - len(all_data))

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": batch_limit
        }

        if end_time:
            params["endTime"] = end_time

        # STAGE 7.6.8.4 — BINANCE MARKET-DATA RETRY HARDENING
        response = None
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=15
                )
                response.raise_for_status()
                break

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError
            ) as e:
                if attempt == max_attempts:
                    print(
                        f"❌ BINANCE MARKET DATA FAILED "
                        f"AFTER {max_attempts} ATTEMPTS"
                    )
                    raise

                wait_seconds = 2 ** (attempt - 1)

                print(
                    f"⚠️ Binance market-data attempt "
                    f"{attempt}/{max_attempts} failed: {type(e).__name__}"
                )
                print(
                    f"   Retrying in {wait_seconds}s..."
                )

                time.sleep(wait_seconds)

        batch = response.json()

        if not batch:
            break

        all_data = batch + all_data

        end_time = batch[0][0] - 1

        if len(batch) < batch_limit:
            break

        time.sleep(0.2)

    all_data = all_data[-limit:]

    columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore"
    ]

    # Pandas-free candle processing
    rows = []

    for item in all_data:
        row = dict(zip(columns, item))

        for column in ["open", "high", "low", "close", "volume"]:
            row[column] = float(row[column])

        row["open_time"] = int(row["open_time"])
        row["datetime"] = datetime.fromtimestamp(
            row["open_time"] / 1000,
            tz=timezone.utc
        )

        rows.append(row)

    # Sort chronologically and remove duplicate timestamps
    rows.sort(key=lambda x: x["datetime"])

    unique_rows = []
    seen = set()

    for row in rows:
        if row["datetime"] not in seen:
            seen.add(row["datetime"])
            unique_rows.append(row)

    return unique_rows


# ============================================================
# INDICATORS
# ============================================================

def calculate_rsi(values, period=14):
    values = np.asarray(values, dtype=float)

    if len(values) < period + 1:
        return np.full(len(values), np.nan)

    delta = np.diff(values, prepend=values[0])

    gains = np.maximum(delta, 0)
    losses = np.maximum(-delta, 0)

    rsi = np.full(len(values), np.nan)

    for i in range(period, len(values)):
        avg_gain = np.mean(gains[i - period + 1:i + 1])
        avg_loss = np.mean(losses[i - period + 1:i + 1])

        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))

    return rsi


def calculate_ema(values, span):
    values = np.asarray(values, dtype=float)

    ema = np.empty(len(values))
    ema[0] = values[0]

    alpha = 2 / (span + 1)

    for i in range(1, len(values)):
        ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]

    return ema


def prepare_indicators(df):
    rows = [dict(row) for row in df]

    closes = np.array([row["close"] for row in rows], dtype=float)

    ema_fast = calculate_ema(closes, FAST_EMA)
    ema_slow = calculate_ema(closes, SLOW_EMA)
    rsi = calculate_rsi(closes, RSI_PERIOD)

    prepared = []

    for i, row in enumerate(rows):
        if not (
            np.isnan(ema_fast[i])
            or np.isnan(ema_slow[i])
            or np.isnan(rsi[i])
        ):
            row["ema_fast"] = float(ema_fast[i])
            row["ema_slow"] = float(ema_slow[i])
            row["rsi"] = float(rsi[i])
            prepared.append(row)

    return prepared


# ============================================================
# STRATEGY
# ============================================================

def generate_signal(row):
    """
    Simple baseline strategy.

    LONG:
      Fast EMA > Slow EMA
      RSI between 50 and 70

    EXIT:
      Fast EMA < Slow EMA

    This is intentionally simple.
    Stage 1 is about building and testing the engine,
    not pretending this strategy is already profitable.
    """

    if row["ema_fast"] > row["ema_slow"]:
        if 50 <= row["rsi"] <= 70:
            return "BUY"

    if row["ema_fast"] < row["ema_slow"]:
        return "SELL"

    return "HOLD"


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(df):
    balance = STARTING_BALANCE

    equity_curve = [balance]

    position = None
    entry_price = None
    position_size = 0

    trades = []

    total_fees = 0
    total_slippage = 0

    for i in range(1, len(df)):
        row = df[i]

        signal = generate_signal(row)

        current_price = float(row["close"])

        # ----------------------------------------------------
        # ENTER LONG
        # ----------------------------------------------------

        if position is None and signal == "BUY":

            risk_amount = balance * RISK_PER_TRADE

            if STOP_LOSS_PERCENT <= 0:
                continue

            position_value = risk_amount / STOP_LOSS_PERCENT

            # Never allocate more than available capital
            position_value = min(position_value, balance)

            if position_value <= 0:
                continue

            # Simulated adverse slippage for a BUY
            actual_entry = current_price * (1 + SLIPPAGE_RATE)

            fee = position_value * FEE_RATE

            total_fees += fee
            total_slippage += position_value * SLIPPAGE_RATE

            position_size = (
                position_value - fee
            ) / actual_entry

            entry_price = actual_entry
            position = "LONG"

        # ----------------------------------------------------
        # EXIT LONG
        # ----------------------------------------------------

        elif position == "LONG" and signal == "SELL":

            exit_value = position_size * current_price

            # Simulated adverse slippage for SELL
            actual_exit = current_price * (1 - SLIPPAGE_RATE)

            exit_value = position_size * actual_exit

            fee = exit_value * FEE_RATE

            total_fees += fee
            total_slippage += exit_value * SLIPPAGE_RATE

            pnl = (
                exit_value
                - fee
                - (position_size * entry_price)
            )

            balance += pnl

            trades.append(pnl)

            position = None
            entry_price = None
            position_size = 0

        equity_curve.append(balance)

    # Close remaining position at final price
    if position == "LONG":

        final_price = float(df[-1]["close"])

        exit_value = position_size * final_price

        actual_exit = final_price * (1 - SLIPPAGE_RATE)

        exit_value = position_size * actual_exit

        fee = exit_value * FEE_RATE

        total_fees += fee

        pnl = (
            exit_value
            - fee
            - (position_size * entry_price)
        )

        balance += pnl

        trades.append(pnl)

        equity_curve.append(balance)

    return {
        "starting_balance": STARTING_BALANCE,
        "ending_balance": balance,
        "trades": trades,
        "equity_curve": equity_curve,
        "fees": total_fees,
        "slippage": total_slippage
    }


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(results):

    trades = results["trades"]

    total_trades = len(trades)

    if total_trades == 0:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "max_drawdown": 1,
            "total_return": 0
        }

    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x < 0]

    win_rate = len(wins) / total_trades

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss == 0:
        profit_factor = float("inf")
    else:
        profit_factor = gross_profit / gross_loss

    expectancy = sum(trades) / total_trades

    equity = np.array(results["equity_curve"])

    peaks = np.maximum.accumulate(equity)

    drawdowns = (
        peaks - equity
    ) / peaks

    max_drawdown = float(np.max(drawdowns))

    total_return = (
        results["ending_balance"]
        / results["starting_balance"]
    ) - 1

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "max_drawdown": max_drawdown,
        "total_return": total_return
    }


# ============================================================
# STRATEGY APPROVAL GATE
# ============================================================

def approval_gate(metrics):

    trades = metrics["total_trades"]
    pf = metrics["profit_factor"]
    expectancy = metrics["expectancy"]
    drawdown = metrics["max_drawdown"]

    # Insufficient evidence
    if trades < MIN_TRADES:
        return "WATCH"

    # Clear failure
    if expectancy <= MIN_EXPECTANCY:
        return "REJECTED"

    if drawdown > MAX_DRAWDOWN:
        return "REJECTED"

    if pf < MIN_PROFIT_FACTOR:
        return "WATCH"

    return "APPROVED"


# ============================================================
# WALK-FORWARD TEST
# ============================================================

def walk_forward_test(df, folds=5):

    print("\n🔄 WALK-FORWARD TEST")

    fold_results = []

    fold_size = len(df) // folds

    for i in range(folds):

        start = i * fold_size

        end = (
            len(df)
            if i == folds - 1
            else (i + 1) * fold_size
        )

        test_df = df[start:end]

        if len(test_df) < 100:
            continue

        results = run_backtest(test_df)

        metrics = calculate_metrics(results)

        fold_results.append(metrics)

        print(
            f"   Fold {i + 1}: "
            f"Trades={metrics['total_trades']} | "
            f"Return={metrics['total_return']:.2%} | "
            f"PF={metrics['profit_factor']:.2f} | "
            f"DD={metrics['max_drawdown']:.2%}"
        )

    return fold_results


# ============================================================
# DATABASE RECORDING
# ============================================================

def save_backtest(metrics, results, strategy_name, version):

    conn = sqlite3.connect(DB_FILE)

    now = datetime.now(timezone.utc).isoformat()

    conn.execute("""
        INSERT INTO backtests (
            strategy_name,
            version,
            symbol,
            interval,
            candles,
            starting_balance,
            ending_balance,
            total_return,
            win_rate,
            profit_factor,
            expectancy,
            max_drawdown,
            total_trades,
            fees_paid,
            slippage_cost,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        strategy_name,
        version,
        SYMBOL,
        INTERVAL,
        len(results["equity_curve"]),
        results["starting_balance"],
        results["ending_balance"],
        metrics["total_return"],
        metrics["win_rate"],
        metrics["profit_factor"],
        metrics["expectancy"],
        metrics["max_drawdown"],
        metrics["total_trades"],
        results["fees"],
        results["slippage"],
        now
    ))

    conn.commit()
    conn.close()


def save_strategy_status(strategy_name, version, status):

    conn = sqlite3.connect(DB_FILE)

    now = datetime.now(timezone.utc).isoformat()

    conn.execute("""
        INSERT INTO strategies (
            strategy_name,
            version,
            status,
            created_at,
            last_validation,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        strategy_name,
        version,
        status,
        now,
        now,
        "Stage 1 automated validation"
    ))

    conn.commit()
    conn.close()



# ============================================================
# WALK-FORWARD AUDIT RECORDING
# ============================================================

def save_walk_forward_results(walk_forward, strategy_name, version):

    conn = sqlite3.connect(DB_FILE)

    now = datetime.now(timezone.utc).isoformat()

    for i, metrics in enumerate(walk_forward, start=1):

        conn.execute("""
            INSERT INTO walk_forward_results (
                strategy_name,
                version,
                symbol,
                interval,
                fold,
                trades,
                total_return,
                profit_factor,
                max_drawdown,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            strategy_name,
            version,
            SYMBOL,
            INTERVAL,
            i,
            metrics["total_trades"],
            metrics["total_return"],
            metrics["profit_factor"],
            metrics["max_drawdown"],
            now
        ))

    conn.commit()
    conn.close()


# ============================================================
# PAPER SIGNAL
# ============================================================

def generate_paper_signal(df, strategy_name, version, status):

    latest = df[-1]

    signal = generate_signal(latest)

    # Only approved strategies can generate live-eligible signals.
    # WATCH remains paper-only.
    if status == "REJECTED":
        signal = "BLOCKED"

    price = float(latest["close"])

    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        INSERT INTO paper_signals (
            strategy_name,
            version,
            symbol,
            signal,
            price,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        strategy_name,
        version,
        SYMBOL,
        signal,
        price,
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()
    conn.close()

    return signal, price


# ============================================================
# REPORT
# ============================================================

def print_report(metrics, walk_forward, status):

    print("\n")
    print("=" * 60)
    print("🤖 BINANCE SENTINEL AI — STAGE 1 REPORT")
    print("=" * 60)

    print(f"\n📊 Symbol:              {SYMBOL}")
    print(f"⏱️ Interval:            {INTERVAL}")

    print(
        f"\n💰 Starting Balance:   "
        f"${STARTING_BALANCE:.2f}"
    )

    print(
        f"💰 Ending Balance:     "
        f"${metrics.get('ending_balance', 0):.2f}"
    )

    print(
        f"📈 Total Return:       "
        f"{metrics['total_return']:.2%}"
    )

    print(
        f"🎯 Total Trades:       "
        f"{metrics['total_trades']}"
    )

    print(
        f"🏆 Win Rate:           "
        f"{metrics['win_rate']:.2%}"
    )

    print(
        f"📊 Profit Factor:      "
        f"{metrics['profit_factor']:.2f}"
    )

    print(
        f"💵 Expectancy/Trade:   "
        f"${metrics['expectancy']:.4f}"
    )

    print(
        f"📉 Max Drawdown:       "
        f"{metrics['max_drawdown']:.2%}"
    )

    print(
        f"💸 Fees Paid:          "
        f"${metrics.get('fees', 0):.4f}"
    )

    print(
        f"📉 Slippage Cost:      "
        f"${metrics.get('slippage', 0):.4f}"
    )

    print("\n🔄 Walk-Forward Summary")

    if walk_forward:

        for i, result in enumerate(walk_forward, 1):

            print(
                f"   Fold {i}: "
                f"{result['total_return']:.2%} return | "
                f"PF {result['profit_factor']:.2f} | "
                f"DD {result['max_drawdown']:.2%}"
            )

    print("\n🏆 STRATEGY APPROVAL STATUS")

    if status == "APPROVED":
        print("   🟢 APPROVED")

    elif status == "WATCH":
        print("   🟡 WATCH — PAPER TRADING ONLY")

    else:
        print("   🔴 REJECTED — LIVE EXECUTION BLOCKED")

    print("\n" + "=" * 60)


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n🤖 BINANCE SENTINEL AI")
    print("🧪 STAGE 1 — PROOF OF EDGE ENGINE")
    print("⚠️ PAPER/BACKTEST ONLY — NO REAL ORDERS\n")

    initialize_database()

    strategy_name = "EMA_RSI_BASELINE"
    version = "1.0"

    try:

        df = fetch_binance_data(
            SYMBOL,
            INTERVAL,
            CANDLES
        )

    except Exception as e:

        print("\n❌ MARKET DATA ERROR")
        print(str(e))
        return

    if len(df) < 200:

        print("\n❌ Not enough market data.")
        return

    print(
        f"\n✅ Downloaded {len(df)} candles."
    )

    df = prepare_indicators(df)

    # --------------------------------------------------------
    # Full backtest
    # --------------------------------------------------------

    print("\n🔬 Running full backtest...")

    results = run_backtest(df)

    metrics = calculate_metrics(results)

    # Add costs for reporting
    metrics["ending_balance"] = results["ending_balance"]
    metrics["fees"] = results["fees"]
    metrics["slippage"] = results["slippage"]

    # --------------------------------------------------------
    # Walk forward
    # --------------------------------------------------------

    walk_forward = walk_forward_test(df)

    save_walk_forward_results(
        walk_forward,
        strategy_name,
        version
    )

    # --------------------------------------------------------
    # Approval
    # --------------------------------------------------------

    status = approval_gate(metrics)

    save_backtest(
        metrics,
        results,
        strategy_name,
        version
    )

    save_strategy_status(
        strategy_name,
        version,
        status
    )

    # --------------------------------------------------------
    # Paper signal
    # --------------------------------------------------------

    signal, price = generate_paper_signal(
        df,
        strategy_name,
        version,
        status
    )

    print_report(
        metrics,
        walk_forward,
        status
    )

    print(
        f"\n📡 Latest Price: ${price:,.2f}"
    )

    print(
        f"📄 Paper Signal: {signal}"
    )

    print(
        "\n💾 Results saved to sentinel.db"
    )

    print(
        "\n✅ Stage 1 run completed."
    )

    return {
        "symbol": SYMBOL,
        "metrics": metrics,
        "walk_forward": walk_forward,
        "status": status,
        "signal": signal,
        "price": price
    }


if __name__ == "__main__":
    main()
