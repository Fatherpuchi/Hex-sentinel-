#!/usr/bin/env python3
"""hex_roles.py - roles_v1 (spec: roles_v1_spec.md). ADVISORY roles, no vote.
ChatGPT (OpenAI API): evidence classifier + plan critic. OpenRouter: sampled second labeler.
Nothing here feeds the guard, the agreement score, a prompt, a plan or a decision; every failure is
swallowed. Keys come from the environment or .env and are never printed. Writes only shadow_roles and
shadow_roles_items in shadow.db plus roles_state.json.
Usage: python3 hex_roles.py selftest | check | livecheck [openai|openrouter] | report
Imported by sentinel_ai.py: hex_roles.run_roles_safe(ctx) -> list of lines"""
import os
import re
import sys
import json
import time
import random
import hashlib
import sqlite3
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "shadow.db")
ENV_PATH = os.path.join(HERE, ".env")
CONFIG_PATH = os.path.join(HERE, "roles_config.json")
STATE_PATH = os.path.join(HERE, "roles_state.json")
MIN_N = 30
HARD = {"openai_requests_per_day": 100, "openai_tokens_per_day": 150000, "max_output_tokens": 2000,
        "or_items_per_day": 20, "items_per_analysis": 10, "run_seconds": 30, "per_analysis": 2, "breaker": 3,
        "or_total_per_day": 45}
DEFAULT = {"openai_model": "gpt-5-mini", "openai_url": "https://api.openai.com/v1/chat/completions",
           "openrouter_model": "poolside/laguna-s-2.1:free",
           "openrouter_url": "https://openrouter.ai/api/v1/chat/completions", "reasoning_effort": "low",
           "roles_provider": "openrouter", "roles_model": "openai/gpt-oss-120b:free", "roles_reasoning": "low",
           "enabled": {"classifier": True, "critic": True, "or_labeler": True},
           "openai_requests_per_day": 36, "openai_tokens_per_day": 120000, "max_output_tokens": 1500,
           "or_total_per_day": 38,
           "or_items_per_day": 20, "items_per_analysis": 10, "run_seconds": 30}
NUM_KEYS = ("openai_requests_per_day", "openai_tokens_per_day", "max_output_tokens", "or_items_per_day",
            "items_per_analysis", "run_seconds", "or_total_per_day")
EFFORTS = ("", "minimal", "low", "medium", "high")
FRESH = {"day": None, "openai_requests": 0, "openai_tokens": 0, "or_requests": 0, "or_items": 0,
         "errors": 0, "off_day": None}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def clean(text, n):
    t = "" if text is None else str(text)
    t = "".join(ch if ch.isprintable() else " " for ch in t)
    return re.sub(r"\s+", " ", t).strip()[:n]


def keep_lines(text, n):
    t = "".join(ch if (ch == "\n" or ch.isprintable()) else " " for ch in str(text or ""))
    return t.strip()[:n]


def redact(text, keys=()):
    t = str(text)
    for k in keys:
        if k:
            t = t.replace(k, "[REDACTED]")
    t = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", t)
    return re.sub(r"sk-[A-Za-z0-9_\-]{10,}", "[REDACTED]", t)


def load_key(name, environ=None, env_path=ENV_PATH):
    environ = os.environ if environ is None else environ
    v = environ.get(name)
    if not (v and v.strip()):
        v = None
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("export "):
                        line = line[7:].lstrip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, val = line.partition("=")
                    if k.strip() == name:
                        v = val.strip()
                        break
        except Exception:
            return None
    if v and len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    v = re.sub(r"[^A-Za-z0-9_.\-]", "", v or "")
    return v or None


def load_config(path=CONFIG_PATH):
    cfg = json.loads(json.dumps(DEFAULT))
    if not os.path.exists(path):
        return cfg, None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        for k in ("openai_model", "openrouter_model"):
            if k in raw:
                if not isinstance(raw[k], str) or not raw[k].strip():
                    raise ValueError(k)
                cfg[k] = raw[k].strip()
        for k, prefix in (("openai_url", "https://api.openai.com/"), ("openrouter_url", "https://openrouter.ai/")):
            if k in raw:
                if not isinstance(raw[k], str) or not raw[k].startswith(prefix):
                    raise ValueError(k)
                cfg[k] = raw[k]
        for k in NUM_KEYS:
            if k in raw:
                if not isinstance(raw[k], int) or isinstance(raw[k], bool):
                    raise ValueError(k)
                cfg[k] = max(1, min(raw[k], HARD[k]))
        if "reasoning_effort" in raw:
            if raw["reasoning_effort"] not in EFFORTS:
                raise ValueError("reasoning_effort")
            cfg["reasoning_effort"] = raw["reasoning_effort"]
        if "roles_provider" in raw:
            if raw["roles_provider"] not in ("openrouter", "openai"):
                raise ValueError("roles_provider")
            cfg["roles_provider"] = raw["roles_provider"]
        if "roles_model" in raw:
            if not isinstance(raw["roles_model"], str) or not raw["roles_model"].strip():
                raise ValueError("roles_model")
            cfg["roles_model"] = raw["roles_model"].strip()
        if "roles_reasoning" in raw:
            if raw["roles_reasoning"] not in EFFORTS:
                raise ValueError("roles_reasoning")
            cfg["roles_reasoning"] = raw["roles_reasoning"]
        if "enabled" in raw:
            if not isinstance(raw["enabled"], dict):
                raise ValueError("enabled")
            for k, v in raw["enabled"].items():
                if k in cfg["enabled"]:
                    if not isinstance(v, bool):
                        raise ValueError(k)
                    cfg["enabled"][k] = v
        return cfg, None
    except Exception:
        return None, "roles_config.json unreadable or invalid"


def load_state(path=STATE_PATH):
    if not os.path.exists(path):
        return dict(FRESH), None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        st = dict(FRESH)
        for k in ("openai_requests", "openai_tokens", "or_requests", "or_items", "errors"):
            v = raw.get(k, 0)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ValueError(k)
            st[k] = v
        for k in ("day", "off_day"):
            v = raw.get(k)
            if v is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v)):
                raise ValueError(k)
            st[k] = v
        return st, None
    except Exception:
        return None, ("roles_state.json unreadable or corrupt (fix or delete it by hand after checking "
                      "your OpenAI usage)")


def save_state(path, st):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def roll_state(st, today):
    if st.get("day") != today:
        st.update(day=today, openai_requests=0, openai_tokens=0, or_requests=0, or_items=0,
                  errors=0, off_day=None)
# --- end part 1 ---


PLAN_KEYS = ("DIRECTION", "ENTRY_LOW", "ENTRY_HIGH", "STOP_LOSS", "TP1", "TP2", "TP3")
DIRS = ("BULLISH", "BEARISH", "NEUTRAL", "IRRELEVANT")
HORIZONS = ("HOURS", "DAYS", "WEEKS", "UNKNOWN")
CLAIMS = ("FACT", "OPINION", "PROMO", "UNKNOWN")
VERDICTS = ("CONSISTENT", "MINOR_ISSUES", "MAJOR_ISSUES")
CLASSIFIER_SYSTEM = (
    "You label web evidence items about one crypto coin. You see only the item text and know no trading signal. "
    "Return ONLY a JSON object: {\"items\": [{\"n\": 1, \"direction\": \"BULLISH|BEARISH|NEUTRAL|IRRELEVANT\", "
    "\"horizon\": \"HOURS|DAYS|WEEKS|UNKNOWN\", \"claim\": \"FACT|OPINION|PROMO|UNKNOWN\", "
    "\"reason\": \"max 12 words\"}]}. direction is the likely effect of the item on the coin's price; "
    "IRRELEVANT if the item is not about the coin. Do not invent facts. One entry per item, in order.")
