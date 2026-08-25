---
title: Voice plugin version-one build run plan
type: feat
status: active
date: 2026-08-25
origin: docs/brainstorms/2026-08-25-voice-plugin-requirements.md
backend: inline
---

# Voice plugin version-one build run plan

## Summary

One run-wide implementation plan for parent contract infiquetra/infiquetra-agent-plugins#27:
build the portable Agent Plugins package `voice` — a spoken conversational loop for one
explicitly bound, Herdr-managed Claude Code session — as seven executable units (U1–U7,
issues #28–#34) across the contract's four-lane dependency graph. The plan honors the
contract's unit boundaries, owned file surfaces, shared-file collision rules, and
exact-once ownership of requirements R1–R33 without redesign; its job is to close the
HOW decisions the requirements deferred to planning so each worker session can build its
unit from this document alone.

Base commit for the run: `dd10d9b` on `origin/main` (verified equal to `origin/main` at
planning time). Backend is **inline** for every unit; the run is externally orchestrated
per the parent contract's per-run vendor table.

## Problem Frame

Voice behaviour across the operator's coding-agent environment is fragmented and
client-specific; no common contract governs provider selection, egress posture, privacy,
or approval safety ([requirements doc](../brainstorms/2026-08-25-voice-plugin-requirements.md),
Problem Frame). The product requirement, which no unit may narrow: a single explicitly
bound Claude session speaks its completed response (from the `Stop` hook's
`last_assistant_message`, after Markdown cleanup, fenced code-block contents omitted);
the operator toggles recording in the Voice pane, speaks, toggles again; a hosted
speech-to-text provider transcribes; and the text returns to that same session's input
box, unsubmitted and editable. This is a two-way conversational loop — explicitly not an
alert-only product, and blocked-session alerting must never be substituted for it.

## Execution contract carried forward (fixed, not revisited)

These are the parent contract's rulings. The plan implements them; it does not reopen them.

**Scope authorities.** Issue #27 and the seven child issues #28–#34 govern scope. The
requirements are [docs/brainstorms/2026-08-25-voice-plugin-requirements.md](../brainstorms/2026-08-25-voice-plugin-requirements.md)
(R1–R33, AE1–AE8). Evidence/provenance only, never scope:
[docs/ideation/2026-08-25-voice-plugin-ideation.md](../ideation/2026-08-25-voice-plugin-ideation.md),
[the accepted doc review](../reviews/2026-08-25-voice-plugin-requirements-doc-review.md)
(READY, no P0/P1), and
[the post-integration freshness review](../reviews/2026-08-25-voice-plugin-requirements-post-integration-freshness-review.md)
(READY, no P0/P1).

**Lane graph.** G1: U1. G2: U2, U3, U4 (each depends on U1; maximum true concurrency is
three). G3: U5 (depends on U1, U2, U3, U4 — U3 because R18's refusal is audible), U6
(depends on U1, U2, U3, U4). G4: U7 (depends on U1–U6). No concurrency is manufactured
to fill the worker cap.

**Providers are resolved (D1, D2) — do not reopen.** Text-to-speech is Voice Forge on
the Mac mini over the local network: `POST {VOICE_FORGE_BASE_URL}/v1/audio/speech`
(OpenAI-compatible shape), voice selected by `VOICE_FORGE_VOICE_ID`, egress class
`local-network`, no hard-coded IP address. Speech-to-text is xAI Grok through the local
Hermes relay: `POST {VOICE_HERMES_BASE_URL}/api/audio/transcribe?profile={VOICE_HERMES_PROFILE}`
(acceptance values `http://127.0.0.1:8765` and `mimir-engineer`), authenticated by the
in-memory loopback `X-Hermes-Session-Token` read from the dashboard root page, with
exactly one token refresh and one retry on 401 — never a loop. `voice` never reads
`auth.json`, never copies the xAI OAuth bearer, never persists or logs the session
token, never imports Hermes code, and never disables Hermes authentication. Effective
audio egress for the speech-to-text route leaves the machine and is stated as external
(KTD4 maps this onto R21's closed set).

**Other settled operator decisions.** D3: capture via `/opt/homebrew/bin/ffmpeg` with
the macOS AVFoundation input device; microphone permission is proven at preflight (P6).
D4: the operator adds the documented Herdr-wide `voice stop` keybinding; `voice` only
preflights its presence (R14) and never writes Herdr configuration (R15). D5: retention
is ephemeral — audio deleted after success and failure, no transcript log, no telemetry.

**Preflight gates P1–P9** are run fresh by the coordinator immediately before dispatch;
planning does not rely on any of them beyond what it independently verified (see
Grounded facts). A failed or unexplained proof stops the run. **The preflight P2 finding
binds U2's design:** Claude Code runs `Stop` hooks synchronously — a blocking 8-second
hook was measured delaying turn settle by 8.19 s, while a detaching hook returned in
0.030 s. R1's non-stalling guarantee is therefore an implementation constraint on the
hook itself: it must detach its work and return immediately (KTD2).

**Review consensus.** Exactly one Saga Code Review session owns each frozen work-unit
revision; the reviewed commit is named in the durable typed result. Every applicable
declared lens must score at least 9 with no lens below 7; scores are never averaged;
findings are validated before repair; maximum three cycles, then best-result-with-
disclosed-shortfall. The applicable lenses per unit are predeclared in this plan (see
Review lenses per unit); lenses are never invented at review time.

**Board ownership.** The coordinator is the sole Operations-board writer. Workers,
reviewers, and this planning session write no board state.

**Stop conditions** (verbatim classes from #27): a needed CI edit; a needed credential,
billing decision, or paid endpoint; P8/P9 failure (never substitute a provider); a
proposed Herdr-configuration write; non-interactive microphone permission failure;
review below threshold after three cycles; any destructive action; source-pin drift;
two units contending for one owned surface.

**Proportionality.** `voice` is a private, single-user developer plugin. Every unit
prefers the smallest compatible implementation — no enterprise, multi-tenant,
internet-scale, high-availability, regulatory, or over-defensive machinery — while
credential, shell, filesystem, Git, privacy/retention, destructive-action, and
production boundaries keep full strength. Standard-library Python at the repository
floor `python>=3.12`, tested with `unittest` (R31); `urllib.request` for HTTP — no
`requests`, no `httpx`.

## Grounded facts this plan relies on (verified 2026-08-25 in this repository and on this host)

- `scripts/check_repo.py` requires every `plugins/*/plugin.json` to carry
  `$schema: https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` plus non-empty
  `name`, `version`, `description` (`scripts/check_repo.py:53-63,311-336`). A missing
  `PROVENANCE.json` is explicitly not an error for a package authored here
  (`scripts/check_repo.py:501-507`) — R30's posture is validated, not merely tolerated.
- Portable skill documents are validated: `plugins/*/skills/<dir>/SKILL.md` frontmatter
  may use only `name`, `description`, `license`, `compatibility`, `metadata`,
  `allowed-tools`, and `name` must equal the skill directory name
  (`scripts/check_repo.py:121-131,792-831`).
- A credential-value scan covers every text file under `plugins/`
  (`scripts/check_repo.py:895-927`); fixtures must use inert values per
  [docs/public-safe-summary.md](../public-safe-summary.md).
- CI already collects new package tests: `.github/workflows/ci.yml` runs
  `python -m pytest plugins/*/tests -q` on Python 3.12. No CI edit is needed or
  permitted. The hermetic job runs `check_repo.py`, `unittest discover -s tests`, and
  `git diff --check`.
- The floor token is policed repo-wide: any floor a document states must read exactly
  `python>=3.12` (`tests/test_python_floor.py`); the declaration-site list is closed and
  does not include the new package, so `plugins/voice/README.md` may state the floor but
  must state it exactly.
- The installed Herdr CLI exposes `herdr agent get` (agent → fields including `pane_id`
  and `agent_status`), `herdr pane send-text` ("Send literal text to a pane"), and
  `herdr pane run` (text plus Enter — forbidden for delivery). `herdr agent wait --help`
  names the closed agent-state set: `idle`, `working`, `blocked`, `done`, `unknown`.
- The session-id join is live: `herdr agent list` shows each Claude pane's
  `agent_session.value` equal to that session's Claude `session_id` (observed for this
  planning session itself). Each listed agent carries `agent_status` and `pane_id`.
  Preflight P3 re-proves the join before dispatch.
- Herdr custom keybindings live at `~/.config/herdr/config.toml` on this host
  (`[[keys.command]]` entries). KTD13 probes that path read-only; tests inject it.
- The live Hermes relay at `http://127.0.0.1:8765/api/health` reports version `0.20.4`
  with `auth_required: false`. `POST /api/audio/transcribe` accepts JSON field
  `data_url` (a `data:` base64 URL) and returns `transcript` and `provider`. That is a
  wire contract, not a licence to import Hermes code.
- The Claude plugin hook descriptor shape is confirmed against the installed
  `openai-codex/codex` plugin: `hooks/hooks.json` top-level `hooks.Stop[].hooks[]`
  entries of `{"type": "command", "command": "node \"${CLAUDE_PLUGIN_ROOT}/…\"", "timeout": N}`
  — interpreter-prefixed. Voice uses `python3` in the same shape (KTD2). Preflight P1
  re-confirms the `Stop` payload fields.
- Only `plugins/mission-control/tests/` exists among plugin test trees today, and it
  claims the top-level `tests` package name inside the shared pytest process
  (`plugins/mission-control/tests/__init__.py`). KTD12 keeps `voice` out of that
  namespace.
- The engineering-journal entries the requirements carry forward exist:
  subprocess stdin/deadline discipline (LEARNINGS, "A harness that inherits stdin
  behaves differently in a terminal than under a scheduler"), absent-never-means-empty
  (LEARNINGS, "An optional safety setting is a safety setting that is off"; DECISIONS,
  "The port descriptor is closed, and its safety fields are stated rather than
  defaulted"), and operator-supplied executables (DECISIONS, "A client's real executable
  is supplied by the operator, never discovered").

## Requirements and exact-once ownership

The 33 requirements live in the requirements document and are not restated here; the
run-wide contract is that each is implemented, reviewed, merged, and evidenced exactly
once, by exactly one unit. This mapping is the contract's, verified complete and
non-overlapping (9+3+3+5+4+8+1 = 33):

| Unit | Child | Requirements owned |
| --- | --- | --- |
| U1 | #28 | R20, R21, R23, R24, R28, R29, R30, R31, R32 |
| U2 | #29 | R1, R2, R3 |
| U3 | #30 | R5, R6, R7 |
| U4 | #31 | R10, R12, R25, R26, R27 |
| U5 | #32 | R16, R17, R18, R19 |
| U6 | #33 | R4, R8, R9, R11, R13, R14, R15, R22 |
| U7 | #34 | R33 |

Acceptance examples AE1–AE8 are recorded with observed results by U7. A unit that
believes it must edit another unit's surface stops and raises the conflict on #27
rather than editing across the boundary.

## Key Technical Decisions

These close the questions the requirements explicitly deferred to planning (state home,
pane/hook sharing, provider-declaration shape and storage, delivery escaping, pane
key presentation) plus the design forks the child issues leave open. Each is a
decision with rationale; workers do not re-litigate them. Operator decisions D1 and
D2 are carried, not reopened.

**KTD1 — State home and the pane↔hook seam: one machine-local state directory, shared
through small JSON files, no daemon.** Runtime state lives in a single directory,
default `~/.local/state/voice/`, overridable with `VOICE_STATE_DIR` (tests point it at
a temp dir). Contents: `binding.json` (the sticky binding), `recording.json` (active
recorder pid + wav path while recording), `playback.json` (active playback pid + audio
path while speaking), `refused-transcript.txt` (the R19 transient hold — a single
current file, consumed or discarded, never appended, so it is not a transcript log under
R26), and unique `speak-<uuid>.json` payload files (the KTD2 hook→speak handoff —
`{"text": "<last_assistant_message>"}`, one file per spawn, never reused, deleted by
the speak child on every exit path). The `Stop` hook and the Voice pane share state only
through these files. Writes are write-temp-then-`os.replace` (atomic on one filesystem,
stdlib). Rationale: the non-goals exclude any resident daemon or background listener, a
single operator makes file-granularity coordination sufficient, and `~/.local/state`
survives reboots, which sticky binding (R2) requires. Rejected: repo-relative state
(wrong scope — worktrees multiply it), `/tmp` (cleaned by the OS; binding must persist),
sockets/daemons (machinery without a requirement), passing the response text on the
child's stdin (KTD2 closes stdin; R32 forbids inheriting it), or passing it as an argv
element (long replies must not meet `ARG_MAX`).

**KTD2 — The Stop hook detaches; the harness timeout is a backstop, not a budget.**
Preflight P2's measurement makes this binding: `Stop` hooks run synchronously.
`stop_hook.py` therefore does exactly four things: read the hook payload from stdin
once; compare `session_id` against `binding.json` (a local file read — no subprocess on
this path); only when bound, write `last_assistant_message` to a unique
`speak-<uuid>.json` under the state dir; and spawn U3's `speak.py` as a fully detached
argv child, then exit 0 immediately. The spawn is
`[sys.executable, speak_path, payload_path]` with `start_new_session=True`, stdin
explicitly closed, stdout/stderr to devnull, via U1's process helper.
`speak_path` is resolved from the hook file as
`Path(__file__).resolve().parents[2] / "scripts" / "speak.py"` (the portable package
root, not the Claude extension root). The hook does **not** import `speak`, does **not**
clean Markdown, and does **not** call Voice Forge — those are U3, concurrent in G2.
`hooks/hooks.json` declares the `Stop` entry as
`{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/stop_hook.py\"","timeout":5}`
— interpreter-prefixed like the verified `openai-codex/codex` `Stop` hook, 5-second
timeout as a harness-side backstop; the hook's own return is ~30 ms. Unbound,
mismatched, absent, or unparseable binding, or empty `last_assistant_message` → exit 0
with no spawn, no payload file, and no sound (R3). The hook never blocks on, waits for,
or reads back from the child.

**KTD3 — R32 deadlines without R5 length gates: deadlines derive from the medium, never
from the text.** Every subprocess gets stdin explicitly closed and a deadline (R32), but
no deadline may act as a response-length gate (R5). Policy by class, with the numbers
pinned so workers do not invent them: (a) bounded helper calls (`herdr agent get`,
`herdr pane send-text`) get a **10-second** timeout; (b) playback's deadline is the
synthesized audio's actual duration (wav header via the stdlib `wave` module) plus a
**2-second** margin — long replies get long deadlines, so nothing is truncated; (c) the
capture recorder is spawned with `ffmpeg -t 600` (10 minutes) as both the media ceiling
and the subprocess deadline; ceiling expiry ends capture, **deletes the wav**, and never
auto-transcribes — transcription still happens only on the operator's explicit stop
press (R12); (d) the detached speak child (KTD2) cannot be waited on by its parent, so it
carries its deadlines internally: Voice Forge HTTP uses a **10-second connect** timeout
and a **300-second read** timeout (generous, not scaled from character count — a timeout
is a named refusal, never truncation or a shortened utterance) plus the duration-derived
playback deadline. A hang is a named refusal; a long reply that finishes synthesizing
inside 300 seconds is spoken whole.

**KTD4 — Egress classes: R21's closed set is the enum; "external" is a derived
predicate, not a fifth value.** `providers.py` defines the egress class as exactly the
four R21 literals: `on-device`, `local-network`, `named-remote-service`,
`unofficial-remote-endpoint`; an unknown class is rejected. The Voice Forge declaration
is `local-network`. The Hermes speech-to-text route is declared
`named-remote-service` — the named service is xAI; Hermes is loopback transport, and a
loopback address never downgrades the class. The contract's "effective audio egress:
external" is honored as a predicate on the closed set (`named-remote-service` and
`unofficial-remote-endpoint` are external; the other two are not), which is exactly the
distinction R21 requires Voice to draw. This wording matters: writing `external` as an
enum value would break the closed set and U1's acceptance grep.

**KTD5 — Provider declarations are built in code from stated settings; no provider
config file in version one.** `providers.py` constructs exactly two declaration records
— `voice-forge` (text-to-speech) and `hermes-xai` (speech-to-text) — each carrying
invocation-or-endpoint (from settings), capabilities, egress class, and the *name* of
any credential environment variable, never a value (R20). Both credential-name fields
are **empty, and the contract type permits empty**: neither provider needs a credential
variable — Hermes owns the xAI OAuth token, and the loopback session token is a
transport detail (U4), not a declared credential. An unavailable provider raises a named
refusal (provider name + missing prerequisite); nothing substitutes (R23). Rationale for
no config file: both providers are settled operator decisions (D1, D2) and the
behaviour-in-config convention buys nothing until a third provider exists; the smallest
declaration surface is the stated settings plus in-code records. Rejected: a
`providers.toml`/JSON registry (revisit when a provider beyond D1/D2 is actually
declared).

**KTD6 — The settings surface: stated names, split defaults, absent never means
empty.** `settings.py` (U1) is the one settings reader. It resolves, from the
environment: `VOICE_FORGE_BASE_URL` and `VOICE_FORGE_VOICE_ID` — **no default**; absent
produces a named refusal at preflight/use (the base URL comes from the Home Lab
deployment receipt; baking a default would hard-code a deployment, and no IP address is
ever hard-coded); `VOICE_HERMES_BASE_URL` (documented default `http://127.0.0.1:8765`)
and `VOICE_HERMES_PROFILE` (documented default `mimir-engineer`) — the acceptance
values; `VOICE_CAPTURE_BIN` (documented default `/opt/homebrew/bin/ffmpeg`, per D3) and
`VOICE_PLAYBACK_BIN` (documented default `/usr/bin/afplay`) — executables are
operator-supplied settings, never discovered (journal decision carried forward);
`VOICE_STATE_DIR` (KTD1); and `VOICE_RETENTION`, whose only accepted value in version
one is `ephemeral` — the smallest clear setting name for D5, written down rather than
defaulted silently (R28); any other value is refused by name rather than honored.
All values are non-secret; no setting may carry a credential. An unset setting is
distinguished from an empty one, and empty is never silently treated as a value
(absent-never-means-empty, carried from the journal).

**KTD7 — The single-speaker join: bind-time resolution, local comparison on the hot
path.** `voice_cli bind <agent>` (U6) resolves the chosen Herdr agent once via
`herdr agent get` and writes `binding.json`: the Herdr agent name, its
`agent_session.value` (the Claude session id), its `pane_id`, and a bound-at timestamp.
The binding is single-valued and sticky: it changes only on an explicit re-bind (R2) —
nothing infers a target from focus or recency. The hook (U2) compares its own payload
`session_id` against the stored value with a pure local file read — no `herdr` call on
the hot path, so every session's turn settle stays unaffected. Delivery (U5) re-resolves
`pane_id` and state through `herdr agent get` at send time. A stale binding (bound
session restarted, new session id) yields silence until re-bound; the pane displays the
bound identity continuously (R4), which makes staleness visible rather than surprising.

**KTD8 — Voice Forge synthesis: request wav, play through the stated player, delete
after playback.** `speak.py` (U3) POSTs the OpenAI-compatible JSON body — `input` text,
`voice` = `VOICE_FORGE_VOICE_ID`, `response_format` = `wav` — to
`{VOICE_FORGE_BASE_URL}/v1/audio/speech` with `urllib.request`, writes the response
bytes to a temp file under the state dir, plays it with `VOICE_PLAYBACK_BIN` through
U1's process helper (deadline per KTD3b), records `playback.json` so U6's stop key and
barge-in can terminate the player process immediately (R8/R9 support), and deletes the
audio file after playback ends, is stopped, or fails (D5's ephemeral posture covers
synthesized audio as well as recorded audio). wav is chosen so the stdlib `wave` module
can read the real duration for the deadline. Unreachable/unhealthy Voice Forge or a
non-2xx response → named refusal, never substitution (R23). `speak.py` exposes two
importable entry points: `speak(text)` (used by the `__main__` child and by U5's audible
refusal with a short fixed refusal phrase) and `stop_playback()` (used by U6 and by
`speak()` itself so a new utterance replaces any still-playing one). It is also a
runnable child: `python3 speak.py <payload.json>` reads KTD1's `{"text": "..."}`,
deletes that payload file in a `finally` (malformed payload synthesizes nothing),
cleans the text (KTD10), then calls `speak()`. A response whose cleaned text is empty
(for example, a reply that was only a fenced code block) synthesizes nothing and exits
silently — that is R7's omission, not a failure.

**KTD9 — Hermes transcription: data-URL body, in-memory token, one refresh, one
retry.** `transcribe.py` (U4) obtains the session token by GETting
`{VOICE_HERMES_BASE_URL}/` and extracting `window.__HERMES_SESSION_TOKEN__` from the
served page; holds it in process memory only; POSTs JSON
`{"data_url": "data:audio/wav;base64,<...>"}` to
`/api/audio/transcribe?profile={VOICE_HERMES_PROFILE}` with the
`X-Hermes-Session-Token` header, built on `urllib.request`. The field name is `data_url`
— that is the live relay's `AudioTranscriptionRequest` (verified 2026-08-25 against the
acceptance relay at `http://127.0.0.1:8765`, health version `0.20.4`); do not invent
`audio`, `file`, or `content`. `mime_type` is omitted: the data-URL header already
carries `audio/wav`. On 401 it refreshes the token from the root page once and retries
once; a second 401 fails by name — never a loop. The response fields `transcript` and
`provider` are consumed (`ok` is ignored); the response `provider` is the authoritative
resolution, and a provider other than the profile's expected `xai` is a named refusal,
not a silent substitution (R23). The token never appears in command arguments, on disk,
in logs, or in evidence. `auth_required: false` on `/api/health` is never read as
anonymous access to protected routes. This unit does not import Hermes code; the field
name is a wire contract, not a Python dependency.

**KTD10 — Markdown cleanup: strip formatting, omit fenced contents, parse nothing
fancy.** `text_cleanup.py` (U3) removes fenced code blocks (backtick and tilde fences)
contents-and-fences first (R7), then strips formatting syntax so it is not spoken (R6):
heading markers, emphasis/strong markers, list and blockquote markers, horizontal
rules, link syntax (keep the link text, drop the URL), inline-code backticks (keep the
span text), and table pipes. No length gate, ceiling, truncation, sentence parsing, or
summarisation exists anywhere in the path (R5) — a long input comes back whole. This is
a small line/regex pass, not a Markdown parser; fidelity beyond the tested classes is
explicitly not a version-one goal.

**KTD11 — Delivery: resolve, check, normalize, send-text; the blocked check refuses
audibly; the race residual is preserved, not patched.** `deliver.py` (U5) exposes three
module-level entry points: `deliver(text)`, `use_refused()`, and `discard_refused()`.
`deliver(text)` resolves the bound agent through `herdr agent get` (pane_id +
`agent_status` from the closed state set `idle|working|blocked|done|unknown`, 10-second
deadline). If `agent_status` is `blocked`, nothing is sent: the refusal is spoken
through U3's `speak()` entry point, and the transcript is retained transiently in
`refused-transcript.txt` until the operator explicitly uses or discards it — never
auto-delivered, never queued (R18, R19). Otherwise the transcript is
whitespace-normalized to a single line (speech has no meaningful line structure, and
this removes any chance a raw newline reaches the terminal as Enter — the escaping
question the requirements deferred to planning) and delivered with
`herdr pane send-text <pane_id> <text>` as an argv list, no shell — literal text,
without Enter, unsubmitted and editable (R16). `use_refused()` reads and deletes the
hold file then calls `deliver` on that text; `discard_refused()` deletes it. `herdr pane
run` is never invoked. Only the bound agent is ever targeted (R17); an unresolvable
bound agent is a named error in the pane, not a fallback to another target. The
check-then-send race is the contract's stated residual: narrowed, deliberately not
closed here — the guard belongs to Herdr as a proposed enhancement, and no workaround
machinery is built. U6 may call these entry points only through an injectable lazy
import (KTD16); it must not copy send-text into `pane.py`.

**KTD12 — Test seams and CI hermeticity: fakes everywhere, no `__init__.py`, unique
names.** CI's plugin-test job runs on `ubuntu-latest`, which has no `afplay`, no
AVFoundation `ffmpeg` device, no Herdr, and no live providers — so no unit test may
touch the network, spawn a real platform binary, or shell out to `herdr`. Every seam is
injectable: HTTP through a small opener seam in each HTTP-using module, subprocesses
through U1's `process.py` runner seam, clocks/paths through `VOICE_STATE_DIR`. Tests are
`unittest.TestCase` classes (R31), standard library only, runnable standalone and
collected by CI's `python -m pytest plugins/*/tests -q`. `plugins/voice/tests/` ships
**no `__init__.py`**: `plugins/mission-control/tests/` already claims the top-level
`tests` package inside the shared pytest process, and a second `tests` package would
shadow it; without `__init__.py` each voice test imports as a top-level module, and the
thirteen test basenames are verified unique across every collected plugin test tree
today. Each test file inserts `plugins/voice/scripts` on `sys.path` itself (the
mission-control convention); the script module names (`providers`, `settings`,
`process`, `binding`, `text_cleanup`, `speak`, `record`, `transcribe`, `deliver`,
`pane`, `preflight`, `voice_cli`) collide with no module another plugin's tests import
today. Real-world behaviour is proven by preflight gates P1–P9 and U7's manual
acceptance (R33), not by unit tests. Test fixture values are inert (no
credential-shaped literals — the repo gate scans every text file under `plugins/`).

**KTD13 — R14 keybinding preflight is a read-only probe of Herdr's `config.toml`.**
Herdr keeps custom keybindings in its `config.toml` (per the CLI's own
`config reset-keys` help). Version-one probe path is `~/.config/herdr/config.toml`
(XDG; verified present on this host 2026-08-25, with custom bindings as
`[[keys.command]]` entries). `preflight.py` reads that path read-only — tests inject
the path — and reports whether any binding's command string contains `voice stop`,
reporting absence by name (R14) and never writing any Herdr configuration (R15). The
voice README documents a `[[keys.command]]` stanza whose command string contains
`voice stop`; the operator chooses the key (D4). Preflight does not require a specific
`type` field. If the file is absent or unreadable, preflight reports that state; it
never creates or repairs it.

**KTD14 — Package identity: manifest per repository rule; no provenance, no port
descriptor, no changelog.** `plugins/voice/plugin.json` carries the Agent Plugins
`$schema`, `name: voice`, an initial `version` `0.1.0`, and a real description
(repository rule; validated by `check_repo.py`). The package ships no `PROVENANCE.json`
and no `ports/` descriptor — it is authored here with no upstream to pin — and the
README states that plainly (R30; `check_repo.py` treats the absent manifest as valid by
design). No `CHANGELOG.md` in version one: no repository gate requires one, git history
carries the record, and the run's file surfaces are closed; revisit on first external
release. The Claude client extension carries its own `plugin.json` at
`plugins/voice/com.infiquetra.claude/plugin.json` in the same shape as the unifi and
mission-control client extensions; `plugins/voice/adapters/**` must never exist.

**KTD15 — Preflight's end-to-end speech-to-text sample is synthesized, not bundled and
not recorded.** U6's runtime preflight (R22) proves the transcription path with a short
real audio sample. Rather than committing a binary fixture or coupling the probe to
microphone capture, preflight synthesizes a short fixed phrase through the already-
probed Voice Forge path and submits that audio to the Hermes relay, expecting a
non-empty transcript and `provider` = `xai`. If synthesis is unavailable, the sample
check is reported by name as not-run (the token, profile, and health probes still run) —
degradation is named, never silent. Rejected: a committed wav asset (binary in a
text-audited package, and a second copy of a phrase the loop can produce for free);
recording a fresh sample (couples the speech-to-text probe to P6's microphone grant).

**KTD16 — The Voice pane is the listen-path sequencer; same-lane units never import
each other at module level.** The requirements deferred pane presentation to planning;
this closes it. U6's pane is the only long-running process, so it sequences the listen
path without owning it: on `t` while idle it calls U3 `stop_playback()` then U4
`record.toggle()` (R9 then R10); on `t` while recording, `record.toggle()` returns the
wav path and the pane then calls U4 `transcribe.transcribe(path)` and U5 `deliver(text)`.
U4 never imports U5; U6 never implements send-text or HTTP. Because U5 and U6 dispatch
concurrently, `pane.py` and `voice_cli.py` import `deliver` only inside the key/command
handler through an injectable seam (default: function-level import); tests fake the
seam so U6 can land before `deliver.py` exists. The same lazy-import rule applies to
`use_refused` / `discard_refused`. Keys, processed immediately without waiting for Enter
via stdlib `tty.setcbreak`/`termios` on the pane's stdin (no `curses`, no third-party
TUI, no `input()`): `t` toggle recording, `s` stop playback, `u` use refused transcript,
`d` discard refused transcript, `q` quit the pane. While recording, the pane displays
the literal `*** RECORDING ***` (R11; tests look for `RECORDING`) next to the bound
Herdr agent name and session id from `binding.json` (R4). This does not add a G3
dependency and does not reopen the parent graph.

## Worker bindings and backend

Backend is **inline** for every unit — operator-decided for this run, recorded in this
plan's frontmatter, and never a workflow backend. The run is orchestrated externally per
#27's per-run table; vendor, model, effort, account, and concurrency are per-run
operator decisions, not plan decisions, and launch templates are validated by preflight
P7 before any dispatch.

| Role | Binding (from #27) | Cap |
| --- | --- | --- |
| Implementation units, pool 1 (priority 1) | Qwen `qwen3.8-max-preview`, xhigh, ModelStudio token plan | 4 |
| Implementation units, pool 2 (fallback) | Antigravity `gemini-3.7-flash-high` (effort in model id) | 4 |
| Saga Code Review (every unit) | Grok `grok-4.6`, xhigh, grok.com login | 6 |
| Saga Document Review of this plan | Grok `grok-4.6`, xhigh | 1 |

Pool selection is deterministic — highest-priority pool with free capacity; never
manufacture concurrency to fill a cap. If pool 2 never runs, closeout discloses it as
configured capacity, not validated capability. Herdr workspaces are run-specific
(`voice-run`, `voice-run-2`, …), fixed at preflight.

## Review lenses per unit (predeclared)

Lens identifiers are from the Saga Code Review roster. The four always-on lenses —
`architecture-maintainability`, `correctness`, `security`, `testing` — apply to every
unit and are not repeated in the table. Conditional lenses are declared here, once, with
the reason each applies; no lens is invented at review time. `previous-comments` joins
automatically on any review cycle after the first when unresolved threads exist (its
roster trigger), and is not listed per unit. `deployment-infrastructure` and
`performance` are declared not applicable run-wide: CI is untouched by hard rule, nothing
deploys, and no requirement states a latency or throughput target.

| Unit | Conditional lenses | One-line reason each |
| --- | --- | --- |
| U1 | `api-contract`; `reliability`; `privacy`; `documentation-clarity` | The declaration/settings contract is consumed by every other unit; the subprocess helper is failure-handling machinery (deadlines, closed stdin); the stated retention posture (R28/D5) lives here; the README R30 statement is a required operator-facing truth. |
| U2 | `reliability`; `api-contract` | Asynchronous detachment under the synchronous-Stop-hook constraint is the unit's load-bearing behaviour; the hooks.json descriptor and the binding-store interface are contracts U5/U6 consume. |
| U3 | `api-contract`; `reliability` | The Voice Forge HTTP contract plus the speak/stop entry points U5 and U6 call; named refusals, the stop handle, and duration-derived deadlines are failure-path behaviour. |
| U4 | `privacy`; `reliability`; `api-contract` | External audio egress, ephemeral retention, no transcript log, and no telemetry are this unit's core requirements; the single 401 refresh-and-retry and capture ceiling are failure-path behaviour; the Hermes request/response and token header are a consumed contract. |
| U5 | `adversarial`; `api-contract`; `reliability` | R18 is a policy gate against speech-as-approval with a stated race residual that invites adversarial probing; the Herdr CLI contract (send-text, never run) is load-bearing; refusal and transient-retention semantics are failure-path behaviour. |
| U6 | `agent-usability`; `accessibility-human-usability`; `api-contract`; `documentation-clarity` | The Agent Skill is a capability an agent must discover and operate; the pane is the human-operated surface (R4 identity, R11 loud indicator, stop keys); the CLI plus both provider probe contracts are interface surfaces; SKILL.md and preflight reports are operator guidance. |
| U7 | `documentation-clarity` | The unit's entire output is documentation: acceptance evidence, README verification, and journal entries. |

Consensus per #27: every applicable lens ≥ 9, none below 7, never averaged, at most
three cycles.

## Implementation Units

Each unit runs in its own worktree branched from the then-current `origin/main`, lands
as its own pull request, and receives exactly one Saga Code Review at a frozen clean
head. `Backend: inline` on every unit. Owned paths are exhaustive: a unit writes only
its owned paths, and raising a cross-boundary conflict on #27 beats editing. Every unit
verifies with the same four commands from the repository root before freeze:
`python3 scripts/check_repo.py` · `python3 -m unittest discover -s tests` ·
`python3 -m pytest plugins/voice/tests -q` · `git diff --check`.

**Patterns to follow (every unit).** Portable package layout from `plugins/unifi/` and
`plugins/mission-control/` (vendor-neutral `scripts/` + `skills/`, Claude files only
under `com.infiquetra.claude/`). Tests copy `plugins/mission-control/tests/`:
`sys.path.insert` of `../scripts`, `unittest.TestCase`, no `import pytest` in voice
tests (R31; CI still collects with pytest). Same-lane collaboration follows KTD2 and
KTD16: argv and injectable lazy imports, never an import of a file the other G2/G3
unit has not yet landed.

### U1. Package foundation, provider declaration contract, and subprocess discipline

The portable package root plus the three contracts every later unit imports: provider
declarations, stated settings, and the subprocess helper.

**Child issue:** #28 · **Lane:** G1 · **Depends on:** none

**Requirements owned:** R20, R21, R23, R24, R28, R29, R30, R31, R32

**Worker:** pool-assigned at dispatch (see Worker bindings) · **Backend:** inline

**Owned paths:** `plugins/voice/plugin.json`, `plugins/voice/README.md`,
`plugins/voice/scripts/providers.py`, `plugins/voice/scripts/settings.py`,
`plugins/voice/scripts/process.py`, `plugins/voice/tests/test_providers.py`,
`plugins/voice/tests/test_settings.py`, `plugins/voice/tests/test_process.py`

**Approach.** Create the package root per KTD14 (manifest with `$schema`/name/version/
description; README stating the loop, the settings table, the D4 keybinding line, the
`python>=3.12` floor, and — plainly — that the package carries no provenance manifest
and no port descriptor, R30). `providers.py` implements KTD4 and KTD5: the closed
four-value egress enum, the declaration record with a permitted-empty credential-name
field, the two in-code declarations, and a named-refusal error type carrying provider
name plus missing prerequisite. `settings.py` implements KTD6 (stated names, split
defaults, absent-never-means-empty, `VOICE_RETENTION` = `ephemeral` only) and the KTD1
state-dir resolution. `process.py` implements R32 for everyone: a bounded runner
(argv list, stdin explicitly closed, required timeout) and a detached spawner
(`start_new_session=True`, stdin closed, output to devnull) whose deadline contract is
KTD3d — both with an injectable seam (KTD12). No hook, no Claude-specific file, lives in
portable core (R29).

**Failure modes to cover:** unknown egress class; declaration missing endpoint;
credential-name field carrying a value-shaped string (rejected — names only); unset
vs empty setting; unknown `VOICE_RETENTION` value; runner called without a timeout
(impossible by signature); detached spawn leaking stdin.

**Test scenarios** (`plugins/voice/tests/`): `test_providers.py` — a declaration
carries invocation-or-endpoint, capabilities, egress class, and a credential variable
*name* with no value; the empty credential name is valid; exactly the four R21 egress
literals are accepted and anything else is rejected; the external-egress predicate is
true for `named-remote-service` and false for `local-network`; an unavailable provider
raises the named refusal, never a fallback. `test_settings.py` — the ephemeral
retention posture is stated, not defaulted; an unknown retention value is refused by
name; absent is never treated as empty; the four provider settings resolve (Hermes
defaults, Forge refuse-by-name when unset); no setting carries a secret; the state dir
honors `VOICE_STATE_DIR`. `test_process.py` — every spawned subprocess has stdin
explicitly closed and a deadline attached; the detached spawner starts a new session
and closes stdin; the runner rejects shell-string invocation.

**Verification:** the four run-wide commands, plus #28's acceptance greps (import
check, four egress literals, four settings names, no `auth.json`/`XAI_API_KEY`, README
R30 match, no `*hook*` file under `scripts/`).

### U2. Claude client extension: Stop hook, binding store, single-speaker guard

The Claude-only extension (hook descriptor + detached `Stop` hook) plus the portable
sticky-binding store.

**Child issue:** #29 · **Lane:** G2 · **Depends on:** U1

**Requirements owned:** R1, R2, R3

**Worker:** pool-assigned at dispatch · **Backend:** inline

**Owned paths:** `plugins/voice/com.infiquetra.claude/plugin.json`,
`plugins/voice/com.infiquetra.claude/hooks/hooks.json`,
`plugins/voice/com.infiquetra.claude/hooks/stop_hook.py`,
`plugins/voice/scripts/binding.py`, `plugins/voice/tests/test_binding.py`,
`plugins/voice/tests/test_stop_hook.py`

**Approach.** `binding.py` (portable core — vendor-neutral per R29) implements KTD7:
read/write of `binding.json` (agent name, session id, pane id, bound-at), single-valued
and sticky, atomic writes, absent/corrupt read as unbound with the distinction
reportable to the pane. The client extension is exactly
`plugins/voice/com.infiquetra.claude/` (matching the unifi and mission-control
extensions; `plugins/voice/adapters/**` must never be created): its own `plugin.json`,
and `hooks/hooks.json` declaring the `Stop` entry in the verified interpreter-prefixed
shape (KTD2). The client `plugin.json` matches `plugins/unifi/com.infiquetra.claude/`
and `plugins/mission-control/com.infiquetra.claude/` (`name`/`version`/`description`;
no catalog `$schema` at that nested path — `check_repo.py` validates `$schema` only on
`plugins/*/plugin.json`). `stop_hook.py` implements KTD2 verbatim: stdin JSON once,
local binding comparison, unique payload file, detached argv spawn of
`plugins/voice/scripts/speak.py` only when bound, exit 0 immediately on every path. It
does not import `speak`. Response text comes only from the payload's
`last_assistant_message`; the hook never reads the screen or the transcript file.

**Failure modes to cover:** unbound session; mismatched session id; absent state dir;
corrupt `binding.json`; empty `last_assistant_message` (spawn nothing, write no
payload); hook stdin not valid JSON (exit 0 silently — a hook must never break a turn);
speak.py not yet present on disk (spawn still recorded by the seam; U2 tests never
import or execute speak.py).

**Test scenarios** (`plugins/voice/tests/`): `test_binding.py` — exactly one binding
exists at a time; it persists until explicitly changed; rebinding replaces it; nothing
infers a target from focus or recency; corrupt/absent files read as unbound.
`test_stop_hook.py` — a mismatched or unbound session returns without spawning and
produces no sound (spawn seam records zero calls); a bound session writes one unique
payload JSON under the state dir and spawns exactly one detached child whose argv is
`[sys.executable, …/scripts/speak.py, payload_path]`, stdin closed, new session, no
wait (measured against the fake, not wall clock); the hook exits 0 on malformed stdin;
`hooks/hooks.json` declares a `Stop` entry whose command is `python3` plus
`${CLAUDE_PLUGIN_ROOT}/hooks/stop_hook.py`.

**Verification:** the four run-wide commands, plus #29's acceptance checks (manifest
path, `Stop` in hooks.json, no `plugins/voice/adapters`, both pytest files green).

### U3. Speak path: Markdown cleanup, code-block omission, Voice Forge synthesis

Turn the completed response into speech through the declared provider, with a stop
handle and the refusal entry point U5 calls.

**Child issue:** #30 · **Lane:** G2 · **Depends on:** U1

**Requirements owned:** R5, R6, R7

**Worker:** pool-assigned at dispatch · **Backend:** inline

**Owned paths:** `plugins/voice/scripts/text_cleanup.py`,
`plugins/voice/scripts/speak.py`, `plugins/voice/tests/test_text_cleanup.py`,
`plugins/voice/tests/test_speak.py`

**Approach.** `text_cleanup.py` implements KTD10 (fences first, then formatting
syntax; no length machinery of any kind). `speak.py` implements KTD8: the
`urllib.request` POST to `/v1/audio/speech` with the configured voice id, wav response
to a state-dir temp file, playback through `VOICE_PLAYBACK_BIN` via U1's process
helper with the duration-derived deadline (KTD3b), `playback.json` for the live player
pid, `stop_playback()` terminating it immediately, deletion of the audio file on
every exit path, and named refusal on unreachable/unhealthy synthesis (R23). Companion
endpoints (`/health`, `/v1/audio/voices`) belong to U6's preflight, not here. Both
entry points U5/U6 need — `speak(text)` and `stop_playback()` — are module-level and
importable. `__main__` implements the KTD2 child: read the payload path from argv,
delete the payload file in `finally`, clean, speak. `speak()` calls `stop_playback()`
before starting new playback so utterances do not overlap.

**Failure modes to cover:** cleaned text empty (synthesize nothing, exit silently);
synthesis non-2xx / connection refused / timeout (named refusal); playback binary
absent (named refusal); stop while mid-playback (process terminated, file deleted);
very long input (returned whole by cleanup — no gate).

**Test scenarios** (`plugins/voice/tests/`): `test_text_cleanup.py` — emphasis,
headings, links, list and blockquote syntax are not in the output; fenced code-block
contents (backtick and tilde) are omitted entirely; inline code keeps its text without
backticks; a long input is returned whole. `test_speak.py` — the request targets
`POST /v1/audio/speech` at the configured base URL with the configured voice id, built
on `urllib.request` via the opener seam, with the cleaned text verbatim; wav bytes
land in the state dir and are deleted after playback and after failure; the playback
deadline derives from the wav duration; an unreachable Voice Forge raises the named
refusal rather than substituting; `stop_playback()` terminates the recorded pid; the
refusal entry point speaks a supplied message; empty cleaned text produces no request;
`__main__` consumes and deletes a payload file even when synthesis is skipped or fails;
`speak()` stops any current playback before starting a new one.

**Verification:** the four run-wide commands, plus #30's acceptance greps (no
truncation/ceiling vocabulary in `speak.py`, `/v1/audio/speech` present, no HTTP
client import, no hard-coded IP, `def speak` present).

### U4. Listen path: toggle recording, Hermes relay transcription, ephemeral retention

Capture on a toggle, transcribe through the relay with the in-memory session token,
and leave nothing behind.

**Child issue:** #31 · **Lane:** G2 · **Depends on:** U1

**Requirements owned:** R10, R12, R25, R26, R27

**Worker:** pool-assigned at dispatch · **Backend:** inline

**Owned paths:** `plugins/voice/scripts/record.py`,
`plugins/voice/scripts/transcribe.py`, `plugins/voice/tests/test_record.py`,
`plugins/voice/tests/test_transcribe.py`

**Approach.** `record.py`: toggle semantics (R10) over `recording.json` — first press
spawns `VOICE_CAPTURE_BIN` (D3) with argv
`[capture_bin, "-f", "avfoundation", "-i", ":0", "-t", "600", wav_path]` writing a wav
under the state dir (`:0` is the version-one AVFoundation default mic; a non-zero
ffmpeg exit is a named refusal, not device discovery). `toggle()` returns `None` on
start and the wav path on an explicit second press. An abandoned recording (never
stopped, or discarded) and ceiling expiry produce no transcription request (R12) and
**delete the wav** (D5 ephemeral covers audio that never reached transcription, not
only R25's after-transcription case). After an explicit stop, the pane (KTD16)
transcribes; the audio file is deleted immediately after transcription returns —
success and failure alike (R25). U4 does not import `deliver`. `transcribe.py`
implements KTD9 in full: token from the dashboard root held in memory, JSON body
`{"data_url": "data:audio/wav;base64,<...>"}`, profile query parameter,
`X-Hermes-Session-Token` header, one refresh and one retry on 401, named refusal on
the second 401 / unreachable relay / unexpected provider, transcript+provider
consumed, no transcript file written anywhere (R26), no telemetry of any kind (R27),
token never in argv, disk, logs, or evidence. Standard library only; the credential
boundary is absolute (no `auth.json`, no bearer copy, no `XAI_API_KEY`, no Hermes
import).

**Failure modes to cover:** double start press; stop with no active recording;
recorder exits early (ceiling or crash) — wav deleted, no transcribe; abandoned
recording — wav deleted, no transcribe; ffmpeg non-zero (named refusal, wav deleted);
transcription 401→refresh→200; 401→refresh→401 (named failure, no loop); relay
unreachable; response missing transcript or naming an unexpected provider; request
body uses `data_url` and no other audio field; audio deletion on every path including
exception paths.

**Test scenarios** (`plugins/voice/tests/`): `test_record.py` — one press starts and a
second stops and returns the wav path; nothing is transcribed before the second press;
an abandoned recording issues no request and deletes the wav; ceiling expiry deletes
the wav and issues no request; the audio file is gone after a successful run and after
a deliberately failed one (retention scenarios named `retention` for #31's `-k` gate);
the recorder argv includes `-f avfoundation`, `-i :0`, and `-t 600`, and the subprocess
carries the ceiling deadline and closed stdin.
`test_transcribe.py` — the request posts JSON `{"data_url": "data:audio/wav;base64,…"}`
to `/api/audio/transcribe` with the configured profile query parameter via
`urllib.request`, with the in-memory token header; the body has no `audio`/`file`/
`content` key; a 401 triggers exactly one refresh from the root page and one retry
(scenarios named `retry`); a second 401 fails by name; the token is never written to
disk, logged, or placed in command arguments; an unreachable relay raises the named
refusal; an unexpected response provider raises the named refusal; no transcript file
is written; no telemetry call is made; no credential is read and no Hermes module is
imported.

**Verification:** the four run-wide commands, plus #31's acceptance greps (no
transcript-log identifiers, no telemetry identifiers, `/api/audio/transcribe`
present, no credential reads, token-header present with no persist/log pattern, no
Hermes/requests/httpx imports).

### U5. Deliver path: unsubmitted pane delivery and audible blocked-state refusal

Return the transcript to the bound agent's input box unsubmitted — or refuse audibly
when that agent is blocked on a human decision.

**Child issue:** #32 · **Lane:** G3 · **Depends on:** U1, U2 (sticky binding), U3
(audible refusal), U4 (transcript)

**Requirements owned:** R16, R17, R18, R19

**Worker:** pool-assigned at dispatch · **Backend:** inline

**Owned paths:** `plugins/voice/scripts/deliver.py`,
`plugins/voice/tests/test_deliver.py`

**Approach.** KTD11 verbatim: `deliver(text)`, `use_refused()`, `discard_refused()`.
Resolve the sticky-bound agent with `herdr agent get` (pane id + `agent_status` from
the closed set, 10-second deadline); `blocked` → speak the refusal through U3 and hold
the transcript transiently in `refused-transcript.txt` for explicit use or discard
(R18, R19); otherwise normalize the transcript to a single line and deliver with
`herdr pane send-text` (argv list, 10-second timeout, stdin closed) — literal text
without Enter (R16). `herdr pane run` never appears. The bound agent is the only
target (R17): no broadcast, no fallback, no recency inference. The non-atomic
check-then-send residual is stated in the module docstring and deliberately not
patched. Both `herdr` invocations go through U1's process helper. U6 calls these
entry points through the KTD16 seam; this unit does not import `pane`.

**Failure modes to cover:** blocked agent (refusal spoken, nothing sent, transcript
held); bound agent unresolvable (named error, nothing sent anywhere else); multi-line
and punctuation-heavy transcripts (normalized, delivered literally); refused
transcript then explicit use (delivered once) or discard (deleted); no queueing or
retry of a refused transcript.

**Test scenarios** (`plugins/voice/tests/test_deliver.py`): delivery resolves the pane
through `herdr agent get` and calls `herdr pane send-text` with the transcript;
`herdr pane run` is never invoked (scenario names include `unsubmitted` and `bound`
for #32's `-k` gates); only the bound agent is targeted; a blocked agent receives no
text and triggers the audible refusal through the U3 seam (scenarios named `blocked`);
a refused transcript is retained transiently, is never auto-delivered or queued, and
explicit discard removes it; `use_refused()` delivers once and clears the hold;
`discard_refused()` deletes the hold without sending; a multi-line transcript is
delivered as one line; the send subprocess carries a 10-second deadline and closed
stdin.

**Verification:** the four run-wide commands, plus #32's acceptance greps (zero
`pane run`, `agent get` + `send-text` present, no clipboard/AppleScript/raw-tty
path).

### U6. Agent Skill entrypoint, Voice pane controls, and provider/keybinding preflight

The operator-facing surface: the portable Agent Skill that starts the pane, the pane's
display and keys, and the preflight that names what is missing.

**Child issue:** #33 · **Lane:** G3 · **Depends on:** U1, U2 (identity), U3 (stop
playback), U4 (indicator, barge-in)

**Requirements owned:** R4, R8, R9, R11, R13, R14, R15, R22

**Worker:** pool-assigned at dispatch · **Backend:** inline

**Owned paths:** `plugins/voice/skills/voice/SKILL.md`,
`plugins/voice/scripts/voice_cli.py`, `plugins/voice/scripts/pane.py`,
`plugins/voice/scripts/preflight.py`, `plugins/voice/tests/test_pane.py`,
`plugins/voice/tests/test_preflight.py`,
`plugins/voice/tests/test_skill_entrypoint.py`

**Approach.** The entrypoint is the smallest legitimate portable surface: an Agent
Skill at `plugins/voice/skills/voice/SKILL.md` (frontmatter constrained to the
validated six-field allowlist, `name: voice` matching its directory) that documents
starting the pane, the in-pane keys `t`/`s`/`u`/`d`/`q` (KTD16), and running
preflight through the bundled CLI — not a second command surface. No MCP server anywhere. `voice_cli.py` is a small argparse CLI:
`pane` (run the pane loop), `bind <agent>` (KTD7), `preflight`, `toggle`, and `stop`
(the command the D4 Herdr-wide keybinding invokes; terminates playback via U3).
`pane.py` runs in its own Herdr pane (R13) and implements KTD16: a single-threaded
standard-library loop using `tty.setcbreak`/`termios` so keys apply without Enter
(no `curses`, no `input()`). It displays the bound Herdr agent name and session id
continuously alongside recording state (R4), shows the literal `*** RECORDING ***`
while recording (R11), and handles `t`/`s`/`u`/`d`/`q` as specified in KTD16. Starting
a recording calls U3 `stop_playback()` first (R9); an explicit second `t` takes the
wav path from U4 `toggle()`, transcribes through U4, and delivers through the U5 lazy
import seam — U6 does not implement send-text. `preflight.py` implements R22/R23 with
KTD13 and KTD15:
Voice Forge — `GET /health` requiring a usable backend (a healthy process with no
backend fails), `GET /v1/audio/voices` requiring the configured voice id, then a real
short synthesis; Hermes — `GET /api/health` (never reading `auth_required: false` as
anonymous access), token from the root page in memory, `/api/profiles` with the token
header requiring the configured profile with `stt.provider` = `xai` (no credential
displayed), then the KTD15 synthesized sample through `/api/audio/transcribe`
requiring `provider` = `xai`; plus the D4 keybinding presence probe and capture/
playback binary checks. Every failure is reported by provider and prerequisite name;
nothing is substituted; nothing is installed or written.

**Failure modes to cover:** healthy-process/no-backend Voice Forge; voice id missing
from the voices list; anonymous relay call (token-missing condition, not healthy);
profile absent or resolving a different provider; keybinding absent; capture or
playback binary missing; every probe failing by name without touching another
provider.

**Test scenarios** (`plugins/voice/tests/`): `test_skill_entrypoint.py` — the skill
file exists with valid frontmatter limited to the allowed fields, names the CLI that
starts the pane, names the in-pane keys `t`/`s`/`u`/`d`/`q`, and declares no MCP
server. `test_pane.py` — bound identity and
recording state are both displayed; `s` interrupts playback immediately rather than at
utterance end (stop seam called on keypress, not after Enter); `t` while idle stops
playback first then starts recording; `t` while recording transcribes and calls the
deliver seam with the transcript; `u`/`d` call the use/discard seams; the literal
`*** RECORDING ***` is present while recording and absent otherwise; `deliver` is not
imported at module load.
`test_preflight.py` — a missing provider is reported by name and never substituted; a
healthy-but-backend-less Voice Forge fails; a missing voice id fails by name; a
profile that does not resolve `stt.provider: xai` fails by name; an anonymous relay
call is treated as token-missing rather than healthy; the token is read in memory and
never persisted, printed, or logged; an absent `voice stop` keybinding is reported,
and no Herdr configuration file is ever written (the probe seam records reads only).

**Verification:** the four run-wide commands, plus #33's acceptance checks (skill and
CLI files exist, zero MCP identifiers package-wide, preflight probes all five
endpoint paths, no credential reads, token header present with no persist/log
pattern, no Herdr-config write pattern).

