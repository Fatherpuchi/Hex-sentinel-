# exec_v1 spec - Hex Sentinel execution module (DRAFT, text only, no code)

Status: DRAFT for operator review. NOT frozen. It freezes only when the operator says "freeze exec_v1" and a later commit records it. Until then edits are allowed. Errata 73.

## 1. Confirmed settings (operator, in chat)
- Exchange: Binance USD-M Futures. Margin mode: isolated. Leverage: 10x.
- Risk per trade: a fixed planned loss of at most USD 1.50 at the stop-loss, excluding fees and slippage. Size from stop distance and exchange symbol rules; reject the trade if the risk cannot be kept within the limit.
- Maximum new entries: 5 per UTC day (a ceiling, never a quota). Maximum simultaneous open positions: 1 initially.
- Restart behavior: live trading is OFF after every restart.
- Environment order: Binance Demo first. Real funds only by a separate written operator decision after the approval test in section 11.

## 2. Placement and switch
- A new module hex_exec.py is called only after the existing final decision gate and receives the finished decision. It never changes Stage 1, the consensus guard, the risk filter, thresholds or paper logging. Trigger: a decision with final_action PAPER_BUY or PAPER_SELL (the history shows such rows exist, for example PAPER_SELL with risk_status CAUTION). The exact hook point is fixed after the gate code is read.
- State file exec_state.json, outside git, written atomically: mode, env (demo or mainnet), UTC-day entry counter, kill flag, breaker count, realized loss today. A missing or corrupt file, or any restart, means mode OFF. The entry counter and loss total survive restarts.
- Hidden command `tradus` (not in the help list): `tradus status`; `tradus on` (typed phrase plus preflight; mainnet needs a second, different phrase); `tradus off` (instant, no confirmation); `tradus kill` (OFF plus cancel of unfilled entries); `tradus close SYMBOL` (confirmation required).
- The banner shows LIVE TRADING: ON/OFF plus the env. It shows BLOCKED unless mode is ON and the preflight passed. Live execution stays BLOCKED in the existing code paths until this spec is frozen, implemented, selftested and demo-verified.

## 3. Preflight for ON
- Keys for that env are loaded and never printed; the base URL matches the env; a read-only signed account call works; the clock is within tolerance of the exchange; API restrictions are read where the endpoint allows and withdrawals must be off (mainnet ON refuses otherwise); position mode is read and must be one-way; isolated margin and leverage 10 can be set for the symbol; symbol rules are loaded; the daily cap and size caps are set. Mainnet ON also needs a non-empty approved list.

## 4. Position sizing (exact)
- risk_usd = 1.50 (a hard cap in code; lowering is allowed, raising needs exec_v2). stop_dist = |entry - stop|. qty_raw = risk_usd / stop_dist. qty = qty_raw rounded DOWN to the symbol step size, never up.
- Reject if qty < min quantity, qty x entry < min notional, or qty x stop_dist > risk_usd after rounding.
- notional = qty x entry. margin = notional / 10. Reject if margin exceeds available balance x (1 - 0.20).
- Liquidation check: estimate the liquidation distance from leverage and the maintenance rate of the symbol's bracket; reject if stop_dist / entry > 0.80 x that distance. After the fill, read the exchange's liquidation price; if the stop is not inside it, close at once (rule 6).
- Estimated round-trip fees and their ratio to risk_usd are logged. They do not cause a rejection unless the operator sets a limit.
- Planned loss excludes fees and slippage. Real loss at a stop can be larger: stop-market slippage, gaps, fees.

## 5. Per-order checks (in order; any failure means no order and a logged reason)
- mode ON; the decision is BUY or SELL; the plan has entry, stop and TP1 on the correct side (decisions with 0.0 levels never trade); approved list (mainnet); fewer than 5 entries today (UTC, counted at submission, a cancelled entry still counts); open positions below the cap of 1; the realized loss today below the limit (section 7); sizing (section 4); liquidity floor (24h volume rank as in errata 45, spread check once the public endpoint is verified); last price within 0.3% of the planned entry (else stale); breaker not tripped.
- If several candidates pass in one cycle, they are ordered by TP1 reward-to-risk as a tiebreak only. That is not a claim of quality.