CRITIC_SYSTEM = (
    "You check two paper-trading plans for one crypto coin. Never recommend trading or live execution and never "
    "predict profit. Return ONLY a JSON object: {\"contradictions\": [\"max 15 words each\"], "
    "\"stop_vs_range\": \"one short sentence or n/a\", \"verdict\": \"CONSISTENT|MINOR_ISSUES|MAJOR_ISSUES\"}. "
    "Base the verdict on the rule checks given, on contradictions between plan A and plan B, and on whether a "
    "stop looks tighter than normal daily movement. Use only the text given.")


def parse_plan(text):
    out = {}
    for k in PLAN_KEYS:
        m = re.search(r"(?im)^[ \t>*#-]*\**" + k + r"\**[ \t]*:[ \t]*\**[ \t]*([A-Za-z0-9.,+\-]+)", str(text or ""))
        if m:
            out[k] = m.group(1).strip()
    return out


def num(s):
    try:
        v = float(str(s).replace(",", ""))
    except Exception:
        return None
    return v if v == v and abs(v) != float("inf") else None


def rule_checks(plan, signal=None, price=None):
    bad = []
    d = str(plan.get("DIRECTION", "")).upper()
    if d not in ("BUY", "SELL"):
        bad.append("missing or invalid DIRECTION")
    v = {}
    for k in PLAN_KEYS[1:]:
        x = num(plan.get(k))
        if x is None or x <= 0:
            bad.append("missing or invalid " + k)
        else:
            v[k] = x
    if signal in ("BUY", "SELL") and d in ("BUY", "SELL") and d != signal:
        bad.append("DIRECTION differs from the engine signal")
    if len(v) == 6 and d in ("BUY", "SELL"):
        lo, hi, st = v["ENTRY_LOW"], v["ENTRY_HIGH"], v["STOP_LOSS"]
        t1, t2, t3 = v["TP1"], v["TP2"], v["TP3"]
        if lo > hi:
            bad.append("entry zone inverted")
        if d == "BUY":
            if st >= lo:
                bad.append("stop is not below the entry zone")
            if not (t1 < t2 < t3):
                bad.append("take-profits are not increasing")
            if t1 <= hi:
                bad.append("TP1 is not above the entry zone")
        else:
            if st <= hi:
                bad.append("stop is not above the entry zone")
            if not (t1 > t2 > t3):
                bad.append("take-profits are not decreasing")
            if t1 >= lo:
                bad.append("TP1 is not below the entry zone")
        p = num(price)
        if p and p > 0 and (hi < p * 0.99 or lo > p * 1.01):
            bad.append("entry zone is more than 1% away from the report price")
    return bad


def item_key(title):
    return hashlib.sha1(str(title).lower().strip().encode("utf-8")).hexdigest()[:12]


def items_from_web(web, n):
    if not isinstance(web, dict):
        return []
    pkg = (web.get("package") or {}) if "package" in web else web
    ev = pkg.get("evidence", []) if isinstance(pkg, dict) else []
    out, seen = [], set()
    for it in (ev if isinstance(ev, list) else []):
        if not isinstance(it, dict):
            continue
        title = clean(it.get("title"), 200)
        if not title:
            continue
        key = item_key(title)
        if key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "title": title, "summary": clean(it.get("summary"), 300),
                    "publisher": clean(it.get("publisher"), 40), "domain": clean(it.get("source_domain"), 40),
                    "source_type": clean(it.get("source_type"), 20),
                    "kw": str(it.get("direction") or "NEUTRAL").upper()[:12]})
        if len(out) >= n:
            break
    return out


def classifier_user(symbol, items):
    lines = ["Coin: %s" % clean(symbol, 20), "Items:"]
    for i, it in enumerate(items, 1):
        lines.append("%d. %s | publisher=%s | %s" % (i, it["title"], it["publisher"] or "unknown",
                                                     it["summary"] or "(no summary)"))
    lines.append("Return JSON only.")
    return "\n".join(lines)


def critic_user(ctx, order, plans, checks):
    out = ["Engine signal: %s" % clean(ctx.get("signal"), 12), "Report price: %s" % clean(ctx.get("price"), 20)]
    for label, name in zip("AB", order):
        out.append("Plan %s:\n%s" % (label, keep_lines(plans[name], 1100)))
        out.append("Rule checks by code for plan %s: %s" % (label, "; ".join(checks[name]) or "none"))
    out.append("Report excerpt:\n%s" % keep_lines(ctx.get("report"), 1500))
    out.append("Return JSON only.")
    return "\n".join(out)


