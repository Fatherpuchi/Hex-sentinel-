"""
HEX SENTINEL — CLI THEME
============================================================
Lightweight, zero-dependency ANSI color helpers for the
Hex Sentinel terminal interface.

Design goals:
- No new pip dependency (raw ANSI escapes -- Termux, Linux
  and modern Windows Terminal all support these natively).
- Colors auto-disable when NO_COLOR is set or stdout isn't
  a real terminal (piped to a file/log), so redirected output
  and CI logs stay clean plain text.
- One place to change the palette instead of hunting through
  502+ print() calls scattered across sentinel_ai.py.

Usage:
    from sentinel_theme import c, status_color, kv, header, badge

    print(header("HEX SENTINEL — 24H PAPER PREDICTION", "🔮"))
    print(kv("Market Signal", "BUY"))          # auto-colored green
    print(kv("Live Execution", "BLOCKED"))     # auto-colored red/bold
    print(badge("APPROVED"))                   # "[ APPROVED ]" in green
"""

import os
import sys


def _color_enabled():
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("SENTINEL_FORCE_COLOR") == "1":
        return True
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


COLOR_ENABLED = _color_enabled()

RESET = "\033[0m" if COLOR_ENABLED else ""
BOLD = "\033[1m" if COLOR_ENABLED else ""
DIM = "\033[2m" if COLOR_ENABLED else ""

GREEN = "\033[32m" if COLOR_ENABLED else ""
RED = "\033[31m" if COLOR_ENABLED else ""
YELLOW = "\033[33m" if COLOR_ENABLED else ""
CYAN = "\033[36m" if COLOR_ENABLED else ""
MAGENTA = "\033[35m" if COLOR_ENABLED else ""
BLUE = "\033[34m" if COLOR_ENABLED else ""
GRAY = "\033[90m" if COLOR_ENABLED else ""

BRIGHT_GREEN = "\033[92m" if COLOR_ENABLED else ""
BRIGHT_RED = "\033[91m" if COLOR_ENABLED else ""
BRIGHT_YELLOW = "\033[93m" if COLOR_ENABLED else ""


def c(text, color, bold=False):
    """Wrap `text` in a color (and optionally bold), auto-resetting."""
    prefix = (BOLD if bold else "") + color
    return f"{prefix}{text}{RESET}" if prefix else str(text)


# ------------------------------------------------------------
# Semantic status -> color mapping.
# One dict to keep BUY/SELL/HOLD, APPROVED/WATCH/REJECTED,
# and SUCCESS/FAILURE/NEUTRAL all visually consistent.
# ------------------------------------------------------------
_STATUS_COLORS = {
    # Bullish / go / good outcomes
    "BUY": BRIGHT_GREEN, "APPROVED": BRIGHT_GREEN, "SUCCESS": BRIGHT_GREEN,
    "AGREEMENT": BRIGHT_GREEN, "PAPER_BUY": BRIGHT_GREEN, "ACTIVE": GREEN,
    "AVAILABLE": GREEN, "RECORDED": GREEN, "CLEARED": GREEN,
    "TP3": BRIGHT_GREEN, "TP1": GREEN, "TP2": GREEN,

    # Bearish / stop / bad outcomes
    "SELL": BRIGHT_RED, "REJECTED": BRIGHT_RED, "FAILURE": BRIGHT_RED,
    "BLOCKED": BRIGHT_RED, "CONFLICT": BRIGHT_RED, "PAPER_SELL": BRIGHT_RED,
    "ERROR": BRIGHT_RED, "INVALID": BRIGHT_RED, "VALIDATION_FAILED": BRIGHT_RED,
    "STOP_LOSS": BRIGHT_RED,

    # Caution / neutral / in-between
    "HOLD": BRIGHT_YELLOW, "WATCH": BRIGHT_YELLOW, "NEUTRAL": BRIGHT_YELLOW,
    "CAUTION": BRIGHT_YELLOW, "PAPER_HOLD": BRIGHT_YELLOW,
    "PAPER_ONLY": BRIGHT_YELLOW, "MONITORING": BRIGHT_YELLOW,
    "PENDING": BRIGHT_YELLOW, "NO_RECENT_EVIDENCE": YELLOW,

    # Unknown / inactive
    "UNKNOWN": GRAY, "IDLE": GRAY, "NONE": GRAY,
}


