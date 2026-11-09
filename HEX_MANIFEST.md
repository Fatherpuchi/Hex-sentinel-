# HEX MANIFEST (generated facts, no secrets)

Generated 2026-11-09 22:12 UTC by make_manifest.py. Regenerate weekly. HANDOFF.md holds the rules and the status.

## 1. Environment
- python 3.14.6 | Android aarch64
- numpy 2.4.4 | requests 2.34.2 | python-dotenv 1.2.3

## 2. Git
- branch wip/protect-YYYYMMDD | HEAD aeeb012 2026-11-09 21:53:30 +0000
- commits 72 | unpushed 0
- remote: git@github.com:Fatherpuchi/Hex-sentinel-.git
- last 15 commits:
  - aeeb012 errata 79: breakout19_log.py for breakout19_v1, daily.sh
  - 3d398ca errata 78: breakout19_v1 FROZEN, S and M as logged context
  - c064565 errata 77: breakout19_v1 text spec (DRAFT, no code)
  - 3bba078 errata 76: first research_v1 runs (observation only)
  - f208b71 errata 75: research_log.py for research_v1 (selftest only)
  - 7783b3e errata 74: research_v1 text spec (no code)
  - 684d118 errata 73: exec_v1 execution specification (DRAFT, no code)
  - 7a784d0 errata 72: noiseband_log.py for noiseband_v1, daily.sh
  - 82f82bf errata 71: Gemini 503 wait screen (display only)
  - ecd9ded errata 70: noiseband_v1 text spec (no code)
  - 807d8e9 errata 69: levelcmp_log.py for levelcmp_v1 (selftest only), daily.sh
  - 3ba0d4b errata 68: levelcmp_v1 text spec (no code)
  - ca8deb6 errata 67: first webdir_v1 read (observation only)
  - e0e1f8f errata 66: webdir_log.py for webdir_v1 (selftest only), daily.sh
  - 0fb4bd9 errata 65: webdir_v1 text spec (no code)

## 3. API inventory (names only; values are never written here)

Variables in .env (and the code files that mention each name):
- GROQ_API_KEY: set | sentinel_ai.py, sentinel_ai_backup_20260910_214308.py, sentinel_ai_duplicate_cleanup_backup_20260910_222625.py, sentinel_ai_final_audit_backup.py, sentinel_ai_market_backup_20260910_222414.py, sentinel_ai_market_backup_20260910_222438.py
- GEMINI_API_KEY: set | sentinel_ai.py, sentinel_ai_backup_20260910_214308.py, sentinel_ai_duplicate_cleanup_backup_20260910_222625.py, sentinel_ai_market_backup_20260910_222414.py, sentinel_ai_market_backup_20260910_222438.py, sentinel_ai_startup_backup_20260910_214443.py
- CEREBRAS_API_KEY: set | not referenced by name in any .py file
- OPENROUTER_API_KEY: set | or_probe.py, sentinel_ai.py
- GEMINI_API_KEY_2: set | sentinel_ai.py
- GEMINI_API_KEY_3: set | sentinel_ai.py
- TAVILY_API_KEY: set | research_log.py

External hosts mentioned in code (host: files):
- api.binance.com: carry_collector.py, carry_inventory.py, carry_klines_inventory.py, counterfactual_grade.py
- api.coingecko.com: evidence.py, sentinel_ai.py, sentinel_ai_backup_20260910_214308.py, sentinel_ai_final_audit_backup.py
- api.coinlore.net: evidence.py
- api.example-host.com: make_manifest.py
- api.groq.com: sentinel_ai.py, sentinel_ai_backup_20260910_214308.py, sentinel_ai_duplicate_cleanup_backup_20260910_222625.py, sentinel_ai_final_audit_backup.py
- api.tavily.com: research_log.py
- b.org: research_log.py
- c.org: research_log.py
- d.org: research_log.py
- dev.kwayisi.org: stocks.py
- e.org: research_log.py
- fapi.binance.com: carry_collector.py, carry_inventory.py, carry_klines_inventory.py, counterfactual_grade.py
- generativelanguage.googleapis.com: sentinel_ai.py, sentinel_ai_backup_20260910_214308.py, sentinel_ai_duplicate_cleanup_backup_20260910_222625.py, sentinel_ai_market_backup_20260910_222414.py
- hidden-host.com: make_manifest.py
- news.google.com: sentinel_ai.py, sentinel_ai_backup_20260910_214308.py, sentinel_ai_duplicate_cleanup_backup_20260910_222625.py, sentinel_ai_market_backup_20260910_222414.py
- openrouter.ai: or_probe.py, sentinel_ai.py
- www.a.com: research_log.py
- www.example.com: research_log.py
- www.w3.org: hex_chart.py, lab_play.py

