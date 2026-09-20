import csv
import os
from bisect import bisect_left
from collections import Counter


ONE_H_FILE = "historical_data/regimes/BTCUSDT_1h_regimes.csv"
FOUR_H_FILE = "historical_data/regimes/BTCUSDT_4h_regimes.csv"

OUTPUT_DIR = "historical_data/core"

CORE_OUTPUT = (
    f"{OUTPUT_DIR}/BTCUSDT_1h_core_signals.csv"
)

SUMMARY_OUTPUT = (
    f"{OUTPUT_DIR}/hex_sentinel_core_summary.csv"
)


# ============================================================
# DATA LOADING
# ============================================================

def safe_float(value):

    if value is None or value == "":
        return None

    try:
        return float(value)

    except ValueError:
        return None


def safe_int(value):

    if value is None or value == "":
        return None

    try:
        return int(float(value))

    except ValueError:
        return None


def load_data(filename):

    rows = []

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            parsed = {}

            for key, value in row.items():

                if key == "open_time":
                    parsed[key] = safe_int(value)

                elif key in (
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
                ):
                    parsed[key] = safe_float(value)

                else:
                    parsed[key] = value

            if parsed.get("open_time") is not None:
                rows.append(parsed)

    rows.sort(
        key=lambda x: x["open_time"]
    )

    return rows


# ============================================================
# SIGNAL INTELLIGENCE
# ============================================================

def classify_direction(
    row
):

    ema20 = row.get("ema20")
    ema50 = row.get("ema50")
    close = row.get("close")
    rsi = row.get("rsi14")
    momentum = row.get("momentum12")

    if None in (
        ema20,
        ema50,
        close,
        rsi,
        momentum,
    ):
        return "UNKNOWN"

    long_score = 0
    short_score = 0

    # Trend
    if ema20 > ema50:

        long_score += 2

        if close > ema20:
            long_score += 1

    elif ema20 < ema50:

        short_score += 2

        if close < ema20:
            short_score += 1

    # RSI
    if rsi >= 55:
        long_score += 1

    elif rsi <= 45:
        short_score += 1

    # Momentum
    if momentum > 0:
        long_score += 1

    elif momentum < 0:
        short_score += 1

    if long_score > short_score:

        return "LONG"

    if short_score > long_score:

        return "SHORT"

    return "NEUTRAL"


def calculate_signal_score(
    row,
    direction
):

    if direction not in (
        "LONG",
        "SHORT",
    ):
        return 0, []

    score = 0
    reasons = []

    ema20 = row.get("ema20")
    ema50 = row.get("ema50")
    close = row.get("close")
    rsi = row.get("rsi14")
    momentum = row.get("momentum12")
    volume_ratio = row.get(
        "volume_ratio20"
    )
    volatility = row.get(
        "volatility20"
    )

    if None in (
        ema20,
        ema50,
        close,
        rsi,
        momentum,
    ):
        return 0, reasons

    # --------------------------------------------------------
    # LONG SIGNAL
    # --------------------------------------------------------

    if direction == "LONG":

        if ema20 > ema50:

            score += 25
            reasons.append(
                "EMA_BULLISH"
            )

        if close > ema20:

            score += 15
            reasons.append(
                "PRICE_ABOVE_EMA20"
            )

        if rsi >= 55:

            score += 15
            reasons.append(
                "RSI_BULLISH"
            )

        if momentum > 0:

            score += 15
            reasons.append(
                "POSITIVE_MOMENTUM"
            )

    # --------------------------------------------------------
    # SHORT SIGNAL
    # --------------------------------------------------------

    elif direction == "SHORT":

        if ema20 < ema50:

            score += 25
            reasons.append(
                "EMA_BEARISH"
            )

        if close < ema20:

            score += 15
            reasons.append(
                "PRICE_BELOW_EMA20"
            )

        if rsi <= 45:

            score += 15
            reasons.append(
                "RSI_BEARISH"
            )

        if momentum < 0:

            score += 15
            reasons.append(
                "NEGATIVE_MOMENTUM"
            )

    # --------------------------------------------------------
    # VOLUME CONFIRMATION
    # --------------------------------------------------------

    if (
        volume_ratio is not None
        and volume_ratio >= 1.0
    ):

        score += 10

        reasons.append(
            "VOLUME_CONFIRMED"
        )

    # --------------------------------------------------------
    # VOLATILITY QUALITY
    # --------------------------------------------------------

    if volatility is not None:

        if volatility > 0:

            score += 5

            reasons.append(
                "VOLATILITY_ACTIVE"
            )

    return score, reasons