def parse_json(text):
    t = str(text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        v = json.loads(t[i:j + 1])
    except Exception:
        return None
    return v if isinstance(v, dict) else None


def norm(v, allowed, default):
    v = str(v or "").upper().strip()
    return v if v in allowed else default


def norm_labels(obj, n):
    out = {}
    arr = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(arr, list):
        return out
    for e in arr:
        if not isinstance(e, dict):
            continue
        try:
            k = int(e.get("n"))
        except Exception:
            continue
        if 1 <= k <= n and k not in out:
            out[k] = (norm(e.get("direction"), DIRS, "INVALID"), norm(e.get("horizon"), HORIZONS, "UNKNOWN"),
                      norm(e.get("claim"), CLAIMS, "UNKNOWN"), clean(e.get("reason"), 80))
    return out


def norm_critic(obj):
    o = obj if isinstance(obj, dict) else {}
    cs = o.get("contradictions")
    cs = [clean(x, 100) for x in cs[:5]] if isinstance(cs, list) else []
    return {"contradictions": cs, "stop_vs_range": clean(o.get("stop_vs_range"), 120),
            "verdict": norm(o.get("verdict"), VERDICTS, "INVALID")}
# --- end part 2 ---


def _usage(data):
    u = data.get("usage") if isinstance(data, dict) else None
    try:
        return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    except Exception:
        return 0, 0


def chat_call(post, url, key, body, timeout):
    res = {"ok": False, "status": 0, "text": "", "finish": "", "in": 0, "out": 0, "secs": 0.0, "error": ""}
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    t0 = time.time()
    try:
        r = post(url, headers=headers, json=body, timeout=timeout)
    except Exception as e:
        res["error"] = clean(redact(e, (key,)), 120)
        res["secs"] = time.time() - t0
        return res
    res["secs"] = time.time() - t0
    res["status"] = getattr(r, "status_code", 0)
    if res["status"] != 200:
        res["error"] = "HTTP %s: %s" % (res["status"], clean(redact(getattr(r, "text", ""), (key,)), 150))
        return res
    try:
        data = r.json()
        ch = data["choices"][0]
        res["text"] = str((ch.get("message") or {}).get("content") or "")
        res["finish"] = str(ch.get("finish_reason") or "")
        res["in"], res["out"] = _usage(data)
    except Exception:
        res["error"] = "unexpected response shape"
        return res
    if not res["text"].strip():
        res["error"] = "empty content (finish_reason=%s)" % res["finish"]
        return res
    if res["finish"] == "length":
        res["error"] = "finish_reason=length (output cut)"
        return res
    res["ok"] = True
    return res


def openai_body(cfg, system, user, max_out):
    b = {"model": cfg["openai_model"],
         "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
         "max_completion_tokens": max_out, "response_format": {"type": "json_object"}}
    if cfg.get("reasoning_effort"):
        b["reasoning_effort"] = cfg["reasoning_effort"]
    return b


def openrouter_body(cfg, system, user):
    return {"model": cfg["openrouter_model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": 500}


def roles_target(cfg, keys):
    """-> (provider, url, model, key) for roles 1 and 2."""
    if cfg.get("roles_provider") == "openrouter":
        return "openrouter", cfg["openrouter_url"], cfg["roles_model"], keys.get("openrouter")
    return "openai", cfg["openai_url"], cfg["openai_model"], keys.get("openai")


def roles_body(cfg, system, user, max_out):
    if cfg.get("roles_provider") == "openrouter":
        b = {"model": cfg["roles_model"],
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
             "max_tokens": max_out}
        if cfg.get("roles_reasoning"):
            b["reasoning"] = {"effort": cfg["roles_reasoning"]}
        return b
    return openai_body(cfg, system, user, max_out)


SCHEMA = [
    "create table if not exists shadow_roles(id integer primary key autoincrement, created_utc text, symbol text, "
    "role text, provider text, model text, prompt_hash text, status text, reason text, http_status integer, "
    "finish_reason text, in_tokens integer, out_tokens integer, latency_s real, parsed text, raw text, "
    "plan_order text)",
    "create table if not exists shadow_roles_items(id integer primary key autoincrement, created_utc text, "
    "day_utc text, symbol text, call_id integer, item_key text, title text, kw_direction text, source text, "
    "direction text, horizon text, claim text, reason text)"]


def ensure_schema(con):
    for s in SCHEMA:
        con.execute(s)
    con.commit()


def store_call(con, now, symbol, role, provider, model, phash, status, reason, res, parsed, order):
    res = res or {}
    cur = con.execute(
        "insert into shadow_roles(created_utc, symbol, role, provider, model, prompt_hash, status, reason, "
        "http_status, finish_reason, in_tokens, out_tokens, latency_s, parsed, raw, plan_order) "
        "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (now.strftime("%Y-%m-%dT%H:%M:%SZ"), symbol, role, provider, model, phash, status, reason,
         res.get("status"), res.get("finish"), res.get("in"), res.get("out"), round(res.get("secs", 0.0), 2),
         json.dumps(parsed) if parsed is not None else None, clean(res.get("text"), 2000), order))
    con.commit()
    return cur.lastrowid


def store_items(con, now, symbol, cid, items, labels, source):
    ts, day = now.strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y-%m-%d")
    for i, it in enumerate(items, 1):
        lab = labels.get(i)
        con.execute(
            "insert into shadow_roles_items(created_utc, day_utc, symbol, call_id, item_key, title, kw_direction, "
            "source, direction, horizon, claim, reason) values(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, day, symbol, cid, it["key"], it["title"][:160], it["kw"], source,
             lab[0] if lab else None, lab[1] if lab else None, lab[2] if lab else None, lab[3] if lab else None))
    con.commit()


class Deadline:
    def __init__(self, clock, seconds):
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self):
        return self.end - self.clock()


def gate_openai(cfg, st, key, today, used, remaining):
    if not key:
        return "no OpenRouter key" if cfg.get("roles_provider") == "openrouter" else "no OpenAI key"
    if st.get("off_day") == today:
        return "OpenAI roles off for today (error breaker)"
    if used >= HARD["per_analysis"]:
        return "per-analysis request cap"
    if st["openai_requests"] >= cfg["openai_requests_per_day"]:
        return "daily request cap reached"
    if st["openai_tokens"] >= cfg["openai_tokens_per_day"]:
        return "daily token cap reached"
    if cfg.get("roles_provider") == "openrouter" and st["openai_requests"] + st["or_requests"] >= cfg["or_total_per_day"]:
        return "OpenRouter daily budget reached (shared with the fallback)"
    if remaining < 5:
        return "run time limit"
    return ""


def after_openai(st, res, today, state_path):
    st["openai_requests"] += 1
    tok = res["in"] + res["out"]
    st["openai_tokens"] += tok if tok else (1500 if res["ok"] else 0)
    if res["ok"]:
        st["errors"] = 0
    else:
        st["errors"] += 1
        if st["errors"] >= HARD["breaker"]:
            st["off_day"] = today
    save_state(state_path, st)


def run_openai(role, system, user, cfg, keys, st, today, state_path, con, now, symbol, used, dl, post, order=""):
    prov, url, model, key = roles_target(cfg, keys)
    why = gate_openai(cfg, st, key, today, used, dl.remaining())
    if why:
        return None, None, why, False
    phash = hashlib.sha1((system + "\n" + user).encode("utf-8")).hexdigest()[:12]
    res = chat_call(post, url, key,
                    roles_body(cfg, system, user, cfg["max_output_tokens"]), max(5, min(25, int(dl.remaining()))))
    after_openai(st, res, today, state_path)
    parsed = parse_json(res["text"]) if res["ok"] else None
    status = "OK" if parsed is not None else "ERROR"
    reason = "" if parsed is not None else (res["error"] or "reply was not a JSON object")
    cid = store_call(con, now, symbol, role, prov, model, phash, status, reason, res, parsed, order)
    return parsed, cid, reason, True
# --- end part 3 ---