## 4. Tracked files (path | bytes | sha256[:16]); FROZEN = never edit by hand
- .gitignore | 1285 | ca601117df71f16c
- CLAUDE_HEX_SENTINEL_AUDIT.md | 18649 | ee479c476ea09a3a
- LOCK_STALE_SECONDS | 0 | e3b0c44298fc1c14
- analyze_market_regimes.py | 11293 | 474bd06e6418fd66
- backtest_engine.py | 4451 | 759f9164f6bbec40
- batch1_calib.py | 12048 | 6c7248c7802fa0a7
- batch1_calib_checkpoint_v2.json | 870 | 3b1eeb328f0e5fe4
- batch1_calib_checkpoint_v3.json | 4888 | 1139cc656597c42d
- batch1_calib_result_v3.json | 11134 | 0cc39f3e950c8fa9
- batch1_calib_spec.py | 8935 | caa8efc5f6d46909 FROZEN
- batch1_calib_spec_v1.json | 7253 | c334684c1e2b5e7e FROZEN
- batch1_calib_spec_v2.json | 8607 | 694075b69e2f004c FROZEN
- batch1_calib_spec_v3.json | 9132 | 9db7876d2dd17ec3 FROZEN
- batch1_engine.py | 8202 | 7bbd78e2e9899ac7 FROZEN
- batch1_errata_v1.md | 69311 | fc63312efd02513c
- batch1_log_e006.py | 5102 | cf1534d51ed4eeb1
- batch1_log_e007.py | 4633 | ddb5e702dd0e8162
- batch1_real.py | 7113 | 7b8b7cd67064a025
- batch1_real_result_v1.json | 5287 | 3315b6698b15effe
- batch1_spec.py | 14857 | 91d6122d48d991fa FROZEN
- batch1_spec_v1.json | 12659 | 2e3f825cccd0b6be FROZEN
- breakout19_log.py | 30674 | c37a259602e22ab3
- breakout19_v1_spec.md | 7011 | 891c8a9a13fc0d92 FROZEN
- build_historical_features.py | 9203 | 830cefcf8774e682
- calib2_result.json | 242 | 71347f0e83955697
- calib3_result.json | 173 | 5b12cdbf96bce087
- carry_calib.py | 7469 | 516560aa16e82a4d
- carry_calib22.py | 11857 | 9064a102f3ddf3a2
- carry_calib22_result.json | 933 | b7a05a7b27aae798
- carry_collector.py | 8321 | 1e943620ddacb979
- carry_coverage_detail.py | 3931 | 8b51ea6bd9cde371
- carry_forward_coins.json | 630 | 12314927ff4409e5
- carry_forward_log.jsonl | 6005 | e1bc934fb2f83bce
- carry_forward_obs.py | 13659 | 1e7cb8200d928d99
- carry_forward_spec_v1.json | 6760 | 9f3dd0bf8a1fca0a FROZEN
- carry_inventory.py | 5430 | 6abd2d327e6cb007
- carry_klines_inventory.py | 8656 | 697597a429b39853
- carry_log_e003.py | 3232 | c952e7fb311834de
- carry_markcheck.py | 2529 | 2357ed7a81db106a
- carry_screen.py | 27086 | 8dc2eb4141b0cf78
- carry_spec.py | 5845 | 42793eae8f572093 FROZEN
- carry_spec22.py | 3873 | 475ae28a4fd8ed0b FROZEN
- carry_spec23.py | 14662 | d28a403c0b6245e1 FROZEN
- carry_spec_v2_1.json | 5070 | 87bd63d47b28dc53 FROZEN
- carry_spec_v2_2.json | 7166 | c7c5103d22bbf58b FROZEN
- carry_spec_v2_3.json | 9007 | c3bf6a1b5cca646c FROZEN
- carry_verify.py | 1298 | a884cbefa0c5871d
- carry_weekly.sh | 290 | f39e2bcef3e619ee
- codeplan_log.py | 15121 | e8c49c07dcfd8d3a
- codeplan_v1_spec.md | 3932 | bb0c2f59af191df4 FROZEN
- composite_rating.py | 4390 | d7211e3693ef6c02
- counterfactual_grade.py | 4932 | 61e0490c92cf268c
- daily.sh | 2903 | 4288dfb96c0df90a
- diagnose_tp1.py | 3671 | dc3c7ffaa8a85f20
- evaluate_core_performance.py | 13226 | 8b8dce9c61722a8f
- evaluate_prediction_accuracy.py | 13830 | 25cc5481c65b39b6
- evidence.py | 8118 | 0ab0919fc2a3519e
- exec_v1_spec.md | 9708 | 806a3343d7f942f5 FROZEN
- experiments.json | 21412 | 039a3f93bac178c5 FROZEN
- fade_audit.py | 6247 | d2a182caab4ecd37
- fade_calib.py | 1889 | 1e520ef39091f1e4
- fade_calib2.py | 9917 | ec280f699276ee10
- fade_calib3.py | 3951 | 93f24b4a8611984f
- fade_data.py | 3330 | ee8b9db2ef77c7eb
- fade_experiment.py | 17757 | f3725353c9e08b8c
- fade_power.py | 1495 | c942fec76b91ffaa
- fade_study.py | 8171 | b8afc611a286c3b3
- freeze_calib_v2.py | 2694 | b43bfd0b1955594c
- freeze_calib_v3.py | 1986 | 311f14867d7f7472
- funding_replay.py | 6988 | 35568aba066e5ac3
- gate_check.py | 7599 | c47cdad07d0c2d11
- harness_import.py | 9252 | 783ddb0eff7ef09e
- harness_init.py | 3262 | c6502591b6e129b9
- harness_spec.py | 14734 | b3c4316935cef287 FROZEN
- harness_spec_v1.json | 15669 | e053b446dc264b6d FROZEN
- held_plan_grade.py | 10672 | cf99e06d0f4b6d55
- hex.py | 1829 | b60966e26459e923
- hex_anim.py | 1050 | fdfacba0c0f63bfe
- hex_chart.py | 13865 | c251f46f0e7dab3e
- hex_colors.py | 2371 | 0f357e12a9574173
- hex_economics.py | 6424 | 093b39cd2156eb61
- hex_replay.py | 2311 | 76265e23381f0b2c
- hex_selftrade.py | 6736 | e79cf8d5f387b36d
- hex_sentinel_core.py | 21546 | 6619bb8d49c8d8ff
- historical_backtest.py | 17557 | 767e3cdac4b0c63d
- lab_data.py | 3605 | 9ac8dcf6e74afd61
- lab_engine.py | 15649 | d3b055a44975d1f5
- lab_ideas.py | 1552 | 47e236bd4f160caa
- lab_play.py | 18058 | f3ef3890621e1baf
- lab_play_tests.py | 6357 | baf1b9e85fea8448
- lab_stats.py | 5641 | e3e10ac810cae63a
- lab_tests.py | 11061 | 62b8125011083e21
- levelcmp_log.py | 23845 | fa63ecabead87640
- levelcmp_v1_spec.md | 4473 | c0836b37819d7a8e FROZEN
- levels_log.py | 13049 | 7376b168a2580974
- levels_v1_spec.md | 3534 | 4f17a452e6e4ff66 FROZEN
- market_ctx_log.py | 23334 | 236a73e8cde516ad
- market_ctx_v1_spec.md | 4884 | ca048489410fd143 FROZEN
- market_facts.py | 13905 | 72e4eb6fa34825d6
- noiseband_log.py | 19948 | 8cd5831ae0c3d61c
- noiseband_v1_spec.md | 3896 | 40337beebdd88759 FROZEN
- oi_collector.py | 6148 | 74badde368f4a073
- orderbook_spec_v1.md | 4467 | e296045ab0f76b95 FROZEN
- panel_extract.py | 1235 | 666d7b48d3087c0d
- panel_shape.json | 2487 | 02e3624a954886ef
- portfolio_walk_forward_validation.py | 21078 | 5c2b403924335b11
- pred_report.py | 4611 | b99cd0e7eb7d956e
- process_historical_data.py | 5224 | d77e02dcdf160b84
- rating_backtest.py | 2299 | 7ce274dbe6161e7f
- rating_compare.py | 2356 | de46f2dd4c39c170
- rating_report.py | 6154 | a9e5a8c61cbbea40
- rating_strong.py | 1824 | 14871ec63ed04d19
- research_log.py | 20162 | 90a101596c97d007
- research_v1_spec.md | 4366 | 3583b3a95b734089 FROZEN
- sentinel_ai.py | 420879 | e32d089aedfae3af
- sentinel_stage1.py | 25744 | c71577fc4d4ef081
- sentinel_theme.py | 9683 | 43239be4304b9c88
- shadow_log.py | 4508 | bc2f67ddb565bf2b
- signal_intelligence_engine.py | 4 | a00c3b59d5e9e2d8
- stocks.py | 15661 | 4c06cc214da83ab2
- strategy_hook.json | 861 | 5cc297b026fbc63f
- strategy_optimizer.py | 22177 | bbb40ad670217f69
- tv_rating.py | 6813 | b1157262b4c9c3fc
- validate_historical_data.py | 4054 | 25c635a73408d6ef
- walk_forward_validation.py | 14487 | 965fd1f0809d950b
- webdir_log.py | 17987 | a247cf4ec587ae27
- webdir_v1_spec.md | 4057 | 26d479eddb162a67 FROZEN