# ============================================================
# REGIME INTELLIGENCE
# ============================================================

def get_regime_bonus(
    row,
    direction
):

    regime = row.get(
        "combined_regime",
        "UNKNOWN"
    )

    bonus = 0
    quality = "NEUTRAL"

    if direction == "LONG":

        if regime == "BULL_LOW_VOL":

            bonus = 15
            quality = "FAVORABLE"

        elif regime == "BULL_HIGH_VOL":

            bonus = 10
            quality = "FAVORABLE"

        elif regime.startswith(
            "BEAR"
        ):

            bonus = -15
            quality = "UNFAVORABLE"

        elif regime.startswith(
            "SIDEWAYS"
        ):

            bonus = -5
            quality = "WEAK"

    elif direction == "SHORT":

        if regime == "BEAR_LOW_VOL":

            bonus = 15
            quality = "FAVORABLE"

        elif regime == "BEAR_HIGH_VOL":

            bonus = 10
            quality = "FAVORABLE"

        elif regime.startswith(
            "BULL"
        ):

            bonus = -15
            quality = "UNFAVORABLE"

        elif regime.startswith(
            "SIDEWAYS"
        ):

            bonus = -5
            quality = "WEAK"

    return (
        bonus,
        regime,
        quality,
    )


# ============================================================
# 4H MULTI-TIMEFRAME CONTEXT
# ============================================================

def build_4h_lookup(
    four_h_rows
):

    times = []

    for row in four_h_rows:

        times.append(
            row["open_time"]
        )

    return times


def get_latest_closed_4h_row(
    current_time,
    four_h_rows,
    four_h_times
):

    # 4h candle duration
    four_hours_ms = (
        4
        * 60
        * 60
        * 1000
    )

    # Find latest 4h candle that had
    # already CLOSED before this 1h decision.
    latest_available_time = (
        current_time
        - four_hours_ms
    )

    index = bisect_left(
        four_h_times,
        latest_available_time
    )

    # Exact timestamp found
    if (
        index < len(four_h_times)
        and four_h_times[index]
        == latest_available_time
    ):

        return four_h_rows[index]

    # Otherwise previous candle
    index -= 1

    if index >= 0:

        return four_h_rows[index]

    return None


def calculate_mtf_consensus(
    direction,
    current_time,
    four_h_rows,
    four_h_times
):

    four_h_row = (
        get_latest_closed_4h_row(
            current_time,
            four_h_rows,
            four_h_times,
        )
    )

    if four_h_row is None:

        return (
            "NO_4H_DATA",
            0,
            "UNKNOWN",
        )

    four_h_direction = (
        classify_direction(
            four_h_row
        )
    )

    four_h_regime = (
        four_h_row.get(
            "combined_regime",
            "UNKNOWN"
        )
    )

    # Agreement
    if (
        direction == four_h_direction
        and direction in (
            "LONG",
            "SHORT",
        )
    ):

        return (
            "CONFIRMED",
            15,
            four_h_regime,
        )

    # Strong opposite direction
    if (
        direction == "LONG"
        and four_h_direction
        == "SHORT"
    ):

        return (
            "CONFLICT",
            -20,
            four_h_regime,
        )

    if (
        direction == "SHORT"
        and four_h_direction
        == "LONG"
    ):

        return (
            "CONFLICT",
            -20,
            four_h_regime,
        )

    return (
        "NEUTRAL",
        0,
        four_h_regime,
    )


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def get_confidence_level(
    score
):

    if score >= 85:
        return "VERY_HIGH"

    if score >= 70:
        return "HIGH"

    if score >= 55:
        return "MEDIUM"

    if score >= 40:
        return "LOW"

    return "VERY_LOW"


def clamp_score(
    score
):

    if score < 0:
        return 0

    if score > 100:
        return 100

    return score


# ============================================================
# SELECTIVE SIGNAL ENGINE
# ============================================================