def run_roles(ctx, cfg, keys, st, state_path, con, post, now, rng, clock=time.time):
    lines = ["ADVISORY ROLES (no vote, not used by any gate)"]
    dl = Deadline(clock, cfg["run_seconds"])
    who = "chatgpt" if cfg.get("roles_provider") != "openrouter" else (str(cfg["roles_model"]).split("/")[-1].split(":")[0] or "roles model")
    symbol = str(ctx.get("symbol") or "?")
    today = now.strftime("%Y-%m-%d")
    roll_state(st, today)
    used = 0
    items = items_from_web(ctx.get("web"), cfg["items_per_analysis"])
    gpt = {}
    if cfg["enabled"]["classifier"]:
        if not items:
            lines.append("  evidence classifier: no evidence items")
        else:
            try:
                parsed, cid, why, did = run_openai("CLASSIFIER", CLASSIFIER_SYSTEM, classifier_user(symbol, items),
                                                   cfg, keys, st, today, state_path, con, now, symbol, used, dl, post)
                used += 1 if did else 0
                if parsed is not None:
                    gpt = norm_labels(parsed, len(items))
                    store_items(con, now, symbol, cid, items, gpt, "chatgpt")
                    for i, it in enumerate(items, 1):
                        lab = gpt.get(i)
                        lines.append("  %d. %s | keyword %s | %s" % (
                            i, ("%s/%s/%s" % lab[:3]) if lab else "no label", it["kw"], it["title"][:60]))
                else:
                    lines.append("  evidence classifier (%s): %s" % (who, why or "no result"))
            except Exception as e:
                lines.append("  evidence classifier: error (%s)" % type(e).__name__)
    if cfg["enabled"]["or_labeler"] and keys.get("openrouter") and items:
        try:
            sample = [it for it in items if int(it["key"], 16) % 5 == 0]
            sample = sample[:max(0, cfg["or_items_per_day"] - st["or_items"])]
            if cfg.get("roles_provider") == "openrouter" and st["openai_requests"] + st["or_requests"] >= cfg["or_total_per_day"]:
                sample = []
            if sample and dl.remaining() >= 5:
                user = classifier_user(symbol, sample)
                res = chat_call(post, cfg["openrouter_url"], keys["openrouter"],
                                openrouter_body(cfg, CLASSIFIER_SYSTEM, user), max(5, min(20, int(dl.remaining()))))
                st["or_requests"] += 1
                st["or_items"] += len(sample)
                save_state(state_path, st)
                parsed = parse_json(res["text"]) if res["ok"] else None
                reason = "" if parsed is not None else (res["error"] or "reply was not a JSON object")
                phash = hashlib.sha1((CLASSIFIER_SYSTEM + "\n" + user).encode("utf-8")).hexdigest()[:12]
                cid = store_call(con, now, symbol, "OR_LABELER", "openrouter", cfg["openrouter_model"], phash,
                                 "OK" if parsed is not None else "ERROR", reason, res, parsed, "")
                if parsed is not None:
                    lab = norm_labels(parsed, len(sample))
                    store_items(con, now, symbol, cid, sample, lab, "openrouter")
                    lines.append("  second labeler (openrouter): %d item(s) labeled" % len(lab))
                else:
                    lines.append("  second labeler (openrouter): %s" % reason)
        except Exception as e:
            lines.append("  second labeler: error (%s)" % type(e).__name__)
    if cfg["enabled"]["critic"]:
        try:
            plans = {"groq": str(ctx.get("groq") or ""), "gemini": str(ctx.get("gemini") or "")}
            pp = dict((k, parse_plan(v)) for k, v in plans.items())
            if not any(pp[k].get("DIRECTION") for k in plans):
                lines.append("  plan critic: no parsable plan")
            else:
                checks = dict((k, rule_checks(pp[k], ctx.get("signal"), ctx.get("price"))) for k in plans)
                lines.append("  rule checks (code): " + " | ".join(
                    "%s: %s" % (k, "; ".join(checks[k]) or "ok") for k in ("groq", "gemini")))
                order = ["groq", "gemini"]
                if rng.random() < 0.5:
                    order.reverse()
                tag = "A=%s,B=%s" % (order[0], order[1])
                parsed, cid, why, did = run_openai("CRITIC", CRITIC_SYSTEM, critic_user(ctx, order, plans, checks),
                                                   cfg, keys, st, today, state_path, con, now, symbol, used, dl,
                                                   post, tag)
                if parsed is not None:
                    c = norm_critic(parsed)
                    con.execute("update shadow_roles set parsed=? where id=?", (json.dumps(dict(c, checks=checks)), cid))
                    con.commit()
                    lines.append("  plan critic (%s): %s | stop vs range: %s | contradictions: %s" % (who,
                        c["verdict"], c["stop_vs_range"] or "n/a", "; ".join(c["contradictions"]) or "none"))
                else:
                    lines.append("  plan critic (%s): %s" % (who, why or "no result"))
        except Exception as e:
            lines.append("  plan critic: error (%s)" % type(e).__name__)
    return lines


def run_roles_safe(ctx):
    try:
        cfg, err = load_config()
        if err:
            return ["ADVISORY ROLES: off (%s)" % err]
        st, err = load_state()
        if err:
            return ["ADVISORY ROLES: off (%s)" % err]
        keys = {"openai": load_key("OPENAI_API_KEY"), "openrouter": load_key("OPENROUTER_API_KEY")}
        if not (keys["openai"] or keys["openrouter"]):
            return ["ADVISORY ROLES: off (no keys found)"]
        import requests
        con = sqlite3.connect(DB, timeout=10)
        try:
            ensure_schema(con)
            return run_roles(ctx, cfg, keys, st, STATE_PATH, con, requests.post, utcnow(), random.Random())
        finally:
            con.close()
    except Exception as e:
        return ["ADVISORY ROLES: error (%s)" % type(e).__name__]


def kappa(pairs):
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / float(n)
    cats = set(a for a, _ in pairs) | set(b for _, b in pairs)
    pe = sum((sum(1 for a, _ in pairs if a == c) / float(n)) * (sum(1 for _, b in pairs if b == c) / float(n))
             for c in cats)
    return None if pe >= 1.0 else (po - pe) / (1.0 - pe)
# --- end part 4 ---


def build_report(con):
    names = set(r[0] for r in con.execute("select name from sqlite_master where type='table'"))
    if "shadow_roles" not in names or "shadow_roles_items" not in names:
        return ["no shadow_roles tables yet"]
    rows = con.execute("select role, status, count(*), sum(coalesce(in_tokens, 0)), sum(coalesce(out_tokens, 0)) "
                       "from shadow_roles group by 1, 2 order by 1, 2").fetchall()
    out = ["calls: %s | tokens in %d, out %d" % (", ".join("%s/%s %d" % (r[0], r[1], r[2]) for r in rows) or "none",
                                                sum(r[3] for r in rows), sum(r[4] for r in rows))]
    gpt = con.execute("select kw_direction, direction from shadow_roles_items "
                      "where source='chatgpt' and direction is not null").fetchall()
    dist = {}
    for _, d in gpt:
        dist[d] = dist.get(d, 0) + 1
    out.append("chatgpt directions: " + (", ".join("%s %d" % (k, dist[k]) for k in sorted(dist)) or "none"))
    if len(gpt) < MIN_N:
        out.append("chatgpt vs keyword labels: n=%d (counts only; needs %d)" % (len(gpt), MIN_N))
    else:
        out.append("chatgpt vs keyword labels: n=%d agreement %.1f%%" % (
            len(gpt), 100.0 * sum(1 for k, d in gpt if k == d) / len(gpt)))
    pairs = con.execute(
        "select a.direction, b.direction from shadow_roles_items a join shadow_roles_items b "
        "on a.item_key = b.item_key and a.day_utc = b.day_utc and a.symbol = b.symbol "
        "where a.source='chatgpt' and b.source='openrouter' and a.direction is not null "
        "and b.direction is not null").fetchall()
    if len(pairs) < MIN_N:
        out.append("second labeler vs chatgpt: n=%d (counts only; needs %d)" % (len(pairs), MIN_N))
    else:
        k = kappa(pairs)
        out.append("second labeler vs chatgpt: n=%d agreement %.1f%% kappa %s" % (
            len(pairs), 100.0 * sum(1 for a, b in pairs if a == b) / len(pairs), "n/a" if k is None else "%.2f" % k))
    vc = {}
    for (p,) in con.execute("select parsed from shadow_roles where role='CRITIC' and status='OK'"):
        try:
            v = json.loads(p).get("verdict")
        except Exception:
            v = None
        vc[v or "?"] = vc.get(v or "?", 0) + 1
    out.append("critic verdicts: " + (", ".join("%s %d" % (k, vc[k]) for k in sorted(vc)) or "none"))
    out.append("Advisory only. Grading against price outcomes is a separate step, not in this file. "
               "No pass bar, no causal claim.")
    return out


def cmd_report():
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        for ln in build_report(con):
            print(ln)
    except Exception as e:
        print("cannot read shadow.db (%s)" % type(e).__name__)