## 5. Files present but NOT in git (names and sizes; contents are never listed)
- .daily_state_2026-10-23 | 108 bytes
- .env | 519 bytes
- HANDOFF.md | 6496 bytes
- apply_harness_registration.py | 3055 bytes
- backup_hex.sh | 929 bytes
- band | 0 bytes
- batch1_calib_draft.txt | 7081 bytes
- batch1_calib_driver.py | 2056 bytes
- batch1_calib_driver_integrating.py | 10941 bytes
- batch1_calib_driver_real.py | 11283 bytes
- batch1_calib_result.json | 2350 bytes
- batch1_draft.txt | 12581 bytes
- batch1_pilot_runtime.py | 4967 bytes
- batch1_quick_timer.py | 5460 bytes
- batch1_research_spec.txt | 8618 bytes
- calib_full_v2.log | 784 bytes
- calib_full_v3.log | 9314 bytes
- candidate_strategies_spec.txt | 3094 bytes
- carry_collector_run_20261012T224303Z.log | 1197 bytes
- carry_collector_run_20261012T224442Z.log | 1197 bytes
- carry_collector_run_20261012T225717Z.log | 1197 bytes
- carry_collector_run_20261013T064950Z.log | 1204 bytes
- carry_draft_fwd.txt | 6906 bytes
- carry_draft_hist.txt | 9079 bytes
- carry_forward.db | 2985984 bytes
- carry_forward_obs_20261012T224347Z.log | 2495 bytes
- carry_forward_obs_20261012T224538Z.log | 2495 bytes
- carry_forward_obs_20261012T225826Z.logcd | 2495 bytes
- carry_forward_obs_20261013T065503Z.log | 2518 bytes
- carry_klines.db | 392990720 bytes
- combined_harness_prep.py | 4053 bytes
- dedupe_hypotheses_migrate.py | 5173 bytes
- dedupe_hypotheses_migrate_fix.py | 6356 bytes
- fade.db | 97083392 bytes
- funding.db | 12582912 bytes
- harness.db | 126976 bytes | sha256[:16] dba61fe81d4574c3
- harness_draft.txt | 15472 bytes
- harness_register_helper.py | 4729 bytes
- hband | 0 bytes
- hex_audit.txt | 1482997 bytes
- hex_selftrade.log | 574 bytes
- hi | 0 bytes
- lab.db | 19431424 bytes
- make_manifest.py | 12652 bytes
- market_stats.db | 34222080 bytes
- oneoff_integrate_from_result.py | 2835 bytes
- oneoff_integrate_from_result_fix.py | 3299 bytes
- or_probe.py | 6001 bytes
- patch_add_candidate_strategies.py | 16663 bytes
- performance | 798 bytes
- prereg_calibration.json | 554 bytes
- prereg_ensemble.json | 513 bytes
- prereg_pred_accuracy.json | 1249 bytes
- prereg_profitability.json | 975 bytes
- pw_progress.json | 254 bytes
- register_batch1_hypotheses.py | 2465 bytes
- register_spec_versions.py | 764 bytes
- research_state.json | 82 bytes
- restore_hex.sh | 832 bytes
- review_all.py | 1541 bytes
- review_out.txt | 9055 bytes
- sentinel.db | 5136384 bytes
- sentinel_48h.db | 159744 bytes
- sentinel_4h.db | 385024 bytes
- sentinel_72h.db | 151552 bytes
- sentinel_ai.py.backup | 268865 bytes
- sentinel_ai.py.backup_api_patch | 280940 bytes
- sentinel_ai.py.backup_consensus | 259395 bytes
- sentinel_ai.py.backup_provider_rr | 270321 bytes
- sentinel_ai.py.backup_rate_limit | 277195 bytes
- sentinel_ai.py.backup_symbol_validation_20260910_133758 | 271272 bytes
- sentinel_ai.py.stage_7_6_8_10_backup_20260911_085612 | 310298 bytes
- sentinel_ai.py.stage_7_6_8_5_backup | 247070 bytes
- sentinel_ai_backup_20260910_214308.py | 277394 bytes
- sentinel_ai_duplicate_cleanup_backup_20260910_222625.py | 298240 bytes
- sentinel_ai_final_audit_backup.py | 44615 bytes
- sentinel_ai_market_backup_20260910_222414.py | 280940 bytes
- sentinel_ai_market_backup_20260910_222438.py | 291755 bytes
- sentinel_ai_pre_lifecycle_backup.py | 44615 bytes
- sentinel_ai_pre_lifecycle_transitions_backup.py | 51364 bytes
- sentinel_ai_pre_stage6_backup.py | 28574 bytes
- sentinel_ai_stage2_1_backup.py | 4815 bytes
- sentinel_ai_stage2_backup.py | 2677 bytes
- sentinel_ai_stage4_3_backup.py | 19468 bytes
- sentinel_ai_stage5_1_backup.py | 23486 bytes
- sentinel_ai_stage5_1_working_backup.py | 25076 bytes
- sentinel_ai_stage5_backup.py | 23486 bytes
- sentinel_ai_stage6_10_backup.py | 65703 bytes
- sentinel_ai_stage6_16_backup.py | 84542 bytes
- sentinel_ai_stage6_1_backup.py | 40908 bytes
- sentinel_ai_stage6_4_backup.py | 53501 bytes
- sentinel_ai_stage6_5_backup.py | 55397 bytes
- sentinel_ai_stage6_6_backup.py | 56787 bytes
- sentinel_ai_startup_backup_20260910_214443.py | 277454 bytes
- sentinel_ai_startup_backup_20260910_214630.py | 277454 bytes
- sentinel_stage1.py.save | 17085 bytes
- sentinel_stage1_backup.py | 19261 bytes
- sentinel_stage1_pandas_backup.py | 19261 bytes
- sentinel_stage1_stage1_2_backup.py | 20327 bytes
- sentinel_stage1_stage5_1_backup.py | 22076 bytes
- shadow.db | 782336 bytes
- sp_progress.json | 259 bytes
- stock_paper.db | 8192 bytes

