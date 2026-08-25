---
date: 2026-08-25
topic: voice-plugin
maturity: requirements-ready
source: docs/ideation/2026-08-25-voice-plugin-ideation.md — survivors 1 (providers declare), 2 (seam split by direction), 4 (lease discipline), 5 (born-portable custody record), 6 (blocked-session signal, deferred as optional), 7 (speech is not an approval channel)
---

# Voice Plugin — Requirements

## Summary

A portable Agent Plugins package named `voice` that gives one explicitly bound, Herdr-managed Claude session a complete spoken conversational loop: the agent's reply is read aloud, the operator toggles a key and speaks, and the transcribed words arrive as editable, unsubmitted text in that same agent's input box. One agent at a time, both directions, no arbitration anywhere.

## Problem Frame

Voice behaviour across the operator's coding-agent environment is fragmented and client-specific. Claude Code's native `/voice` is input-only, hosted by Anthropic, and Claude-specific. A working prior-art plugin at `claude-interface` proves two-way voice is achievable but is macOS- and Claude-bound, depends on fragile terminal-input injection, has no provider contract, and kills every other session's listener when a second session starts. No other Herdr-managed agent receives spoken input, spoken output, or human-blocked notification at all.

The consequence is not that voice is unavailable. It is that provider selection, privacy and egress posture, fallback behaviour, and approval safety are governed inconsistently or not at all, and there is no common way to hold a spoken conversation with a chosen agent.

The cost shape is a fleet that talks in different voices or not at all, and a set of trust boundaries — microphone, credentials, subprocess, approval — that each implementation redecides privately.

## Product Thesis

Voice is one portable, provider-selectable spoken conversation contract for Herdr-managed coding agents. It is not a notification system, not a dictation tool, and not a provider. Its identity is the loop: an agent speaks, the operator answers by voice, and the answer lands as text the operator can still edit before it is sent.

Version one proves that loop for a single Claude session because the loop is the product. Generalisation to other agents follows evidence, not ambition.

## Key Decisions

**Herdr is the required substrate for version one.** Herdr's agent API is the only cross-client lifecycle seam in scope. Voice is explicitly for Herdr-managed agents at this stage, and no per-client fallback is promised, configured, or scaffolded without a demonstrated consumer. Herdr is the repository's recorded vendor-independent execution boundary, and Voice consumes its state-reporting agent integrations, so this inherits a maintained fleet of adapters rather than owing one.

**Response text comes from the Claude `Stop` hook, never from the screen.** Claude Code's own documentation directs hooks needing the final assistant text to use `last_assistant_message` rather than reading the transcript, because the transcript is written asynchronously and can lag. Terminal-output scraping is rejected outright: it is a text-user-interface snapshot, and whatever matches becomes something a speaker says aloud in the room.

**Text reaches the agent through Herdr, not through the terminal.** No supported mechanism exists for an external process to place text into a running Claude session. `herdr agent send-keys` types without submitting, addressed by the Claude session identifier, which is exactly the editable-and-unsubmitted behaviour required. This displaces the four per-terminal injection strategies, the window locator file, the terminal-detection branch, and the per-application Accessibility grants that the prior art needs.

**One binding governs both directions.** Voice binds to a single explicitly selected Herdr agent. Only that agent speaks, and only that agent receives transcription. This removes the need for any speech arbitration, queue, or priority scheme, because nothing can overlap when only one agent can speak.

**Speech is never an approval channel.** When the bound agent is blocked on a permission, approval, or other human-decision prompt, keystrokes are choices rather than text. Voice refuses to deliver, and the refusal is a structural property rather than an intention.

**Providers are declared, never discovered or installed.** The operator states each provider's command or endpoint, its capabilities, and its egress class. Voice preflights and reports; it never installs, provisions, or silently substitutes.

**Voice performs no response-length management.** Voice speaks exactly the text Claude supplies. Concision is an agent output-style concern to be addressed after real usage, not Voice's responsibility. The stop control is consequently the only length control that exists, which is why it is required in three forms: the in-pane stop key (R8), barge-in through the record toggle (R9), and the Herdr-wide `voice stop` keybinding whose presence is preflighted (R14).

## Actors

A1. **The operator** — a single developer, running many concurrent agents under Herdr, who wants to hold a spoken conversation with one of them.

A2. **The bound Claude agent** — one Herdr-managed Claude Code session, explicitly selected, whose replies are spoken and whose input box receives transcription.

A3. **Herdr** — the terminal workspace manager that owns agent identity, lifecycle state, and the input path. Consumed, never modified by Voice.

A4. **The declared providers** — a text-to-speech provider and a speech-to-text provider that the operator has already installed, configured, and paid for. External to the plugin in every sense.

## Key Flows

