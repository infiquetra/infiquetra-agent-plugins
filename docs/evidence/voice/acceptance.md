# Voice plugin version one — acceptance evidence (R33)

- **Date:** 2026-08-25
- **Unit:** U7 (#34), run `orch-2026-08-25-voice`, parent contract #27
- **Accepted-at commit:** `d7bdd51` (branch `orch/orch-2026-08-25-voice-work-u7`,
  the merged whole of U1–U6)
- **Scope authorities:** parent #27, children #28–#34, and
  [the requirements](../../brainstorms/2026-08-25-voice-plugin-requirements.md)
  (R1–R33, AE1–AE8). This file is evidence, not scope.
- **Executed by:** the unattended U7 worker (Qwen), alone on the operator's
  workstation; no human at the keyboard or microphone. Where R33 requires a
  human-shaped input, this is recorded as a finding, never papered over.

R33 accepts version one only when the full loop works, the multi-session
silence check passes, and each safety behaviour has been manually verified.
This record states, per example and per requirement, what was actually
observed on the live, preflighted environment — and what could not be
reproduced unattended.

## Environment as stated for this run

The run's launch manifest carried no `VOICE_*` environment, so this session
stated it from the Home Lab deployment facts, and records every value here:

| Setting | Value | Provenance |
|---|---|---|
| `VOICE_FORGE_BASE_URL` | `http://jeff-mac-mini.infiquetra.com:9876` | Live Voice Forge deployment on the Mac mini (home-lab `asgard_voice.yml`, launchd daemon `ai.hermes.voice-forge`, port 9876). Verified answering: `/health` reports v0.3.0, 9 registered voices, backend `neutts` loaded. No IP address is hard-coded anywhere in the package. |
| `VOICE_FORGE_VOICE_ID` | `freya-pa` | **Recorded choice, no run record names one.** The contract requires a registered Voice Forge voice and names no specific one; `freya-pa` (the Asgard lead persona voice) is registered in the deployment and listed by `GET /v1/audio/voices`. The operator may restate any registered voice. |
| `VOICE_HERMES_BASE_URL` | unset — documented default `http://127.0.0.1:8765` | Live relay on this host, v0.20.4, `hermes -p mimir-engineer dashboard`. The default resolving correctly is itself part of what was tested. |
| `VOICE_HERMES_PROFILE` | unset — documented default `mimir-engineer` | The acceptance profile (D2). |
| `VOICE_RETENTION` | `ephemeral` | Stated explicitly per KTD6/R28. |
| `VOICE_STATE_DIR` | unset — default `~/.local/state/voice` | The designed home. |

Binding (R2): `voice_cli.py bind voice-plugin-orchestrator` — the run's
coordinator Claude session (`ba9505bf-...`, pane `w7H:pE`, status `done`).
Most defensible target: the session coordinating this run, idle at the time;
the delivery evidence below lands in its input box unsubmitted and was left
there for the operator to see and clear. Five Claude sessions were running at
the time (coordinator, `sdlc-orchestrator`, `decision-register-crosswalk-revi`,
`team-mimir-profile-updates-orche`, `claude-plugins-orchestrator`), plus the
worker's own qwen session — more than enough for the multi-session check.

One-time system adjustments for the run, both restored: output volume
50 → 75 → 100 → 50 (original value restored, verified by readback).

## Gate: the suite at the final merged commit

All four run-wide commands at `d7bdd51`:

| Command | Result |
|---|---|
| `python3 scripts/check_repo.py` | `Repository validation passed.` |
| `python3 -m unittest discover -s tests` | `Ran 741 tests ... OK` |
| `python3 -m pytest plugins/voice/tests -q` | `243 passed, 190 subtests passed` |
| `python3 -m pytest plugins/*/tests -q` (the CI glob) | `509 passed, 190 subtests passed` — voice and mission-control collect in one process with no namespace collision (KTD12) |
| `git diff --check` | clean |

## AE1–AE8, observed

### AE1 — Unbound sessions stay silent (R1, R3): **PASS**

Drove the real `Stop` hook (`com.infiquetra.claude/hooks/stop_hook.py`) with
real session payloads from `herdr agent list`:

- Unbound session `sdlc-orchestrator` (`0da2ed79-...`): hook exit 0 in
  **0.05 s**; no payload file, no speak child, state dir unchanged.
- Unbound session `team-mimir-profile-updates-orche` (`9521bc0e-...`): same —
  exit 0 in 0.04 s, silence, no side effects.
- Bound session `voice-plugin-orchestrator` (`ba9505bf-...`): hook exit 0 in
  **0.05 s** while the detached child worked asynchronously: payload file
  written and consumed by the child, `playback.json` carrying the afplay pid
  for the full utterance, then clean state (only `binding.json`). Observed
  end-to-end: ~5 s synthesis, then a continuous afplay window of ~10–11 s for
  the 11.76 s wav, then afplay and child both gone. The reply was spoken; the
  two other sessions produced no sound at all.

One discrepancy recorded for completeness: the first bound-session hook
invocation produced no playback (child exited ~9 s in, silent). The identical
invocation succeeded on every subsequent run, and the foreground equivalent
always succeeded; the consistent difference is model temperature state on the
Voice Forge host (first synthesis after idle loads the `neutts` model). The
detached child's refusal is invisible by design (stderr → devnull), so the
exact refusal text was not recoverable — recorded here rather than silently
dropped.

### AE2 — Stop interrupts mid-utterance (R8): **PASS**

Fired the long-utterance hook (~30 s spoken), let playback run 5 s, then ran
`voice_cli.py stop` — the command the operator's Herdr-wide `voice stop`
keybinding invokes. Within 1 s: afplay gone, `playback.json` cleared, the wav
deleted, the speak child exited. Silenced mid-utterance, not at sentence end.
(The `s` pane key routes through the same `speak.stop_playback()` entry
point.)

### AE3 — Barge-in silences playback (R9): **PASS**

With the pane running (driven through its stdin key loop) and a reply being
spoken (afplay pid 58910 live), pressed `t`: the pane ran `stop_playback()`
first — the utterance's afplay is gone in the next observation — and started
recording (`recording.json`: pid 58980 + capture wav path). The pane log
shows the sequence: `recording started — press t to stop and deliver`, then
the status redraw with `recording: *** RECORDING ***`.

### AE4 — Nothing leaves before the second press (R12): **PASS** (with an
abandonment observation)