## 6. Databases (read-only: tables, row counts, columns)

### carry_forward.db
  - f (1517 rows): sym, t, rate, mark
  - mk (11544 rows): sym, t, o, h, l, c
  - pp (11544 rows): sym, t, o, h, l, c
  - sp (11544 rows): sym, t, o, h, l, c

### carry_klines.db
  - mk (1530541 rows): sym, t, o, h, l, c
  - pp (1523997 rows): sym, t, o, h, l, c
  - sp (1555092 rows): sym, t, o, h, l, c

### fade.db
  - k (1050698 rows): sym, t, o, h, l, c, v

### funding.db
  - f (195499 rows): sym, t, rate, mark

### harness.db
  - allowed_transitions (10 rows): from_status, to_status
  - families (3 rows): family, question, alpha_family, defined_utc
  - health_events (0 rows): strategy_id, obs_utc, rule, value, threshold, action
  - hypotheses (7 rows): hyp_id, family, strategy_id, spec_hash, registered_utc
  - hypotheses_old_backup (15 rows): hyp_id, family, strategy_id, spec_hash, registered_utc
  - hypothesis_outcomes (3 rows): hyp_id, test_run_utc, outcome, note
  - observations (0 rows): strategy_id, spec_hash, run_id, obs_utc, revision, value, missing, reason
  - runs (7 rows): run_id, strategy_id, spec_hash, kind, data_seen_before, code_sha256, started_utc
  - spec_versions (5 rows): strategy_id, spec_hash, frozen_at_utc, spec_json
  - status_log (5 rows): strategy_id, from_status, to_status, changed_utc, reason, spec_hash
  - strategies (7 rows): strategy_id, family, created_utc

### lab.db
  - candles (192152 rows): symbol, source, open_time, o, h, l, c, v
  - predictions (3116 rows): set_name, round_id, player, direction, confidence, locked_at
  - reveals (34 rows): set_name, round_id, player, revealed_at
  - rounds (1053 rows): set_name, round_id, ord, symbol, start_time, stratum
  - sets (8 rows): name, seed, n, created, hash, params

### market_stats.db
  - futures_stats (144500 rows): metric, symbol, ts, a, b, c, raw

### sentinel.db
  - agent_decisions (541 rows): id, timestamp, symbol, signal, strategy_status, risk_status, final_action, live_execution, ai_assessment, importance, entry_price, evaluation_price, price_change_pct, outcome, feedback_score, evaluated_at
  - ai_consensus_audit (489 rows): id, timestamp, symbol, strategy_status, market_signal, groq_assessment, gemini_assessment, consensus_status, consensus_action, consensus_reason, final_action, risk_status, live_execution, decision_id
  - ai_web_evidence_audit (958 rows): id, created_at, provider, symbol, evidence_present, evidence_item_count, evidence_context_hash, prompt_length, delivery_status, live_execution
  - backtests (646 rows): id, strategy_name, version, symbol, interval, candles, starting_balance, ending_balance, total_return, win_rate, profit_factor, expectancy, max_drawdown, total_trades, fees_paid, slippage_cost, created_at
  - final_decisions (1 rows): id, timestamp, symbol, signal, decision, score, reason, live_execution
  - paper_signals (646 rows): id, strategy_name, version, symbol, signal, price, created_at, outcome
  - paper_trade_learning_feedback (9 rows): id, paper_trade_id, decision_id, consensus_id, symbol, direction, outcome, feedback_label, decision_score, consensus_score, groq_direction, gemini_direction, groq_score, gemini_score, learning_status, created_at
  - paper_trade_plans (37 rows): id, created_at, expires_at, symbol, direction, entry_price, stop_loss, tp1, tp2, tp3, groq_plan, gemini_plan, consensus_status, status, outcome, exit_price, resolved_at, decision_id, consensus_id, tp1_hit_at, tp2_hit_at, tp3_hit_at, last_checked_at, last_price, price_change_pct, feedback_score, evaluated_at, trade_outcome, prediction_outcome, prediction_evaluated_at, econ_leverage, econ_margin, econ_qty, econ_fees, econ_funding, econ_net_pnl, econ_roi_pct, econ_liquidated, econ_liq_price, econ_stop_beyond_liq, econ_note
  - provider_performance_audit (4 rows): id, consensus_id, decision_id, symbol, provider, provider_direction, provider_result, outcome, created_at
  - rating_log (249 rows): id, symbol, interval, hex_signal, rating, score, ma_score, osc_score, price, created_at
  - strategies (646 rows): id, strategy_name, version, status, created_at, last_validation, notes
  - strategy_versions (2 rows): id, strategy_name, version, status, created_at, updated_at, reason
  - walk_forward_results (3210 rows): id, strategy_name, version, symbol, interval, fold, trades, total_return, profit_factor, max_drawdown, created_at
  - web_intelligence_evidence (3480 rows): id, symbol, information_class, source, source_type, source_quality, title, summary, direction, confidence, importance, freshness, corroboration_count, published_at, retrieved_at, evidence_hash, publisher, source_domain, corroboration_strength, event_key, conflict_status

