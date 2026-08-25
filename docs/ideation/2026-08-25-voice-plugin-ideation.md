---
date: 2026-08-25
topic: voice-plugin
focus: a new portable Agent Plugins plugin named `voice` — true two-way spoken interaction with a coding agent, with selectable provider families
scope: broad
repo: infiquetra-agent-plugins
maturity: idea-ready
---

# Ideation: A Portable `voice` Plugin

This document explores the solution space for a new portable Agent Plugins package named `voice`, giving an operator true two-way spoken interaction with a coding agent — speak input, hear responses — with selectable provider families rather than one hard-wired voice stack. It is ideation only. It contains no plan, no requirements, and no implementation.

Sixty-two candidates were generated across six parallel frames, joined by six operator seeds and five cross-cutting combinations, then filtered adversarially. Seven survived. The rejections are kept with their reasons and stable ids.

## Corrections (added 2026-08-25, after publication)

Later verification against LifeOS's current code contradicted two claims made below. The original text is left unchanged as a record of what was believed at the time; these are the corrections, and they are the accurate statements.

**C1. LifeOS's format hook does not enforce anything.** The Grounding Context below says the spoken closer is "enforced by a format gate that can block the turn," and the survivor 3 rationale refers to "the mechanical enforcement LifeOS uses." Both are wrong. `FormatGate.hook.ts` is observation-only: every branch of its `run()` returns `null`, and violations are appended to a telemetry log rather than acted on. Its own header states this, dated 2026-07-12 — *"this gate does NOT block… the gate logs every violation… and returns null."* A neighbouring file still describes it as having teeth, but that comment is a day older and is contradicted by the code it describes. **Consequence:** the producer-authored spoken line has no enforcement mechanism in the one system that proved the pattern; it rests entirely on prompt compliance.

**C2. LifeOS does not sound a tone when the spoken line is missing.** Survivor 3 below says "when that line is missing the plugin plays a 'finished, nothing to say' tone rather than guessing." That was synthesis presented as observed prior art. LifeOS's real outcome set is exactly two states — spoken audio, or total silence. Nothing stands in for "I skipped this," and an over-length message is rejected whole rather than truncated, producing silence with no signal to the listener. **Consequence:** the earcon-on-absence idea is a proposal originating in this document, not a pattern borrowed from prior art, and it carries no external evidence.

Neither correction changes a survivor's rank or a rejection's reason. Both are reflected accurately in `docs/brainstorms/2026-08-25-voice-plugin-requirements.md`, which was written from the corrected evidence.

## Grounding Context

**Repo.** `infiquetra-agent-plugins` is a *source catalog*, not a runtime. It owns the proposed portable source for Infiquetra Agent Skills and Agent Plugins plus the inputs used to build vendor adapters; existing vendor plugin repositories stay authoritative until a recorded custody decision moves that authority (`AGENTS.md:5-11`, `AGENTS.md:56-57`). It is pure Python, standard library only, no network in continuous integration, pinned at `python>=3.12` by its own journal decision (`docs/engineering-journal/DECISIONS.md:700`). There is no `STRATEGY.md`.

Two rules dominate every idea below. First, `AGENTS.md:52-53`: "Put commands, hooks, native agent definitions, permissions, and client runtime integration in explicit vendor adapters." Second, the reason for that rule, at `docs/cross-vendor-plugin-architecture-brief.md:27-31`: "Agent Plugins 1.0 intentionally does **not** standardize commands, hooks, agent definitions, rules, permissions, Language Server Protocol servers, user interfaces, or marketplace distribution."

The consequence is the central fact of this whole exercise. A plugin that must actually *run* something has exactly two portable seams — an Agent Skill with bundled scripts, and a Model Context Protocol (MCP) server (`brief:46-56`). Everything else is a client adapter, and `brief:75-89` adds that "a client-specific directory does not become portable merely because it is stored beside the portable core."

Nothing in this repo currently has hooks, daemons, event streams, long-running processes, an MCP server, or any pluggable-backend pattern. Every "hook" string in the tree is either prose putting hooks out of portable scope or a test fixture (`tests/test_sync_vendor_source.py:453-461`) using `hooks/hooks.json` as an example of an unclassified path the custody validator must *refuse*. A `voice` plugin appears nowhere in the brief's classification table or its recommended proof sequence — it is new ground.

Five journal entries bind the design directly. "A client's real executable is supplied by the operator, never discovered" (`DECISIONS.md:357`) — a `which` lookup returned a wrapper that exec'd itself until the host ran out of processes, and the recorded conclusion is that the guess "cannot be made correct — only made to look correct on the machine it was tried on." "An optional safety setting is a safety setting that is off" (`LEARNINGS.md:385`) — "'absent' must never mean 'empty'. Make the empty case a thing someone had to write down." Its paired decision (`DECISIONS.md:426`) rejects warning-on-unknown-key because "a warning in a tool nobody watches is a comment." "A harness that inherits stdin behaves differently in a terminal than under a scheduler" (`LEARNINGS.md:488`) — a self-started subprocess must never inherit the parent's standard input "and give it a deadline regardless." And "The cleanup reported containment for a boundary the client can step outside" (`LEARNINGS.md:104`) — "State what the mechanism established, not what it was for."

Two queued P1 items also constrain scope. The repository carries no marketplace manifest anywhere at root, so it cannot be registered as a catalog, and writing one is explicitly not authorized (`QUEUED.md:109`). And the per-client decision that follows the ten-client compatibility matrix is deliberately still open (`QUEUED.md:73`).

