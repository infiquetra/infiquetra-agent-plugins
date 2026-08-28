# Auralis C3 Claude adapter — acceptance evidence

- **Date:** 2026-08-27
- **Unit:** U5, run `orch-auralis-c3-adapter`, issue [#46](https://github.com/infiquetra/infiquetra-agent-plugins/issues/46)
- **Plan:** [`docs/plans/2026-08-27-auralis-c3-adapter.md`](../../plans/2026-08-27-auralis-c3-adapter.md)
- **Scope:** Capability slice C3 (Claude adapter end of the versioned local bridge, voice 0.3.0)
- **Requirements authority:** `infiquetra/auralis` at immutable revision [`b49de1ba4d39cbd8a1e582d72bddca85bf528f8a`](https://github.com/infiquetra/auralis/blob/b49de1ba4d39cbd8a1e582d72bddca85bf528f8a/docs/brainstorms/2026-08-26-auralis-v1-requirements.md) (R20, R21, R22, R23, R25, R106, R107, R121, R122)

This document records the acceptance evidence for capability slice C3: the adapter
side of the versioned local bridge running inside the Claude Code process space,
shipping as `voice` package version `0.3.0`.

---

## Wire authority and provenance

The normative wire contract is **Auralis Bridge Contract v1**, authored by capability
slice C10 in `infiquetra/auralis` at revision `695cd0ecfddf44e0d6e3386da318bd5fde4a1926`.
The byte-identical snapshot is committed in this repository at
[`docs/bridge-v1-from-c10.md`](../../bridge-v1-from-c10.md):

- **Snapshot SHA-256:** `eb47d141e5c1b87bae0bd1c0799386a3aa8806635251db14fc806469b5db19eb`
- **Wire route count:** Exactly five frozen routes (`GET /v1/health`, `PUT /v1/presence`, `DELETE /v1/presence`, `GET /v1/current`, `POST /v1/rendering`). No sixth route is added or required.
- **Contract status flag:** Accepted at Saga Code Review, not yet merged to `auralis` `main`. All wire literals are centralized in `plugins/voice/scripts/bridge_client.py` and tested against the independent-literals fixture `plugins/voice/tests/bridge_stub.py`.

---

## Suite execution at final commit

| Command | Result |
|---|---|
| `python3 scripts/check_repo.py` | `Repository validation passed.` |
| `python3 -m unittest discover -s tests -v` | All tests pass (`Ran 773 tests ... OK`) |
| `python3 -m unittest discover -s plugins/voice/tests -v` | All 23 test modules pass (450 tests) |
| `python3 -m pytest plugins/*/tests -q` | `762 passed, 282 subtests passed in 26.91s` |
| `claude plugin validate plugins/voice --strict` | `✔ Validation passed` |
| `git diff --check` | Clean (no trailing whitespace or whitespace errors) |

---

## Requirements traceability matrix (C3 slice)

| R-ID | Requirement summary | Adapter-boundary share | Test evidence |
|---|---|---|---|
| **R20** | Bound agent authors spoken rendering; adapter never summarizes, shortens, or rewrites content | Gate rejects non-plain text without transformation; plain text is forwarded byte-identical | `plugins/voice/tests/test_rendering_gate.py`, `plugins/voice/tests/test_mcp_server.py` |
| **R21** | MCP surface for submitting authored spoken rendering | Plugin stdio MCP server exposes `submit_spoken_rendering` tool forwarding to `POST /v1/rendering` | `plugins/voice/tests/test_mcp_server.py` |
| **R22** | Unrendered turn completion falls back to cleaned written response rather than silence | Adapter submits only gated plain text, never fabricates submissions, records `fallback` outcome, and suppresses local speak | `plugins/voice/tests/test_stop_hook.py`, `plugins/voice/tests/test_r122_adapter_boundary.py`; joint AE36 |
| **R23** | Fallback turn is visibly marked, distinguishable from authored | Adapter records disjoint `fallback` vs `authored` outcome; Core marks `fallback_accepted` via in-process `acceptFallback()` | `plugins/voice/tests/test_stop_hook.py`, `plugins/voice/tests/test_turn_record.py`; joint AE36 |
| **R25** | No persistent verbosity mode; preferences carried as instructions; no adapter content alteration | Policy store renders instructions text only; adapter has no content transformation path | `plugins/voice/tests/test_voice_policy.py` |
| **R106** | Explicit origin signal for every turn while bound | `UserPromptSubmit` hook queries `GET /v1/current`, matches identity, and injects originated / not-originated signal | `plugins/voice/tests/test_user_prompt_submit_hook.py` |
| **R107** | Voice policy and armed Brief Next Turn override transmitted as instructions; consumed on transmission | Injected into Auralis-originated turns; one-shot `brief_next_turn` is atomically consumed on transmission | `plugins/voice/tests/test_user_prompt_submit_hook.py`, `plugins/voice/tests/test_voice_policy.py` |
| **R121** | Plain spoken text only; Markdown/code rejected with named reasons; never silently cleaned | Gate rejects with `fenced_code_block` or `markdown_formatting`; resubmission of plain text accepted (AE26) | `plugins/voice/tests/test_rendering_gate.py`, `plugins/voice/tests/test_mcp_server.py` |
| **R122** | Rejected rendering with no replacement falls back under R22 | Turn record carries named rejections; Stop hook records `fallback` outcome across production processes | `plugins/voice/tests/test_mcp_server.py`, `plugins/voice/tests/test_stop_hook.py`, `plugins/voice/tests/test_r122_adapter_boundary.py`; joint AE36 |

---

## Acceptance examples (AE) status

### AE26 — Markdown rejected, not cleaned; plain resubmission accepted: **PASS**

- **In-process tool tests:** `plugins/voice/tests/test_mcp_server.py::AE26AndSurfaceRenderingTests::test_ae26_reject_then_accept_no_repair` drives the `submit_spoken_rendering` MCP tool:
  1. A submission with Markdown emphasis and fenced code block returns `disposition: rejected_content`, `reason: fenced_code_block`, with detected classes named in detail. Nothing is forwarded to `POST /v1/rendering`. The turn record retains the verbatim rejected text (no cleaned rewrite).
  2. A plain-text resubmission on the same turn is forwarded byte-identical to `POST /v1/rendering` with the captured `(binding_id, turn_id)` pair and accepted.
- **Declared executable entrypoint:** `plugins/voice/tests/test_mcp_server.py::ExecutableEntrypointTests::test_declared_mcp_server_entrypoint_subprocess` copies the package to an installed-root temporary location and spawns the exact declared argv (`python3 <installed-root>/scripts/mcp_server.py`) over real stdio pipes:
  1. MCP `initialize` echoes protocol version `2024-11-05` and server info `auralis-voice` `0.3.0`.
  2. `tools/list` returns `submit_spoken_rendering` with closed input schema.
  3. `tools/call submit_spoken_rendering` with Markdown heading and bold returns `rejected_content` (`markdown_formatting`).
  4. `tools/call submit_spoken_rendering` with plain text returns `accepted`.
- **Adapter-boundary rejection-to-fallback lifecycle:** `plugins/voice/tests/test_r122_adapter_boundary.py::R122AdapterBoundaryTests::test_r122_rejected_rendering_with_no_replacement_settles_as_fallback` drives the complete multi-process sequence: real `user_prompt_submit_hook.py` subprocess -> real `mcp_server.py` subprocess rejecting Markdown -> no replacement -> real `stop_hook.py` subprocess recording outcome `fallback`.

### AE34 — Joint bridge acceptance with Core (C10): **READY**

The adapter implementation stands ready for joint cross-repository testing:
- Loopback bridge client (`bridge_client.py`) discovers `bridge.json` and implements discovery retry, `GET /v1/health`, `PUT /v1/presence`, `DELETE /v1/presence`, `GET /v1/current`, and `POST /v1/rendering`.
- Three-part adapter identity resolver (`adapter_identity.py`) resolves `agent_session_id`, `pane_id`, and `terminal_id` through Herdr and stated settings (`HERDR_PANE_ID`, `HERDR_BIN_PATH`).
- Lost-response duplicate reconciliation (F8 / §8) is verified at both client and MCP surface layers.
- Joint execution will be scheduled by the orchestrator across repositories once C10 lands on `main`.

### AE36 — Joint rejection-to-fallback end-to-end acceptance (C3 / C5 / C10): **DEPENDENCY RECORDED (OPEN)**

- **Executable home:** Repository `infiquetra/auralis` (Dart integration test suite).
- **Owner:** Capability slice C5 (Audio), with a Dart test harness standing in until C5 is built.
- **Mechanism:** `acceptFallback()` is an in-process Dart API on Core's `turn_coordinator.dart`; it is deliberately not a wire route.
- **Procedure:**
  1. Dart test starts Core on loopback and writes temporary `bridge.json`.
  2. Test starts this adapter's MCP server as a subprocess, registering presence over the real wire.
  3. Harness opens a voice turn on the coordinator.
  4. Real `user_prompt_submit_hook.py` runs, captures `(binding_id, turn_id)` at prompt time.
  5. Test submits Markdown to MCP server; C3 gate answers `rejected_content`; turn stays `open`.
  6. No replacement is submitted; real `stop_hook.py` runs and records outcome `fallback`.
  7. Harness calls in-process `acceptFallback({bindingId, turnId, text})`.
  8. Closing wire assertion: `GET /v1/current` reports the same captured turn in state `fallback_accepted` (R23 mark).
- **Status:** Open cross-repository dependency on `infiquetra/auralis`, tracked here and in the plan.

---

## Performed manual checks

In accordance with U4 and the plan's verification instructions:
- **Context injection:** In a live Herdr-managed session with the mock bridge showing an open bound turn, `user_prompt_submit_hook.py` injects the Auralis origin notice, expected rendering directive, and rendered voice policy instructions into `hookSpecificOutput.additionalContext`.
- **Double-speech suppression:** When the session is wire-bound to an active bridge binding, `stop_hook.py` reconciles the turn record (recording `authored` or `fallback`) and exits 0 without spawning the legacy `scripts/speak.py` process.

---

## Record of guard-mutation checks

During the implementation of U1 and U2, every validation guard and detector was mutation-tested (relaxed -> verified named test failure -> restored):

1. **U1 Token and Identifier Grammar Guards (`test_bridge_client.py`):**
   - Base64url token alphabet guard: mutated to accept `+` and `/` -> `test_token_grammar_violations_refuse_and_make_no_wire_requests` subtests failed -> restored.
   - Base64url padding guard: mutated to accept `=` -> `test_token_grammar_violations_refuse_and_make_no_wire_requests` subtest failed -> restored.
   - Token length guard: mutated to accept 32 chars -> `test_token_grammar_violations_refuse_and_make_no_wire_requests` subtests failed -> restored.
   - Core UUID version guard: mutated to accept UUIDv1 -> `test_malformed_uppercase_or_wrong_version_identifier_refuses_snapshot` subtests failed -> restored.
   - Core UUID lowercase guard: mutated to accept uppercase -> `test_malformed_uppercase_or_wrong_version_identifier_refuses_snapshot` subtests failed -> restored.
2. **U2 Rendering Gate Detector Classes (`test_rendering_gate.py`):**
   - Fenced code block detector: relaxed to require 4 backticks -> `test_gate_rejects_fenced_code_block` and `test_fenced_code_block_backticks` failed -> restored.
   - Indented code block detector: relaxed -> `test_indented_code_block` and `test_tab_indented_code_line` failed -> restored.
   - ATX heading detector: relaxed -> `test_atx_heading`, `test_empty_atx_heading`, `test_tab_delimited_atx_heading` failed -> restored.
   - Setext heading detector: relaxed -> `test_setext_heading` and `test_one_character_setext_underline` failed -> restored.
   - List marker detector: relaxed -> `test_list_marker`, `test_ordered_list_marker_non_one`, `test_multi_digit_ordered_marker_parenthesis`, `test_bullet_marker_at_end_of_line` failed -> restored.
   - Blockquote detector: relaxed -> `test_blockquote` and `test_blockquote_no_space_after_gt` failed -> restored.
   - Horizontal rule detector: relaxed -> `test_horizontal_rule`, `test_spaced_horizontal_rule`, `test_underscore_horizontal_rule` failed -> restored.
   - Table pipe detector: relaxed -> `test_table_pipe_row` and `test_pipe_row_no_leading_or_trailing_pipe` failed -> restored.
   - Link reference definition detector: relaxed -> `test_link_reference_definition` and `test_link_ref_def_multi_word_label` failed -> restored.
   - Hard line break detector: relaxed -> `test_hard_line_break_trailing_spaces`, `test_hard_line_break_backslash`, `test_hard_break_three_trailing_spaces` failed -> restored.
   - Raw HTML detector: relaxed -> `test_raw_html_tag_and_comment` and `test_raw_html_attribute_tag_and_non_tag_openers` failed -> restored.
   - Backslash escape detector: relaxed -> `test_backslash_escape` and `test_backslash_escape_bracket` failed -> restored.
   - Emphasis / strong pair detector: relaxed -> `test_gate_rejects_markdown_emphasis`, `test_emphasis_strong`, `test_three_asterisk_emphasis_run` failed -> restored.
   - Strikethrough detector: relaxed -> `test_strikethrough` and `test_one_tilde_strikethrough` failed -> restored.
   - Inline code span detector: relaxed -> `test_inline_code_span` and `test_two_backtick_code_span` failed -> restored.
   - Inline and reference link detector: relaxed -> `test_inline_link_image`, `test_inline_link_empty_bracket_text`, `test_reference_link` failed -> restored.
   - Autolink detector: relaxed -> `test_autolink` failed -> restored.
   - Flock transaction deadline guard (`test_turn_record.py`): mutated to ignore deadline -> `test_lock_acquisition_timeout_raises_turn_record_busy` and `test_stubbed_clock_acquisition_budget_refusal` failed -> restored.

---

## Conclusion and Verdict

**PASS — Unit U5 packaging, versioning, documentation, and evidence are complete.**
All nine slice requirements (R20, R21, R22, R23, R25, R106, R107, R121, R122) and acceptance criteria are satisfied at the adapter boundary.