def status_color(value):
    """Return the ANSI color code for a known status word, else ''."""
    if value is None:
        return GRAY
    return _STATUS_COLORS.get(str(value).upper(), "")


def status(value, default="UNKNOWN"):
    """Colorize a status/signal string based on its own meaning."""
    text = value if value not in (None, "") else default
    return c(text, status_color(text), bold=True)


def badge(value, default="UNKNOWN"):
    """A bracketed, colored badge: [ APPROVED ]."""
    text = value if value not in (None, "") else default
    return c(f"[ {text} ]", status_color(text), bold=True)


def kv(label, value, width=18, default="UNKNOWN"):
    """
    An aligned 'Label: value' line with the value auto-colored
    by status_color() when it matches a known status word,
    left plain otherwise (e.g. prices, IDs, timestamps).
    """
    text = value if value not in (None, "") else default
    color = status_color(text)
    value_str = c(text, color, bold=bool(color))
    return f"{label + ':':<{width}}{value_str}"


def header(title, emoji="", width=60):
    """A boxed section header, matching the existing '='*60 style."""
    bar = "=" * width
    title_line = f"{emoji + ' ' if emoji else ''}{title}"
    return f"{c(bar, CYAN)}\n{c(title_line, CYAN, bold=True)}\n{c(bar, CYAN)}"


def subheader(title, emoji="", width=60):
    """A lighter section divider for sub-sections within a report."""
    bar = "-" * width
    title_line = f"{emoji + ' ' if emoji else ''}{title}"
    return f"\n{c(title_line, MAGENTA, bold=True)}\n{c(bar, GRAY)}"


def live_execution_line(value="BLOCKED"):
    """
    The safety-critical 'Live execution' line. Always rendered in
    bold red/green regardless of the general status palette, since
    this is the one line in the whole UI that must never be missed.
    """
    color = BRIGHT_GREEN if str(value).upper() == "ENABLED" else BRIGHT_RED
    return f"{c('🔒 Live execution:', color, bold=True)} {c(value, color, bold=True)}"


def format_price(value):
    """
    Format a USD price for display, scaling decimal places to the
    coin's actual magnitude instead of a fixed 2 decimals.

    BUGFIX: sentinel_stage1.py's "Latest Price" line and
    sentinel_ai.py's "Current Price" line both used f"${price:,.2f}",
    which is fine for BTC/ETH but rounds any sub-cent altcoin price
    (e.g. a $0.0013 micro-cap) straight down to "$0.00" -- making a
    real, successfully-fetched price look like a fetch failure. This
    was purely a display bug: the underlying float value was correct
    the whole time and every actual trade-safety calculation (entry
    zone distance, stop-loss distance, etc.) already used the full
    unrounded float, so no calculation logic needed to change here --
    only what gets printed.
    """
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "$0.00"

    if price == 0:
        return "$0.00"
    if price >= 1:
        return f"${price:,.2f}"
    if price >= 0.01:
        return f"${price:,.4f}"

    # Sub-cent price: show up to 8 decimals, trimmed of trailing
    # zeros, so $0.00000123 shows as such instead of "$0.00".
    text = f"{price:.8f}".rstrip("0").rstrip(".")
    return f"${text}"


def print_router_result(tool_name, result):
    """
    Pretty-print a router tool result (status, history, market
    snapshot, scan, cache) instead of the raw dict/list repr these
    all used to get dumped through with a bare print(). None of
    these commands have their own dedicated formatter, so this one
    function covers all of them at the single shared call site.

    - dict results (status, cache) print as aligned, auto-colored
      "Label: value" lines.
    - list-of-tuple results (decision history) print one row per
      line, colorizing any element that matches a known status word.
    - anything else prints as-is.
    """
    print("\n" + c(f"🤖 {tool_name}", CYAN, bold=True))

    if isinstance(result, dict):
        if not result:
            print(c("(empty)", GRAY))
            return
        for key, value in result.items():
            label = str(key).replace("_", " ").title()
            label = label.replace("Api", "API")  # .title() doesn't know acronyms
            print(kv(label, value))
        return

    if isinstance(result, list):
        if not result:
            print(c("No results.", GRAY))
            return
        for row in result:
            if isinstance(row, (list, tuple)):
                parts = []
                for v in row:
                    color = status_color(v)
                    parts.append(c(str(v), color, bold=True) if color else str(v))
                print(" | ".join(parts))
            else:
                print(row)
        return

    print(result)