**Context-libraries.** `infiquetra-context-library` (read from `origin/main`) supplies the plugin/skill repository archetype (manifests, distribution metadata, packaging tests, versioning and compatibility notes), the required engineering-journal shape, the Python toolchain standard, and the security baseline — never hardcode secrets, ship `.env.example` placeholders, validate at trust boundaries. It escalates on anything touching personally identifiable information or consent. Two things it does *not* supply matter here: it has no standard whatsoever for microphone access, audio recording, recording retention, telemetry, subprocess or daemon lifecycle, or configuration precedence; and its Python standard says `>=3.13`, `uv`, and `pytest` with an 80% coverage floor, while this repo pins `>=3.12` and validates with `unittest`. A `voice` plugin sits between two authorities on tooling and gets no cover at all on the microphone question.

**Named repos.** Four prior-art sources were read directly.

`claude-interface` (local, `/Users/jefcox/workspace/coxauto/claude-interface`) is a shipped, working macOS two-way voice plugin for Claude Code — and therefore the most valuable source here, because it is the only one that actually listens *and* speaks. It uses stock `say` with no flags at all (`src/hooks/tts_stop_hook.sh:51`), Apple `SFSpeechRecognizer` with `AVAudioEngine` for capture (`Sources/VoiceListener/VoiceListener.swift:20-24,73-79`), and four Claude Code lifecycle hooks registered into `~/.claude/settings.json`. It carries three hard-won findings: launchd must be the "responsible process" or the binary aborts with a privacy violation inside an IDE terminal on macOS 26 (`claude-voice-start:43-48`, CHANGELOG v1.0.1); the terminal-input-queue injection ioctl `TIOCSTI` has been disabled since macOS 12 (`docs/plans/2026-03-09-voice-input-plugin-design.md:36`), which is why text injection needs four separate per-emulator strategies (`src/bridge/claude-voice-bridge.py:146-155`) plus a raw `time.sleep(0.15)` before the Return keystroke; and it has no provider abstraction and no barge-in at all — every `say` is a backgrounded subshell nothing tracks or kills.

Hermes Agent (read-only prior art, never owned by this plugin) supplies the most complete provider abstraction: sibling abstract base classes for text-to-speech and transcription, a name-keyed registry, ten built-in speech providers and six transcription providers, and a structured preflight (`tools/voice_mode.py:1124-1183`) that composes independent checks into one report with a human-readable line each. It also supplies the sharpest anti-pattern: an unregistered provider name falls through the dispatch chain and *silently substitutes* Edge text-to-speech, then silently falls back again to a local model, with only a log line (`tools/tts_tool.py:2340-2364`). Its transcription half is better and honours an explicit choice with no silent cloud fallback. Its fix commit `a8c96a95ef` supplies a genuinely portable idea: a playback watchdog sized from the clip's probed duration rather than a fixed ceiling, with the idle timer re-armed around the whole playback window.

`voice-forge` (github.com/Infiquetra/voice-forge, commit `b4d101c`) is a self-hosted **text-to-speech-only** service; its sibling listening service is "planned" and does not exist even as a stub. Two ideas are worth lifting: a `@runtime_checkable` Protocol with a union reference type absorbing "voice = audio sample" versus "voice = preset id" versus "voice = pre-encoded state" (`src/voice_forge/backends/__init__.py:38-113`), and a three-state discovery call reporting `known` / `installed` / `loaded` separately per backend with a structured 503 naming the fix (`server.py:157-163,616-645`). It cannot be consumed as a dependency — its README's `pip install voice-forge-tts` claim does not hold, and the package returns HTTP 404 on the index.

`LifeOS` (github.com/danielmiessler/LifeOS, read live, MIT) is speech-**out** only; there is no speech input anywhere in its voice pipeline. Its contribution is the readback-selection mechanism: the system prompt mandates every reply end with a one-line spoken closer the agent writes itself (`LIFEOS_SYSTEM_PROMPT.md:54`), enforced by a format gate that can block the turn. *(Corrected — see C1: the gate is observation-only and cannot block.)* Its validator rejects filler and conversational openers, and its fallback returns the empty string, commented "invalid voice completions should be skipped, not spoken." Its scars are equally instructive: a multi-tier extraction fallback "spoke CHANGE bullets for six days on one install before anyone noticed"; one hung audio player "froze for 9h and silently blocked every voice message behind it while /voice/health stayed green"; and its transcript parser is anchored by name because "quoted third-party content can carry a 🗣️ marker, and what matches here gets SPOKEN."

**External context.** Claude Code already ships a native `/voice` — dictation only, audio streamed to Anthropic's servers, no text-to-speech, no barge-in, one fixed provider, and it does not work over SSH. Published prior art converges on four integration seams and no more: a lifecycle hook on the Stop event (dominant, at least four independent projects); a daemon plus Unix-domain-socket IPC; transcript log-tailing; and an MCP tool that polls an utterance queue around every tool call. A fifth, a subprocess wrapper, is used by TalkiTo but its mechanism is undocumented. The category verdict is blunt: **nobody has published a clean interrupt story for a bare terminal.** Two failure modes appear in no published source and are therefore likely unsolved — terminal raw-mode conflicts between a voice layer and the agent's own text user interface, and permission-prompt races where the agent needs a yes-or-no while speech is mid-sentence.

On providers: `say` supports voice selection, rate, and file output, none of which the prior art uses. Apple's `SpeechAnalyzer` with `SpeechTranscriber` (WWDC 2025 session 277) is the current recommended on-device speech-input path, distinct from the older `SFSpeechRecognizer` the prior art uses, and it attaches a `SpeechDetector` module for voice activity. The exact privacy-permission entitlement and the on-device-versus-server split were not verified from Apple's own reference text and remain open. "Edge TTS" needs care: the `edge-tts` package is an unofficial reverse-engineered client against the endpoint behind Edge's Read Aloud feature, which Microsoft's own forum position calls a terms-of-service violation — it is not a peer of Azure Speech or ElevenLabs. And the architectural fork that matters most: a fused speech-to-speech model such as OpenAI Realtime is **fundamentally incompatible with selectable provider families**, because you cannot swap half of one model.