F1. **The conversational loop.**

**Trigger:** the bound agent finishes a response.
**Covers R1, R5, R6, R7, R10, R11, R12, R16, R17.**

The Claude `Stop` hook fires asynchronously and compares its own session identifier against the current binding. If it matches, Voice cleans the supplied text and speaks it through the declared text-to-speech provider. The operator presses the toggle key in the Voice pane, which stops any playback in progress and starts recording, with the recording state shown unmistakably. The operator speaks and presses the toggle key again. Only then is the audio transcribed. The resulting text is delivered into the bound agent's input box unsubmitted, where the operator can edit it and send it. The loop repeats.

F2. **Binding and rebinding.**

**Trigger:** the operator starts Voice, or chooses a different agent.
**Covers R2, R3, R4.**

The operator explicitly selects one Herdr agent. The binding persists until explicitly changed, and the bound target is displayed continuously alongside the recording state. Voice never infers a target from focus and never follows the most recent speaker.

F3. **Refusal while blocked.**

**Trigger:** recording stops and transcription completes while the bound agent is blocked.
**Covers R18, R19.**

Voice checks the bound agent's state immediately before delivery. If the agent is blocked, Voice sends nothing, states the refusal audibly, and retains the transcript transiently. The operator explicitly uses or discards it. Voice never delivers it automatically and never queues it for later delivery.

## Requirements

**Binding and speaking scope**

R1. The Claude `Stop` hook ships with the plugin, runs asynchronously so it never stalls a turn, and compares its own session identifier against the current binding before doing anything else.

R2. Voice binds to exactly one Herdr agent, selected explicitly by the operator, and remains bound until the operator explicitly changes it.

R3. Only the bound agent may speak. An unbound session's hook does nothing and produces no sound.

R4. The bound agent's identity is displayed continuously, alongside the recording state, wherever the operator can see it while using Voice.

**Spoken output**

R5. Voice speaks exactly the text Claude supplies through `last_assistant_message`. Voice applies no length gate, ceiling, truncation, truncation notice, sentence parsing, or summarisation.

R6. Voice applies basic markdown cleaning so formatting syntax is not spoken aloud.

R7. The contents of fenced code blocks are omitted entirely from speech.

R8. Playback can be stopped immediately by a key in the Voice pane.

R9. Starting a recording immediately stops any playback in progress.

**Voice input**

R10. Recording is toggled: one press starts it, a second press stops it. Version one does not implement press-and-hold.

R11. While recording, Voice displays a loud, unmistakable in-pane recording indicator.

R12. Nothing is transcribed and nothing is sent until the operator explicitly stops the recording.

R13. Voice runs in its own pane, because an interactive Claude session owns the pane it occupies.

R14. Voice preflights whether a documented Herdr-wide keybinding invoking `voice stop` is present, and reports its absence.

R15. Voice never modifies Herdr configuration.

**Delivery and safety**

R16. Transcribed text is delivered into the bound agent's input box unsubmitted and editable.

R17. The bound agent is the only permitted delivery target.

R18. When the bound agent is blocked on a permission, approval, or other human-decision prompt, Voice refuses to insert or submit the transcription and states the refusal audibly.

R19. A refused transcript is retained only transiently, until the operator explicitly uses or discards it. It is never delivered automatically and never queued for automatic delivery.

**Providers and preflight**

R20. Voice ships no provider implementations. Each provider is declared by the operator with its invocation or endpoint, its capabilities, its egress class, and the name of any credential environment variable it needs (never the value).

R21. Egress class is a stated value from a closed set — on-device, local-network, named-remote-service, or unofficial-remote-endpoint — and Voice distinguishes external egress from local-network use.

R22. Voice preflights a declared endpoint and its stated capabilities before use, and reports a missing or misconfigured prerequisite by name rather than failing at first use.

R23. Voice never substitutes one provider for another. A provider that is unavailable produces a named refusal, never a silent fallback.

R24. Provider installation, credential provisioning, billing, and service management are outside the plugin.

**Privacy and retention**

R25. Temporary audio is deleted immediately after transcription, including when transcription fails.

R26. Voice keeps no transcript log of its own. The only durable record is the bound agent's own conversation history after text is delivered.

R27. Voice emits no telemetry.

R28. Retention behaviour is a stated setting rather than a silent default, so the empty case is something a person wrote down.

**Packaging and validation**

R29. The package is portable core plus a Claude client adapter. Hooks live in the adapter, never in portable core.

R30. The package carries no provenance manifest and no port descriptor, because it is authored here and has no upstream to pin. Its README states that plainly rather than leaving absence to carry the meaning.

R31. Code is standard-library Python at the repository's declared floor, tested with `unittest` alongside the existing suite.

