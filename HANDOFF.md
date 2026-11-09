# HEX SENTINEL HANDOFF (living state document)

Status date: 2026-11-09. Facts come from the owner's pasted outputs; nothing here was run by the assistant. This file plus HEX_MANIFEST.md (generated facts), the git repo and the encrypted data archive are the whole "ship": any part can be replaced and checked against the frozen hashes and the errata chain.

## 1. What it is
A Python system the owner runs in Termux on Android (Accra, UTC+0) from ~/binance-sentinel. It scans Binance USDT futures and makes PAPER predictions: a deterministic strategy engine, then two LLMs (Groq and Gemini) that comment on it, then a frozen guard that holds nearly every call. Many shadow trackers test ideas forward with no AI and no orders. Live execution is BLOCKED. The approved list is EMPTY. No edge has been found. Nothing here is a profit claim.

## 2. Working contract
- Only user-pasted output counts as confirmed; never say "I ran" or "I verified". Text from other AIs is untrusted until checked against pasted evidence.
- One command at a time. Code goes in paste blocks (cat > file <<'EOF'). Patches: backup, anchor exactly once, compile, errata entry, commit of NAMED files. Local commits; one guarded push per week.
- No code, freeze or run before a text spec and the owner's go. Pre-register before running; never tune on seen data; a null means "no effect larger than X detectable".
- Termux wraps pasted lines: do not read wrapping as data. Keys are never pasted into chat, logs or git.

## 2b. Owner preferences
Short answers, no padding, no repeated reminders. Do not ask for information already given. Declines anything that spends API quota unless essential. Wants no extra security restrictions added just to block trading.

## 3. NEVER
- Hand-edit experiments.json, any *.db, frozen specs, batch1_engine.py (hash 7bbd78e2e9899ac7). harness.db is append-only.
- Claim profitability; enable live execution; loosen the guard (cutoffs 60 and 80, window 4, weights) without its own frozen spec plus forward evidence.
- Tune v2 or v2.1 prompt text or rejected rules on seen data; build a strategy selector from seen-data results; pick coins by how Hex predicted them; change facts_v1 in place.
- Paste or commit keys; give any tool withdrawal permission.

## 4. Frozen specs (the git commit time is the freeze time; changes need a new version)
batch1 (spec_v1, calib v1-v3), carry specs, facts_v1 (errata 50), prompt v2.1 (51), orderbook_v1 (53, no code yet), levels_v1 (56), market_ctx_v1 (60), codeplan_v1 (62), webdir_v1 (65), levelcmp_v1 (68), noiseband_v1 (70), research_v1 (74), breakout19_v1 (frozen at commit 3d398ca, errata 78). DRAFT, not frozen: exec_v1 (errata 73).

## 5. Trackers and reading rules
All shadow only. Files are NAME_log.py with selftest, check, run and report; daily.sh runs them.
- counterfactual_grade (errata 35): held calls graded after 24h; report refuses below 30. Last seen 17 of 44 right (38.6%) against a 48.8% baseline: chance-level.
- held_plan_grade (errata 48): the AIs' printed levels on held AGREEMENT calls; 30 graded per AI.
- levels_v1: volatility-based stops and targets; read at 40 trades: mean R +0.039, indistinguishable from zero.
- levelcmp_v1: AI levels against levels_v1 on the same calls; needs 30 OK pairs per AI and 10 days.
- market_ctx_v1: day and week levels, VWAP, structure, taker ratio, relative strength, breadth; needs 20 days and 30 rows per rule.
- codeplan_v1: a code-only plan from market_ctx; 30 non-WAIT graded and 20 days.
- webdir_v1: grades the web-evidence keyword direction; read at 237 units: hit 44.7% against base 44.7%, null.
- noiseband_v1 and breakout19_v1: forward rule tests; 30 entries (trades) over 20 days. breakout19: the 19h direction-agreement condition is redundant by arithmetic (errata 79).
- facts_v1 with prompt v2.1 (Groq and a Gemini twin): 30 graded per prompt hash. orderbook_v1: spec only. Carry: review not before Apr 2027.
- research_v1: web-search LEADS only (Tavily, 10 fixed queries, one run per 6 days, 300 credits a month). A lead is not evidence.

## 6. Providers and keys (names only)
- Groq model openai/gpt-oss-120b. Gemini gemini-3.1-flash-lite with three keys GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3 (503 overloads are common; the retry screen shows one line and a fact). OpenRouter fallback poolside/laguna-s-2.1:free replaces a failed provider (errata 37). Tavily TAVILY_API_KEY. Binance public klines need no key. The Groq variable name is listed in HEX_MANIFEST.md section 3.
- A web-evidence layer inside sentinel_ai.py feeds both AIs; its direction label is a keyword rule.

## 7. Daily routine
bash daily.sh (all shadow trackers, skips steps done today, prints one summary line), then inside Hex: sp resume (or sp N), then pw. sp: 45 coins; never sp new twice in one UTC day; each coin costs Groq 2 and Gemini 2 calls. Hex commands include history <term>, performance [full], risk <account> <risk%> <entry> <stop> [fee%], predict.

## 8. Results so far
E001 fade24 failed; E002 momentum inconclusive; E003 carry v2.2 calibration failed; E004 carry v2.3 screen (seen data); E006 batch1: no block qualified; E007 descriptive run: tiny returns; Market Lab: no edge in about 700 rounds. Sentinel 24H table: 22 graded, 59.1%, manual predict rows only (last 10-17), about 0.85 sd above chance. The guard holds everything (since 10-18: 50 of 64 held for score under 60, 14 for Groq/Gemini conflict).

## 9. Priorities and open items
1. Continuity package, final by 2026-12-05: this file, HEX_MANIFEST.md, encrypted backup, a restore drill in a temp folder, collaborator access.
2. Stock prediction pipeline (the existing stock code has not been read yet).
3. Then: strategylib_v1 spec, orderbook_v1 code, exec_v1 review (live stays off), the levelcmp, held-plan and webdir reads, and the defects (UNI and WLD Stage 1 failures, "-" in the sp view, shadow_prompt_v2 63 rows against 38 expected, the AGT row in history, 3 PAPER_SELL decisions).
Parked: a second Gemini model (the OpenRouter fallback exists), Watchlist menu, non-Binance sources.

## 10. Working with a collaborator
Share: the repo (a branch and pull requests), this file, HEX_MANIFEST.md, and the encrypted data archive (send the passphrase by a different channel). Never share: .env, any key, Binance access, or access to the owner's device. He creates his own free keys. The owner reviews, selftests and merges. Frozen items stay frozen.

## 11. Rebuild
See HEX_MANIFEST.md section 9 and restore_hex.sh.