def get_final_signal(
    direction,
    confidence,
    regime_quality,
    mtf_status
):

    if direction not in (
        "LONG",
        "SHORT",
    ):

        return "NO_TRADE"

    # Reject direct timeframe conflict
    if mtf_status == "CONFLICT":

        return "NO_TRADE"

    # Reject unfavorable regime
    if regime_quality == "UNFAVORABLE":

        return "NO_TRADE"

    # Only HIGH or VERY_HIGH
    # confidence is actionable.
    if confidence in (
        "HIGH",
        "VERY_HIGH",
    ):

        return direction

    return "NO_TRADE"


# ============================================================
# SIGNAL QUALITY
# ============================================================

def get_signal_quality(
    score,
    final_signal
):

    if final_signal == "NO_TRADE":

        if score >= 55:
            return "FILTERED"

        return "REJECTED"

    if score >= 85:
        return "ELITE"

    if score >= 70:
        return "HIGH_QUALITY"

    return "STANDARD"


# ============================================================
# CORE ENGINE
# ============================================================

def run_core_engine(
    one_h_rows,
    four_h_rows
):

    four_h_times = (
        build_4h_lookup(
            four_h_rows
        )
    )

    output = []

    total_rows = len(
        one_h_rows
    )

    for index, row in enumerate(
        one_h_rows
    ):

        if (
            index % 5000 == 0
            and index > 0
        ):

            print(
                f"Processing: "
                f"{index}/{total_rows}"
            )

        direction = (
            classify_direction(
                row
            )
        )

        base_score, reasons = (
            calculate_signal_score(
                row,
                direction,
            )
        )

        regime_bonus, regime, regime_quality = (
            get_regime_bonus(
                row,
                direction,
            )
        )

        mtf_status, mtf_bonus, four_h_regime = (
            calculate_mtf_consensus(
                direction,
                row["open_time"],
                four_h_rows,
                four_h_times,
            )
        )

        raw_score = (
            base_score
            + regime_bonus
            + mtf_bonus
        )

        confidence_score = (
            clamp_score(
                raw_score
            )
        )

        confidence_level = (
            get_confidence_level(
                confidence_score
            )
        )

        final_signal = (
            get_final_signal(
                direction,
                confidence_level,
                regime_quality,
                mtf_status,
            )
        )

        signal_quality = (
            get_signal_quality(
                confidence_score,
                final_signal,
            )
        )

        output.append({

            "open_time":
                row.get("open_time"),

            "close":
                row.get("close"),

            "base_direction":
                direction,

            "base_score":
                base_score,

            "regime":
                regime,

            "regime_quality":
                regime_quality,

            "regime_bonus":
                regime_bonus,

            "mtf_status":
                mtf_status,

            "four_h_regime":
                four_h_regime,

            "mtf_bonus":
                mtf_bonus,

            "confidence_score":
                confidence_score,

            "confidence_level":
                confidence_level,

            "signal_quality":
                signal_quality,

            "final_signal":
                final_signal,

            "reasons":
                "|".join(
                    reasons
                ),

            "future_return_4h":
                row.get(
                    "future_return_4h"
                ),

            "future_return_12h":
                row.get(
                    "future_return_12h"
                ),

            "future_return_24h":
                row.get(
                    "future_return_24h"
                ),

            "future_return_48h":
                row.get(
                    "future_return_48h"
                ),
        })

    return output


# ============================================================
# OUTPUT
# ============================================================