No standard exists for wiring speech into an agent. MCP remains a text and tool-call protocol with no audio content type; voice-enabled models act as MCP *clients*, not the reverse. Every project surveyed invented its own seam.

## Topic Axes

1. **Integration seam and agent lifecycle** — how the plugin attaches to a running coding agent, what each seam can observe or interrupt, and its failure modes.
2. **Provider abstraction and capability discovery** — the interface split across transcription, synthesis, capture, and playback; how a family is selected; preflight; degradation without silent substitution; and the privacy, cost, latency, and platform tradeoffs each family carries.
3. **Turn-taking and interruption** — duplex model, push-to-talk versus continuous listening, barge-in, cancel, echo suppression, and how long the microphone stays open.
4. **Readback selection** — what of the agent's output is spoken at all, who decides, and how the decision is enforced.
5. **Portability boundary and packaging** — portable core versus client adapters versus external providers, and how a born-portable package fits a catalog whose tooling presumes an upstream original.

## Ranked Survivors

### 1. Providers declare; the plugin never guesses, never substitutes

Every provider ships a stated declaration of what it is and what it can do, and an unmet requirement is a named refusal rather than a quiet swap to something else.

Each provider entry states four things that today are inferred: the executable path, supplied by the operator and never discovered; an egress class from a closed vocabulary (on-device, local-network, named-remote-service, unofficial-remote-endpoint); a capability set (streams partial output, interruptible mid-utterance, works offline, returns a file or a stream, needs network, can be split from its other half); and the *name* of any credential environment variable, never its value. The operator additionally sets a posture — a maximum permitted egress class — and a provider above that ceiling is refused by name even when its key is configured. Preflight verifies by performing a tiny real synthesis, not by checking that an import resolves.

This is the repo's own recorded rules applied to a new domain rather than a new invention. `DECISIONS.md:357` already forbids discovering an executable, `LEARNINGS.md:385` already forbids a safety field whose absence disables a control, and `DECISIONS.md:426` already rejects warning-on-unknown-key as "a comment." Voice is where those rules bite hardest, because a misconfigured provider and a working one both present to the operator as the same thing: silence. It also settles the operator's four provider seeds as one mechanism instead of four code paths, and it makes the honest split visible — `say` and `SpeechAnalyzer` share only a vendor, so "native macOS" is two providers with different declared shapes, not one family.

The costs are real. The operator writes more configuration, and a wrong declaration fails at first use rather than at install time. Declaring an egress class also sits close to the out-of-scope line: describing where a provider sends data is not provisioning it, but the boundary should be written down before it drifts. And a declared latency figure from a hosted service is a marketing median, not a measurement, so anything scheduled against it needs a runtime correction.

| field | value |
|-------|-------|
| basis | direct: `docs/engineering-journal/DECISIONS.md:357`, `LEARNINGS.md:385`, `DECISIONS.md:426`; anti-pattern at Hermes `tools/tts_tool.py:2340-2364` (unknown name silently substitutes Edge, then NeuTTS, log line only); pattern at voice-forge `server.py:157-163,616-645` and `backends/kokoro.py:83-87` |
| source | combined |
| confidence | 92 |
| complexity | Med |
| axis | Provider abstraction and capability discovery |
| status | Unexplored |

### 2. Split the seam by direction: speech out is a client publisher, speech in is a portable tool

Speaking and listening are attached at different points, because the seam that can observe agent output cannot inject operator input, and forcing both through one seam is what produced the worst code in the prior art.

Speech out rides whatever cheap trigger each client offers — a Claude Code Stop hook, a Cursor rule, a manual command — and each of those is a thin *publisher* living in that client's adapter directory, doing nothing but posting a structured utterance and returning. Speech in rides an MCP tool the agent calls, which blocks until the operator's utterance is transcribed and returns it as an ordinary tool result. Because a tool result is the one path every supported client already handles, there is no terminal injection anywhere in the design.

The evidence for the split is unusually direct. `TIOCSTI` has been disabled since macOS 12, so `claude-interface` needs four separate per-emulator injection strategies plus a `time.sleep(0.15)` race workaround — roughly ten times the surface of its one-line speaking path, and the part that silently breaks when a terminal application updates. Meanwhile no hook fires *during* generation, which the hook-based projects state themselves, so a hook can only ever observe. And `AGENTS.md:52-53` makes every hook adapter-only regardless, while `brief:46-56` makes an MCP server portable core. The split puts the fragile half where the repo's rules already say it belongs and deletes the injector entirely.

The honest cost is that an MCP tool only fires when the agent *chooses* to call it, so listening rests on skill-instruction compliance rather than on a hook that fires unconditionally. This would also be the catalog's first MCP server, which the architecture brief wants as a proof case but which nothing here has yet paid for. If MCP turns out to be unreachable on enough of the ten clients, transcript log-tailing (`R7`) is the fallback, and its cost is a bet on undocumented internal formats.

| field | value |
|-------|-------|
| basis | direct: `AGENTS.md:52-53`; `docs/cross-vendor-plugin-architecture-brief.md:27-31,46-56`; claude-interface `docs/plans/2026-03-09-voice-input-plugin-design.md:36` and `src/bridge/claude-voice-bridge.py:100,134,146-155`; web research, hook seam — "no hook fires DURING generation" |
| source | combined |
| confidence | 84 |
| complexity | High |
| axis | Integration seam and agent lifecycle |
| status | Unexplored |

### 3. One utterance type, one speaker at a time, and a floor that needs nothing installed

Anything wanting to be heard emits a small structured utterance — text, urgency, scope, an interruptibility flag, and an optional non-speech alternative — and a single arbiter decides what is voiced, what waits, and what is dropped.