R32. Every subprocess Voice starts runs with its standard input explicitly closed and a deadline attached.

R33. Version one is accepted only when the full loop works, the multi-session silence check passes, and each safety behaviour has been manually verified.

## Acceptance Examples

These examples exercise the conversational loop and the load-bearing safety behaviours. They are not the complete acceptance set: R33 gates version one on the full loop, the multi-session silence check, and a manual verification of every safety behaviour, including requirements that carry no example here.

AE1. **Unbound sessions stay silent.** **Covers R1, R3.** With at least two Claude sessions running and Voice bound to one of them, the bound session's reply is spoken and the other session's reply produces no sound at all.

AE2. **Stop interrupts mid-utterance.** **Covers R8.** While a long reply is being spoken, pressing the stop key in the Voice pane silences it immediately rather than at the end of the current sentence.

AE3. **Barge-in silences playback.** **Covers R9.** While a reply is being spoken, pressing the toggle key to start recording stops the speech immediately and begins recording.

AE4. **Nothing leaves before the second press.** **Covers R12.** Starting a recording and then abandoning it without the second press results in no transcription request and no delivery.

AE5. **Refusal while blocked.** **Covers R18, R19.** With the bound agent showing a permission prompt, completing a recording produces an audible refusal, no keystrokes reach the agent, and the transcript is available for the operator to use or discard explicitly.

AE6. **Missing provider is named.** **Covers R22, R23.** With a declared provider absent or misconfigured, Voice reports which provider and which prerequisite is missing, and does not speak or transcribe through a different one.

AE7. **Audio does not survive.** **Covers R25.** After a completed loop, and again after a deliberately failed transcription, no recorded audio file remains.

AE8. **Delivered text is editable.** **Covers R16.** After delivery, the transcribed text sits in the bound agent's input box unsent, and the operator can edit it before submitting.

## Success Criteria

The operator can hold a spoken back-and-forth with one chosen agent — hearing a reply, answering by voice, seeing the answer arrive as editable text, and continuing — without touching the keyboard except for the toggle and the send.

Every safety decision recorded here has a corresponding manual check that was actually performed, rather than a claim in this document.

Running Voice with a fleet of concurrent agents produces sound from exactly one of them.

## Scope Boundaries

**Deferred for later**

- Generalisation to other Herdr-managed agents. The loop is proven for Claude first; other clients follow on evidence.
- Blocked-session alerts across the fleet. Retained as optional supporting functionality with its own recorded behaviour — blocked state only, a settling delay, coalescing, and the focused pane suppressed — but it does not define or delay this product.
- Apple's on-device `SpeechAnalyzer` as a speech-to-text provider. Deferred, not rejected. It returns when its compiled, signed, permission-bearing implementation is understood, and it must not reopen version one's toolchain. It carries a preflight obligation the others do not: its model assets are fetched on demand and can be evicted under disk pressure, so offline capability is a runtime state rather than a property.
- Local `whisper.cpp` or an operator-managed local-network speech service. Both are legitimate declared providers under the same contract; neither is a prerequisite.
- True press-and-hold recording. Possible only if the terminal and multiplexer both forward key-release events, which is unverified and deliberately untested. An evidence-backed enhancement, never a version-one promise.
- Response-length management of any kind. If replies prove too long to listen to, the remedy is the agent's output style, not a Voice feature. This is also a deliberate divergence from the ideation's producer-authored spoken closer (survivor 3): version one keeps no authorship layer between Claude's text and speech, per R5.

**Outside this product's identity**

