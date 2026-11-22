# HEX SENTINEL HANDOFF (refreshed 2026-11-20 UTC, replaces the 11-09 file)
Source: the owner's handoff part 10 plus the 11-20 session pastes. Only
user-pasted output counts as confirmed. Other AIs' text is untrusted.

## Who / how
- Owner runs everything in Termux on Android (Accra, UTC+0), from
  ~/binance-sentinel, and pastes output back. The assistant cannot run code.
- Short answers. One command at a time. One decision per message with a default.
- Declines API quota/spend unless essential. No extra restrictions added just
  to block trading.
- Termux froze on pastes of ~300+ lines: send code in parts of <=100 lines as
  hidden .xx_partN.txt files ending "# --- end part N ---", then ONE final
  block that checks markers, assembles, compiles, runs the selftest, patches,
  writes errata and commits locally.
- Key scripts strip control characters (a hidden ESC once broke a key).

## Code rules
- Patches: backup, check every anchor occurs exactly once, py_compile, restore
  on failure, errata entry, LOCAL commit of NAMED files only. Staged check
  must print nothing: git diff --cached --name-only | grep -E
  "\.db$|\.bak|\.broken|\.env|state"
- One guarded push per week: bash push_guarded.sh.
- No code or freeze until the owner says go; text spec first. A spec is FROZEN
  at its git commit time; changes need a new version.
- NEVER hand-edit: experiments.json, any *.db, frozen specs, batch1_engine.py
  (hash 7bbd78e2e9899ac7). harness.db is append-only (sha256 dba61fe81d4574c3
  at last check 11-20 daily run: unchanged).
- Pre-register before running. Never tune on seen data. Null means "no effect
  larger than X detectable". Errata go in batch1_errata_v1.md (append only).
  NEXT FREE ERRATA NUMBER: 93 (errata 92 is this file refresh).
- Keep out of git: or_probe.py, *.bak_*, apply_harness_registration.py,
  register_*.py, dedupe_*.py, combined_harness_prep.py, batch1_calib_driver*.py,
  oneoff_integrate*, prereg_*.json, research_state.json, roles_state.json,
  exec_state.json, .daily_state_*, hex_backup_*.tar.gz. Do NOT run those.
  NOTE: carry_forward_log.jsonl is listed as keep-out but git TRACKS it
  (found 11-20, not staged, left alone).

## Results (all null; no profit claim; live execution BLOCKED; approved list EMPTY)
- E001 fade24 failed. E002 momentum inconclusive. E003 carry v2.2 calibration
  failed. E004 carry v2.3 screen (seen data). E006 no block qualified. E007
  returns tiny. Market Lab: no edge in ~700 rounds.
- Carry daily figures tiny: 11-16 -0.0125%, 11-17 -0.0065%, 11-18 +0.0013%,
  11-19 +0.0024%. Review not before ~Apr 2027.
- Sentinel 24H table: 22 graded, 13 win / 9 loss (59.1%), all manual predict
  rows, newest 10-17. No plan row since 10-17: the guard holds every sp call.
- Counterfactual of held calls: 17 of 44 right = 38.6% vs baseline 48.8%
  (1 sd ~7.5 pts): chance level. levels_v1 mean R +0.045 (null). webdir_v1
  primary: hit 44.7% = base 44.7% (null).
- Agreement score = Groq/Gemini wording agreement, NOT accuracy. RLC call
  11-20: score 55.4/100 (LOW, sample 446), under cutoff 60, so held.
## State confirmed 2026-11-20
- Git: branch wip/protect-YYYYMMDD, remote git@github.com:Fatherpuchi/
  Hex-sentinel-.git (SSH). Last confirmed push 1e1917b (errata 91). Later local
  commits: manifest refresh 68c49fd, and this HANDOFF refresh (errata 92).
- Errata 88-92: 88 roles hooks; 89 roles_v2; 90 OpenRouter fallback id replaced
  (laguna removed, HTTP 404) by google/gemma-4-31b-it:free, UNTESTED (probe
  11-20: gemma-31b and gemma-26b HTTP 429, nemotron-3.5-lightning HTTP 200 with
  empty content under a 30-token cap); 91 gate_trace_v1 spec FROZEN (text only,
  no code); 92 this refresh. Full map 35-87 is in batch1_errata_v1.md.