### U7. End-to-end acceptance evidence, README verification, and journal closeout

Prove the loop end to end, record AE1–AE8 as observed, verify U1's README truth, and
write the run's journal entries.

**Child issue:** #34 · **Lane:** G4 · **Depends on:** U1, U2, U3, U4, U5, U6

**Requirements owned:** R33

**Worker:** pool-assigned at dispatch · **Backend:** inline

**Owned paths:** `docs/evidence/voice/acceptance.md`, `plugins/voice/README.md`
(finalize/verify only — R30 stays owned by U1), `docs/engineering-journal/DECISIONS.md`,
`docs/engineering-journal/LEARNINGS.md`. Repository root `README.md` and
`docs/README.md` only if a claim in them became untrue — not a routine surface
(parent shared-file rule).

**Approach.** Execute the full conversational loop against the live, preflighted
environment and record each acceptance example AE1–AE8 with what was actually
observed — including AE1's multi-session silence check (at least two Claude sessions
running, exactly one speaks) — in `docs/evidence/voice/acceptance.md`, naming R33 and
every safety behaviour manually verified. Verify (never re-implement) that the README
still plainly states the absent provenance manifest and port descriptor; drift is a
finding against U1's merged work, not a licence to re-own R30. As the run's **sole
journal writer** (both files are newest-first inserts; two writers guarantee anchor
displacement — the exact defect class both review records repaired), record the run's
DECISIONS entries (this plan's KTDs that survive contact with implementation, with
rationale and revisit-when) and LEARNINGS entries (at minimum: the measured
synchronous-Stop-hook constraint and the detach pattern, with the preflight evidence).
An un-evidenceable acceptance example is a finding raised on #27, never a silent
omission.