Exactly one utterance holds the operator's attention at a time. Higher urgency preempts, equal or lower waits, and the routine cases render as a short tone rather than a sentence. The text is authored by the producer, not extracted by the plugin: the agent writes its own one-line spoken closer as part of its reply, and when that line is missing the plugin plays a "finished, nothing to say" tone rather than guessing which part of the prose mattered. *(Corrected — see C2: LifeOS goes silent; the tone is a proposal here, not observed prior art.)* Because the non-speech alternative travels with the utterance, the lowest tier works with no provider configured at all.

Three independent domains and three prior-art scars point the same way. Aviation aural-alert practice allows one alert at a time and deliberately withholds a master caution from low-urgency advisories, because a master alert used for everything trains crews to ignore it — which is exactly what narrating every tool call does. Peer-reviewed screen-reader research finds auditory icons beat both abstract tones and full speech on reaction time and dual-task interference, because they do not compete with language comprehension for the same channel. Meanwhile `claude-interface` has no arbiter at all and two hooks firing close together simply overlap; LifeOS's derived-readback fallback spoke the wrong thing for six days; and its transcript parser had to be hardened because quoted third-party content that matches the marker gets spoken aloud in the room. Producer-authored text removes both the quality problem and the injection surface at once.

The cost is that the spoken line now depends on the agent's cooperation, and the mechanical enforcement LifeOS uses is a hook — so the *policy* is portable and the *enforcement* is not. For a single-user tool an unenforced instruction plus a tone on absence is probably enough, but that is a judgement to make deliberately. There is also a real tension with the survivor below: an arbiter implies cross-session state, and the cheapest honest form of that is a lease file, not a daemon.

| field | value |
|-------|-------|
| basis | direct: LifeOS `LIFEOS_SYSTEM_PROMPT.md:54`, `hooks/lib/output-validators.ts:44-57`, `VoiceCompletion.hook.ts:99-100`, `TranscriptParser.ts:26-27`; claude-interface `tts_hook.sh:55`, `tts_stop_hook.sh:24-39,51`. external: NASA/TM-2017-219720 and FAA general guidance ch. 4 §3; auditory-icon meta-analysis, tandfonline 10.1080/25742442.2023.2219201; VoiceXML 2.0 per-prompt `bargein` / `bargeintype` |
| source | combined |
| confidence | 88 |
| complexity | Med |
| axis | Readback selection |
| status | Unexplored |

### 4. Every scarce or dangerous resource is held under an expiring lease

The microphone, the speaker, and any warm model process are each held by a bounded, self-expiring, visibly-held lease rather than being a mode that is simply on.

Push-to-talk is a lease the length of a keypress. A playback lease is sized from the clip's probed duration rather than a fixed ceiling. A warm helper process holding a local model renews its lease by use and exits on its own when nobody renews — no launch agent, no supervision, and an orphan cannot outlive its expiry. Every child process starts with standard input explicitly closed and a deadline attached, and the lease file is also what lets one arbiter exist across sessions without a daemon.

The failure modes this closes are all on record. `LEARNINGS.md:488` states the rule directly: never inherit the parent's standard input, "and give it a deadline regardless, because closing stdin does not stop a program that ignores EOF." LifeOS's watchdog exists because one hung audio player "froze for 9h and silently blocked every voice message behind it while /voice/health stayed green." Hermes's fix commit replaced a hardcoded 120-second playback *ceiling* — which cut long readbacks off mid-sentence — with a floor plus the probed duration. And the most complete published daemon design names its own structural failure as "a stale socket or an orphan holding the microphone." A lease is the smallest mechanism that gives residency without supervision and makes the open-microphone window an expiring fact rather than an intention.

Two cautions. `LEARNINGS.md:104` is directly on point: a lease bounds what *this* plugin holds, not what the operating system or another application does, and the claim must be written to say only that. And a per-utterance warm-process lease is a latency optimisation whose value depends entirely on which provider family is configured — a system speech service pays nothing to start, so "needs a warm process" belongs in the provider declaration from survivor 1, not in the architecture.

| field | value |
|-------|-------|
| basis | direct: `LEARNINGS.md:488`, `LEARNINGS.md:104`; Hermes commit `a8c96a95ef` (duration-probed playback timeout, idle timer re-armed in `finally`) and `tools/neutts_synth.py` (~500MB model as a subprocess killed after each call, "no lingering memory"); LifeOS `voice.ts:453-455`; claude-voice's named failure mode |
| source | combined |
| confidence | 87 |
| complexity | Med |
| axis | Turn-taking and interruption |
| status | Unexplored |

### 5. One portable executable, shim adapters, and a stated born-portable origin

All behaviour lives in a single portable executable under the skill's scripts directory behind a stable text contract, every client adapter is a shim short enough to read at a glance, and the package states in its own record that it has no upstream original.

The naive build under this repo's rules grows one reimplementation of voice logic per supported client — ten of them, drifting apart. Putting the whole implementation behind one contract and reducing each adapter to "invoke it and exit" is the only shape that survives a ten-client matrix where no two clients share an extension mechanism. It also makes the core testable under this repo's actual gates — standard library only, no network, `unittest` — with no client, no microphone, and no credential installed, provided a declared null provider exists as a first-class citizen rather than a mock hidden in the test directory.

The custody half matters as much. `ports/<package>.json` presumes a real upstream Claude-plugin original to synchronize from and byte-diff against, and `voice` has none. Leaving the descriptor absent lets absence carry the meaning, which is precisely what `LEARNINGS.md:385` forbids and `DECISIONS.md:426` rejects — and the custody validator already *refuses* an unclassified path rather than adjudicating it (`tests/test_sync_vendor_source.py:453-461`). `voice` would be the first born-portable package and the next several are also born-portable, so the record either exists once or a class of packages quietly opts out of custody validation.