def write_output(
    rows,
    filename
):

    fieldnames = [

        "open_time",
        "close",

        "base_direction",
        "base_score",

        "regime",
        "regime_quality",
        "regime_bonus",

        "mtf_status",
        "four_h_regime",
        "mtf_bonus",

        "confidence_score",
        "confidence_level",

        "signal_quality",
        "final_signal",

        "reasons",

        "future_return_4h",
        "future_return_12h",
        "future_return_24h",
        "future_return_48h",
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


# ============================================================
# SUMMARY
# ============================================================

def write_summary(
    rows,
    filename
):

    total_rows = len(rows)

    final_signals = Counter(
        row["final_signal"]
        for row in rows
    )

    confidence_levels = Counter(
        row["confidence_level"]
        for row in rows
    )

    mtf_statuses = Counter(
        row["mtf_status"]
        for row in rows
    )

    quality_levels = Counter(
        row["signal_quality"]
        for row in rows
    )

    fieldnames = [

        "category",
        "name",
        "count",
        "percentage",
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

        groups = [

            (
                "FINAL_SIGNAL",
                final_signals,
            ),

            (
                "CONFIDENCE",
                confidence_levels,
            ),

            (
                "MTF_STATUS",
                mtf_statuses,
            ),

            (
                "SIGNAL_QUALITY",
                quality_levels,
            ),
        ]

        for category, counter in groups:

            for name, count in sorted(
                counter.items()
            ):

                percentage = (
                    count
                    / total_rows
                    * 100
                    if total_rows > 0
                    else 0
                )

                writer.writerow({

                    "category":
                        category,

                    "name":
                        name,

                    "count":
                        count,

                    "percentage":
                        f"{percentage:.2f}",
                })


# ============================================================
# DISPLAY RESULTS
# ============================================================

def print_results(
    rows
):

    total = len(rows)

    signals = Counter(
        row["final_signal"]
        for row in rows
    )

    confidence = Counter(
        row["confidence_level"]
        for row in rows
    )

    mtf = Counter(
        row["mtf_status"]
        for row in rows
    )

    quality = Counter(
        row["signal_quality"]
        for row in rows
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "HEX SENTINEL CORE RESULTS"
    )

    print(
        "=" * 60
    )

    print(
        f"\nTotal candles: {total}"
    )

    print(
        "\nFINAL SIGNALS"
    )

    print(
        "-" * 40
    )

    for name in (
        "LONG",
        "SHORT",
        "NO_TRADE",
    ):

        count = signals.get(
            name,
            0,
        )

        percentage = (
            count
            / total
            * 100
            if total > 0
            else 0
        )

        print(
            f"{name:<12} "
            f"{count:>6} "
            f"{percentage:>7.2f}%"
        )

    print(
        "\nCONFIDENCE LEVELS"
    )

    print(
        "-" * 40
    )

    for name in (
        "VERY_HIGH",
        "HIGH",
        "MEDIUM",
        "LOW",
        "VERY_LOW",
    ):

        count = confidence.get(
            name,
            0,
        )

        percentage = (
            count
            / total
            * 100
            if total > 0
            else 0
        )

        print(
            f"{name:<12} "
            f"{count:>6} "
            f"{percentage:>7.2f}%"
        )

    print(
        "\nMULTI-TIMEFRAME STATUS"
    )

    print(
        "-" * 40
    )

    for name in sorted(
        mtf
    ):

        count = mtf[name]

        percentage = (
            count
            / total
            * 100
            if total > 0
            else 0
        )

        print(
            f"{name:<12} "
            f"{count:>6} "
            f"{percentage:>7.2f}%"
        )

    print(
        "\nSIGNAL QUALITY"
    )

    print(
        "-" * 40
    )

    for name in sorted(
        quality
    ):

        count = quality[name]

        percentage = (
            count
            / total
            * 100
            if total > 0
            else 0
        )

        print(
            f"{name:<16} "
            f"{count:>6} "
            f"{percentage:>7.2f}%"
        )


# ============================================================
# MAIN
# ============================================================

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
        "HEX SENTINEL CORE INTELLIGENCE ENGINE"
    )

    print(
        "=" * 60
    )

    print(
        "\nLOADING 1H DATA..."
    )

    one_h_rows = (
        load_data(
            ONE_H_FILE
        )
    )

    print(
        f"1H rows loaded: "
        f"{len(one_h_rows)}"
    )

    print(
        "\nLOADING 4H DATA..."
    )

    four_h_rows = (
        load_data(
            FOUR_H_FILE
        )
    )

    print(
        f"4H rows loaded: "
        f"{len(four_h_rows)}"
    )

    print(
        "\nRUNNING CORE ENGINE..."
    )

    output_rows = (
        run_core_engine(
            one_h_rows,
            four_h_rows,
        )
    )

    write_output(
        output_rows,
        CORE_OUTPUT,
    )

    write_summary(
        output_rows,
        SUMMARY_OUTPUT,
    )

    print_results(
        output_rows
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "HEX SENTINEL CORE COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"\nCore signals:"
        f"\n{CORE_OUTPUT}"
    )

    print(
        f"\nSummary:"
        f"\n{SUMMARY_OUTPUT}"
    )


if __name__ == "__main__":
    main()