### sentinel_48h.db
  - agent_decisions (3 rows): id, timestamp, symbol, signal, strategy_status, risk_status, final_action, live_execution, ai_assessment, importance, entry_price, evaluation_price, price_change_pct, outcome, feedback_score, evaluated_at
  - ai_consensus_audit (3 rows): id, timestamp, symbol, strategy_status, market_signal, groq_assessment, gemini_assessment, consensus_status, consensus_action, consensus_reason, final_action, risk_status, live_execution, decision_id
  - ai_web_evidence_audit (6 rows): id, created_at, provider, symbol, evidence_present, evidence_item_count, evidence_context_hash, prompt_length, delivery_status, live_execution
  - backtests (3 rows): id, strategy_name, version, symbol, interval, candles, starting_balance, ending_balance, total_return, win_rate, profit_factor, expectancy, max_drawdown, total_trades, fees_paid, slippage_cost, created_at
  - final_decisions (0 rows): id, timestamp, symbol, signal, decision, score, reason, live_execution
  - paper_signals (3 rows): id, strategy_name, version, symbol, signal, price, created_at, outcome
  - paper_trade_learning_feedback (0 rows): id, paper_trade_id, decision_id, consensus_id, symbol, direction, outcome, feedback_label, decision_score, consensus_score, groq_direction, gemini_direction, groq_score, gemini_score, learning_status, created_at
  - paper_trade_plans (0 rows): id, created_at, expires_at, symbol, direction, entry_price, stop_loss, tp1, tp2, tp3, groq_plan, gemini_plan, consensus_status, status, outcome, exit_price, resolved_at, decision_id, consensus_id, tp1_hit_at, tp2_hit_at, tp3_hit_at, last_checked_at, last_price, price_change_pct, feedback_score, evaluated_at, trade_outcome, prediction_outcome, prediction_evaluated_at, econ_leverage, econ_margin, econ_qty, econ_fees, econ_funding, econ_net_pnl, econ_roi_pct, econ_liquidated, econ_liq_price, econ_stop_beyond_liq, econ_note
  - provider_performance_audit (0 rows): id, consensus_id, decision_id, symbol, provider, provider_direction, provider_result, outcome, created_at
  - rating_log (3 rows): id, symbol, interval, hex_signal, rating, score, ma_score, osc_score, price, created_at
  - strategies (3 rows): id, strategy_name, version, status, created_at, last_validation, notes
  - strategy_versions (0 rows): id, strategy_name, version, status, created_at, updated_at, reason
  - walk_forward_results (15 rows): id, strategy_name, version, symbol, interval, fold, trades, total_return, profit_factor, max_drawdown, created_at
  - web_intelligence_evidence (26 rows): id, symbol, information_class, source, source_type, source_quality, title, summary, direction, confidence, importance, freshness, corroboration_count, published_at, retrieved_at, evidence_hash, publisher, source_domain, corroboration_strength, event_key, conflict_status

### sentinel_4h.db
  - agent_decisions (9 rows): id, timestamp, symbol, signal, strategy_status, risk_status, final_action, live_execution, ai_assessment, importance, entry_price, evaluation_price, price_change_pct, outcome, feedback_score, evaluated_at
  - ai_consensus_audit (9 rows): id, timestamp, symbol, strategy_status, market_signal, groq_assessment, gemini_assessment, consensus_status, consensus_action, consensus_reason, final_action, risk_status, live_execution, decision_id
  - ai_web_evidence_audit (40 rows): id, created_at, provider, symbol, evidence_present, evidence_item_count, evidence_context_hash, prompt_length, delivery_status, live_execution
  - backtests (20 rows): id, strategy_name, version, symbol, interval, candles, starting_balance, ending_balance, total_return, win_rate, profit_factor, expectancy, max_drawdown, total_trades, fees_paid, slippage_cost, created_at
  - final_decisions (0 rows): id, timestamp, symbol, signal, decision, score, reason, live_execution
  - paper_signals (20 rows): id, strategy_name, version, symbol, signal, price, created_at, outcome
  - paper_trade_learning_feedback (0 rows): id, paper_trade_id, decision_id, consensus_id, symbol, direction, outcome, feedback_label, decision_score, consensus_score, groq_direction, gemini_direction, groq_score, gemini_score, learning_status, created_at
  - paper_trade_plans (1 rows): id, created_at, expires_at, symbol, direction, entry_price, stop_loss, tp1, tp2, tp3, groq_plan, gemini_plan, consensus_status, status, outcome, exit_price, resolved_at, decision_id, consensus_id, tp1_hit_at, tp2_hit_at, tp3_hit_at, last_checked_at, last_price, price_change_pct, feedback_score, evaluated_at, trade_outcome, prediction_outcome, prediction_evaluated_at, econ_leverage, econ_margin, econ_qty, econ_fees, econ_funding, econ_net_pnl, econ_roi_pct, econ_liquidated, econ_liq_price, econ_stop_beyond_liq, econ_note
  - provider_performance_audit (0 rows): id, consensus_id, decision_id, symbol, provider, provider_direction, provider_result, outcome, created_at
  - rating_log (20 rows): id, symbol, interval, hex_signal, rating, score, ma_score, osc_score, price, created_at
  - strategies (20 rows): id, strategy_name, version, status, created_at, last_validation, notes
  - strategy_versions (0 rows): id, strategy_name, version, status, created_at, updated_at, reason
  - walk_forward_results (100 rows): id, strategy_name, version, symbol, interval, fold, trades, total_return, profit_factor, max_drawdown, created_at
  - web_intelligence_evidence (218 rows): id, symbol, information_class, source, source_type, source_quality, title, summary, direction, confidence, importance, freshness, corroboration_count, published_at, retrieved_at, evidence_hash, publisher, source_domain, corroboration_strength, event_key, conflict_status