The discipline is real but the verification is not, and that gap should be named rather than papered over. A film's dialogue-free stem has a hard physical test; "contains no client-specific assumption" has none. The predictable failure is that the first adapter written will be Claude's, and a core authored while only that adapter exists will quietly encode Claude's hook semantics. Someone has to propose what stands in for the test.

| field | value |
|-------|-------|
| basis | direct: `AGENTS.md:52-53`; `brief:75-89,93-104`; `LEARNINGS.md:5` ("a second home that does not inherit the first home's invariant is the same defect again"); `DECISIONS.md:426`; `tests/test_sync_vendor_source.py:453-461`; anti-pattern at claude-interface `tts_stop_hook.sh:24-39` (real logic inside the hook). external: film music-and-effects track practice — author the portable stem during the mix, never extract it after |
| source | combined |
| confidence | 90 |
| complexity | Med |
| axis | Portability boundary and packaging |
| status | Unexplored |

### 6. Version one only says that a session is blocked on a person

Invert which behaviour is mandatory: the plugin may say almost nothing, except that whenever an agent has stopped and cannot proceed without a human it must produce an audible signal naming which session is waiting.

Everything else — completion narration, selective readback, spoken input — is optional and arrives later. The mandatory signal is the highest-priority utterance in the arbiter, so it preempts anything currently speaking, and it is a short tone rather than a sentence, which means it works with no provider configured at all.

The seeds treat speak-on-completion as the anchor interaction, but completion is the case where the operator is *least* blocked — the work is finished and the transcript is right there on screen. The case where audio has unique value is the inverse: the agent is stalled, the operator has looked away, and nothing on the screen will reach them. The single thing `claude-interface` speaks unprompted that is genuinely load-bearing is the permission prompt, and the permission-prompt race — the agent needing a yes-or-no while speech is mid-sentence — is one of the two failure modes that appear in no published source. Making blockage the highest-priority preempting event is a direct answer to it. Alarm-fatigue research reinforces the shape from the other side: the overwhelming majority of alarms are non-actionable, and delaying annunciation until a condition persists is a named pragmatic intervention.

This is a deliberate under-build and should be argued as one. A version that only signals blockage is a notifier, not a voice assistant, and it does not exercise the transcription half at all — so the risky half of the design gets no evidence from it. It is also honest that it ships without the recall half: if a signal is missed there is no "what did I miss," and no surveyed prior art offers a precedent for one.

| field | value |
|-------|-------|
| basis | external: NASA/TM-2017-219720 and FAA guidance on withholding a master caution from low-urgency advisories; monitor alarm-fatigue literature (PMC4206416; PubMed 26663904) on actionable-alarm fraction and alarm delay. direct: claude-interface `scripts/register_hooks.py:56-85` (a `PreToolUse` hook with matcher `""` whose whole job is speaking permission-prompt text); web research — permission-prompt races undocumented anywhere; LifeOS's anti-notification-fatigue policy |
| source | combined |
| confidence | 80 |
| complexity | Low |
| axis | Readback selection |
| status | Unexplored |

### 7. Speech is not an approval channel

Transcribed speech is conversational input only. It never answers a permission prompt, never confirms a destructive or hard-to-reverse action, and never auto-submits.

Two rules follow. The plugin does not route a transcript into a pending yes-or-no, so there is no window in which a misheard "yeah" lands on an approval. And a transcript is staged as editable text for the operator to glance at and correct, rather than pasted and submitted — the drive-through pattern, where the channel that verifies is deliberately not the channel that failed. If spoken approval is ever wanted, the escape hatch is the aviation one: read back what was heard and require a confirming turn, so that a mismatch becomes *detectable* rather than merely rarer.

Speech recognition has an irreducible error rate and the audio channel carries no error correction of its own, so any path from audio to an irreversible action runs a known error class straight into an unrecoverable outcome. A coding agent's action space includes deleting things. Every surveyed project either has no spoken command path at all or injects transcribed text straight into the prompt with no verification layer — and `claude-interface` creates exactly the dangerous shape by speaking permission-prompt text from an all-tools hook while having no confirmation path.

The cost is deliberate capability reduction, which is the point: this is a line that is cheap to hold from the start and effectively impossible to add once an operator has grown used to approving by voice. It is also worth noting the drive-through analogy has a limit — a short closed-vocabulary order reads back in a glance, and an open-prose instruction to a coding agent may not.

| field | value |
|-------|-------|
| basis | reasoned: a known, irreducible misrecognition rate in a channel with no error correction must not terminate in an irreversible action; every surveyed project either avoids the path entirely or takes it unverified. external: ICAO readback/hearback (IP06) — standardized phraseology exists so mismatches become detectable; drive-through order confirmation — the verifying modality is deliberately different from the input modality |
| source | combined |
| confidence | 83 |
| complexity | Low |
| axis | Turn-taking and interruption |
| status | Unexplored |

## Tradeoffs Made Visible

### Integration seams, with their failure modes

| seam | can observe | can inject input | portable core? | failure modes on record |
|---|---|---|---|---|
| Lifecycle hook (Stop / PreToolUse) | after a turn only | no | no — adapter by `AGENTS.md:52-53` | does not scope to one terminal across concurrent sessions; no hook fires during generation, so only playback can be interrupted, never the work |
| MCP tool | when the agent calls it | yes, as a tool result | yes — `brief:46-56` | fires only if the agent chooses to call it; no audio content type in MCP, so audio must stay local; a long-running tool call is a window with no control |
| Daemon + socket IPC | continuously | via a client of its own | no | stale socket; orphan holding the microphone; needs supervision a single-user tool should not carry |
| Transcript log-tailing | after writes land | no | partly — a path descriptor is data | bets on undocumented internal formats; poll-based lag; must guess which open transcript is live |
| Subprocess / PTY wrapper | everything | yes | no | fragile against text-user-interface redraws, alternate-screen switching, and cursor-position queries — which the target agent's own interface uses |
| Terminal injection (clipboard + keystroke) | n/a | yes, badly | no | `TIOCSTI` disabled since macOS 12; four per-emulator strategies; a `sleep(0.15)` race; per-terminal accessibility grants |