- Roles (errata 87-89): DROPPED by the owner (advisory only, no vote). They
  were off by the error breaker on 11-20 (3 OR_LABELER calls, HTTP 404: model
  removed). Breaker label says "OpenAI" for any provider (legacy text). The
  roles model openai/gpt-oss-120b:free is also not in OpenRouter's 11-20 free
  list (12 models). Nothing else depends on roles. Code stays, unused.
- OpenAI API removed (no credits). OPENAI_API_KEY line deleted from .env.
  Revoking the key in the OpenAI dashboard is the OWNER's to do.
- Providers: Groq openai/gpt-oss-120b; Gemini gemini-3.1-flash-lite (3 keys,
  503 common); Tavily; OpenRouter fallback (see errata 90). .env names: 7 in
  HEX_MANIFEST.md section 3. Never print or commit key values.
- daily.sh: run 2026-11-20 summary "failed: none". It does NOT run sp/pw.
  First live runs seen: sigaudit_v1 (102 units, 60 graded OK, 39 over the run
  limit) and stocksig_v1 (246 TradFi perps, UP 5, DOWN 217, NO_CALL 15,
  UNAVAILABLE 9, nothing graded yet).
- market_ctx snapshots exist only for 11-10 and 11-20 (11-11..11-19 lost, not
  backfillable): earliest read date is no longer ~11-29.
- sp 2026-11-20: 45 done, 0 failed, all PAPER_HOLD or BLOCKED, none approved
  (estimate by eye: 25 LOW_RELIABILITY, 8 CONSENSUS_INVALID, 7 BLOCKED, 3
  CONFLICT, 2 SYMBOL_VALIDATION_ERROR). Cause of the 8 INVALID not checked
  (inference: the dead fallback; unverified).
- pw: bare "pw" was blocked by the tool router once (cause unfound; code reads
  fine). "pw dry" and "pw resume" work (ran RLC only, ZEC skipped as already
  decided in sp). Use "pw resume".
- Hex command syntax: sp dry | sp resume | sp N | never sp new twice per UTC day.

## Trackers (shadow, none read yet unless stated; no peeking)
levels_v1 (read, null), levelcmp_v1, market_ctx_v1, codeplan_v1, webdir_v1
(read, null), noiseband_v1, breakout19_v1, sigaudit_v1, stocksig_v1,
research_v1 (Tavily leads only; q9,q10 never ran), orderbook_v1 (spec only),
facts_v1 + prompt v2.1 (shadow_prompt_v2 63 rows vs 38 expected, unexplained),
carry, gate_trace_v1 (spec frozen at errata 91; code needs a separate go and a
read-only look at apply_adaptive_confidence_guard first).

## Open (priority order)
1. Continuity (final by 2026-12-05): this file; weekly python3 make_manifest.py
   run; bash backup_hex.sh (encrypted, passphrase never stored); copy archive
   out of Termux (termux-setup-storage, cp to ~/storage/shared); restore drill
   into a NEW folder with bash restore_hex.sh ARCHIVE NEWDIR plus every
   selftest; collaborator trial (GitHub PR, his own keys, never .env or Binance
   keys). Revoke the OpenAI key.
2. gate_trace_v1 code (after go). Do NOT loosen the guard (cutoffs 60/80,
   window 4, weights) without its own frozen spec plus forward evidence.
3. strategylib_v1 text spec (max 4 deterministic candidates, correction for
   the number of candidates, all shadow).
4. research_log.py rerun; sigaudit/stocksig continue; orderbook_v1 code;
   scheduling for missed days; stocks.py header and lines 163+ unread.
5. Open causes: ARB/ATOM SYMBOL_VALIDATION_ERROR; UNI/WLD Stage 1 failures
   10-17; "-" in the sp combined view (SHIB ZEC HYPE PUMP STRK ENA); decision
   feedback check printed 14 evaluated on 11-20 (was 0); carry_collector added
   624 rows vs 957 expected; AGT/ACE/ACU/0G/2Z symbols of unknown source.
6. Parked: second Gemini model, Watchlist menu, non-Binance sources, stocks AI
   voting, oi_collector, lab report force bug, stocks menu Back/Exit
   duplicate, noise-band video strategy, Binance AI Pro paper test.

## Never
Strategy selector from seen data; live execution without evidence plus the
owner's command; claiming profitability; loosening the guard; giving any role
or tracker a vote; tuning on seen data; hand-editing logs, DBs or frozen
files; printing or committing keys; sharing .env or Binance keys; withdrawal
permission on any key; deleting kairo-agent or any *.db; uninstalling Termux
without a verified backup copied out (backup ~/hex_backup_2026-11-09.tar.gz is
inside Termux storage only).