### sentinel_72h.db
  - agent_decisions (1 rows): id, timestamp, symbol, signal, strategy_status, risk_status, final_action, live_execution, ai_assessment, importance, entry_price, evaluation_price, price_change_pct, outcome, feedback_score, evaluated_at
  - ai_consensus_audit (1 rows): id, timestamp, symbol, strategy_status, market_signal, groq_assessment, gemini_assessment, consensus_status, consensus_action, consensus_reason, final_action, risk_status, live_execution, decision_id
  - ai_web_evidence_audit (2 rows): id, created_at, provider, symbol, evidence_present, evidence_item_count, evidence_context_hash, prompt_length, delivery_status, live_execution
  - backtests (1 rows): id, strategy_name, version, symbol, interval, candles, starting_balance, ending_balance, total_return, win_rate, profit_factor, expectancy, max_drawdown, total_trades, fees_paid, slippage_cost, created_at
  - final_decisions (0 rows): id, timestamp, symbol, signal, decision, score, reason, live_execution
  - paper_signals (1 rows): id, strategy_name, version, symbol, signal, price, created_at, outcome
  - paper_trade_learning_feedback (0 rows): id, paper_trade_id, decision_id, consensus_id, symbol, direction, outcome, feedback_label, decision_score, consensus_score, groq_direction, gemini_direction, groq_score, gemini_score, learning_status, created_at
  - paper_trade_plans (1 rows): id, created_at, expires_at, symbol, direction, entry_price, stop_loss, tp1, tp2, tp3, groq_plan, gemini_plan, consensus_status, status, outcome, exit_price, resolved_at, decision_id, consensus_id, tp1_hit_at, tp2_hit_at, tp3_hit_at, last_checked_at, last_price, price_change_pct, feedback_score, evaluated_at, trade_outcome, prediction_outcome, prediction_evaluated_at, econ_leverage, econ_margin, econ_qty, econ_fees, econ_funding, econ_net_pnl, econ_roi_pct, econ_liquidated, econ_liq_price, econ_stop_beyond_liq, econ_note
  - provider_performance_audit (0 rows): id, consensus_id, decision_id, symbol, provider, provider_direction, provider_result, outcome, created_at
  - rating_log (1 rows): id, symbol, interval, hex_signal, rating, score, ma_score, osc_score, price, created_at
  - strategies (1 rows): id, strategy_name, version, status, created_at, last_validation, notes
  - strategy_versions (0 rows): id, strategy_name, version, status, created_at, updated_at, reason
  - walk_forward_results (5 rows): id, strategy_name, version, symbol, interval, fold, trades, total_return, profit_factor, max_drawdown, created_at
  - web_intelligence_evidence (12 rows): id, symbol, information_class, source, source_type, source_quality, title, summary, direction, confidence, importance, freshness, corroboration_count, published_at, retrieved_at, evidence_hash, publisher, source_domain, corroboration_strength, event_key, conflict_status

### shadow.db
  - shadow_codeplan (40 rows): id, created_utc, ctx_id, day_utc, symbol, direction, call_s, call_v, call_t, call_r, n_up, n_down, entry, snap_ms, status
  - shadow_codeplan_grade (0 rows): id, graded_utc, ctx_id, symbol, direction, entry, u_pct, stop, tp1, tp2, tp3, outcome, r_result, dir_ret_pct, candles_used, source, status, reason
  - shadow_combined (142 rows): id, created_utc, symbol, final_action, direction, longs, shorts, matches, opposes, label, shadow_date, shadow_flag, price
  - shadow_counterfactual (47 rows): id, created_utc, created_ms, hour_bucket, symbol, direction, dir_source, price, risk_status, due_ms, graded_utc, exit_price, exit_source, move_pct, was_right, baseline_rate, excluded, excl_reason
  - shadow_held_plans (54 rows): id, audit_id, ai, created_utc, created_ms, hour_bucket, symbol, direction, entry_low, entry_high, stop_loss, tp1, tp2, tp3, source, graded_utc, entered, tp1_min, tp2_min, tp3_min, stop_min, outcome, note
  - shadow_levelcmp (54 rows): id, created_utc, held_id, cf_id, levels_id, ai, symbol, direction, audit_ms, day_utc, ai_entry, ai_stop, ai_tp1, ai_tp2, ai_tp3, calc_entry, calc_stop, calc_tp1, calc_tp2, calc_tp3, ai_outcome, calc_outcome, ai_r, calc_r, ai_stop_pct, calc_stop_pct, stored_ai_outcome, consistent, candles_used, source, status, reason
  - shadow_levels (44 rows): id, created_utc, cf_id, symbol, direction, entry, u_pct, stop, tp1, tp2, tp3, outcome, r_result, candles_used, source, status, reason
  - shadow_market_breadth (1 rows): id, created_utc, day_utc, n_coins, n_ok, pos24_share, pos168_share, up_struct_share, median_r24
  - shadow_market_ctx (40 rows): id, created_utc, day_utc, snap_ms, symbol, source, status, reason, last_open_ms, last_close, age_min, candles, numbers_json
  - shadow_market_ctx_fwd (0 rows): id, ctx_id, graded_utc, fwd_pct
  - shadow_market_facts (28 rows): id, created_utc, symbol, version, source, status, reason, last_open_ms, age_min, candles_used, deviation_pct, text, numbers_json
  - shadow_prompt_v2 (63 rows): id, created_utc, symbol, provider, model, http_status, finish_reason, latency_s, out_tokens, prompt_hash, price, final_action, v1_assessment, v1_direction, v2_assessment, v2_direction, v2_fields_json, v2_raw, error
  - shadow_prompt_v2_1 (28 rows): id, created_utc, symbol, provider, model, http_status, finish_reason, latency_s, out_tokens, prompt_hash, price, final_action, v1_assessment, v1_direction, v2_assessment, v2_direction, v2_fields_json, v2_raw, error, facts_id, facts_status
  - shadow_prompt_v2_1g (22 rows): id, created_utc, symbol, provider, model, key_label, http_status, finish_reason, latency_s, prompt_hash, price, final_action, v2_assessment, v2_direction, v2_fields_json, v2_raw, error, facts_id, skip_reason
  - shadow_provider_calls (186 rows): id, created_utc, symbol, provider, model, ok, error, latency_s
  - shadow_pw_runs (14 rows): id, created_utc, symbol, tag, why, signal, final_action, risk_status, price
  - shadow_research_leads (40 rows): id, run_utc, query_no, url, title, snippet, domain, published, provider_score, source_note
  - shadow_runs (5 rows): applies_date, run_utc, lag_hours, flag, n_coins, engine_hash, notes
  - shadow_sentinel (37 rows): plan_id, symbol, direction, plan_created_at, captured_utc
  - shadow_signals (800 rows): applies_date, strategy, symbol, weight
  - shadow_webdir (1053 rows): id, created_utc, unit_key, kind, symbol, snap_ms, day_utc, call_dir, n_bull, n_bear, event_key, status
  - shadow_webdir_grade (990 rows): id, graded_utc, unit_id, entry, fwd_pct, status, reason, source, candles_used