def cmd_check():
    cfg, err = load_config()
    print("config: " + (err or "ok"))
    if cfg:
        print("roles provider %s | roles model %s | roles reasoning %r | labeler model %s" % (
            cfg["roles_provider"], cfg["roles_model"], cfg["roles_reasoning"], cfg["openrouter_model"]))
        print("budget: roles requests/day %d, openrouter total/day %d (free tier is 50/day, shared with the fallback)" % (
            cfg["openai_requests_per_day"], cfg["or_total_per_day"]))
        print("legacy openai path (dormant unless roles_provider is openai): openai model %s | openrouter model %s | reasoning_effort %r" % (
            cfg["openai_model"], cfg["openrouter_model"], cfg["reasoning_effort"]))
        print("enabled %s | caps: openai requests/day %d, tokens/day %d, max output %d, openrouter items/day %d, "
              "items/analysis %d, run seconds %d" % (cfg["enabled"], cfg["openai_requests_per_day"],
                                                     cfg["openai_tokens_per_day"], cfg["max_output_tokens"],
                                                     cfg["or_items_per_day"], cfg["items_per_analysis"],
                                                     cfg["run_seconds"]))
    print("keys: OPENAI_API_KEY %s | OPENROUTER_API_KEY %s" % (
        "found" if load_key("OPENAI_API_KEY") else "NOT found",
        "found" if load_key("OPENROUTER_API_KEY") else "NOT found"))
    st, err = load_state()
    if st is None:
        print(err)
    else:
        print("state: day %s | openai requests %d, tokens %d | openrouter requests %d, items %d | errors %d | off_day %s"
              % (st["day"], st["openai_requests"], st["openai_tokens"], st["or_requests"], st["or_items"],
                 st["errors"], st["off_day"]))
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        has = con.execute("select count(*) from sqlite_master where name='shadow_roles'").fetchone()[0]
        n = con.execute("select count(*) from shadow_roles").fetchone()[0] if has else 0
        print("stored calls: %d | nothing was requested or written" % n)
    except Exception as e:
        print("cannot read shadow.db (%s)" % type(e).__name__)


def cmd_livecheck(target):
    import requests
    cfg, err = load_config()
    if err:
        print(err)
        return
    st, err = load_state()
    if st is None:
        print(err)
        return
    keys = {"openai": load_key("OPENAI_API_KEY"), "openrouter": load_key("OPENROUTER_API_KEY")}
    now = utcnow()
    today = now.strftime("%Y-%m-%d")
    roll_state(st, today)
    item = {"key": item_key("t"), "title": "Spot Bitcoin ETF approved by a major regulator",
            "summary": "The regulator approved the first spot ETF filings.", "publisher": "test", "domain": "",
            "source_type": "", "kw": "NEUTRAL"}
    user = classifier_user("TESTCOIN", [item])
    if target == "openrouter":
        if not keys["openrouter"]:
            print("OPENROUTER_API_KEY not found; nothing requested")
            return
        res = chat_call(requests.post, cfg["openrouter_url"], keys["openrouter"],
                        openrouter_body(cfg, CLASSIFIER_SYSTEM, user), 25)
        st["or_requests"] += 1
        st["or_items"] += 1
        save_state(STATE_PATH, st)
    else:
        prov, url, model, key = roles_target(cfg, keys)
        why = gate_openai(cfg, st, key, today, 0, 30)
        if why:
            print("not run: " + why)
            return
        res = chat_call(requests.post, url, key,
                        roles_body(cfg, CLASSIFIER_SYSTEM, user, cfg["max_output_tokens"]), 25)
        after_openai(st, res, today, STATE_PATH)
    print("%s livecheck: ok=%s http=%s finish=%s tokens in/out %s/%s time %.1fs" % (
        target, res["ok"], res["status"], res["finish"] or "-", res["in"], res["out"], res["secs"]))
    if res["error"]:
        print("error: " + res["error"])
    parsed = parse_json(res["text"]) if res["ok"] else None
    if parsed is not None:
        print("labels: %s" % norm_labels(parsed, 1))
    elif res["ok"]:
        print("reply was not a JSON object: " + clean(redact(res["text"], [k for k in keys.values() if k]), 200))
# --- end part 5 ---