**Failure modes to cover:** an acceptance example that cannot be reproduced (raise on
#27); README drift (finding against U1); suite red at the final merged commit (blocks
closeout).

**Test scenarios:** none — no new automated test is required (evidence-and-journal
unit); its gate is that every previously added test passes at the final merged
commit. `Test expectation: none — documentation/evidence unit; the automated gate is
the existing suite at the final commit.`

**Verification:** the four run-wide commands at the final merged commit, plus #34's
acceptance greps (R33 named, AE1–AE8 all recorded, README R30 intact) and the parent
contract's closeout checklist.

## Landing and merge schedule

Each unit branches from the then-current `origin/main`, freezes a clean head, passes
its single Saga Code Review at that head, and merges with CI green before its
dependents dispatch. Order: **U1 alone** (G1 — the contract every later unit
imports). Then **U2, U3, U4 concurrently** (G2 — three worktrees; their owned file
sets are disjoint, so merges land in completion order without contention). Then **U5
and U6 concurrently** (G3 — disjoint surfaces; both rebase on the merged G2 state).
**U7 last and serial** (G4 — it needs the merged whole, the live loop, and sole
journal-writer status). The run's shared-file rules hold throughout: the two
README touches are serialized by design (U1 implements R30; U7 verifies at the end);
`plugins/voice/tests/**` is written strictly per-unit, one file set per unit, never
edited across units; `.github/workflows/ci.yml` is written by nobody; repository root
`README.md` and `docs/README.md` are U7 only if a claim became untrue. Same-lane units
(U2∥U3, U5∥U6) share no owned path and must not import each other at module level
(KTD2, KTD16).

