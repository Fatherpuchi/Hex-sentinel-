import sys, math
import lab_engine as E
from lab_data import connect

G, R, Y, X = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def fade24(view, k=1.5):
    cl = [c[3] for c in view.candles]
    rets = [math.log(cl[i] / cl[i - 1]) for i in range(1, len(cl))]
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    if sd == 0:
        return None
    z = math.log(cl[-1] / cl[-25]) / (sd * math.sqrt(24))
    if z >= k:
        return "DOWN", 60
    if z <= -k:
        return "UP", 60
    return None


IDEAS = {"fade24": fade24}


def run(conn, set_name):
    ids = [r for (r,) in conn.execute("SELECT round_id FROM rounds WHERE set_name=? ORDER BY ord", (set_name,))]
    if not ids:
        print(R + "no such set" + X)
        return
    for name, fn in IDEAS.items():
        new = abst = 0
        for rid in ids:
            res = fn(E.get_view(conn, set_name, rid))
            if res is None:
                abst += 1
                continue
            try:
                E.lock_prediction(conn, set_name, rid, name, res[0], res[1])
                new += 1
            except E.LockedError:
                pass
        print(f"{G}{name}: locked {new} new, abstained on {abst} of {len(ids)}{X}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "run":
        c = connect()
        if a[1].lower().startswith("human"):
            raise SystemExit(R + "not on human sets" + X)
        run(c, a[1])
    else:
        print("usage: lab_ideas.py run SET")