### Provider families

| family | privacy | cost | latency class | platform | notes |
|---|---|---|---|---|---|
| Native macOS `say` | on-device | free | batch only — no streaming, no cancel token beyond killing the process | macOS | supports voice selection, rate, and file output; the prior art uses none of them. File output is what makes a duration-sized playback watchdog possible on a zero-credential provider |
| Native macOS speech input | on-device | free | streaming, with an attachable voice-activity module | macOS | `SpeechAnalyzer` + `SpeechTranscriber` (WWDC 2025 session 277) supersedes `SFSpeechRecognizer`; requires launchd as the responsible process or it aborts under an IDE terminal. Entitlement string and on-device-versus-server split unverified |
| Local models | on-device | free after download | Kokoro reported sub-300ms first audio; Piper ~40ms; whisper.cpp with Metal ~10x realtime | any, best on Apple Silicon | hundreds of megabytes resident; two inference runtimes need not share a device-string vocabulary |
| ElevenLabs | leaves the machine | ~$0.05 per 1,000 characters on the low-latency tier (aggregator figure, re-verify) | ~75ms reported | any | famous and library voices return a permission error, so a working key is not a working voice |
| `edge-tts` | leaves the machine | free | streaming | any | **unofficial reverse-engineered client**; Microsoft's own position is that unofficial use violates its terms. Not a peer of Azure Speech; the operator may declare it, the plugin should not ship it as a named adapter |
| Fused speech-to-speech | leaves the machine | metered | lowest, preserves prosody | any | structurally incompatible with selectable provider families — you cannot swap half of one model |

Latency deserves one correction that changes provider choice. Input latency and output latency are not the same quantity, and the prior art conflates them. `claude-interface`'s own latency work is entirely about input, where the operator is genuinely waiting; on the output side the agent has already finished and the operator is free. If the output budget is seconds rather than milliseconds, then `say`, Piper, and Kokoro are not compromises — they are simply sufficient, and the cost and privacy argument changes shape.

### Separation of concerns

Five things are separable and should stay separate: transcription, synthesis, capture and playback devices, agent lifecycle integration, and the provider adapters themselves. The device layer is worth calling out because no prior art does — selecting a Bluetooth headset's microphone drops the link to the mono voice profile and audibly degrades everything else playing on the machine, which is a collateral cost of holding the microphone open that belongs in the provider declaration alongside privacy and latency.

### Configuration shape and precedence

Every source read converged on the same two-layer split, and it is worth adopting: behaviour lives in a configuration file, secrets live in the environment, and the process environment wins over any dotfile. Hermes states it plainly — settings are behavioural, not secrets. Layer resolution should be per-call override, then persisted default, then a stated fallback, with the whole chain printed once at startup naming the provider actually chosen. Nothing should default silently; per `DECISIONS.md:426` the empty case is something a person writes down.

### Interaction modes, assessed

Push-to-talk survives as the default: it is half-duplex done honestly, and the key-down is the unambiguous hand-off signal the medium cannot otherwise supply — the same role "over" plays on a shared radio channel. Continuous listening does not survive (`R1`); every implementation surveyed pays for it with echo suppression that deliberately makes barge-in impossible, and it imposes an audible cost on everything else using the machine's audio. Speak-on-completion survives only in inverted form (survivor 6) — completion is when the operator is least blocked. Selective readback survives as producer-authored text (survivor 3). Interruption and cancel survive as one mechanism — a tracked utterance with a kill switch — with the honest caveat that silencing playback is not the same as stopping the work, and only the first is reachable from a hook.

## Smallest Viable First Version and Credible Extensions

The smallest viable version is survivor 6 with survivors 1, 4, and 5 underneath it: a portable executable and one Claude Code adapter shim that plays a short tone, at highest priority, when a session is blocked on a person — with providers declared rather than discovered, every child process leased and deadlined, and a stated born-portable custody record. It needs no provider installed, no credential, and no microphone, which means it is testable under this repo's actual gates and useful on the day it lands.

Credible extensions, roughly in order: producer-authored spoken lines for completion, once the arbiter exists; the MCP listening tool (survivor 2), which is where the real design risk sits and deserves its own evidence; a pre-rendered phrase catalogue for the high-frequency utterances (`R14`), which makes a premium hosted voice economically viable for the rare long readback; per-utterance interruptibility flags; presence gating on keystroke recency (`R15`), paired with the recall path it needs to be honest; and a repository pronunciation and confusables lexicon (`R16`), which is notable for being the one genuinely portable artifact in an otherwise adapter-dominated plugin.

## Did not survive (revivable)

Explicit rejection is the quality mechanism. Cut ideas keep stable ids so they can be revived, which re-enters the Phase 3 filter with new evidence.