- Provider installation, credentials, billing, and service lifecycle.
- Multi-session speech arbitration, queues, priorities, and automatic opt-in. The single-binding design exists so these are unnecessary rather than deferred.
- Any resident daemon or background listener.
- Continuous listening and wake-word activation.
- A Model Context Protocol listening tool. Ruled out on evidence verified at decision time but not archived in this repository: plugin-bundled servers were confirmed on only four of the ten named clients, Hermes cannot host one this way (its MCP path is its native plugin system, not a portable plugin bundle, per the brief's compatibility table), and a blocking tool call is moved to a background task after two minutes on Claude Code, which silently breaks the turn-taking this loop depends on.
- Terminal-output scraping and terminal-input injection.
- Modifying Herdr, or vendoring any part of it.

## Dependencies and Assumptions

**Depends on Herdr** for agent identity, lifecycle state, and the input path. Two exact join keys were confirmed against a live session: the Claude `session_id` a hook receives appears as `agent_session.value` in `herdr agent list`, and `HERDR_PANE_ID` is present in every pane's environment. Identity is therefore supplied, never guessed. These confirmations, the no-submit semantics of `herdr agent send-keys`, and the guard asymmetry between `herdr agent prompt` and `send-keys` are live-session results and are not archived in this repository; planning re-confirms each before implementation relies on it.

**Depends on declared providers** being installed and configured by the operator before use.

**Assumes the operator's terminal grants microphone access.** The permission prompt attaches to the terminal application rather than to the recording tool, so it is granted once and inherited.

**Assumes an interactive Claude session owns its pane**, which is why Voice runs in a separate one. This was reasoned from how an interactive session works rather than probed directly.

**Accepted unknown: whether Claude truncates `last_assistant_message` upstream.** Claude Code's documentation states the field exists and recommends it, but never states whether it is complete on a long response. This is deliberately not being tested. If Claude does cap it, Voice speaks less than it believes and reports nothing, because from Voice's side nothing was dropped.

**Stated residual: the blocked-state check is not atomic.** Voice checks the bound agent's state and then delivers; the agent can become blocked in between. This narrows the exposure rather than eliminating it. Closing it fully would require a guard inside `herdr agent send-keys` — which `herdr agent prompt` already has and `send-keys` does not — and that belongs to Herdr as a proposed enhancement, not to Voice as workaround machinery.

**Durability.** Two shifts would change this product's value. If Claude Code ships native two-way voice with interruption, the differentiator narrows to cross-agent portability and provider choice. If Herdr grows its own voice channel, the portable core would be better placed there. Both argue for keeping Voice small and its provider contract clean, which is the shape chosen.

## Outstanding Questions

**Deferred to planning**

- Where the binding and recording state live on disk, and how the Voice pane and the `Stop` hook share them.
- How the stop key, the toggle key, and the recording indicator are presented within the Voice pane.
- The exact shape of the provider declaration and where it is stored, honouring the convention both prior-art systems reached independently: behaviour in a configuration file, secrets in the environment, environment winning.
- Whether `herdr agent send-keys` requires any escaping for multi-line or punctuation-heavy transcripts.

**Non-blocking follow-ups**

- The toolchain conflict between this repository's declared Python floor with `unittest` and `infiquetra-context-library`'s standard requiring a higher floor with `uv` and `pytest`. It applies to every package in this catalog, not only this one, and is a context-library question rather than a Voice question.
- The absence of any organisational standard covering microphone access, audio recording, retention, or telemetry. This package's position on those is a candidate to promote into `infiquetra-context-library` as the first such standard.
- A guarded `send-keys` operation proposed to Herdr.

## Sources and Research

- `docs/ideation/2026-08-25-voice-plugin-ideation.md` — the ideation run this brainstorm consumes, including the rejections retained with reasons.
- `AGENTS.md:52-53` — commands, hooks, native agent definitions, permissions, and client runtime integration belong in explicit vendor adapters.
- `docs/cross-vendor-plugin-architecture-brief.md:27-31,46-56,61-63,93-104` — what Agent Plugins 1.0 does not standardise, the portable package shape, the Herdr execution boundary, and the ten-client compatibility table.
- `docs/engineering-journal/DECISIONS.md:748` — a client's real executable is supplied by the operator, never discovered. Governs every provider path and both join keys.
- `docs/engineering-journal/LEARNINGS.md:468` and `DECISIONS.md:817` — a setting whose empty value disables a control must never be optional; absent must never mean empty. Governs egress class and retention.
- `docs/engineering-journal/LEARNINGS.md:571` — a self-started subprocess must never inherit the parent's standard input, and needs a deadline regardless. Carried by R32.
- `docs/engineering-journal/LEARNINGS.md:187` — state what the mechanism established, not what it was for. Governs how the blocked-state residual is described.
- `scripts/check_repo.py` — a package with no provenance manifest is not an error, because a package authored in this repository has no upstream to pin. `plugins/fleet-core/` is the working precedent for a skill-less, scripts-only package with no port descriptor.
- Claude Code hooks documentation — the `Stop` event, the `last_assistant_message` field and the recommendation to prefer it over the transcript, asynchronous hook execution, and plugin-provided hooks declared at the plugin root. Cited by source name only; no durable capture lives in this repository, so archive the relevant excerpts before implementation relies on these field semantics.
- `claude-interface` (local prior art, read-only) — proves the `Stop`-hook-to-speech path and supplies the counter-examples: four per-terminal injection strategies, no push-to-talk, and a cross-session process kill that makes it unusable on a fleet.
- LifeOS (read-only) — proves the producer-authored readback pattern and supplies its costs: an enforcement gate that is observation-only, no maximum length where one is expected, a whole-message rejection at five hundred characters that produces silence, and no user-facing way to stop speech.
- voice-forge (read-only) — the provider Protocol and the three-state installed-versus-configured-versus-loaded discovery pattern, adopted as ideas rather than as a dependency.
