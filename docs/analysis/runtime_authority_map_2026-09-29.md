# P0a Runtime Authority Map · 2026-09-29

> 自动生成的只读审计摘要。JSON 是机器原件；本页只做人读投影。

## 摘要

- writer 记录：**228**；其中 production/tooling：**130**。
- uncertain alias：**19**。这些不是已证 writer，也不能当作已排除。
- AST 解析错误：**0**。
- 多 production writer 的事实：**24**。
- 本次 quick：**45 PASS / 0 FAIL / 164 SKIP**；登记 quick=209。
- quick 预检计数与实跑计数一致：**True**。

## 五域与 writer

| semantic fact | target owner | removal | prod writers | unknown aliases |
|---|---|---|---:|---:|
| `completed` | BeatReducer | P2c | 12 | 0 |
| `completed_by_card` | BeatReducer | P2c | 9 | 0 |
| `completed_beats` | BeatReducer | P2c | 1 | 1 |
| `canon_performance_state` | BeatReducer | P2c | 2 | 0 |
| `branch_progress` | WorldCommit | P2c | 29 | 1 |
| `scene_receipts` | WorldCommit | P2c | 2 | 0 |
| `world_transactions` | WorldCommit | P2c | 2 | 0 |
| `causal_receipts` | WorldCommit | P2c | 3 | 0 |
| `run_observation_ledger` | WorldCommit | P2c | 9 | 7 |
| `player_state` | WorldCommit | P2 | 11 | 0 |
| `body_frames` | WorldCommit | P2c | 2 | 4 |
| `world_cursor` | WorldCommit | P2c | 7 | 2 |
| `private_inner_states` | ActorMindReducer | P3 | 6 | 0 |
| `prior_reflect_by_cons` | ActorMindReducer | P3 | 2 | 0 |
| `actor_minds` | ActorMindReducer | P3 | 5 | 2 |
| `fsm_by_cons` | ActorMindReducer | P3 | 3 | 1 |
| `rel_state_by_cons` | ActorMindReducer | P3 | 3 | 1 |
| `ended` | ExitLifecycle | P1 | 4 | 0 |
| `_run_closed` | ExitLifecycle | P1 | 2 | 0 |
| `run_receipt` | ExitLifecycle | P1 | 3 | 0 |
| `_last_exit_intent_exit_spec` | ExitPolicy | P1 | 3 | 0 |
| `pending_entry` | ExitPolicy | P1 | 2 | 0 |
| `ryuya_flashback_return` | ExitPolicy | P1 | 3 | 0 |
| `utterance_queue` | DeliveryCommit | P2/P6 | 0 | 0 |
| `sql:run_meta` | ExitLifecycle/RunRegistry | P1b | 2 | 0 |
| `sql:delta_ledger` | WorldCommit/Settlement | P1b/P2 | 1 | 0 |
| `sql:delta_sediment` | Settlement | P1b/P2 | 2 | 0 |
| `sql:run_receipts` | ExitLifecycle | P1b | 0 | 0 |

## 生产 writer 明细

### `completed` → BeatReducer

- `runtime/free_stage_prototype.py:7470` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7927` · `FreeStageSession._maybe_enter_ryuya_flashback` · assign · **production** · high
- `runtime/free_stage_prototype.py:8556` · `FreeStageSession._emit_canon_segment` · method:append · **production** · high
- `runtime/free_stage_prototype.py:8918` · `FreeStageSession.start` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9796` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9920` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:10165` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:10859` · `FreeStageSession.step` · method:extend · **production** · high
- `runtime/free_stage_prototype.py:11426` · `FreeStageSession.skip_scene` · assign · **production** · high
- `runtime/free_stage_prototype.py:11535` · `FreeStageSession.skip_scene` · assign · **production** · high
- `runtime/free_stage_prototype.py:12058` · `FreeStageSession._maybe_transition` · assign · **production** · high
- `runtime/free_stage_prototype.py:12091` · `FreeStageSession._maybe_transition` · assign · **production** · high

### `completed_by_card` → BeatReducer

- `runtime/free_stage_prototype.py:7471` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7865` · `FreeStageSession._maybe_enter_ryuya_flashback` · assign · **production** · high
- `runtime/free_stage_prototype.py:8706` · `FreeStageSession._canon_step_result` · assign · **production** · high
- `runtime/free_stage_prototype.py:10941` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10996` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:11446` · `FreeStageSession.skip_scene` · assign · **production** · high
- `runtime/free_stage_prototype.py:11480` · `FreeStageSession.skip_scene` · assign · **production** · high
- `runtime/free_stage_prototype.py:11656` · `FreeStageSession._maybe_transition` · assign · **production** · high
- `runtime/free_stage_prototype.py:11775` · `FreeStageSession._maybe_transition` · assign · **production** · high