| id | title | summary | reason | status |
|----|-------|---------|--------|--------|
| R1 | Continuous listening as a mode | Keep the microphone open and detect utterance boundaries from audio energy | Not justified by any evidence found; the seed itself asked for justification. Every surveyed implementation buys echo suppression that makes barge-in impossible, all boundary detection is hand-tuned per person and room (one repo ships 1.2s while its own design doc says 0.3s), and holding the microphone degrades other audio on the machine | rejected |
| R2 | Resident voice daemon with socket IPC | A long-lived process owns the models and devices; hooks talk to it over a Unix socket | Too much machinery for a private single-user tool, and its recorded failure mode — stale socket, orphan holding the microphone — is exactly what leases avoid. The brief also assigns live process orchestration to Herdr, not to a plugin. Revive if local-model load latency proves unacceptable under leases | rejected |
| R3 | Subprocess / PTY wrapper | Run the agent as a child and intercept its terminal stream | Fragile against text-user-interface redraws, alternate-screen switching, and cursor-position queries the target agent's own interface uses; the one published example does not document its mechanism | rejected |
| R4 | Terminal injection of transcribed text | Clipboard-plus-keystroke or AppleScript injection into the terminal | Duplicated and beaten by survivor 2, which removes the need entirely. `TIOCSTI` is dead since macOS 12, and the shipped alternative needs four per-emulator paths plus a sleep-based race | rejected |
| R5 | The Stop hook as the plugin's architecture | Make a post-response hook the plugin's primary structure | Hooks are adapter-only by `AGENTS.md:52-53` and unstandardized by Agent Plugins 1.0; a hook cannot inject input and cannot fire during generation. Not cut as a *publisher* — survivor 2 keeps it in exactly that role | revisited |
| R6 | Wake-word always-listening trigger | A spoken phrase activates listening | Depends on R1, which did not survive | rejected |
| R7 | Transcript log-tailing as the primary seam | Watch the agent's own session files and derive turn boundaries | Bets on undocumented internal formats, is poll-based, and must guess which transcript is live. Retained deliberately as the fallback if MCP proves unreachable on enough clients | rejected |
| R8 | Fused speech-to-speech providers | Adopt a single-model speech-to-speech provider for lowest latency | Structurally incompatible with the stated requirement — you cannot swap half of one model. Revive only if selectable provider families stops being a requirement | rejected |
| R9 | Ship `edge-tts` as a named provider adapter | Bundle the Edge Read-Aloud client as a peer provider | Unofficial reverse-engineered client that Microsoft's own position calls a terms-of-service violation; shipping a named adapter is an implied endorsement. The operator may declare it as their own command row under survivor 1 | rejected |
| R10 | Lazy install of missing provider dependencies | Install a provider's package on demand when it is selected | Provider installation is explicitly out of scope; this is the pattern to reject, not adapt | rejected |
| R11 | Per-agent or per-context voice assignment | Different voices for different agents or contexts | The one project that shipped it disavowed it in its own docs as configuration with no consumer in code — the pattern to avoid is shipping unconsumed config | rejected |
| R12 | Emotional presets carried as markers inside spoken text | Embed markers that adjust synthesis parameters | An embedded mini-protocol parsed out of speech, for a marginal payoff, on a design whose whole point is not parsing text it did not author | rejected |
| R13 | Vendor or depend on voice-forge | Consume the existing Infiquetra text-to-speech service as a dependency | Its published package does not exist on the index despite its README; it is text-to-speech only with no listening sibling; and its model-hosting weight is far beyond a single-user tool. Its Protocol shape and three-state discovery are borrowed as ideas in survivor 1 | rejected |
| R14 | Pre-rendered phrase catalogue | Render the small closed set of frequent utterances once per voice to files | Overlaps survivors 3 and 6, which already give the frequent cases a non-speech rendering. Genuinely good as a later extension once the utterance type exists | rejected |
| R15 | Presence gating on keystroke recency | Speak only when the operator has been quiet, on the theory that a present operator is reading | Strong and well-sourced, but overlaps survivor 6's trigger and is only honest with a recall path ("what did I miss") for which no prior art exists. Revive with a proposal for the recall half | rejected |
| R16 | Repository pronunciation and confusables lexicon | One data file for how to say identifiers, what to expect to hear, and which pairs need confirmation | A real and genuinely portable artifact, but an enhancement rather than a founding decision, and its derivation is heuristic. A strong candidate for the first extension after the core lands | rejected |
| R17 | Cost ledger for spoken characters | Meter and display spend per provider | Consumption accounting sits close to the out-of-scope billing boundary and adds machinery a single-user tool does not need; the pre-rendered catalogue captures most of the value | rejected |
| R18 | Interlocking table for turn state | Enumerate conflicting states and make conflicting transitions unsettable, failing to silence | The enumeration discipline is right and is absorbed into survivor 4's rationale, but the mechanism overreaches for a single-user tool and can only constrain this plugin's own transitions, not the operating system's | rejected |
| R19 | Split speaking and listening into two installable packages | Package the two halves separately so microphone access can be declined | Attractive on trust grounds and the natural fracture line, but premature in a repo with no marketplace manifest at all and an unsettled custody story for even one born-portable package. Revive once the first package lands | rejected |
| R20 | Speak-late settling window | Deliberately delay speech to coalesce events and allow silent cancellation | Its central insight — that output latency and input latency are different budgets — is absorbed into the provider-family assessment above, which is where it changes decisions | rejected |
| R21 | Spoken hand-off token replacing voice-activity detection | End a turn with a spoken word rather than a key release | Under push-to-talk the key release already is the hand-off token; this is only needed in the no-hands case, which is not the target. Revive if hands-free becomes a requirement | rejected |
| R22 | Agent-blind seam | Assume the agent cannot be instructed at all and derive everything from its incidental output | Premise contradicted by the available evidence: an Agent Skill is precisely an instruction to the agent and is one of the two portable seams. Directly opposed to survivor 3 | rejected |
| R23 | Cross-session speaker arbiter as a resident service | A machine-wide broker process owning both devices | The arbitration itself survives inside survivor 3; only the resident-service form is cut, superseded by the lease file in survivor 4 | rejected |