## Scope Boundaries

Governed by the requirements document's Scope Boundaries section; the run-binding
exclusions from #27, restated so no unit drifts into them:

- No generalisation to non-Claude Herdr-managed agents; no fleet-wide blocked-session
  alerts (deferred supporting functionality — never a substitute for the loop).
- No Apple `SpeechAnalyzer`, no local `whisper.cpp`, no operator-managed local
  speech service in this run; no provider installation, credentials, billing, or
  service lifecycle inside `voice` (R24).
- No press-and-hold recording; no response-length management of any kind (R5); no
  multi-session arbitration, queues, or priorities; no resident daemon or background
  listener; no continuous listening or wake words.
- No Model Context Protocol server or listening tool; no terminal-output scraping; no
  terminal-input injection outside the supported Herdr commands; no modifying or
  vendoring Herdr (R15).
- No new HTTP client dependency (standard library `urllib.request` only, R31); no CI
  edits; no board writes by any worker; no engineering-journal writes by any unit but
  U7.

**Deferred to follow-up work** (distinct from non-goals): a guarded `send-text`
proposed to Herdr (closes the KTD11 residual at the right layer); additional declared
providers under the same contract (whisper.cpp, SpeechAnalyzer, a provider config
file per KTD5); a package `CHANGELOG.md` on first external release (KTD14); promoting
this package's microphone/retention/telemetry posture toward an organisational
standard (a context-library question, per the requirements doc's non-blocking
follow-ups).