### `completed_beats` → BeatReducer

- `runtime/free_stage_prototype.py:7472` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:9085` · `FreeStageSession._mark_frame_beats_for_progress` · pass_to_mutating_helper · **unknown_alias** · medium · frame_beat_ledger.mark_done

### `canon_performance_state` → BeatReducer

- `runtime/free_stage_prototype.py:7473` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:8496` · `FreeStageSession._canon_scene_state` · method:setdefault · **production** · high

### `branch_progress` → WorldCommit

- `runtime/free_stage_prototype.py:7488` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7827` · `FreeStageSession._ensure_opening_synopsis_and_pendant` · method:append · **production** · high
- `runtime/free_stage_prototype.py:7891` · `FreeStageSession._maybe_enter_ryuya_flashback` · assign · **production** · high
- `runtime/free_stage_prototype.py:8085` · `FreeStageSession._record_player_branch_fact` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9447` · `FreeStageSession._append_autonomous_decision` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9798` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9805` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9815` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9854` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:9858` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9881` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:9886` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9894` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9909` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9911` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9933` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:10015` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10026` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10069` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10902` · `FreeStageSession.step` · method:append · **production** · high
- `runtime/free_stage_prototype.py:11675` · `FreeStageSession._maybe_transition` · method:append · **production** · high
- `runtime/free_stage_prototype.py:11677` · `FreeStageSession._maybe_transition` · method:append · **production** · high
- `runtime/free_stage_prototype.py:11771` · `FreeStageSession._maybe_transition` · method:append · **production** · high
- `runtime/free_stage_prototype.py:11787` · `FreeStageSession._maybe_transition` · method:append · **production** · high
- `runtime/free_stage_prototype.py:11789` · `FreeStageSession._maybe_transition` · method:append · **production** · high
- `runtime/free_stage_prototype.py:11995` · `FreeStageSession._maybe_transition` · pass_to_mutating_helper · **unknown_alias** · medium · apply_offscreen_lives
- `runtime/scene_contracts.py:99` · `register_branch_progress` · assign · **production** · high
- `runtime/scene_state.py:111` · `SceneState.load` · assign · **production** · high
- `scripts/test_world_truth_readonly_runtime.py:37` · `test_real_save_keeps_truth_db_readonly` · method:append · **production_tooling** · high
- `web/scene_api.py:3075` · `handle` · assign · **production** · high

### `scene_receipts` → WorldCommit

- `runtime/free_stage_prototype.py:7490` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7559` · `FreeStageSession._record_scene_receipt` · method:append · **production** · high

### `world_transactions` → WorldCommit

- `runtime/free_stage_prototype.py:7491` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7703` · `FreeStageSession._commit_world_transaction` · assign · **production** · high

### `causal_receipts` → WorldCommit

- `runtime/free_stage_prototype.py:7492` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:9401` · `FreeStageSession._append_actor_decisions` · method:append · **production** · high
- `runtime/free_stage_prototype.py:9521` · `FreeStageSession._run_autonomous_decision` · method:append · **production** · high

### `run_observation_ledger` → WorldCommit