- In-pane window: between the first `t` (recording started) and the second
  `t`, sampled over ~6 s: state carries only the live recording
  (`recording.json` + growing `capture-*.wav`); no transcription request is
  issued and nothing is delivered — the pane log carries no transcribe or
  deliver line until the second press.
- Abandonment: the pane exited (its stdin closed) while the recorder ran.
  Observed afterwards: the detached ffmpeg recorder kept capturing; no
  transcription request was issued and nothing was delivered — the recording
  simply persisted until an explicit stop or the 600 s ceiling.
- Dead-recorder path: killing that abandoned recorder and pressing the toggle
  cleaned the capture up **without transcribing it** (`_abandon` deleted the
  wav, cleared the state, started a fresh recording) — R12's "never
  transcribed without an explicit stop" held through the failure path too.

### AE5 — Refusal while blocked (R18, R19): **NOT REPRODUCIBLE UNATTENDED —
finding F4**

No Herdr agent was in the `blocked` state at any point during this run
(snapshot at delivery time: 11 `idle`, 2 `done`, 1 `working`; `blocked: none`),
and this session cannot drive another agent onto a permission prompt without
interfering with the operator's other sessions. The live blocked branch was
therefore not exercised. The blocked-path semantics are covered hermetically
in `plugins/voice/tests/test_deliver.py` (blocked → nothing sent, hold file
written, audible refusal spoken, `DeliveryRefusal` raised; `use_refused` /
`discard_refused` explicit-only). The coordinator should either re-run AE5
attended with the bound agent parked on a prompt, or raise the gap on #27.

### AE6 — Missing provider is named (R22, R23): **PASS**

