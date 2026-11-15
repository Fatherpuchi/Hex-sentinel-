# roles_v1 spec - four-AI role design (DRAFT, text only, no code)

Status: FROZEN at the commit that contains this line (the git commit time is the freeze time). Any change needs roles_v2. Errata 86 (draft) and 87 (freeze).

## 1. Decision record
- Operator decisions (chat): add ChatGPT (OpenAI API) as a third AI with role 1 (evidence classifier) and role 2 (plan critic), in the live run and not shadow-only; make Groq and Gemini differ slightly; give OpenRouter a role. The assistant advised shadow first (a role that is never graded cannot be trusted) and recorded it; the operator's decision stands. "Live" means: runs in the real analysis flow, printed in the output and stored. It does NOT mean a vote.

## 2. Hard rule: advisory, no vote
- New outputs never enter compare_multi_ai_assessments, the agreement score, the guard, Stage 1, final decisions, plans, thresholds or execution, and are not fed into the prompts of Groq or Gemini. Any promotion into a decision input needs its own frozen spec and forward evidence (30 graded units over 10 distinct days per role). Live execution stays BLOCKED.

## 3. Roles
- Groq (analyst, baseline): prompts unchanged.
- Gemini (skeptic): same system prompt and output format; one paragraph added to the user prompt only: weigh the strongest reasons the signal could be wrong before choosing the assessment; if they outweigh the case for it choose CAUTIOUS or NEUTRAL; REASON names the single strongest risk. The effective date is recorded in errata; the audit table has no variant column, so before/after comparisons use dates. A provider that fails over to OpenRouter gets the baseline prompt.
- ChatGPT role 1 (evidence classifier): per analysis, up to 10 web-evidence items from the existing evidence package (title, summary, source, published_at, retrieved_at). It sees no engine signal and no AI answer. Per item: DIRECTION (BULLISH, BEARISH, NEUTRAL, IRRELEVANT), HORIZON (HOURS, DAYS, WEEKS, UNKNOWN), CLAIM (FACT, OPINION, PROMO, UNKNOWN), one short reason.
- ChatGPT role 2 (plan critic): sees the engine report, the engine signal and both AI plans in a randomized A/B order. Output: RULE_VIOLATIONS (stop on the wrong side, TPs not monotonic, entry outside the zone, missing levels), CONTRADICTIONS between the plans, STOP_DISTANCE against the 24h range when facts_v1 is available, VERDICT (CONSISTENT, MINOR_ISSUES, MAJOR_ISSUES). It cannot change a plan or a decision.
- OpenRouter: keeps its fallback duty (errata 37). New: a second labeler of the same role-1 items with a free model of a different family, at most 20 items per day chosen by a fixed rule (every 5th item id), leaving the rest of the free-tier daily cap for fallback. It measures agreement with ChatGPT (rate and Cohen's kappa) and never votes.

## 4. Display and storage
- Outputs appear under the existing run output as an ADVISORY ROLES block and are stored with prompt hash, model, tokens, latency and error in a new shadow_roles table in shadow.db. A module hex_roles.py is called after the AI answers; any failure or timeout is swallowed and never changes the run; per-run limit 30 seconds.

## 5. Budgets (hard caps in code, kept in roles_state.json)
- ChatGPT: at most 2 requests per analysis, 100 per UTC day, 1500 output tokens per request (hidden reasoning tokens count toward it) and a daily token cap; stops for the day at the cap. The model name comes from a config file chosen from OpenAI's current docs (avoid a snapshot with a published shutdown date). A spend limit is also set in the OpenAI dashboard. Estimated cost about 3 USD per month at 45 analyses a day (the assistant's arithmetic; reasoning tokens can multiply it).
- OpenRouter: 20 labeling calls per day. Free-model limits found in docs: 20 requests per minute and 50 per day (1000 after 10 USD lifetime purchases), account-wide.

## 6. Evaluation (registered before any data)
- Classifier: DIRECTION labels graded against the next 24h return on the same symbol-day units and rules as webdir_v1, beside the keyword labels; 30 units over 20 days. Critic: share of MAJOR_ISSUES plans that hit the stop first against the others (levelcmp and held_plan_grade rows); 30 plans. Skeptic: agreement rate with Groq and CAUTIOUS share before and after the effective date, and the hit rate of non-neutral assessments under the v2 grading rule; 30 graded. OpenRouter labeler: agreement and kappa with ChatGPT on 30 items. No pass bar, no causal claim.

## 7. Never
- No key in git, logs or chat. ChatGPT and OpenRouter never see account, order or key data. No role gets a vote or a decision input without a new frozen spec.

## 8. Known limits
- The evidence for role and model diversity comes from math, QA and groundedness benchmarks, not trading; results are mixed and role prompts alone often keep correlated errors. Groq's model (gpt-oss) is released by OpenAI, so ChatGPT adds less independence than a different vendor would. All AIs share the same evidence pool. The skeptic lens may lower agreement and increase holds. Free OpenRouter models rotate and are rate-limited at peak. Not a profit claim.

## 9. Implementation notes at freeze (errata 87)
- Code: hex_roles.py (module, selftest, check, livecheck, report); roles_config.json (optional) holds model names, lower caps and per-role switches; URLs are accepted only on api.openai.com and openrouter.ai; caps in the config can only be lowered. roles_state.json holds the daily counters and the error breaker (3 errors in a row switch the OpenAI roles off until the next UTC day).
- Role 2 also runs deterministic rule checks in code (stop on the wrong side, TPs out of order, TP1 inside the entry zone, direction differing from the engine signal, entry zone more than 1 percent from the report price) and displays them even when no key is present; the model only adds contradictions, a stop-versus-range remark and the verdict. Plans reach the model in a random A/B order without provider names.
- OpenRouter samples the items whose title hash mod 5 is 0, at most 20 items per day, one attempt per analysis, 20 seconds. OpenAI request parameters: max_completion_tokens, response_format json_object, reasoning_effort low; no temperature.
- Not in this file: grading against price outcomes (a later tracker on webdir_v1 units) and the hooks into sentinel_ai.py (the Gemini skeptic paragraph and the call to run_roles_safe), which are separate anchored patches.