- `runtime/free_stage_prototype.py:7516` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7755` · `FreeStageSession._finalize_prologue_pendant` · assign · **production** · high
- `runtime/free_stage_prototype.py:7755` · `FreeStageSession._finalize_prologue_pendant` · pass_to_mutating_helper · **unknown_alias** · medium · _ledger_append
- `runtime/free_stage_prototype.py:7786` · `FreeStageSession._maybe_emit_pendant_layer_c` · assign · **production** · high
- `runtime/free_stage_prototype.py:7786` · `FreeStageSession._maybe_emit_pendant_layer_c` · pass_to_mutating_helper · **unknown_alias** · medium · _ledger_append
- `runtime/free_stage_prototype.py:9701` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:9824` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:9824` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · _ledger_append
- `runtime/free_stage_prototype.py:10879` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10879` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · _ledger_append
- `runtime/free_stage_prototype.py:10886` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10886` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · _ledger_append
- `runtime/free_stage_prototype.py:10908` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10908` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · _ledger_append
- `runtime/free_stage_prototype.py:12083` · `FreeStageSession._maybe_transition` · assign · **production** · high
- `runtime/free_stage_prototype.py:12083` · `FreeStageSession._maybe_transition` · pass_to_mutating_helper · **unknown_alias** · medium · _ledger_append

### `player_state` → WorldCommit

- `runtime/free_stage_prototype.py:7507` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7746` · `FreeStageSession._finalize_prologue_pendant` · assign · **production** · high
- `runtime/free_stage_prototype.py:9637` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:9670` · `FreeStageSession.step` · method:setdefault · **production** · high
- `runtime/free_stage_prototype.py:9671` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:11097` · `FreeStageSession.step` · method:update · **production** · high
- `runtime/free_stage_prototype.py:11098` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:11135` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:11137` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:11138` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:11885` · `FreeStageSession._maybe_transition` · assign · **production** · high

### `body_frames` → WorldCommit

- `runtime/free_stage_prototype.py:7527` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7747` · `FreeStageSession._finalize_prologue_pendant` · pass_to_mutating_helper · **unknown_alias** · medium · apply_body_frame_holding
- `runtime/free_stage_prototype.py:8925` · `FreeStageSession.start` · pass_to_mutating_helper · **unknown_alias** · medium · settle_body_frames_from_npc_turns
- `runtime/free_stage_prototype.py:10284` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10964` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · settle_body_frames_from_npc_turns
- `runtime/free_stage_prototype.py:10992` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · settle_body_frames_from_npc_turns

### `world_cursor` → WorldCommit

- `runtime/free_stage_prototype.py:7474` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7528` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7930` · `FreeStageSession._maybe_enter_ryuya_flashback` · assign · **production** · high
- `runtime/free_stage_prototype.py:9121` · `FreeStageSession._advance_world_cursor_for_card` · assign · **production** · high
- `runtime/free_stage_prototype.py:9123` · `FreeStageSession._advance_world_cursor_for_card` · assign · **production** · high
- `runtime/free_stage_prototype.py:9130` · `FreeStageSession._advance_world_cursor_for_card` · assign · **production** · high
- `runtime/free_stage_prototype.py:9131` · `FreeStageSession._advance_world_cursor_for_card` · method:setdefault · **production** · high
- `runtime/free_stage_prototype.py:11498` · `FreeStageSession.skip_scene` · pass_to_mutating_helper · **unknown_alias** · medium · self._tick_offscreen_lines
- `runtime/free_stage_prototype.py:11998` · `FreeStageSession._maybe_transition` · pass_to_mutating_helper · **unknown_alias** · medium · self._tick_offscreen_lines

### `private_inner_states` → ActorMindReducer

- `runtime/free_stage_prototype.py:7478` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:9287` · `FreeStageSession._tick_private_inner_states` · assign · **production** · high
- `runtime/free_stage_prototype.py:10123` · `FreeStageSession.step` · method:setdefault · **production** · high
- `runtime/free_stage_prototype.py:10178` · `FreeStageSession.step` · method:setdefault · **production** · high
- `runtime/free_stage_prototype.py:10487` · `FreeStageSession.step` · method:setdefault · **production** · high
- `runtime/free_stage_prototype.py:11605` · `FreeStageSession._refresh_inner_states_on_scene_enter` · assign · **production** · high

### `prior_reflect_by_cons` → ActorMindReducer

