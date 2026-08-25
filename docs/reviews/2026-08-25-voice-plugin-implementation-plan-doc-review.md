---
date: 2026-08-25
kind: doc-review
target: docs/plans/2026-08-25-voice-plugin-implementation-plan.md
reviewed_revision: 07dbb89a413fd10af2766e67f2443394b951f686
branch: orch/orch-2026-08-25-voice-docreview-grok
classification: issue-derived implementation plan
blocked: false
cycles: 1
---

# Doc Review — Voice Plugin Implementation Plan

**Verdict: READY after in-place repair.** Twelve validated findings (four P1, four P2, four P3) were repaired in the plan; no P0; no remaining open finding. Finding IDs D1–D12 in this artifact are this review's findings, not operator decisions D1/D2, which were not reopened.

## Review result

| field | value |
|-------|-------|
| target | `docs/plans/2026-08-25-voice-plugin-implementation-plan.md` |
| reviewed revision | `07dbb89a413fd10af2766e67f2443394b951f686` (plan as committed; findings raised against that text) |
| working-tree repairs | applied on `orch/orch-2026-08-25-voice-docreview-grok` (HEAD `17fc995`) |
| origin/main at review | `dd10d9b2b6b33f52f85971bf720df43065349a07` — matches the plan's stated base pin |
| classification | issue-derived implementation plan (path `docs/plans/` plus parent/child issues) |
| rubric phase | issue (three cores; three extras applied by judgment) |
| parent contract | [infiquetra/infiquetra-agent-plugins#27](https://github.com/infiquetra/infiquetra-agent-plugins/issues/27) |
| children | [#28](https://github.com/infiquetra/infiquetra-agent-plugins/issues/28)–[#34](https://github.com/infiquetra/infiquetra-agent-plugins/issues/34) |
| origin requirements | `docs/brainstorms/2026-08-25-voice-plugin-requirements.md` (R1–R33) |
| blocked | false — no remaining P0/P1 |
| cycles run | 1 (repairs applied; affected HOW closures re-read) |
| artifact | `docs/reviews/2026-08-25-voice-plugin-implementation-plan-doc-review.md` |
| override rationale | none needed |
| linked issue / plan | #27; repaired target plan |

The parent contract, all seven child issues, the requirements document, `scripts/check_repo.py`, `.github/workflows/ci.yml`, `tests/test_python_floor.py`, live `herdr` CLI output, `~/.config/herdr/config.toml` (path and `[[keys.command]]` shape only), the installed `openai-codex/codex` `hooks.json`, and the live Hermes relay at `http://127.0.0.1:8765/api/health` (version `0.20.4`) were checked before any repair.

## Readiness summary

The repaired plan can drive implementation of the portable `voice` plugin without a worker inventing a same-lane import, a Stop-hook text channel, a Hermes JSON field, pane keys, or numeric deadlines.

Exact-once ownership of R1–R33 is complete and non-overlapping (9+3+3+5+4+8+1 = 33) and matches #27. The lane graph matches #27, including U5's dependency on U3 for the audible R18 refusal.

Providers stay Voice Forge `POST /v1/audio/speech` and Hermes `POST /api/audio/transcribe` with the in-memory `X-Hermes-Session-Token`, one refresh and one retry on 401. The Claude `Stop` hook is planned to detach and return immediately.

Python is standard-library `urllib.request` with no HTTP client dependency. No credential is read, persisted, or logged. Operator decisions D1 and D2 are carried forward, not reopened.

## Findings

All findings validated before repair. Finding IDs are this review's, sorted by priority, then source anchor, then title.

| id | priority | anchor (at `07dbb89`) | validation verdict | disposition | summary |
|----|:--------:|-----------------------|--------------------|-------------|---------|
| D1 | P1 | KTD2 / U2 Stop hook | valid — KTD2 closes stdin on the detached child and never named a payload file or argv, so `last_assistant_message` had no channel to `speak.py`; U2 and U3 are concurrent G2, so an import would also violate #27 | repaired | Stop hook could not hand response text to U3 without inventing a channel or stealing speak.py |
| D2 | P1 | KTD9 / U4 transcribe body | valid — #31 names `AudioTranscriptionRequest` as a data URL but not the JSON key; the live relay's body field is `data_url` (verified against `POST /api/audio/transcribe` on the acceptance host, health `0.20.4`) | repaired | Worker would invent `audio`/`file`/`content` and fail live transcription |
| D3 | P1 | U5/U6 G3 seam / U6 approach | valid — U6 approach said pane handles use/discard "with U5" while G3 is concurrent and #33 forbids implementing delivery in U6; module-level `import deliver` would fail if U6 landed first | repaired | Listen-path sequencer and U5 invocation were unspecified across concurrent G3 |
| D4 | P1 | U6 pane presentation | valid — requirements deferred stop/toggle/indicator presentation to planning; Open Questions said none blocking; `input()` cannot satisfy R8 | repaired | Pane keys and unbuffered input were left for the worker to invent |
| D5 | P2 | U4 capture argv | valid — D3 names ffmpeg + AVFoundation but not the device selector or `-t` value | repaired | Capture argv pinned to `-f avfoundation -i :0 -t 600` |
| D6 | P2 | KTD3 deadlines | valid — "order of 10 s" / "order of 10 minutes" / unspecified HTTP read timeout; a short HTTP timeout would fail long replies and look like a length gate | repaired | 10 s helpers, 2 s playback margin, 600 s capture, 10/300 s synthesis HTTP |
| D7 | P2 | U2 `hooks.json` command | valid — Codex Stop hook is interpreter-prefixed (`node "…"`); the plan's command was a bare `.py` path | repaired | Command is `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/stop_hook.py"` |
| D8 | P2 | KTD13 / Open Questions | valid — R14 probe path was deferred though this host has `~/.config/herdr/config.toml` | repaired | Probe path pinned; tests inject it |
| D9 | P3 | U7 owned paths | valid — #27 gives U7 root `README.md` / `docs/README.md` only if a claim became untrue | repaired | Restated as non-routine |
| D10 | P3 | Implementation Units | valid — plan-sections require Patterns to follow; units omitted them | repaired | Run-wide patterns line added |
| D11 | P3 | R11 indicator | valid — "loud unmistakable" had no testable literal | repaired | `*** RECORDING ***` |
| D12 | P3 | U2 client `plugin.json` | valid — catalog `$schema` is required only on `plugins/*/plugin.json`; nested client manifests in unifi/mission-control have no `$schema` | repaired | Nested manifest matches those two |

### Repair notes for the non-obvious dispositions

D1's repair is a unique `speak-<uuid>.json` under `VOICE_STATE_DIR` plus argv `[sys.executable, speak_path, payload_path]`. Stdin stays closed (R32). U2 does not import `speak.py`.

D2's repair names JSON `{"data_url": "data:audio/wav;base64,<...>"}`. That is the live relay's wire field, not a Hermes Python import.

D3/D4's repair is KTD16: the pane sequences listen without owning it; `deliver` is a lazy injectable import; keys are `t`/`s`/`u`/`d`/`q` via stdlib `tty.setcbreak`. The parent graph is unchanged.

D5 also deletes abandoned and ceiling-expired wavs (D5 ephemeral), not only post-transcription (R25), so a recording that never reached Hermes does not remain on disk.

## Invalid candidates (validated and rejected, no repair)

| id | candidate | reason invalid |
|----|-----------|----------------|
| N1 | Treat #28/#31 "egress is `external`" as a fifth R21 enum value | R21's closed set is four literals; #27 D2 says "effective audio egress: external"; KTD4's predicate on `named-remote-service` is the only reading that satisfies both. #28's own AC greps the four R21 literals |
| N2 | Split U6 (preflight vs pane) because #33 invited a split | Parent graph and child numbering are the contract; splitting would reopen #27. Eight requirements and seven files are inside the issue-sizing band |
| N3 | Reopen operator D1 or D2 | Explicitly out of this review's authority; the plan carries both |
| N4 | Add a provider config file to honour the brainstorm's "behaviour in a configuration file" convention | That was deferred to planning; KTD5 rejects it with rationale and a revisit-when. Adding it would broaden version one |
| N5 | Switch delivery back to `herdr agent send-keys` because the requirements doc still names it | #27, #32, preflight P5, and the installed CLI all use `herdr pane send-text` (no Enter). `send-keys` accepts logical key names only |

## Applied fixes

| finding | edit made to the target plan |
|---------|------------------------------|
| D1 | KTD1 payload files; KTD2 argv spawn; U2/U3 `__main__` child; tests assert argv and no import |
| D2 | KTD9/`transcribe.py` body field `data_url`; U4 tests forbid other audio keys |
| D3 | KTD11 `use_refused`/`discard_refused`; KTD16 lazy import; U5/U6 approaches |
| D4 | KTD16 keys, `tty.setcbreak`, indicator literal; SKILL.md names the keys |
| D5 | U4 ffmpeg argv; abandon/ceiling delete wav without transcribing |
| D6 | KTD3 pinned numbers; synthesis HTTP timeout is a named refusal, not truncation |
| D7 | `hooks.json` command interpreter-prefixed |
| D8 | KTD13 path `~/.config/herdr/config.toml`; Open Questions no longer lists it |
| D9 | U7 owned-paths note for root README surfaces |
| D10 | Run-wide Patterns to follow under Implementation Units |
| D11 | Literal `*** RECORDING ***` |
| D12 | Nested client `plugin.json` has no catalog `$schema` |

No repair was declined. No journal or board write: #27 makes U7 the sole journal writer and the coordinator the sole board writer.

## Rubric review record (issue phase, inline)

Cores applied: `acceptance_criteria_clarity`, `devils_advocate_issue`, `spec_fidelity`. Extras applied by judgment: `context_completeness` (non-trivial repo, named files required), `issue_sizing` (seven units, U6 at eight requirements), `prerequisite_mapping` (multi-issue run with a real dependency graph).

| rubric | cycle 1 (at `07dbb89`) | after repair (affected areas) |
|--------|:----------------------:|:-----------------------------:|
| acceptance_criteria_clarity | 7 — load-bearing ACs exist, but pane keys, Hermes JSON field, and hook text channel were not observable | 9 |
| devil's advocate | 8 — smallest-slice posture holds; same-lane collaboration was the failure-mode gap | 9 |
| spec fidelity | 9 — R-mapping and #27 graph were already correct; KTD4 maps D2 "external" onto R21 | 9 |
| context completeness | 7 — files named; several HOW channels missing | 9 |
| issue sizing | 8 — U6 large but inside the parent contract | 8 (untouched) |
| prerequisite mapping | 7 — graph matched #27; G2/G3 invocation was implicit | 9 |

No rubric BLOCK condition was met. Rubric findings were merged into the D-series above and not reclassified as a separate readiness list.

## Checks the operator asked for (post-repair)

| check | result |
|-------|--------|
| R1–R33 exact-once ownership | Pass. Table sums 33; Counter of R-IDs is 1 each; matches #27 |
| Lane/dependency graph and shared-file rules match #27 | Pass. G1 U1; G2 U2∥U3∥U4; G3 U5∥U6; G4 U7. U5 depends on U3 for R18. README serialized; tests per-unit; CI nobody; journal U7 only |
| U5 depends on U3 for audible R18 | Pass |
| Voice Forge `POST /v1/audio/speech`; Hermes `POST /api/audio/transcribe` with in-memory `X-Hermes-Session-Token`, one refresh, one retry | Pass. KTD8/KTD9; `data_url` now named |
| Claude Stop hook DETACH and return immediately | Pass. KTD2; stdin closed; no wait |
| Python standard-library only, no HTTP client | Pass. `urllib.request`; greps forbid `requests`/`httpx` |
| No credential read, persisted, or logged | Pass. Empty credential-name field; no `auth.json`/`XAI_API_KEY`; token in memory only |

## Engine offer

Report-only. Issue #27 binds Saga Document Review of this plan to Grok `grok-4.6` at extra-high effort, which is this session.

No cross-family panel was requested, and none was dispatched. Finding IDs above are available for an advisory second opinion if the operator names one.

`/founder-review` is not recommended here: product scope is locked by #27 and the requirements document; this review's job was HOW readiness, not ambition.

## Residual risk from limited evidence

`last_assistant_message` completeness remains the requirements' accepted unknown: if Claude caps it upstream, Voice speaks less and reports nothing.

The blocked-state check-then-send race remains the contract's stated residual; KTD11 still does not patch it.

`VOICE_FORGE_VOICE_ID` remains a runtime value from the Home Lab receipt (D1, P8), not a plan decision.

ffmpeg device `:0` is the version-one AVFoundation default; an external mic on another index fails by named refusal rather than by discovery.

Hermes `data_url` is verified against the relay running today (health `0.20.4`). A future Hermes body rename is a stop-and-re-derive event, not a Voice fallback.

## Operator question

This review picked pane keys `t` toggle, `s` stop, `u` use refused, `d` discard, `q` quit, and ffmpeg capture device `:0`. If those are wrong for the keyboard or microphone you actually use, say so before U4/U6 dispatch — they are HOW defaults, not product-scope changes.