## Risks and pre-mortem

**Most likely failure first:** a worker adds machinery the contract forbids — a retry
loop around the 401 refresh, a provider fallback, a config framework, a length gate
"for safety" — or edits across an owned surface. Mitigations: the owned-path lists
above are exhaustive and executable; KTD5/KTD9/KTD10 name the forbidden machinery
explicitly; the adversarial and reliability lenses are predeclared where those
temptations live; two-units-one-surface is a run stop condition.

- **`last_assistant_message` completeness is an accepted unknown** (carried from the
  requirements): if Claude caps it upstream, Voice speaks less and reports nothing.
  Deliberately untested; no mitigation built.
- **Preflight gates can fail** (P1–P9): the plan builds against verified contracts
  with injected seams, so implementation proceeds hermetically; only preflight and
  U7's acceptance need the live environment. A failed gate stops the run rather than
  triggering redesign — U2/U3 are unbuildable as specified only if P1/P2 re-derive
  differently, and that is a stop, not a workaround.
- **The blocked-state check races delivery** (stated residual): narrowed by checking
  immediately before send; closing it belongs to Herdr. Preserved deliberately
  (KTD11).
- **Provider outages mid-run** (Voice Forge on the Mac mini; Hermes locally): named
  refusals by design; U7's acceptance is the only merge-path step that needs both
  live simultaneously.