- `runtime/free_stage_prototype.py:10462` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:11184` · `FreeStageSession.step` · assign · **production** · high

### `actor_minds` → ActorMindReducer

- `runtime/actor_theater.py:142` · `ActorTheater._queue_public_event` · pass_to_mutating_helper · **unknown_alias** · medium · apply_event_receipt
- `runtime/actor_theater.py:147` · `ActorTheater._queue_public_event` · assign · **production** · high
- `runtime/actor_theater.py:179` · `ActorTheater.run` · pass_to_mutating_helper · **unknown_alias** · medium · apply_event_receipt
- `runtime/actor_theater.py:184` · `ActorTheater.run` · assign · **production** · high
- `runtime/free_stage_prototype.py:7481` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:9199` · `FreeStageSession._ensure_actor_mind` · assign · **production** · high
- `runtime/free_stage_prototype.py:9209` · `FreeStageSession._apply_actor_mind_receipt` · assign · **production** · high

### `fsm_by_cons` → ActorMindReducer

- `runtime/free_stage_prototype.py:7479` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:10291` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10777` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10777` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · ott.tick_fsm

### `rel_state_by_cons` → ActorMindReducer

- `runtime/free_stage_prototype.py:7480` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:10292` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10783` · `FreeStageSession.step` · assign · **production** · high
- `runtime/free_stage_prototype.py:10783` · `FreeStageSession.step` · pass_to_mutating_helper · **unknown_alias** · medium · ott.tick_rel

### `ended` → ExitLifecycle

- `runtime/free_stage_prototype.py:7442` · `FreeStageSession._mark_ended` · assign · **production** · high
- `runtime/free_stage_prototype.py:7485` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:11537` · `FreeStageSession.skip_scene` · assign · **production** · high
- `runtime/free_stage_prototype.py:12097` · `FreeStageSession._maybe_transition` · assign · **production** · high

### `_run_closed` → ExitLifecycle

- `runtime/free_stage_prototype.py:7458` · `FreeStageSession._close_run_once` · assign · **production** · high
- `runtime/free_stage_prototype.py:7487` · `FreeStageSession.reset` · assign · **production** · high

### `run_receipt` → ExitLifecycle

- `runtime/free_stage_prototype.py:7453` · `FreeStageSession._close_run_once` · assign · **production** · high
- `runtime/free_stage_prototype.py:7461` · `FreeStageSession._close_run_once` · assign · **production** · high
- `runtime/free_stage_prototype.py:7486` · `FreeStageSession.reset` · assign · **production** · high

### `_last_exit_intent_exit_spec` → ExitPolicy

- `runtime/free_stage_prototype.py:11749` · `FreeStageSession._maybe_transition` · assign · **production** · high
- `runtime/free_stage_prototype.py:11755` · `FreeStageSession._maybe_transition` · assign · **production** · high
- `runtime/free_stage_prototype.py:12095` · `FreeStageSession._maybe_transition` · assign · **production** · high

### `pending_entry` → ExitPolicy

- `runtime/free_stage_prototype.py:8238` · `FreeStageSession._pending_entry_target_path` · assign · **production** · high
- `runtime/free_stage_prototype.py:12056` · `FreeStageSession._maybe_transition` · assign · **production** · high

### `ryuya_flashback_return` → ExitPolicy

- `runtime/free_stage_prototype.py:7524` · `FreeStageSession.reset` · assign · **production** · high
- `runtime/free_stage_prototype.py:7867` · `FreeStageSession._maybe_enter_ryuya_flashback` · assign · **production** · high
- `runtime/free_stage_prototype.py:12060` · `FreeStageSession._maybe_transition` · assign · **production** · high

### `sql:run_meta` → ExitLifecycle/RunRegistry

- `runtime/run_registry.py:70` · `open_run` · insert_into · **production** · high · SQL DML
- `scripts/settle_run.py:179` · `settle` · update · **production_tooling** · high · SQL DML

### `sql:delta_ledger` → WorldCommit/Settlement

- `runtime/delta_db.py:56` · `append_delta_rows` · insert_into · **production** · high · SQL DML

### `sql:delta_sediment` → Settlement

- `scripts/settle_run.py:167` · `settle` · delete_from · **production_tooling** · high · SQL DML
- `scripts/settle_run.py:170` · `settle` · insert_into · **production_tooling** · high · SQL DML

## Verify 登记 inventory

| status | count |
|---|---:|
| full_not_run | 7 |
| pass | 45 |
| skip | 164 |

