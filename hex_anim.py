import sys, time, random, shutil

G, R, C, D, X = "\033[92m", "\033[91m", "\033[96m", "\033[2m", "\033[0m"
BL = "▁▂▃▄▅▆▇█"

def out(s):
    sys.stdout.write(s)
    sys.stdout.flush()

def main():
    w = min(shutil.get_terminal_size().columns - 2, 48)
    out("\033[?25l")  # hide cursor
    try:
        p, line = 4.0, []
        for _ in range(w):
            old = p
            p = max(0, min(7, p + random.uniform(-1.6, 1.6)))
            line.append((G if p >= old else R) + BL[int(p)])
            out("\r" + "".join(line) + X)
            time.sleep(0.03)
        out("\n\n" + C)
        for ch in "H E X   S E N T I N E L":
            out(ch)
            time.sleep(0.05)
        out(X + "\n" + D + "paper mode - live execution blocked" + X + "\n\n")
        for i in range(w + 1):
            out("\r" + C + "█" * i + D + "░" * (w - i) + X + f" {i * 100 // w:3d}%")
            time.sleep(0.02)
        out("\n")
    finally:
        out("\033[?25h" + X)  # always restore cursor

if __name__ == "__main__":
    main()