**Rejection summary.** Of 68 candidates, 7 survived. The largest cut group was integration seams: five distinct mechanisms (R3, R4, R5, R7, R22, plus R2's daemon form) fell to one rule — `AGENTS.md:52-53` makes every client-runtime mechanism an adapter, so none of them can be the plugin's architecture, though two survive as adapter-local publishers or fallbacks. The second largest group was machinery a single-user tool does not need (R2, R17, R18, R19, R23). A third group was ideas that are genuinely good but are extensions rather than founding decisions (R14, R15, R16, R20) — these are the most likely revival candidates and are listed as such in the extensions section. Three were cut on external facts rather than design judgement (R8 incompatible by construction, R9 terms-of-service, R13 the package does not exist). No axis ended with zero survivors.

## Co-ideation Log

Records partnership provenance: which ideas came from the operator and how each fared under the identical critique. Seeds were passed into all six frame agents to build on, challenge, or combine, and entered the merged pool as peers.

| source | entered | idea / seed | outcome |
|--------|---------|-------------|---------|
| user-seed | Phase 0 | S1 — native macOS/Apple mechanisms, including an assessment of `say` and the native speech-input mechanism | survived, **split in two**, absorbed into #1. `say` and `SpeechAnalyzer` share only a vendor; their declared shapes differ completely. Assessment delivered: `say` supports voice, rate, and file output and the prior art uses none of them; `SpeechAnalyzer`/`SpeechTranscriber` supersedes `SFSpeechRecognizer`; launchd must be the responsible process |
| user-seed | Phase 0 | S2 — locally running STT and TTS models | survived, absorbed into #1 as a declared capability class; the daemon question it raises routed to R2, answered by the lease in #4 |
| user-seed | Phase 0 | S3 — already-configured external services such as ElevenLabs and Microsoft Edge voices | survived in part; ElevenLabs absorbed into #1, `edge-tts` split off and cut to R9 on its terms-of-service status |
| user-seed | Phase 0 | S4 — other compatible providers supported by evidence | survived, absorbed into #1 — declaration is what makes "other providers" an open set rather than a roadmap of adapters |
| user-seed | Phase 0 | S5 — client hooks, especially post-response or post-tool | **challenged and demoted**, R5, status `revisited`. Hooks are adapter-only by repo rule, cannot inject input, and cannot fire during generation. They survive as one thin publisher inside survivor 2, not as the architecture. The seam comparison the seed asked for is in the Tradeoffs table |
| user-seed | Phase 0 | S6 — push-to-talk; continuous listening only if justified; speak-on-completion; selective readback; interruption and cancel | **split five ways.** Push-to-talk survived as the default (#4, #7). Continuous listening cut to R1 — no justification survived. Speak-on-completion survived only inverted (#6). Selective readback survived as producer-authored text (#3). Interruption and cancel survived as one leased, tracked mechanism (#4) with a stated limit on what it can reach |
| frame-agent | Phase 2 | Providers declare capabilities and egress; never silently substitute | survived as #1 (strongest basis in the run — three of the repo's own journal rules) |
| frame-agent | Phase 2 | Split the seam by direction | survived as #2 |
| combined | Phase 2 | Utterance type + priority arbiter + zero-provider tone floor | survived as #3 |
| combined | Phase 2 | Lease discipline for microphone, playback, and warm process | survived as #4 |
| combined | Phase 2 | One executable, shim adapters, stated born-portable origin | survived as #5 |
| frame-agent | Phase 2 | Forbidden to be silent when the agent is blocked on a human | survived as #6 |
| frame-agent | Phase 2 | Voice cannot approve anything | survived as #7 |
| frame-agent | Phase 2 | 55 further candidates across six frames | cut → R1–R23 and the rejection summary |

Note on provenance: no external-engine generator lane ran. The operator declined the external-engine offer in Phase 0, so all generation was in-process Claude frame agents plus the operator's seeds. This is recorded as a non-blocking note, not a partial failure.

## Open Operator Decisions

1. **Is the MCP listening tool worth being the catalog's first MCP server?** Survivor 2 depends on it, the architecture brief wants an MCP-bearing proof case, and nothing here has paid that cost yet. If the answer is no, the input half falls back to R7 (transcript tailing) or is deferred entirely, and version one is survivor 6 alone.
2. **Does a born-portable package get a `ports/` descriptor?** The docs leave it open, and `voice` is the first package to hit the gap. Whatever it does becomes precedent for every future born-portable package.
3. **Which Python authority governs?** The context library requires `>=3.13`, `uv`, and `pytest` with an 80% coverage floor; this repo pins `>=3.12` and validates with `unittest`. A plugin cannot satisfy both silently.
4. **What is the microphone policy, given that no org standard exists?** The context library documents nothing on microphone access, recording retention, or telemetry. The plugin either states its own position or ships with none. This is also a candidate to promote back into `infiquetra-context-library` as the org's first sensitive-local-device standard.
5. **Is an unenforced instruction good enough for producer-authored speech?** The enforcement mechanism in the prior art is a hook, which is adapter-only here, so the policy is portable and the enforcement is not.
6. **How much does the client matrix have to cover?** `QUEUED.md:73` deliberately leaves the per-client decision open, and a new plugin either inherits that openness or forces the decision.

Two factual gaps should be closed before any of this becomes a plan: the exact macOS privacy entitlement and the on-device-versus-server split for `SpeechAnalyzer` were not verified from Apple's own reference text, and the ElevenLabs and local-model latency and pricing figures above come from aggregators rather than vendor pages.

## Recommended Next Step

Take survivor 1 — providers declare, the plugin never guesses and never substitutes — into `/brainstorm`. It has the strongest basis in the run, it is the interface decision that is hardest to change later, and survivors 2 through 6 all consume it. It is also the one survivor that can be specified without first settling the MCP question in open decision 1.