### SKIP 原因

- 2 × 未建：scripts/tests/test_observer_debug.py
- 1 × 未建：scripts/tests/test_pipeline_steps.py
- 1 × 未建：scripts/tests/test_scene_runtime.py
- 1 × 未建：scripts/tests/test_director_contract.py
- 1 × 未建：scripts/tests/test_improv_gate.py
- 1 × 未建：scripts/tests/test_scene_api_fallback.py
- 1 × 未建：scripts/tests/test_condition_regression.py
- 1 × 未建：scripts/tests/test_location_kind_coverage.py
- 1 × 未建：scripts/tests/test_scene_surface.py
- 1 × 未建：scripts/tests/test_opening_forensic_baseline.py
- 1 × 未建：scripts/tests/test_post_completion_forensic_regressions.py
- 1 × 未建：scripts/tests/test_c16_integrity_regressions.py
- 1 × 未建：scripts/tests/test_c16_16_1_forensic_truth.py
- 1 × 未建：scripts/tests/test_c16_canon_performance.py
- 1 × 未建：scripts/tests/test_b0_canon_performance.py
- 1 × 未建：scripts/tests/test_director_three_projection.py
- 1 × 未建：scripts/tests/test_player_premise_leak_gate.py
- 1 × 未建：scripts/tests/test_identity_relation_projection.py
- 1 × 未建：scripts/tests/test_episode_subject_gate.py
- 1 × 未建：scripts/tests/test_director_stall_escalation.py
- 1 × 未建：scripts/tests/test_director_intent_contract.py
- 1 × 未建：scripts/tests/test_live_agency_baseline.py
- 1 × 未建：scripts/tests/test_scene_receipt_branch_migration.py
- 1 × 未建：scripts/tests/test_context_receipt.py
- 1 × 未建：scripts/tests/test_sequential_turn_taking.py
- 1 × 未建：scripts/tests/test_prompt_cache_observability.py
- 1 × 未建：scripts/tests/test_actor_load_contract.py
- 1 × 未建：scripts/tests/test_authoritative_world_transactions.py
- 1 × 未建：scripts/tests/test_actor_mind_v2.py
- 1 × 未建：scripts/tests/test_actor_theater.py
- 1 × 未建：scripts/tests/test_director_ports.py
- 1 × 未建：scripts/tests/test_director_ports_production_wire.py
- 1 × 未建：scripts/tests/test_context_budget_audit.py
- 1 × 未建：scripts/tests/test_context_assembly.py
- 1 × 未建：scripts/tests/test_scene_personality.py
- 1 × 未建：scripts/tests/test_ephemeral_storylet_overlay.py
- 1 × 未建：scripts/tests/test_intent_runtime.py
- 1 × 未建：scripts/tests/test_actor_decision_runtime.py
- 1 × 未建：scripts/tests/test_autonomous_decision.py
- 1 × 未建：scripts/tests/test_milktea_player_join_vertical.py
- 1 × 未建：scripts/tests/test_tianjin_leisure_window.py
- 1 × 未建：scripts/tests/test_observer_world_coordinates.py
- 1 × 未建：scripts/tests/test_director_voice_generation.py
- 1 × 未建：scripts/tests/test_opening_load_and_suspense.py
- 1 × 未建：scripts/tests/test_interaction_dynamics.py
- 1 × 未建：scripts/tests/test_ryuya_prologue_handoff.py
- 1 × 未建：scripts/tests/test_player_action_recall.py
- 1 × 未建：scripts/tests/test_return_split_source_guard.py
- 1 × 未建：scripts/verify_opening_provenance.py
- 1 × 未建：scripts/verify_persona_cores.py
- 1 × 未建：scripts/verify_relevant_knowledge.py
- 1 × 未建：scripts/tests/test_opening_memory.py
- 1 × 未建：scripts/tests/test_memory_lorebook.py
- 1 × 未建：scripts/tests/test_voice_injection.py
- 1 × 未建：scripts/tests/test_agent_state.py
- 1 × 未建：scripts/tests/test_bidding_turntake.py
- 1 × 未建：scripts/tests/test_turn_pacing.py
- 1 × 未建：scripts/tests/test_gm_pacing_exit.py
- 1 × 未建：scripts/tests/test_delta_from_scene.py
- 1 × 未建：scripts/tests/test_runtime_prop_propagation.py
- 1 × 未建：scripts/tests/test_scene_contract_bind.py
- 1 × 未建：scripts/tests/test_no_scratch_leak.py
- 1 × 未建：scripts/tests/test_scene_progress_antirepeat.py
- 1 × 未建：scripts/tests/test_actor_speak_retry.py
- 1 × 未建：scripts/tests/test_llm_transport_retry.py
- 1 × 未建：scripts/tests/test_actor_antirepeat_prompt.py
- 1 × 未建：scripts/tests/test_actor_terminal_initiative.py
- 1 × 未建：scripts/tests/test_gate_handoff.py
- 1 × 未建：scripts/tests/test_director_fastpath.py
- 1 × 未建：scripts/tests/test_scene_state_authority.py
- 1 × 未建：scripts/tests/test_crash_memory_persistence.py
- 1 × 未建：scripts/tests/test_director_gm_role.py
- 1 × 未建：scripts/tests/test_player_surface_no_leak.py
- 1 × 未建：scripts/tests/test_actor_initiative.py
- 1 × 未建：scripts/tests/test_scene_flow_complete.py
- 1 × 未建：scripts/tests/test_opening_structure_guard.py
- 1 × 未建：scripts/tests/test_verify_tier_budget.py
- 1 × 未建：scripts/tests/test_opening_e2e.py
- 1 × 未建：scripts/tests/test_server_smoke.py
- 1 × 未建：scripts/tests/test_console_concurrency.py
- 1 × 未建：scripts/tests/test_name_book.py
- 1 × 未建：scripts/tests/test_knowledge_gate_parity.py
- 1 × 未建：scripts/tests/test_verify_relevant.py
- 1 × 未建：scripts/tests/test_hot_path_io_cache.py
- 1 × 未建：scripts/tests/test_free_stage_save_slots.py
- 1 × 未建：scripts/tests/test_observer_opening_selector.py
- 1 × 未建：scripts/tests/test_free_stage_pacing.py
- 1 × 未建：scripts/tests/test_free_stage_c1_tiananmen.py
- 1 × 未建：scripts/tests/test_aline_tiananmen_truth.py
- 1 × 未建：scripts/tests/test_free_stage_c3_return_split.py
- 1 × 未建：scripts/tests/test_free_stage_c4_aquarium.py
- 1 × 未建：scripts/tests/test_free_stage_c5_dolphin.py
- 1 × 未建：scripts/tests/test_free_stage_c6_shooting.py
- 1 × 未建：scripts/tests/test_free_stage_c7_highway.py
- 1 × 未建：scripts/tests/test_free_stage_c8_hospital.py
- 1 × 未建：scripts/tests/test_free_stage_transition.py
- 1 × 未建：scripts/tests/test_free_stage_memory_consolidation.py
- 1 × 未建：scripts/tests/test_memory_consolidation_x2.py
- 1 × 未建：scripts/tests/test_player_profile_memory_chain.py
- 1 × 未建：scripts/tests/test_free_stage_refusal.py
- 1 × 未建：scripts/tests/test_aline_gate_hygiene.py
- 1 × 未建：scripts/tests/test_free_stage_inner_state.py
- 1 × 未建：scripts/tests/test_free_stage_offscreen.py
- 1 × 未建：scripts/tests/test_free_stage_three_channel.py
- 1 × 未建：scripts/tests/test_free_stage_bidding.py
- 1 × 未建：scripts/tests/test_free_stage_mh_pacing.py
- 1 × 未建：scripts/tests/test_free_stage_per_npc_memory.py
- 1 × 未建：scripts/tests/test_free_stage_director_eye.py
- 1 × 未建：scripts/tests/test_free_stage_q5_transition_modes.py
- 1 × 未建：scripts/tests/test_free_stage_q7_surface_guard.py
- 1 × 未建：scripts/tests/test_free_stage_handoff_t1.py
- 1 × 未建：scripts/tests/test_free_stage_checkpoints.py
- 1 × 未建：scripts/tests/test_free_stage_forced_exit.py
- 1 × 未建：scripts/tests/test_fictional_clock_min.py
- 1 × 未建：scripts/tests/test_prophecy_gate.py
- 1 × 未建：scripts/tests/test_free_stage_lazy_input.py
- 1 × 未建：scripts/tests/test_gate_handoff_free_stage.py
- 1 × 未建：scripts/tests/test_persona_replay_blind_tests.py
- 1 × 未建：scripts/verify_routing_links.py
- 1 × 未建：scripts/verify_status_chronology.py
- 1 × 未建：scripts/verify_no_live_secrets.py
- 1 × 未建：scripts/verify_local_server_security.py
- 1 × 未建：scripts/verify_plan_single_entry.py
- 1 × 未建：scripts/verify_workspace_inventory.py
- 1 × 未建：scripts/verify_runtime_boundaries.py
- 1 × 未建：scripts/test_cross_line_architecture_contract.py
- 1 × 未建：scripts/test_session_domain_state.py
- 1 × 未建：scripts/test_entry_router.py
- 1 × 未建：scripts/test_16zhong_shared_frame.py
- 1 × 未建：scripts/tests/test_golden_sessions.py
- 1 × 未建：scripts/tests/test_session_opening_migration.py
- 1 × 未建：scripts/verify_player_data_snapshot.py
- 1 × 未建：scripts/verify_tuning_ledger.py
- 1 × 未建：scripts/replay_audit.py
- 1 × 未建：scripts/tests/test_replay_audit.py
- 1 × 未建：scripts/tests/test_observer_payload_contract.py
- 1 × 未建：scripts/tests/test_actor_context_projection.py
- 1 × 未建：scripts/tests/test_actor_private_context_isolation.py
- 1 × 未建：scripts/tests/test_opening_memory_projection.py
- 1 × 未建：scripts/tests/test_player_observation_ledger.py
- 1 × 未建：scripts/tests/test_aline_memory_chain.py
- 1 × 未建：scripts/tests/test_actor_observes_player_channels.py
- 1 × 未建：scripts/tests/test_c16_friend_addressing.py
- 1 × 未建：scripts/tests/test_weichu_actor_context.py
- 1 × 未建：scripts/tests/test_weichu_cards.py
- 1 × 未建：scripts/tests/test_three_openings_golden.py
- 1 × 未建：scripts/tests/test_spoiler_gate.py
- 1 × 未建：scripts/run_red_team.py
- 1 × 未建：scripts/tests/test_card_oceanarium_merge.py
- 1 × 未建：scripts/tests/test_16zhong_cards.py
- 1 × 未建：scripts/tests/test_c16_intro_gate.py
- 1 × 未建：scripts/tests/test_c16_first_principles.py
- 1 × 未建：scripts/tests/test_playable_cast_assets.py
- 1 × 未建：scripts/tests/test_frame_card_projection.py
- 1 × 未建：scripts/tests/test_beat_ledger.py
- 1 × 未建：scripts/tests/test_world_calendar.py
- 1 × 未建：scripts/tests/test_offscreen_tick.py
- 1 × 未建：scripts/tests/test_offscreen_actor_action.py
- 1 × 未建：scripts/tests/test_heart_gate.py
- 1 × 未建：scripts/tests/test_w2_content_schema.py
- 1 × 未建：scripts/verify_w2_semantic_consistency.py
- 1 × 未建：scripts/tests/test_acceptance_console.py
- 1 × 未建：scripts/tests/test_card_db_consistency.py

## 审计限制 / 红胶带

- 本报告**不宣称 AST 完备**。动态 setattr/exec、跨函数别名写入和非 Python writer 需要后续 trace/人工调用链补证。
- `unknown_alias` 必须在所属域切换前逐条解释或增加运行 trace；不能因为 production writer 数量看起来少就宣布收口。
- 初始化、load/migration、projection 可以存在，但必须保持单向；本报告分类错误也要在 P0a 内修正。
- 当前多 writer 是 P0a 的测绘结果，不是测试失败；到对应 P1/P2/P3 阶段会升级为 required=0 旁路。
- 本扫描器只读源码和验证器登记，不写 world_truth.db、session、δ 或 runtime 状态。