- **Shared pytest process collisions**: prevented structurally by KTD12 (no
  `__init__.py`, verified-unique basenames and module names); a future package
  reusing a voice module name is caught by CI, not by this run.
- **Journal anchor displacement**: U7-only journal writes; both reviews documented
  this exact defect class, and the rule exists because of it.
- **Newline-in-transcript submits accidentally**: eliminated by KTD11's single-line
  normalization rather than by escaping games.
- **Same-lane import of a not-yet-landed module**: prevented by KTD2 (hook spawns
  speak.py by argv) and KTD16 (pane lazy-imports deliver). Tests fake the seams.
- **Abandoned or ceiling-expired recordings leaving wav files**: U4 deletes the wav
  without transcribing (D5 ephemeral, not only R25).

## Open questions

None blocking. One runtime configuration value is not a plan decision: the concrete
Voice Forge voice id for `VOICE_FORGE_VOICE_ID` (from the Home Lab deployment receipt,
proven present by preflight P8; never an operator gate per D1). The Herdr
`config.toml` path is now KTD13 (`~/.config/herdr/config.toml`), not an open question.

## Unattended decisions log

Decisions this planning session took without an operator in the loop, each with the
defensible default chosen:

- **Destination: `merge`** — the parent's intent envelope sets `merge: auto` with
  reviews required, and the contract's board ladder runs each child through PR,
  review, and merge; `plan-only` would contradict the run design.
