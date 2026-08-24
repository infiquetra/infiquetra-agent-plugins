# Saga Code Review — U0 README truth cleanup (`u0-readme-q1`)

This review covers the frozen documentation-only commit on `orch/mcport-9-resume1-u0-readme-q1` because the mission-control port's later evidence and closeout copy would otherwise be built on a front page that contradicted the repository's own tests.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `d9d95710a56c53d10a6f1807f845e6dde47f3073` (`d9d9571`, `docs(readme): correct the Status section to the verified pilot state`)
- Named base: `0e833f84440ae1fde6b97fc40ec6f31aea577c11`
- Target: `README.md` and `docs/README.md` only (one commit, two files, `+43 / -21`)
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `d9d9571` is accepted under the roster contract.** Every selected lens has a derived overall score of at least 9.0 and every applicable dimension is at least 7.0. Independent gates that this controller actually ran — grep-absence of the two falsified phrases, `git diff --check`, `python3 scripts/check_repo.py`, and `python3 -m unittest discover -s tests` (621 tests, 41.215s, OK) — all passed. Built-versus-planned is CLEAN with the U0 checklist DONE.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (issue #10 / plan U0): rewrite the repository README Status section so it no longer claims the UniFi pilot is paused, that the package has no working entrypoint, or that two of ten clients did not consume it; replace those claims with the verified state and citations; apply the matching one-bullet correction to `docs/README.md` (plan decision KTD6).
- Delivered: exactly those two files. `plugins/unifi/` is untouched. No tests were added (the plan's rejected alternative). `llms.txt` is unchanged and recorded in the commit message as U9's surface.

### Plan-completion (U0)

| Item | State | Evidence |
| --- | --- | --- |
| Remove "has no working entrypoint" and "Two of the ten clients did not consume the package" | DONE | `git show d9d9571:README.md` — both phrases absent |
| Replace "now paused for an operator decision" with completed + stop-at-matrix | DONE | `README.md:15-24`; `docs/README.md:12-14` |
| Cite `tests/test_client_entrypoints.py`, `plugins/unifi/PROVENANCE.json`, and the current matrix | DONE | `README.md:35-44` |
| Keep Codex works-through-an-adapter as current fact | DONE | `README.md:45-48`; matrix table row OpenAI Codex |
| Every remaining Status claim verified or removed | DONE | see Correctness below; Fleet Core slice and site-profile subsections re-checked against the current tree |
| `docs/README.md` matching correction | DONE | one bullet, nothing else in that file moved |
| Repository gate and suite green; no whitespace errors | DONE | `check_repo.py` passed; 621 unit tests OK; `git diff --check` exit 0 |

COMPLETION: 7/7 DONE.

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0. Finding priority and confidence are routing metadata, not additional acceptance gates.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 9.00 | `true` | none |
| `documentation-clarity` | 9.83 | `true` | none |
| `adversarial` | 10.00 | `true` | none |

## What was verified (correctness / documentation-clarity / adversarial)

The two bold replacement claims, and the surrounding Status sentences this unit rewrote, were checked against the frozen tree rather than against the commit message.

- **Both UniFi client entrypoints run.** `plugins/unifi/PROVENANCE.json` classifies `skills/unifi-network/scripts/unifi_network_client.py` and `skills/unifi-protect/scripts/unifi_protect_client.py` as `deterministic-transform` outputs of `resolve-bundled-fleet-module` version 1. Both `_bundled/retry_backoff.py` blobs exist at this revision. `tests/test_client_entrypoints.py` runs both shipped scripts with no credentials and no network, asserts `--help`, and fails when the bundle is removed.
- **All ten clients assessed; none failed.** `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (`matrix-status: current`) lists ten rows: nine `works directly`, OpenAI Codex `works through an adapter`, zero failed, zero unsupported. Cursor Agent is `works directly`; the matrix records the earlier failure as an empty-HOME isolation artifact.
- **Pilot complete; operator decision was to stop at the matrix.** Completion is recorded by `docs/engineering-journal/narratives/2026-08-23-unifi-portability-pilot-retrospective.md` and runbook v1.0.0 (`docs/runbooks/portable-plugin-port.md`, Adopted 2026-08-23). The 2026-08-22 journal decision still titled "Pause the pilot at the compatibility matrix and take no client-specific remediation" opens with "The portability pilot stops at the completed ten-client compatibility matrix." Open distribution decisions remain in `docs/engineering-journal/QUEUED.md`.
- **Unchanged Status subsections kept for a reason.** Portable Fleet Core still ports only `retry_backoff` (`plugins/fleet-core/DEFERRED.md` and `plugins/fleet-core/scripts/fleet_commons/`). The site-profile "discovery-only" claim matches `plugins/unifi/scripts/site_profile.py` and `plugins/unifi/references/site-profile.md`.
- **New links resolve** at the frozen revision for the retrospective, runbook, `DECISIONS.md`, `PROVENANCE.json`, the entrypoint tests, the current matrix, and `QUEUED.md`.
- **Owned-path stale phrases are gone.** `has no working entrypoint`, `now paused for an operator decision`, `did not consume`, and `abort during module import` are absent from both owned files.

No in-scope trust-boundary defect was found. This diff does not touch `gh` credentials, subprocess or git execution, package filesystem custody, or any GitHub mutation surface.

## Coverage

- Suppressed findings: 0 (nothing below confidence 75 was considered reportable).
- Residual risks, not findings and not repairs:
  - `llms.txt:16` still says the pilot is "executed and paused for an operator decision". The unit commit names this as U9 closeout scope; U9 owns `llms.txt`. This is why `documentation-clarity` / `terminology-cross-document-consistency` is 9 rather than 10.
  - The 2026-08-22 decision body still recites contemporaneous facts (Cursor failed; no working entrypoint) that later work superseded. The citation in Status is for the *decision* (stop, no per-client remediation), which issue #10 required. Rewriting that journal entry is outside owned paths.
- Testing gap, accepted by the plan: grep-absence pins the two removed false phrases, not the replacement true claims. Those claims are already enforced by the cited entrypoint tests and matrix checker. Pinning the root README was the rejected alternative because U9 rewrites Status again at closeout. That is why `testing` / `requirements-regression-coverage` is 9 rather than 10.
- Independent gates: grep-absence pass; `git diff --check` pass; `python3 scripts/check_repo.py` pass; `python3 -m unittest discover -s tests` 621 tests OK. `evaluate_review_readiness` can_proceed is true.

## Findings

None.

## Routing

`accepted` — continue to the caller's next independent gate. No fix requests. `llms.txt` staleness is already assigned to U9 by the landing model and is not a U0 repair.