def selftest():
    import io
    import tempfile
    from contextlib import redirect_stdout
    utc = datetime.timezone.utc
    KEY, ORK = "sk-proj-SECRETKEY1234567890", "sk-or-v1-OTHERSECRET123456"

    # 1 helpers
    assert clean("a\x1b[31mb\nc\t d", 50) == "a [31mb c d" and clean(None, 5) == "" and clean("abcdefgh", 5) == "abcde"
    red = redact("Bearer abc.DEF-1 and " + KEY + " and sk-xyz1234567890abc", (KEY,))
    assert KEY not in red and "SECRET" not in red and "abc.DEF-1" not in red and "xyz1234567890" not in red, red
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, ".env")
        assert load_key("OPENAI_API_KEY", {"OPENAI_API_KEY": " k1 "}, p) == "k1"
        assert load_key("OPENAI_API_KEY", {}, p) is None
        with open(p, "w") as f:
            f.write('# c\nOTHER=zz\nexport OPENAI_API_KEY="sk-a\x1bb_c-d"\nOPENROUTER_API_KEY=plain-key\n')
        assert load_key("OPENAI_API_KEY", {}, p) == "sk-ab_c-d" and load_key("OPENROUTER_API_KEY", {}, p) == "plain-key"
        assert load_key("NOPE", {}, p) is None
        assert load_key("OPENAI_API_KEY", {"OPENAI_API_KEY": "fromenv"}, p) == "fromenv"

    # 2 config and state
    with tempfile.TemporaryDirectory() as td:
        cp = os.path.join(td, "c.json")
        cfg, err = load_config(cp)
        assert err is None and cfg["openai_model"] == "gpt-5-mini" and cfg["enabled"]["critic"] is True
        with open(cp, "w") as f:
            json.dump({"openai_model": "gpt-x", "max_output_tokens": 99999, "openai_requests_per_day": 0,
                       "enabled": {"critic": False}, "reasoning_effort": ""}, f)
        cfg, err = load_config(cp)
        assert err is None and cfg["openai_model"] == "gpt-x" and cfg["reasoning_effort"] == ""
        assert cfg["max_output_tokens"] == HARD["max_output_tokens"] and cfg["openai_requests_per_day"] == 1
        assert cfg["enabled"] == {"classifier": True, "critic": False, "or_labeler": True}
        for bad in ("not json", "[1]", json.dumps({"openai_url": "https://evil.example.com/v1"}),
                    json.dumps({"max_output_tokens": "x"}), json.dumps({"enabled": {"critic": "yes"}}),
                    json.dumps({"reasoning_effort": "extreme"}), json.dumps({"openrouter_model": ""})):
            with open(cp, "w") as f:
                f.write(bad)
            assert load_config(cp) == (None, "roles_config.json unreadable or invalid"), bad
        sp = os.path.join(td, "s.json")
        st, err = load_state(sp)
        assert err is None and st["openai_requests"] == 0
        st.update(day="2026-11-12", openai_requests=5)
        save_state(sp, st)
        assert not os.path.exists(sp + ".tmp")
        st2, err = load_state(sp)
        assert st2["openai_requests"] == 5 and st2["day"] == "2026-11-12"
        roll_state(st2, "2026-11-12")
        assert st2["openai_requests"] == 5
        roll_state(st2, "2026-11-13")
        assert st2["openai_requests"] == 0 and st2["day"] == "2026-11-13"
        for bad in ("nope", '{"openai_requests": -1}', '{"day": "garbage"}', '{"errors": true}'):
            with open(sp, "w") as f:
                f.write(bad)
            st3, err = load_state(sp)
            assert st3 is None and "corrupt" in err, bad

    # 3 plans and rule checks
    good = ("ASSESSMENT: BEARISH\nDIRECTION: SELL\nENTRY_LOW: 0.755\nENTRY_HIGH: 0.765\nSTOP_LOSS: 0.77\n"
            "TP1: 0.75\nTP2: 0.735\nTP3: 0.72\n")
    bad_g = good.replace("STOP_LOSS: 0.77", "STOP_LOSS: 0.75").replace("TP1: 0.75", "TP1: 0.74")
    pg = parse_plan(good)
    assert pg == {"DIRECTION": "SELL", "ENTRY_LOW": "0.755", "ENTRY_HIGH": "0.765", "STOP_LOSS": "0.77",
                  "TP1": "0.75", "TP2": "0.735", "TP3": "0.72"}, pg
    assert rule_checks(pg, "SELL", 0.76) == []
    assert parse_plan("**DIRECTION:** BUY\n**STOP_LOSS:** 1,200.5\n") == {"DIRECTION": "BUY", "STOP_LOSS": "1,200.5"}
    buy = {"DIRECTION": "BUY", "ENTRY_LOW": "100", "ENTRY_HIGH": "101", "STOP_LOSS": "99", "TP1": "102",
           "TP2": "103", "TP3": "104"}
    assert rule_checks(buy, "BUY", 100.5) == []
    assert rule_checks(dict(buy, STOP_LOSS="100.5")) == ["stop is not below the entry zone"]
    assert rule_checks(dict(buy, TP3="102.5")) == ["take-profits are not increasing"]
    assert rule_checks(dict(buy, TP1="100.8", TP2="103", TP3="104")) == ["TP1 is not above the entry zone"]
    assert rule_checks(dict(pg, STOP_LOSS="0.75")) == ["stop is not above the entry zone"]
    assert rule_checks(dict(pg, TP1="0.75", TP2="0.74", TP3="0.745")) == ["take-profits are not decreasing"]
    assert rule_checks(pg, "BUY", 0.76) == ["DIRECTION differs from the engine signal"]
    assert rule_checks(pg, "SELL", 0.80) == ["entry zone is more than 1% away from the report price"]
    assert len(rule_checks({})) == 7 and rule_checks({"DIRECTION": "HOLD"})[0] == "missing or invalid DIRECTION"
    assert rule_checks(dict(pg, ENTRY_LOW="0.77", ENTRY_HIGH="0.76"))[0] == "entry zone inverted"

    # 4 items and json
    mk = lambda t, **k: dict({"title": t, "summary": "s " + t, "publisher": "pub", "source_domain": "d.com",
                              "source_type": "major_news", "direction": "BULLISH"}, **k)
    web1 = {"evidence": [mk("A one"), mk("A one"), mk(""), mk("B two", direction=None), "junk", mk("C three")]}
    its = items_from_web(web1, 10)
    assert [i["title"] for i in its] == ["A one", "B two", "C three"], its
    assert its[1]["kw"] == "NEUTRAL" and its[0]["kw"] == "BULLISH"
    assert len(items_from_web({"package": {"evidence": [mk("x%d" % i) for i in range(20)]}}, 10)) == 10
    assert items_from_web(None, 10) == [] and items_from_web({"package": None}, 10) == []
    assert items_from_web({"evidence": "x"}, 10) == []
    assert item_key("A One ") == item_key("a one") and len(item_key("t")) == 12
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1} and parse_json('x {"a": 2} y') == {"a": 2}
    assert parse_json("[1]") is None and parse_json("nothing") is None and parse_json(None) is None
    assert parse_json("{bad}") is None
    lab = norm_labels({"items": [{"n": 1, "direction": "bullish", "horizon": "days", "claim": "fact", "reason": "r"},
                                 {"n": 2, "direction": "moon", "horizon": "x", "claim": "y"},
                                 {"n": 9, "direction": "BULLISH"}, {"n": "a"}, "bad",
                                 {"n": 1, "direction": "BEARISH"}]}, 3)
    assert lab == {1: ("BULLISH", "DAYS", "FACT", "r"), 2: ("INVALID", "UNKNOWN", "UNKNOWN", "")}, lab
    assert norm_labels({"items": "x"}, 3) == {} and norm_labels(None, 3) == {}
    assert norm_critic({"contradictions": ["a"] * 9, "stop_vs_range": "tight", "verdict": "major_issues"}) == {
        "contradictions": ["a"] * 5, "stop_vs_range": "tight", "verdict": "MAJOR_ISSUES"}
    assert norm_critic(None) == {"contradictions": [], "stop_vs_range": "", "verdict": "INVALID"}
    assert close7(kappa([("B", "B"), ("B", "R"), ("R", "R"), ("N", "N")]), 7.0 / 11.0)
    assert kappa([]) is None and kappa([("B", "B"), ("B", "B")]) is None