## 6. Order lifecycle
- Deterministic client order id from the decision id, so a retry cannot duplicate. Entry: LIMIT at the planned entry; cancelled after 10 minutes if unfilled.
- A fill is recorded only after the exchange confirms it: acknowledgement, then a status poll, then fills; partial fills are handled (protect the filled quantity, cancel the rest after the timeout). Nothing is recorded as filled from the request alone.
- After a confirmed fill: exchange-side stop (reduce-only) and one take-profit at TP1 (reduce-only) for the filled quantity. TP2 and TP3 are ignored in v1.
- If protection fails or the liquidation check fails: market reduce-only close (close_if_unprotected, default true), mode OFF, event CRITICAL.
- Time stop: reduce-only market exit 23 hours after entry (configurable, at most 24).
- Append-only exec.db records every request and response with secrets redacted. Local and exchange state (positions, open orders) are reconciled at start and each cycle; a mismatch turns the module OFF.

## 7. OFF, kill and emergency stops
- OFF: no new orders; unfilled entries are cancelled; open positions and their exchange-side stop and TP stay. Time-stop exits do not run while OFF (manage_when_off, default false), and the status screen warns about it. No automatic closing unless configured.
- Breaker: 3 consecutive order errors switch OFF. Daily realized-loss limit: placeholder USD 4.50 (3 x risk), then OFF until the next UTC day. This is a NEW control, proposed because no emergency stop was located in the existing code; the operator may veto it.

## 8. Scanning and ranking
- The existing pipeline runs over the 45-coin list once per UTC day by default (the existing schedule is manual: `sp`). Autonomous running needs a scheduler or loop, which does not exist yet, and Android may kill Termux. Each coin costs Groq 2 and Gemini 2 calls; the operator decides the schedule.
- No ranking by an invented quality score. No threshold is lowered and no signal is invented to reach a quota. Ranking by a measure comes only after that measure has forward evidence.

## 9. Diagnosis of "no approvals" (read-only, shadow)
- A new shadow_gate_trace table stores, per decision, the guard score and its parts, the stage reached and the reason. A `why` command prints the funnel and, per held coin, the failing gate and its distance from the cutoff.
- Held calls are graded by gate state (agreement score under 60, conflict, Stage 1 blocked), at least 30 per group, to ask whether any gate is too strict. Thresholds change only through a new frozen spec with forward evidence.

## 10. Visibility
- `tradus status` shows mode, env, entries x/5, open position, open orders, last events and errors, realized loss today, breaker state. The existing interface banner reflects the mode.

## 11. Approval test (proposed, to be edited before freeze)
- Candidates: guard-passed AI plans, codeplan_v1, noiseband_v1. Forward only, fees from demo fills plus a placeholder 0.10 pp round trip, slippage measured against the signal price.
- At least 100 completed trades over at least 30 distinct days per candidate. Reported: mean net R, win rate, profit factor, maximum drawdown, against random-direction and always-up and always-down baselines at the same times.
- Bar: the 95% lower bound of mean net R (bootstrap by day, corrected for the number of candidates) must exceed 0 and the candidate must beat its baseline. Passing never adds anything to the approved list automatically; the operator decides.

## 12. Demo test plan
- D0 read-only: time, balance, symbol rules, permissions. D1: one minimum-size test through the full path (entry, fill, protection, cancel, close), using a demo-only test signal that passes every check in section 5 except the pipeline decision; the code refuses it unless the env is demo. D2: injected failures (rejection, insufficient balance, timeout, partial fill, duplicate, protective failure). D3: restart with an open position. D4: OFF with open orders.
- Demo fills may differ from real fills, so demo results are no profitability claim.

## 13. Secrets
- Keys live in .env only, never printed or logged (a selftest checks redaction). No withdrawal permission; an IP restriction is recommended. No key is ever pasted into chat.

## 14. To verify against Binance's official docs before any code (not verified)
- Demo URLs (third-party clients disagree about the futures demo host), conditional-order endpoints and parameters (Binance has changed these in the past), reduce-only behavior, margin-type and leverage endpoints, leverage brackets and maintenance rates, fee schedule, liquidation formula, rate limits, position-mode endpoint, API-restriction endpoint.

## 15. Existing controls: located and not located
- Located: Stage 1 status checks, the multi-AI agreement guard (cutoffs 60 and 80, window 4), the final decision audit (audit_final_decision), paper plans with stops and TPs.
- Not located: an emergency stop, the approved-list code. Where existing controls differ from this draft, they win.

## 16. Never
- No claim of profitability or readiness without the evidence in section 11. No loosening of a guard or threshold to make the bot trade. No withdrawal permission. No simulated live order recorded as real. Live ON only by an explicit operator command.
