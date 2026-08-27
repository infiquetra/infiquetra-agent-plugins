---
date: 2026-08-27
kind: doc-review
cycle: 2
target: docs/plans/2026-08-27-auralis-c3-adapter.md
reviewed_revision: 961d0e437fe99eb2a4a2fed2bbd2e54b238b597c
reviewed_plan_blob: c06db4dcfb71425358e3f5a57439bd3c5c03309b
repair_revision: b4362a2ed227c646a4f076e29f089793e8da36de
branch: orch/auralis-c3-adapter-docreview-c3-plan
classification: implementation plan
blocked: true
---

# Focused document re-review, cycle 2 — Auralis C3 Claude adapter implementation plan

**Verdict: STILL BLOCKED / NOT READY TO DRIVE IMPLEMENTATION.** In this repository's plan for Auralis Claude adapter capability slice C3, ten cycle-1 findings are closed, but two priority-one (P1) findings are only partially closed: the requirement R122 rejection-to-fallback test stops at the adapter's local outcome instead of observing Core's actual fallback mark, and the requirement R121 Markdown recognizer still admits Markdown forms outside its claimed complete contract.

## Applied fixes

No fixes were applied in cycle 2. The operator required a focused re-review without rewriting or repairing the plan, so this review artifact is the only cycle-2 repository change.

## Review result

The repaired plan remains blocked by findings F3 and F5; all other cycle-1 findings are closed.

| field | value |
|---|---|
| target | `docs/plans/2026-08-27-auralis-c3-adapter.md` |
| review mode | focused cycle-2 re-review of findings F1 through F12; not a fresh review |
| reviewed revision | `961d0e437fe99eb2a4a2fed2bbd2e54b238b597c`; target blob `c06db4dcfb71425358e3f5a57439bd3c5c03309b` |
| repair revision | `b4362a2ed227c646a4f076e29f089793e8da36de` |
| wire authority | `docs/bridge/bridge-v1.md` in `infiquetra/auralis` at accepted revision `695cd0ecfddf44e0d6e3386da318bd5fde4a1926` |
| tracked wire snapshot | `docs/bridge-v1-from-c10.md`; blob `a706d6f30b09ef726fbf0940aba7a4fa76261063`; Secure Hash Algorithm 256-bit (SHA-256) `eb47d141e5c1b87bae0bd1c0799386a3aa8806635251db14fc806469b5db19eb` |
| blocked | true — two P1 findings remain partially closed |
| findings | 6 P1 closed, 2 P1 partially closed, 4 priority-two (P2) closed; no new findings |
| applied fixes | none |
| review artifact | `docs/reviews/2026-08-27-auralis-c3-adapter-plan-doc-review-cycle2.md` |
| override rationale | none |
| linked issue / plan | `infiquetra/infiquetra-agent-plugins#46`; target plan above |

## Readiness summary

The repair makes the wire pin reproducible, names the fallback boundary between adapter capability slice C3 and audio capability slice C5 without changing the frozen five-route bridge, adds a real Model Context Protocol (MCP) process test, and supplies a real file-transaction mechanism. It also closes the settings custody, lost-response retry, shared-stub ownership, deadline, wire-grammar, and immutable-requirements-link findings.

The plan still substitutes an adapter-local `fallback` value for the Core-side `fallback_accepted` state in its purported end-to-end requirement R122 test. Its Markdown class table also patches the examples named in cycle 1 without defining all Markdown forms that requirement R121 says the surface must reject.

## Finding dispositions

Each cycle-1 finding was checked against the repaired plan and the narrow repository evidence needed to judge that repair.