- **Backend: `inline` (chosen) vs `team-execution` (recommended)** — the saga backend
  recommender, given this run's true shape (24 files, four phases, security-relevant
  boundaries, blocking review consensus), recommends `team-execution`; the operator
  decided `inline` with external orchestration supplying the pools and gates the
  recommender is pricing in. Recorded as recommended-vs-chosen in the plan saga tick.
- **No board writes and no journal writes from this session** — the contract makes
  the coordinator the sole board writer and U7 the sole journal writer; the generic
  planning-phase board moves and DECISIONS.md mirror are therefore skipped here, and
  the KTD journal mirror is delegated to U7's closeout with this plan as source.
- **This plan is the only file this session commits** — the run's shared-file rules
  bind the planning commit too.
- **Lens declarations, KTD1–KTD16, and the per-unit failure-mode sets** were authored
  under the authority the contract grants planning ("the plan declares the applicable
  lenses"; the requirements' deferred-to-planning list) and are review targets for
  the plan's own Saga Document Review, not silent defaults.
- **Pane keys `t`/`s`/`u`/`d`/`q`, unbuffered stdin, ffmpeg `:0` + `-t 600`, helper
  timeout 10 s, playback margin 2 s, synthesis HTTP 10/300 s, Herdr config path
  `~/.config/herdr/config.toml`, and Hermes body field `data_url`** were chosen as the
  smallest defensible closures of questions the requirements deferred to planning or
  that a worker would otherwise invent. They do not reopen operator decisions D1 or D2.
