"""hex_colors.py - adds status colors to Hex's printed output (display only).

install() wraps print(): known status words and +/-% numbers get coloured.
Lines that already contain colour codes are left alone, and nothing is
coloured when output is not a terminal or NO_COLOR is set.
"""
import builtins
import os
import re
import sys

RESET = "\033[0m"
GREEN, RED, YELLOW, CYAN = "\033[92m", "\033[91m", "\033[93m", "\033[96m"
BOLD = "\033[1m"

WORDS = {
    GREEN: ["BUY", "PAPER_BUY", "BULLISH", "APPROVED", "SUCCESS", "AGREEMENT"],
    RED: ["SELL", "PAPER_SELL", "BEARISH", "REJECTED", "FAIL", "FAILED", "BLOCKED",
          "CONFLICT", "INVALID", "LOSS"],
    YELLOW: ["HOLD", "PAPER_HOLD", "NEUTRAL", "WATCH", "CAUTION", "UNEVALUATED",
             "PENDING", "UNKNOWN", "WEAK"],
}
COLOR_OF = {w: col for col, ws in WORDS.items() for w in ws}
WORD_RE = "|".join(sorted(COLOR_OF, key=len, reverse=True))
PATTERN = re.compile(
    r"(?i:live execution:\s*)BLOCKED"          # safe state -> green
    r"|(?<![\w.])[+-]\d+(?:\.\d+)?%"           # signed percentages
    rf"|\b(?:{WORD_RE})\b"                     # status words (UPPERCASE only)
)

MENU_RE = re.compile(r"^(\s{2})([a-z][^\n→]*?)(\s+→ )(.*)$")


def _repl(m):
    t = m.group(0)
    if t.lower().startswith("live execution"):
        i = t.rfind("BLOCKED")
        return t[:i] + BOLD + GREEN + t[i:] + RESET
    if t[0] in "+-":
        return (GREEN if t[0] == "+" else RED) + t + RESET
    return BOLD + COLOR_OF[t] + t + RESET


def colorize(text):
    if "\033[" in text:
        return text
    s = text.strip()
    if s and set(s) <= {"=", "-"} and len(s) >= 10:
        return CYAN + text + RESET
    if s.endswith(" registered."):
        return GREEN + text + RESET
    menu = MENU_RE.match(text)
    if menu:  # "  status   -> description": colour the command name
        return menu.group(1) + BOLD + CYAN + menu.group(2) + RESET + menu.group(3) + PATTERN.sub(_repl, menu.group(4))
    return PATTERN.sub(_repl, text)


def install():
    if os.getenv("NO_COLOR") or not sys.stdout.isatty():
        return
    real_print = builtins.print

    def colored_print(*args, **kwargs):
        if kwargs.get("file") in (None, sys.stdout):
            args = tuple(colorize(a) if isinstance(a, str) else a for a in args)
        real_print(*args, **kwargs)

    builtins.print = colored_print