Live named refusals from the real entry points (no substitution exists — only
the two declared providers are in the package):

| Misconfiguration | Observed |
|---|---|
| `VOICE_FORGE_BASE_URL` unset | `voice: VOICE_FORGE_BASE_URL: is not set and carries no default; state it explicitly` — exit 1, nothing spoken, payload file deleted |
| `VOICE_FORGE_BASE_URL=http://127.0.0.1:9` | `voice: provider 'voice-forge': synthesis request failed: [Errno 61] Connection refused` — exit 1 |
| `VOICE_FORGE_VOICE_ID=` (set but empty) | `voice: VOICE_FORGE_VOICE_ID: is set but empty; absent is one state and empty is another, and empty is never treated as a value` — absent never means empty, live |
| `VOICE_HERMES_BASE_URL=http://127.0.0.1:9` during stop-and-deliver | `voice: provider 'hermes-xai': the relay is unreachable or dropped the connection: URLError` — the wav was deleted by the failed transcription, nothing delivered |
| Preflight with these misconfigurations | every dependent probe reports `not-run` naming its missing prerequisite; no silent skip |

### AE7 — Audio does not survive (R25): **PASS with one residual race —
finding F6**

- Completed loop: after every successful speak and every transcribe, the
  state dir returned to `binding.json` alone — no `speak-*.wav`, no
  `capture-*.wav`, no payload files. Verified by listing after each scenario.
- Failed transcription: wav deleted on the refusal path (observed for both
  the unreachable-relay refusal and the provider-mismatch refusal).
- Residual: one 78-byte header-only `capture-*.wav` survived a killed
  zero-frame recorder — the recorder flushed its header a hair after the
  transcribe path's refusal and unlink had already run. The orphan was
  removed during this acceptance run; the product carries no stray-capture
  GC. See finding F6.