# --- end part 6 ---

    # 5 chat_call shapes against a fake post (no network)
    class Resp:
        def __init__(self, code, data=None, text=""):
            self.status_code, self._d, self.text = code, data, text

        def json(self):
            if isinstance(self._d, Exception):
                raise self._d
            return self._d

    def okbody(text, fin="stop", pin=11, pout=7):
        return {"choices": [{"message": {"content": text}, "finish_reason": fin}],
                "usage": {"prompt_tokens": pin, "completion_tokens": pout}}

    def mkpost(script, log):
        def post(url, headers=None, json=None, timeout=None):
            log.append((url, dict(headers), dict(json), timeout))
            x = script(len(log), url)
            if isinstance(x, Exception):
                raise x
            return x
        return post
    cfg0, _ = load_config("/nonexistent")
    cfg0["roles_provider"] = "openai"
    OU = cfg0["openai_url"]
    body = openai_body(cfg0, "SYS", "USER json", 1500)
    assert body == {"model": "gpt-5-mini", "messages": [{"role": "system", "content": "SYS"},
                                                         {"role": "user", "content": "USER json"}],
                    "max_completion_tokens": 1500, "response_format": {"type": "json_object"},
                    "reasoning_effort": "low"}, body
    assert "reasoning_effort" not in openai_body(dict(cfg0, reasoning_effort=""), "a", "b", 5)
    log = []
    res = chat_call(mkpost(lambda n, u: Resp(200, okbody('{"a":1}')), log), OU, KEY, body, 12)
    assert res["ok"] and res["text"] == '{"a":1}' and (res["in"], res["out"], res["status"]) == (11, 7, 200), res
    assert log[0][0] == OU and log[0][1] == {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    assert log[0][3] == 12 and KEY not in json.dumps(log[0][2]) and KEY not in log[0][0]
    for resp, frag in ((Resp(401, {}, "bad key " + KEY), "HTTP 401"), (RuntimeError("boom " + KEY), "boom"),
                       (Resp(200, {"nope": 1}), "unexpected response shape"), (Resp(200, okbody("")), "empty content"),
                       (Resp(200, okbody('{"a":1}', fin="length")), "finish_reason=length")):
        r = chat_call(mkpost(lambda n, u, x=resp: x, []), OU, KEY, body, 5)
        assert not r["ok"] and frag in r["error"] and KEY not in r["error"], (frag, r)
    assert "[REDACTED]" in chat_call(mkpost(lambda n, u: Resp(401, {}, "k " + KEY), []), OU, KEY, body, 5)["error"]
# --- end part 7 ---

    # 6 full flow with a fake exchange: calls, stored rows, state, display, anonymity
    def find_titles(count, want):
        out, k = [], 0
        while len(out) < count:
            t = "Headline number %d" % k
            k += 1
            if int(item_key(t), 16) % 5 == want:
                out.append(t)
        return out
    samp, non = find_titles(2, 0), find_titles(3, 1)
    titles = [non[0], samp[0], non[1], samp[1], non[2]]
    web = {"evidence": [mk(t, direction=d) for t, d in zip(titles, ["BULLISH", "NEUTRAL", "BEARISH", "NEUTRAL",
                                                                      "BULLISH"])]}
    gpt_lab = {"items": [{"n": i, "direction": d, "horizon": "DAYS", "claim": "FACT", "reason": "r%d" % i}
                         for i, d in enumerate(["BULLISH", "NEUTRAL", "BEARISH", "BULLISH", "IRRELEVANT"], 1)]}
    or_lab = {"items": [{"n": 1, "direction": "NEUTRAL"}, {"n": 2, "direction": "BEARISH"}]}
    crit = {"contradictions": ["entry zones differ"], "stop_vs_range": "tight", "verdict": "minor_issues"}

    def script(n, url):
        if "openrouter" in url:
            return Resp(200, okbody(json.dumps(or_lab)))
        return Resp(200, okbody(json.dumps(gpt_lab if n == 1 else crit)))
    ctx = {"symbol": "RLCUSDT", "report": "Latest Price: 0.76", "signal": "SELL", "price": 0.76,
           "groq": good, "gemini": bad_g, "web": web}

    class Rng:
        def __init__(self, v):
            self.v = v

        def random(self):
            return self.v
    now = datetime.datetime(2026, 11, 12, 10, 0, tzinfo=utc)
    const_clock = lambda: 1000.0

    def go(cfg, keys, script, ctx=ctx, st=None, now=now, rng=None, clock=const_clock, con=None):
        td = tempfile.mkdtemp()
        sp = os.path.join(td, "s.json")
        st = st if st is not None else dict(FRESH)
        con = con if con is not None else sqlite3.connect(":memory:")
        ensure_schema(con)
        log = []
        buf = io.StringIO()
        with redirect_stdout(buf):
            lines = run_roles(ctx, cfg, keys, st, sp, con, mkpost(script, log), now, rng or Rng(0.1), clock)
        text = "\n".join(lines)
        assert KEY not in text and ORK not in text and "SECRET" not in text, text
        return lines, text, log, st, sp, con
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": ORK}, script)
    assert len(log) == 3 and log[0][0].startswith("https://api.openai.com/") and log[1][0].startswith("https://openrouter.ai/")
    assert log[2][0].startswith("https://api.openai.com/")
    u0 = log[0][2]["messages"][1]["content"]
    assert all(t in u0 for t in titles) and not any(w in u0 for w in ("BULLISH", "BEARISH", "SELL", "signal")), u0
    u1 = log[1][2]["messages"][1]["content"]
    assert all(t in u1 for t in samp) and not any(t in u1 for t in non), u1
    u2 = log[2][2]["messages"][1]["content"]
    assert u2.index("STOP_LOSS: 0.75") < u2.index("STOP_LOSS: 0.77") and "groq" not in u2.lower()
    assert "gemini" not in u2.lower() and "stop is not above the entry zone" in u2 and "Plan A:" in u2
    rows = con.execute("select role, status, plan_order, in_tokens, out_tokens, provider from shadow_roles "
                       "order by id").fetchall()
    assert [r[:2] for r in rows] == [("CLASSIFIER", "OK"), ("OR_LABELER", "OK"), ("CRITIC", "OK")], rows
    assert rows[2][2] == "A=gemini,B=groq" and rows[0][3:5] == (11, 7) and rows[1][5] == "openrouter", rows
    assert con.execute("select count(*) from shadow_roles_items where source='chatgpt'").fetchone()[0] == 5
    assert con.execute("select count(*) from shadow_roles_items where source='openrouter'").fetchone()[0] == 2
    got = dict(con.execute("select title, direction from shadow_roles_items where source='chatgpt'").fetchall())
    assert got[samp[0]] == "NEUTRAL" and got[samp[1]] == "BULLISH" and got[non[2]] == "IRRELEVANT", got
    kw = dict(con.execute("select title, kw_direction from shadow_roles_items where source='chatgpt'").fetchall())
    assert kw[non[1]] == "BEARISH" and kw[samp[0]] == "NEUTRAL"
    assert (st["openai_requests"], st["openai_tokens"], st["or_requests"], st["or_items"], st["errors"]) == (2, 36, 1, 2, 0)
    assert load_state(sp) == (st, None)
    assert lines[0] == "ADVISORY ROLES (no vote, not used by any gate)" and "BULLISH/DAYS/FACT" in text
    assert "second labeler (openrouter): 2 item(s) labeled" in text and "plan critic (chatgpt): MINOR_ISSUES" in text
    assert "gemini: stop is not above the entry zone" in text and "groq: ok" in text
    assert "contradictions: entry zones differ" in text
    pj = json.loads(con.execute("select parsed from shadow_roles where role='CRITIC'").fetchone()[0])
    assert pj["verdict"] == "MINOR_ISSUES" and pj["checks"]["groq"] == [], pj
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": None}, script, rng=Rng(0.9))
    assert con.execute("select plan_order from shadow_roles where role='CRITIC'").fetchone()[0] == "A=groq,B=gemini"
    assert len(log) == 2
# --- end part 8 ---

    # 7 caps, breaker, time limit, missing keys, bad replies, safe wrapper
    lines, text, log, st, sp, con = go(dict(cfg0, openai_requests_per_day=1), {"openai": KEY, "openrouter": None}, script)
    assert len(log) == 1 and "plan critic (chatgpt): daily request cap reached" in text and "rule checks (code)" in text, text
    lines, text, log, st, sp, con = go(dict(cfg0, openai_tokens_per_day=10), {"openai": KEY, "openrouter": None}, script)
    assert len(log) == 1 and "daily token cap reached" in text and st["openai_tokens"] == 18, (text, st)
    lines, text, log, st, sp, con = go(dict(cfg0, enabled={"classifier": False, "critic": True, "or_labeler": False}),
                                       {"openai": KEY, "openrouter": ORK}, script)
    assert len(log) == 1 and "evidence classifier" not in text and "plan critic (chatgpt)" in text
    err500 = lambda n, u: Resp(500, {}, "oops " + KEY)
    st = dict(FRESH)
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": None}, err500, st=st)
    assert len(log) == 2 and st["errors"] == 2 and st["off_day"] is None and "HTTP 500" in text, (text, st)
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": None}, err500, st=st)
    assert len(log) == 1 and st["off_day"] == "2026-11-12" and "error breaker" in text, (text, st)
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": None}, err500, st=st)
    assert len(log) == 0 and "OpenAI roles off for today" in text
    later = now + datetime.timedelta(days=1)
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": None}, err500, st=st, now=later)
    assert len(log) == 2 and st["off_day"] is None and st["errors"] == 2, st
    tick = [0.0]

    def jump():
        v = tick[0]
        tick[0] = 100.0
        return v
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": ORK}, script, clock=jump)
    assert len(log) == 0 and "run time limit" in text, text
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": None, "openrouter": None}, script)
    assert len(log) == 0 and "no OpenAI key" in text and "rule checks (code)" in text, text
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": None},
                                       lambda n, u: Resp(200, okbody("not json at all")))
    assert "reply was not a JSON object" in text and st["errors"] == 0 and len(log) == 2, (text, st)
    assert con.execute("select count(*) from shadow_roles where status='ERROR'").fetchone()[0] == 2
    assert con.execute("select count(*) from shadow_roles_items").fetchone()[0] == 0
    lines, text, log, st, sp, con = go(dict(cfg0), {"openai": KEY, "openrouter": None}, script,
                                       ctx=dict(ctx, web=None, groq="nothing", gemini="here"))
    assert "no evidence items" in text and "plan critic: no parsable plan" in text and len(log) == 0, text
    g = globals()
    real = g["load_config"]

    def boom(*a, **k):
        raise RuntimeError("x")
    g["load_config"] = boom
    try:
        assert run_roles_safe(ctx) == ["ADVISORY ROLES: error (RuntimeError)"]
    finally:
        g["load_config"] = real
    assert g["load_config"] is real

    # 7b the OpenRouter roles provider (the default): URL, key, body, shared budget
    cfgR = dict(cfg0, roles_provider="openrouter")
    c2, e2 = load_config("/nonexistent")
    assert e2 is None and c2["roles_provider"] == "openrouter" and c2["roles_model"] == "openai/gpt-oss-120b:free"
    assert c2["roles_reasoning"] == "low" and c2["openai_requests_per_day"] == 36 and c2["or_total_per_day"] == 38
    with tempfile.TemporaryDirectory() as td2:
        cp2 = os.path.join(td2, "c.json")
        for bad in (json.dumps({"roles_provider": "other"}), json.dumps({"roles_model": ""}),
                    json.dumps({"roles_reasoning": "extreme"})):
            with open(cp2, "w") as f:
                f.write(bad)
            assert load_config(cp2) == (None, "roles_config.json unreadable or invalid"), bad
        with open(cp2, "w") as f:
            json.dump({"or_total_per_day": 999, "roles_provider": "openai", "roles_model": "m/x:free",
                       "roles_reasoning": ""}, f)
        c3, e3 = load_config(cp2)
        assert e3 is None and c3["or_total_per_day"] == HARD["or_total_per_day"] and c3["roles_model"] == "m/x:free"
        assert c3["roles_provider"] == "openai" and c3["roles_reasoning"] == ""
    assert roles_target(cfgR, {"openai": "a", "openrouter": "b"})[0::3] == ("openrouter", "b")
    assert roles_target(dict(cfg0), {"openai": "a", "openrouter": "b"})[0::3] == ("openai", "a")
    assert roles_body(cfg0, "s", "u", 9) == openai_body(cfg0, "s", "u", 9)
    scriptR = lambda n, u: Resp(200, okbody(json.dumps([gpt_lab, or_lab, crit][n - 1])))
    lines, text, log, st, sp, con = go(cfgR, {"openai": None, "openrouter": ORK}, scriptR)
    assert len(log) == 3 and all(x[0] == cfgR["openrouter_url"] for x in log), [x[0] for x in log]
    assert all(x[1]["Authorization"] == "Bearer " + ORK for x in log)
    b0, b1 = log[0][2], log[1][2]
    assert b0["model"] == "openai/gpt-oss-120b:free" and b0["max_tokens"] == 1500, b0
    assert b0["reasoning"] == {"effort": "low"} and "max_completion_tokens" not in b0 and "response_format" not in b0
    assert b1["model"] == "poolside/laguna-s-2.1:free" and b1["max_tokens"] == 500, b1
    rows = con.execute("select role, provider, model from shadow_roles order by id").fetchall()
    assert rows == [("CLASSIFIER", "openrouter", "openai/gpt-oss-120b:free"),
                    ("OR_LABELER", "openrouter", "poolside/laguna-s-2.1:free"),
                    ("CRITIC", "openrouter", "openai/gpt-oss-120b:free")], rows
    assert (st["openai_requests"], st["or_requests"], st["openai_tokens"]) == (2, 1, 36), st
    assert "plan critic (gpt-oss-120b): MINOR_ISSUES" in text and "second labeler (openrouter): 2 item(s) labeled" in text
    st0 = dict(FRESH, day="2026-11-12", openai_requests=20, or_requests=18)
    lines, text, log, st, sp, con = go(cfgR, {"openai": None, "openrouter": ORK}, scriptR, st=st0)
    assert len(log) == 0 and text.count("OpenRouter daily budget reached") == 2 and "rule checks (code)" in text, text
    lines, text, log, st, sp, con = go(cfgR, {"openai": KEY, "openrouter": None}, scriptR)
    assert len(log) == 0 and "no OpenRouter key" in text, text

    # 8 report on crafted tables (hand-computed expectations)
    c = sqlite3.connect(":memory:")
    ensure_schema(c)
    assert build_report(sqlite3.connect(":memory:")) == ["no shadow_roles tables yet"]
    small = "\n".join(build_report(c))
    assert "calls: none | tokens in 0, out 0" in small and "chatgpt vs keyword labels: n=0 (counts only; needs 30)" in small
    t0 = now
    for i in range(30):
        g_dir = "BULLISH" if i < 15 else "BEARISH"
        kw_dir = "BULLISH" if i % 3 != 0 else "NEUTRAL"
        if i < 15:
            o_dir = "BULLISH"
        elif i < 24:
            o_dir = "BEARISH"
        else:
            o_dir = "BULLISH"
        its0 = [{"key": "k%02d" % i, "title": "t%d" % i, "kw": kw_dir}]
        store_items(c, t0, "XUSDT", 1, its0, {1: (g_dir, "DAYS", "FACT", "r")}, "chatgpt")
        store_items(c, t0, "XUSDT", 2, its0, {1: (o_dir, "DAYS", "FACT", "r")}, "openrouter")
    store_call(c, t0, "XUSDT", "CRITIC", "openai", "m", "h", "OK", "", {"in": 5, "out": 3}, {"verdict": "MAJOR_ISSUES"}, "A=groq,B=gemini")
    store_call(c, t0, "XUSDT", "CRITIC", "openai", "m", "h", "ERROR", "x", None, None, "")
    rep = "\n".join(build_report(c))
    assert "calls: CRITIC/ERROR 1, CRITIC/OK 1 | tokens in 5, out 3" in rep, rep
    assert "chatgpt directions: BEARISH 15, BULLISH 15" in rep, rep
    assert "chatgpt vs keyword labels: n=30 agreement 33.3%" in rep, rep
    assert "second labeler vs chatgpt: n=30 agreement 80.0% kappa 0.60" in rep, rep
    assert "critic verdicts: MAJOR_ISSUES 1" in rep and "No pass bar" in rep
    print("SELFTEST OK")


def close7(a, b):
    return a is not None and abs(a - b) < 1e-9


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "selftest":
        selftest()
    elif cmd == "check":
        cmd_check()
    elif cmd == "livecheck":
        cmd_livecheck(a[1] if len(a) > 1 else "roles")
    elif cmd == "report":
        cmd_report()
    else:
        print(__doc__)
# --- end part 9 ---