| id | priority | status | evidence checked | disposition |
|---|:---:|:---:|---|---|
| F1 | P1 | closed | Plan lines 55–82; tracked snapshot and exact source revision; snapshot/source SHA-256 equality; clean `git archive` repository check | The source document, revision, digest, and tracked byte-identical snapshot are explicit. A clean checkout contains the target and `scripts/check_repo.py` passes without the old excluded-only convenience copy. |
| F2 | P1 | closed | Plan lines 194–249 and 1013–1025; bridge contract lines 102–110 and 331–335 | The plan assigns named-reason rejection and completion without an accepted rendering to C3, and assigns fallback content, speech, and the visible `fallback_accepted` mark to Core and C5 through the existing in-process `acceptFallback()` API. It adds no bridge route and names acceptance example AE36 as the joint dependency. |
| F3 | P1 | partially closed | Plan lines 887–931 and 1075–1077; bridge contract lines 202–209 and 331–335 | The new test launches the real prompt hook, the declared MCP process, and the real Stop hook, so it closes the fixture-only half. Its final assertion reads only the adapter record's `fallback` value; it neither drives C5's `acceptFallback()` path nor observes the captured Core turn in `fallback_accepted`, and the generic AE36 mapping supplies no executable joint procedure. |
| F4 | P1 | closed | Key Technical Decision 11 at plan lines 508–539; implementation unit U2 tests at lines 746–788; local macOS lock probe | Every writer is routed through one `fcntl.flock`-guarded read-apply-atomic-replace transaction with a named 500 ms refusal. The deterministic two-writer interleaving scenario proves serialization and retention of both updates; a local probe confirmed separate opens contend on the target platform. |
| F5 | P1 | partially closed | Plan lines 253–266 and 710–773 | The repair correctly makes the gate, not `text_cleanup.py`, own the recognizer and adds the four concrete classes cited in cycle 1. The claimed complete class table still omits core Markdown forms, including hard-line-break syntax and block constructs preceded by up to three spaces; as written, examples such as a three-space-indented list or blockquote have no rejecting rule. |
| F6 | P1 | closed | Plan lines 819–868 and 984–989 | The test now launches `python3 <installed-root>/scripts/mcp_server.py` from an installed-root-shaped copy over real pipes and completes initialize, tools/list, rejected tools/call, and accepted tools/call. Packaging tests bind the declaration to those exact command and argument literals. |
| F7 | P1 | closed | Plan lines 451–482, 583–592, and 674–679 | The two Herdr identity names extend the closed `SETTING_NAMES` tuple inside the sole environment reader. `settings.py` and `test_settings.py` belong only to U1, with absent, empty, and closed-set regressions assigned. |
| F8 | P1 | closed | Bridge contract lines 317–322; plan lines 626–635, 670–673, and 856–861 | The byte-equivalent lost-response retry carries explicit context. A retry-only `duplicate_rendering` becomes `accepted_on_retry`, is recorded as authored, cannot become fallback, and does not invite replacement; client- and MCP-surface scenarios cover the path. |
| F9 | P2 | closed | Plan lines 456–458 and 583–602 | `plugins/voice/tests/bridge_stub.py` is named, owned only by U1, and given an explicit sibling-suite import and request-capture contract. |
| F10 | P2 | closed | Plan lines 541–569 and 881–883 | The normative table assigns numeric connect, overall-call, subprocess, lock, hook, and renewal deadlines, with behavior on every expiry and owner-level clock tests. The two new hooks carry literal `timeout: 5` declarations. |
| F11 | P2 | closed | Plan lines 613–657 and 681–684 | Token length, alphabet, and padding violations and lowercase Version 4 universally unique identifier (UUID) violations are explicit fixtures. Each refuses the value, proves no downstream request, and must be mutation-checked before the guard is restored. |
| F12 | P2 | closed | Plan lines 1–6, 46–51, and 1105–1108; moving-branch URL search | Every requirements reference uses the full immutable revision `b49de1ba4d39cbd8a1e582d72bddca85bf528f8a`; no `main` or `master` requirements URL remains. |

## Remaining findings by priority

Two P1 findings still prevent implementation dispatch.

| id | priority | status | required disposition |
|---|:---:|:---:|---|
| F3 | P1 | partially closed | Specify the joint AE36 test that starts with the real C3 rejection, submits no replacement, lets the turn complete, drives C5's existing in-process `acceptFallback()` path, and observes that same Core turn as `fallback_accepted`. This must not add a bridge route. |
| F5 | P1 | partially closed | Close the Markdown defect class rather than only the cycle-1 examples: state the complete syntax grammar the standard-library recognizer implements and assign rejecting cases for every class, including optional block indentation and hard-line-break syntax, while retaining the ordinary-punctuation negative cases. |

## Repair-introduced findings

No new finding was introduced by the repair. Findings F3 and F5 are the original cycle-1 defects with meaningful but incomplete repairs.

## Verification evidence

The wire-pin and repository claims were reproduced from tracked bytes, and the unchanged repository test suite remains green.

| check | result |
|---|---|
| cycle-1 review and repaired plan read completely | pass |
| repair commit scope | pass; only the plan and tracked bridge snapshot changed |
| authoritative bridge revision available locally | pass; `695cd0ecfddf44e0d6e3386da318bd5fde4a1926` |
| authoritative bridge bytes equal tracked snapshot | pass; matching SHA-256 `eb47d141e5c1b87bae0bd1c0799386a3aa8806635251db14fc806469b5db19eb` |
| tracked snapshot present in reviewed revision | pass; blob `a706d6f30b09ef726fbf0940aba7a4fa76261063` |
| `PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_repo.py` in current checkout | pass |
| same repository checker in a clean `git archive HEAD` | pass |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q` | pass; 755 tests |
| plan unchanged during cycle-2 review | pass; blob remains `c06db4dcfb71425358e3f5a57439bd3c5c03309b` |

## Residual risk from limited evidence

This was a focused plan re-review, not implementation or live acceptance. The Auralis bridge contract remains unmerged to `auralis` main, so acceptance example AE34 must still revalidate the real two-repository wire later; the tracked snapshot makes the implementation input reproducible but does not replace that joint proof.

No formal idea-, issue-, or specification-phase rubric ran because the explicit target is a single implementation plan. No external-reviewer panel was requested or dispatched.