- Preflight sample files are deleted immediately after the round trip
  (`probe_sample_round_trip`'s `finally`).

### AE8 — Delivered text is editable (R16): **PASS**

Transcribed the synthesized phrase through the live relay (`transcript: 'This
is the voice acceptance test.'`, `provider: xai`), then `deliver()` — the
exact seam the pane calls. Observed:

- `herdr agent get voice-plugin-orchestrator` after delivery: status still
  `done` — **not** `working`, i.e. nothing was submitted (a submitted prompt
  would have started the session working).
- `herdr pane read w7H:pE`: the composer shows `❯ This is the voice
  acceptance test.` with the session at `-- INSERT --` — the text sits in the
  bound agent's input box, unsubmitted, cursor-editable.
- Delivery went only to the bound agent's pane id, re-resolved at send time
  (R17): no broadcast, no fallback.

The delivered text was left in the coordinator's composer for the operator to
see and clear.

## Safety behaviours manually verified (the rest of R33)

| Req | Behaviour | How verified |
|---|---|---|
| R1 | Hook never stalls a turn | Hook wall time 0.04–0.05 s across four invocations while the child worked up to ~40 s asynchronously; detach observed via `start_new_session` child living past the hook's exit |
| R2 | Sticky single binding, explicit change | `binding.json` written by `bind`, unchanged across every hook/toggle/deliver afterwards; nothing re-binds implicitly |
| R4 | Bound identity displayed continuously | Pane status lines redraw `bound: agent voice-plugin-orchestrator · session ba9505bf-...` after every key |
| R5 | No length gate | 75-word reply spoken whole: ~12 s synthesis, continuous ~28–30 s afplay window, no truncation, no refusal; deadline derived from the wav's own duration (11.76 s wav → afplay ran its full length) |
| R6 | Formatting not spoken | Live cleanup of the AE1 reply observed: `**Bold markers**` → `Bold markers`, `[a link](http://example.com)` → `a link`; cleaned text is what was synthesized |
| R7 | Fenced contents omitted | The same reply's ` ```python def never_spoken(): pass``` ` block produced no speech content — cleaned text jumps straight from the link sentence to `That is the whole reply.` |
| R10 | Toggle, not press-and-hold | One press starts, second press stops — observed repeatedly (`voice_cli.py toggle` and the pane `t` key share the one sequencer) |
| R11 | Loud recording indicator | Pane displays the literal `*** RECORDING ***` while recording, `recording: idle` otherwise |
| R12 | Nothing before the explicit stop | AE4 windows above; every transcription attempt in this run began at a second press |
| R13 | Voice in its own pane | Pane ran as its own process; the bound Claude session kept its own pane untouched |
| R14 | Keybinding preflighted, absence reported | `voice preflight` reports `herdr-config: herdr keybinding containing 'voice stop' — no keybinding command contains 'voice stop'` — the operator has not added the D4 binding yet (finding F8); the probe reads `~/.config/herdr/config.toml` and reports by name |
| R15 | Never writes Herdr configuration | `~/.config/herdr/config.toml` mtime unchanged across the entire run (2026-08-24 19:02, before this run); no write path exists in the probed code |
| R16/R17 | Unsubmitted delivery, bound target only | AE8 above |
| R18/R19 | Blocked refusal, transient hold | Hermetic only in this run — see AE5/F4. Code path verified by review + `test_deliver.py`; the hold file is one current file (replace, never append) and `use_refused`/`discard_refused` are explicit-only |
| R20 | Declarations carry credential names, never values | `providers.py` declarations inspected: both credential-variable names are empty (neither provider needs one); the repo-wide credential scan of `plugins/` passes |
| R21 | Closed egress set, external is a predicate | Declarations: `voice-forge` = `local-network`, `hermes-xai` = `named-remote-service`; `is_external_egress` true exactly for `named-remote-service`/`unofficial-remote-endpoint`; unknown classes rejected (suite) |
| R22 | Preflight names prerequisites | AE6 table + the live preflight report (below) |
| R23 | No substitution | Every refusal above names the declared provider; no second provider exists to fall back to; a relay response resolving a provider other than `xai` was refused live by name (finding F3 shows the guard firing on `None`) |
| R24 | No installation/provisioning/billing | Nothing was installed or provisioned; the run consumed the existing deployment read-only |
| R25 | Ephemeral audio | AE7 above |
| R26 | No transcript log | Final state dir: `binding.json` only. Transcripts travel in memory (return values / send-text argv); no file in the package writes a transcript (the refused-hold file is R19's transient, not a log, and was never created in this run) |
| R27 | No telemetry | The only HTTP the package performs is to the two declared endpoints (forge: `/health`, `/v1/audio/voices`, `/v1/audio/speech`; relay: root page, `/api/profiles`, `/api/audio/transcribe`) — nothing else anywhere in the source |
| R28 | Retention stated | `VOICE_RETENTION=ephemeral` stated for this run; the reader refuses unset/other values (suite). Runtime enforcement gap: finding F7 |
| R29 | Hooks in the adapter, portable core stays neutral | Tree: hooks live under `plugins/voice/com.infiquetra.claude/hooks/`; `plugins/voice/scripts/` carries no Claude-specific file |
| R30 | Provenance posture stated plainly | [Package README](../../../plugins/voice/README.md) "Provenance posture" section: authored here, no `PROVENANCE.json`, no port descriptor, no `CHANGELOG.md` until first external release — verified intact, no drift. `check_repo.py` passes with the absent manifest. Root `README.md` makes no voice claims; `docs/README.md` carries one now-imprecise generalization — finding F9 |
| R31 | Stdlib at `python>=3.12`, `unittest` | Suite facts above; README states the floor exactly as `python>=3.12` (line 113); no third-party import in the package |
| R32 | Closed stdin + deadline on every child | Live: the ffmpeg recorder's fds observed as `0u/1u/2u → /dev/null` while recording; every spawned child (ffmpeg, afplay, speak) ran detached with `start_new_session`; deadlines per KTD3 classes held throughout (no deadline fired in any success path) |

## The live preflight report (as observed)

`voice_cli.py preflight` with the stated environment, before any acceptance
scenario:

```text
voice preflight
  failed   voice-forge: GET /health — the process reports status None, not healthy
  ok       voice-forge: GET /v1/audio/voices — voice id 'freya-pa' is listed
  not-run  voice-forge: POST /v1/audio/speech sample synthesis — the voice-forge probes above did not pass
  ok       hermes-xai: GET /api/health — relay answering (version 0.20.4)
  ok       hermes-xai: session token from the root page — read into memory only; never persisted, printed, or logged
  failed   hermes-xai: GET /api/profiles — profile 'mimir-engineer' resolves stt.provider None, not 'xai'
  not-run  hermes-xai: sample round trip via POST /api/audio/transcribe — voice-forge sample synthesis unavailable
  failed   herdr-config: herdr keybinding containing 'voice stop' — no keybinding command contains 'voice stop'
  ok       capture-bin: executable present — present at /opt/homebrew/bin/ffmpeg
  ok       playback-bin: executable present — present at /usr/bin/afplay
verdict: 5 ok, 3 failed, 2 not-run — fail
```

Two of the three failures are probe-contract drift against the live services
(findings F1, F2); the third is the operator's pending D4 keybinding (F8).
The loops themselves were then exercised directly and work — the sample round
trip in particular was run through the real `transcribe` module: synthesized
phrase in, verbatim transcript out, `provider: xai`, wav deleted. The session
token was read into memory and never printed, persisted, or logged anywhere in
this record; `auth.json` was never read; the xAI bearer was never touched.

## Findings (for the coordinator — to raise on #27 / schedule)

- **F1 — Voice Forge health probe contract drift (U6 preflight vs deployed
  v0.3.0).** The probe requires `status` plus a `backend` member; deployed
  `/health` answers `{"ok": true, "version", "registry_dir", "voices_count",
  "backends_available", "backends_loaded"}`. Result: a healthy service with a
  loaded backend fails the health probe, which also gates the sample
  synthesis out of preflight. The service synthesizes fine when driven
  directly. Suggested alignment: accept `ok: true` and treat a non-empty
  `backends_loaded` as the usable-backend proof.
- **F2 — Hermes profile probe contract drift (U6 preflight vs relay v0.20.4).**
  Live `/api/profiles` entries carry no `stt` surface at all (keys:
  `description`, `display_name`, `gateway_running`, `model`, `name`, `path`,
  `provider` — the LLM provider, `skill_count`, …), so
  `stt.provider == "xai"` can never resolve. The real STT guarantee is the
  transcribe round trip itself, which passes with `provider: xai`. Suggested
  alignment: drop the profile-stt assertion or replace it with the round-trip
  sample as the STT proof.
- **F3 — Silence surfaces as a provider-mismatch refusal (KTD9 × relay
  silence mapping).** The relay maps silence / no-speech / hallucination-filtered
  audio to `{"ok": true, "transcript": "", "provider": null}` (its
  `transcribe_recording` omits `provider` on those paths). The R23 guard then
  refuses with `the relay resolved None, not the expected 'xai'` — safe
  (nothing is delivered) but misleading for a quiet room. Suggested closure:
  an empty transcript with absent provider is silence — refuse as "nothing to
  deliver", not as substitution. Observed live twice during this run.
- **F4 — AE5's blocked-state branch was not exercised live.** No agent was
  `blocked` during the unattended window and this session would not force one
  onto another operator session. Hermetic coverage exists
  (`plugins/voice/tests/test_deliver.py`); an attended re-run or a #27 note is
  the coordinator's call.
- **F5 — Capture device `:0` on this host is the iPhone Continuity
  microphone.** `ffmpeg -list_devices` audio: `[0] iPhone 12 Microphone`,
  `[1] Jeffrey's AirPods Pro`, `[2] Microsoft Teams Audio`, `[3] USB audio
  CODEC`. Device `:0` opens and produces valid wav (48 kHz mono) but captured
  rms 8.9 / peak 47 of 32767 while speakers played the acceptance phrase at
  volume 100 — no speaker-to-mic coupling is possible on this host, so live
  voice input needs a human speaking into the Continuity/AirPods mic. The
  listen path was therefore evidenced through the relay round trip plus the
  exact `deliver()` seam the pane uses; the pane sequencer itself was driven
  live through transcription in both the success shape (F3's silence case)
  and the failure shape (unreachable relay). Not a code defect — D3 pins
  `:0` by design — but the human-voice part of the loop remains for attended
  use.
- **F6 — Millisecond flush race leaves an orphan capture wav.** A killed
  zero-frame recorder can flush its header-only wav after the transcribe
  path's refusal and `finally: unlink` have already run; one 78-byte
  `capture-*.wav` survived and was removed manually during this run. The
  product has no stray-capture sweep. Narrow, artificial (requires a dead
  recorder that never wrote), but a real R25 residual.
- **F7 — `VOICE_RETENTION` is stated, read, and tested — and consulted by no
  runtime path.** `settings.retention()` has no caller outside its own tests;
  preflight does not probe it. A mis-stated posture is silently ignored
  rather than refused by name. Behaviour stays safe (the package is
  structurally ephemeral), but KTD6's "refused by name" contract is
  decorative until a runtime or preflight path calls it (U1 surface).
- **F8 — The D4 operator keybinding is not yet added.** Preflight reports the
  absence by name (R14 working as designed); the operator still needs to add
  the `[[keys.command]]` stanza whose command contains `voice stop`
  (documented in the package README).
- **F9 — `docs/README.md` closing claim drifted (conflict recorded, not
  edited).** Its final sentence says "the packages under `plugins/` are
  derived artifacts pinned to an upstream revision rather than a second
  writable source" — true for the ported packages, no longer true as written
  now that `voice` is authored here with no upstream. `docs/README.md` is
  outside this run's owned paths for U7, so the drift is recorded here for
  the coordinator rather than edited across the boundary (the plan's own
  rule: "only if a claim became untrue" collides with this run's owned-path
  list; the coordinator should pick the writer).

## Verdict

**Conditional pass — accepted for merge with findings F1–F9 recorded.**
Everything reproducible unattended was reproduced live against the real
deployment: the speak path end to end through the real hook (AE1, AE2, R5–R7),
the listen path through the real pane sequencer and relay (AE3, AE4, AE6,
AE7) to the boundary of acoustic voice input, delivery observed unsubmitted
and editable in the bound agent's input box (AE8), the multi-session silence
check with three real sessions, and every safety behaviour above verified by
direct observation or named-refusal evidence. Two R33 inputs are inherently
human-shaped and remain for an attended pass: speaking into the microphone
(F5) and parking the bound agent on a permission prompt for AE5 (F4). No
silent omissions: every gap is a numbered finding.

## Finding disposition as of 2026-08-26

The verdict above is the acceptance record as it stood on 2026-08-25 and is not
revised. This section is the running ledger of what has since happened to
F1–F9, so a later reader is not left inferring it from commit history.

| Finding | State | Evidence |
|---|---|---|
| F1 — Voice Forge health probe contract drift | **closed** | Probe now accepts `ok: true` with a non-empty `backends_loaded` (`plugins/voice/scripts/preflight.py`, `_backends_loaded`). Live preflight reports "process healthy with a loaded backend". |
| F2 — Hermes profile probe expects an absent `stt` surface | **closed** | The `stt` assertion is gone (zero occurrences in `preflight.py`); the transcribe round trip is the speech-to-text guarantee, and it passes with `provider: xai`. |
| F3 — relay silence refused as provider substitution | **closed** | An empty transcript with an absent provider is now refused as "nothing to deliver" (`plugins/voice/scripts/transcribe.py`). The substitution guard is unchanged for a non-empty transcript carrying an unexpected provider. |
| F4 — AE5's blocked-state branch not exercised live | **closed** | Closed on operator attestation of the attended pass (2026-08-26), alongside the hermetic coverage in `plugins/voice/tests/test_deliver.py`. See "Attended pass" below. |
| F5 — capture device `:0` is the iPhone Continuity microphone | **closed** | Never a code defect — D3 pins `:0` by design. The human-voice half of the loop was exercised in the attended pass; closed on operator attestation (2026-08-26). See "Attended pass" below. |
| F6 — millisecond flush race can leave an orphan capture wav | **open, tracked** | No stray-capture sweep exists. Narrow and artificial: it requires a dead recorder that never wrote a frame. Not a release blocker; carried to [#43](https://github.com/infiquetra/infiquetra-agent-plugins/issues/43). |
| F7 — `VOICE_RETENTION` is read and tested but never consulted | **open, tracked** | `settings.retention()` still has no caller outside its own tests, re-verified at `958eb50`. Behaviour stays safe because the package is structurally ephemeral, but KTD6's "refused by name" contract is decorative until a runtime or preflight path calls it. Not a release blocker; carried to [#44](https://github.com/infiquetra/infiquetra-agent-plugins/issues/44). |
| F8 — the D4 operator keybinding was not added | **closed** | See below. |
| F9 / code-review F10 — catalog claim drifted | **closed** | Both `docs/README.md` and the root `README.md` now scope the derived-artifact claim to *ported* packages and state that `voice` is authored here with no upstream pin. |

### F8 closed — the operator keybinding is configured and verified runnable

Closing F8 needed two things that did not exist when it was filed: a stop
command that stays valid across plugin updates, and a probe that could tell a
working binding from a plausible-looking one. Both landed first
(PR [#40](https://github.com/infiquetra/infiquetra-agent-plugins/pull/40),
released as `0.2.0` in
PR [#41](https://github.com/infiquetra/infiquetra-agent-plugins/pull/41)).

Operator configuration, reported 2026-08-26:

- Launcher installed at `~/.local/bin/voice`; `command -v voice` resolves it and
  `voice stop` executed.
- Herdr custom command added: `prefix+shift+v`, `type = "shell"`,
  `command = "voice stop"`, description "stop voice playback".
- `herdr config check` passed; `herdr server reload-config` applied with no
  diagnostics.

Independently verified in this repository on 2026-08-26, against the `0.2.0`
install the registry records:

```
ok  herdr-config: herdr keybinding containing 'voice stop'
      — 'voice stop' runs /Users/jefcox/.local/bin/voice
verdict: 10 ok, 0 failed, 0 not-run — pass
```

The full run covers real Voice Forge synthesis and a live xAI transcription
round trip (relay 0.20.5). That green line is worth trusting specifically
because the probe resolves the configured command rather than matching its
text — the false-green defect this finding's closure depended on. Voice wrote
no Herdr configuration at any point; the operator made every change.

### Attended pass — closed on operator attestation, 2026-08-26

F4 and F5 were the two acceptance inputs the unattended run could not reach:
the bound agent parked on a permission prompt, and a person speaking into the
capture device. The operator reports both were exercised on the evening of
2026-08-25 and considers the attended tests complete.

**This is an operator attestation, not a machine-verified result, and is
recorded as one.** No transcript, recording, or state snapshot from that
session was captured into this repository, and this repository did not observe
it. Nothing below should be read as a reproduced test: the distinction between
what was measured here and what was reported to us is the reason this
paragraph exists rather than a green row on its own.

What *is* verified here, and what the attestation rests on top of:

- The delivery seam the attended pass exercises is the same one AE8 drove live,
  observed placing text unsubmitted and editable in the bound agent's composer
  with that session still `done` rather than `working`.
- The blocked-state branch is covered hermetically in
  `plugins/voice/tests/test_deliver.py`: a blocked agent receives nothing, the
  hold file is written, the audible refusal is spoken, `DeliveryRefusal` is
  raised, and `use_refused` / `discard_refused` stay explicit-only.
- Capture device `:0` opens and produces valid 48 kHz mono wav, measured during
  the unattended run. What it could not supply was a human voice, which is
  precisely what the attended pass supplied.
- Live preflight passes 10 ok, 0 failed, 0 not-run against the installed
  `0.2.1` package, including real Voice Forge synthesis and a live xAI
  transcription round trip.

No new test run was invented to close these, and no attended acceptance was
re-run.
