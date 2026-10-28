# research_v1 spec - web research leads module (text spec, no code yet)

Status: FROZEN once committed (the git commit time is the freeze time). Any change needs research_v2. Section 9 lists API details that must be verified against the official docs before code. Errata 74.

## 1. Purpose and decision record
- The operator decided to add a web-search API so strategy research can be retrieved automatically; the assistant had advised skipping it (research can be done in chat for free) and recorded that. Provider: Tavily (free plan of 1,000 credits per month, no card, per Tavily's official docs; the cost of a search is 1 or 2 credits and the docs differ, so budgeting assumes 2).
- The module collects LEADS: links, titles and short snippets about trading strategies and evidence on whether they work out of sample. A lead is not evidence. Nothing here proves a strategy works.

## 2. Isolation (hard rules)
- Standalone research_log.py (selftest | check | run | report). It is not imported by, and does not call, the pipeline, the guard, the prompts, the web-evidence layer, decisions or any execution code.
- Results are never fed to an AI automatically and never change evidence weights, thresholds or decisions. They are shown to humans only. Any lead the assistant reads in chat is treated as untrusted data and never as instructions.
- A strategy is built from a lead only through a written spec with definitions fixed in advance, then shadow forward testing (the strategylib process). The lead's own performance claims are never used.

## 3. Queries (fixed now, 10)
1. cryptocurrency time-series momentum out-of-sample study
2. bitcoin trend following moving average backtest transaction costs
3. crypto intraday momentum strategy peer reviewed
4. cryptocurrency mean reversion strategy out-of-sample evidence
5. crypto volatility breakout strategy evidence
6. Donchian channel breakout cryptocurrency study
7. cryptocurrency perpetual funding rate strategy research
8. technical analysis cryptocurrency profitability data snooping
9. crypto cross-sectional momentum factor research
10. crypto trading strategy replication failed out-of-sample
- Queries 8 and 10 look for negative evidence on purpose. The list changes only through research_v2.

## 4. Budget and schedule
- At most 10 searches per run, one run per 7 days (a second run within 6 days is refused, no force flag). A monthly cap of 300 credits (30 percent of the free plan) counted at an assumed 2 credits per search and stored in research_state.json outside git; the module refuses to run past the cap. A failed request still counts. No retries beyond one attempt per query. A 429 or 5xx stops the run.
- Basic search depth, 5 results per query, no page extraction in v1.

## 5. Storage
- shadow_research_leads in shadow.db, insert-only: id, run_utc, query_no, url (unique), title, snippet (cut to 400 characters), domain, published (only if the API returns one, else empty), provider_score (if returned), source_note. Only the link, title and a short snippet are stored, not full page text.
- `report` prints leads grouped by query (domain, title, link) and the credits used this month. It prints no judgment.

## 6. Secrets
- The key TAVILY_API_KEY lives in .env only (loaded with an explicit path), is never printed or logged, and is never pasted into chat. The selftest checks that the key cannot appear in any printed or stored text.

## 7. Reading rule
- No numeric reading rule applies because nothing is graded. Leads are reviewed by hand. A lead that is peer-reviewed or has a stated out-of-sample result still needs its own pre-registered shadow test. The published decline of predictability after publication (McLean and Pontiff, stock predictors) is the reason for treating every lead with suspicion.

## 8. Known limits
- Search results are unranked by truth. Snippets can be wrong, promotional or injected text. Dates may be missing. A fixed query list will miss strategies not named in it. Free-plan terms can change.

## 9. To verify against Tavily's official docs before code (not verified)
- Endpoint path and method, auth header form, request parameter names (query, max_results, search_depth, domain filters, time range), response field names (url, title, content, score, published date), credit accounting and any usage field in the response, rate limits, error codes.