### stock_paper.db
  - preds (1 rows): id, sym, kind, created_ms, entry, direction, thr, end_ms, scored_ms, exit_px, ret, result

## 7. Errata index (number: title)
- 24: quick mode on frozen v1 worlds: model self-check FAILED (B coin lag1 -0.081, B coin abs lag30 0.257 vs 0.149, 
- 26: v2 full run STOPPED by its own WORLD INVALID guard: type A seed 1 world 651, max daily simple return 222.67 (+
- 28: RESULT batch1 calibration v3 (spec 27d0842649a8..., engine 7bbd78e2e9899ac7, result file sha256 0cc39f3e950c8f
- 29: real descriptive run spec and shadow-log spec approved (text). Real run: fade.db read-only, reviewed engine, n
- 31: combined view (display + log only) frozen: labels CONFIRMED/CONFLICT/MIXED/NEUTRAL/NO CALL from non-flat shado
- 32: shadow display covers only the 40-coin universe by user choice; other coins show "not in the 40-coin shadow un
- 33: counterfactual log frozen (log only; guard unchanged, window 4, cutoffs 60/80, weights frozen): trigger risk_s
- 34: display relabel: "Consensus Reliability Safety / Reliability Score / Reliability Status" shown as "AI Agreemen
- 35: counterfactual trigger tightened BEFORE any row was graded: log only when risk_status is AI_CONSENSUS_LOW_RELI
- 36: secret command "sp" added: runs the normal predict pipeline over the 40 shadow-universe coins sequentially (12
- 37: OpenRouter fallback model changed: nvidia/nemotron-3-super-120b-a12b:free -> poolside/laguna-s-2.1:free (call_
- 38: Prompt v2 shadow log (log only, approved text spec): sp now makes ONE extra Groq call per coin (openai/gpt-oss
- 39: Fix to errata 38 hook: first sp 1 test (AAVE) logged '(v2 shadow not logged: name json is not defined)'. _v2_s
- 40: Duplicate sp run (operator mistake, no code fault). sp 1 ran AAVE at 09:15:57 UTC. A second sp 1 was refused (
- 41: Stage 2.2 display notice (print only, approved text spec). In the Stage 2.2 block, when the AI text contains E
- 42: Observation only, no code change: how the agreement score is built (read from calculate_consensus_reliability,
- 43: OpenRouter fallback now rejects a truncated reply (approved text spec). In call_openrouter_analysis, if the re
- 44: Provider call log (log only, approved text spec) and Gemini model decision. Gemini stays on gemini-3.1-flash-l
- 45: Five coins added to the sp list only: ZEC, HYPE, PUMP, STRK, ENA (appended after SP_COINS, so the 40 originals
- 46: New command pw (previous wins), not listed in help, PAPER ONLY, changes no decision. pw dry prints the list; p
- 47: Two display-only changes (approved text specs). (a) performance now prints one compact table (Hrz, Tot, Act, G
- 48: Held-plan grader rules (approved text spec, fixed before any row is graded). Purpose: grade the entry, stop an
- 49: History screen layout (display only, approved layout). In sentinel_theme.py, print_router_result gets one bran
- 50: market_facts.py (facts_v1) added, not connected to anything yet (step 1 of the approved spec). Pure functions 
- 51: Prompt v2.1 + facts_v1 wired into the sp and pw shadow call (log only, approved spec step 2). New _v2_1_shadow
- 52: history search (display only)
- 52: Gemini v2.1 shadow call (log only, approved text spec). New _v2_1_gemini_hook runs after each _v2_1_shadow_hoo
- 53: orderbook_v1 text spec (no code)
- 54: numbering note and Gemini v2.1 hook first live rows
- 55: first counterfactual read (observation only)
- 56: levels_v1 text spec (no code) and facts_v1 content correction
- 57: levels_log.py code for levels_v1 (not yet run)
- 58: first levels_v1 run and read (observation only)
- 59: risk calculator command (display only)
- 60: market_ctx_v1 text spec (no code)
- 61: market_ctx_log.py code for market_ctx_v1 (selftest only)
- 62: codeplan_v1 text spec (no code)
- 63: date correction for errata 53-62 and the four specs
- 64: codeplan_log.py code for codeplan_v1 (selftest only)
- 65: webdir_v1 text spec (no code)
- 66: webdir_log.py code for webdir_v1 (selftest only) and daily.sh
- 67: first webdir_v1 run and read (observation only)
- 68: levelcmp_v1 text spec (no code)
- 69: levelcmp_log.py code for levelcmp_v1 (selftest only) and daily.sh
- 70: noiseband_v1 text spec (no code)
- 71: Gemini 503 wait screen (display only)
- 72: noiseband_log.py code for noiseband_v1 (created by a block that gates on the selftest) and daily.sh
- 73: exec_v1 execution specification (DRAFT, text only, no code)
- 74: research_v1 text spec (web research leads module, no code)
- 75: research_log.py code for research_v1 (created by a block that gates on the selftest)
- 76: first research_v1 runs (observation only)
- 77: breakout19_v1 text spec (DRAFT, no code)
- 78: breakout19_v1 FROZEN (operator: "Option 3 freeze") with S and M as logged context
- 79: breakout19_log.py code for breakout19_v1 (created by a block that gates on the selftest) and daily.sh

## 8. Daily routine (daily.sh)
```
#!/bin/bash
# daily.sh - runs the shell steps of the daily routine, in order.
#   bash daily.sh               run the steps not yet done today (UTC)
#   bash daily.sh --redo NAME   run step NAME again (for example levels_log)
#   bash daily.sh --force       run every step again
# Does NOT run sp or pw (typed inside Hex). Writes only .daily_state_<date>.
cd "$(dirname "$0")" || exit 1
DAY=$(date -u +%Y-%m-%d)
STATE=".daily_state_$DAY"
touch "$STATE"
if [ "$1" = "--force" ]; then : > "$STATE"; fi
if [ "$1" = "--redo" ] && [ -n "$2" ]; then grep -vx "$2" "$STATE" > "$STATE.tmp"; mv "$STATE.tmp" "$STATE"; fi
FAILS=""
echo "daily routine $DAY $(date -u +%H:%M) UTC"
if [ "$(date -u +%H)" -ge 6 ]; then echo "note: past 06:00 UTC, shadow_log rows are marked late (expected)"; fi

step() {
  name="$1"; n="$2"; shift 2
  if grep -qx "$name" "$STATE"; then echo "[skip] $name (done today)"; return; fi
  if [ ! -f "$1" ]; then echo "FAIL: $name: $1 not found"; FAILS="$FAILS $name"; return; fi
  echo "-- $name ..."
  out=$(python3 "$@" 2>&1); rc=$?
  if [ $rc -ne 0 ] || echo "$out" | grep -q "Traceback"; then
    echo "FAIL: $name (exit $rc)"; echo "$out" | tail -n 8; FAILS="$FAILS $name"
  else
    echo "$out" | tail -n "$n"; echo "$name" >> "$STATE"
  fi
}

step shadow_log 3 shadow_log.py run
step carry_collector 3 carry_collector.py run
step carry_forward_obs 6 carry_forward_obs.py run
step counterfactual_grade 4 counterfactual_grade.py grade
step held_plan_grade 4 held_plan_grade.py run
step levels_log 3 levels_log.py run
step market_ctx_log 3 market_ctx_log.py run
if [ -f codeplan_log.py ]; then
  if python3 codeplan_log.py selftest >/dev/null 2>&1; then step codeplan_log 4 codeplan_log.py run
  else echo "FAIL: codeplan_log selftest"; FAILS="$FAILS codeplan_selftest"; fi
fi

if [ -f webdir_log.py ]; then
  if python3 webdir_log.py selftest >/dev/null 2>&1; then step webdir_log 4 webdir_log.py run
  else echo "FAIL: webdir_log selftest"; FAILS="$FAILS webdir_selftest"; fi
fi

if [ -f levelcmp_log.py ]; then
  if python3 levelcmp_log.py selftest >/dev/null 2>&1; then step levelcmp_log 4 levelcmp_log.py run
  else echo "FAIL: levelcmp_log selftest"; FAILS="$FAILS levelcmp_selftest"; fi
fi

if [ -f noiseband_log.py ]; then
  if python3 noiseband_log.py selftest >/dev/null 2>&1; then step noiseband_log 4 noiseband_log.py run
  else echo "FAIL: noiseband_log selftest"; FAILS="$FAILS noiseband_selftest"; fi
fi

if [ -f breakout19_log.py ]; then
  if python3 breakout19_log.py selftest >/dev/null 2>&1; then step breakout19_log 4 breakout19_log.py run
  else echo "FAIL: breakout19_log selftest"; FAILS="$FAILS breakout19_selftest"; fi
fi

B=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
U=$(git rev-list --count "origin/$B..HEAD" 2>/dev/null)
echo "== summary: failed:${FAILS:- none} | unpushed local commits: ${U:-?}"
echo "next, inside Hex: sp resume (or sp 5), then pw."
```

## 9. How to rebuild
1. Install Termux (the F-Droid build is the one guides recommend), then: pkg update && pkg install python git openssl-tool (package names are from memory; verify).
2. pip install numpy requests (versions in section 1; install python-dotenv too if the code imports it).
3. git clone <remote from section 2> binance-sentinel, then cd binance-sentinel and git checkout <branch from section 2>.
4. Restore the data into a NEW folder: bash restore_hex.sh hex_data_DATE.tar.gz.enc ~/binance-sentinel_restored (never over a working folder).
5. Recreate .env from the NAMES in section 3 with fresh keys (Groq, Gemini x3, OpenRouter, Tavily). Binance order keys are not needed by any shadow tool.
6. Run each selftest (all offline): for f in market_facts.py held_plan_grade.py levels_log.py levelcmp_log.py market_ctx_log.py codeplan_log.py webdir_log.py noiseband_log.py breakout19_log.py research_log.py make_manifest.py; do python3 $f selftest; done
7. Run bash daily.sh once and read the summary line. Missed days only delay the counts; forward data that was lost cannot be recreated.
