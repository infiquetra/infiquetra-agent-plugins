"""The named-verb registry (plan U5, requirement R14).

Each verb is declarative data -- its question set, criteria, policy text and
confidence floor -- not a code branch.  Adding a verb is a registry entry plus a
test, which is what makes "the policy lives in exactly one place" enforceable
rather than aspirational: the command-line tool builds its subcommands from this
mapping, so a verb that exists here and nowhere else still works, and a verb that
exists only in the tool reds the registry-completeness test.

Nothing here consumes the confidence floor yet.  The first consumer is the
staffing card (issue 1033); it is recorded here so every caller reads the same
number rather than inventing one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TIER_POLICY = (
    "Tiering rule: judgment, design, architecture, root-cause investigation, or "
    "adversarial review -> opus. Mechanical or deterministic work (scaffolding, "
    "fixed transforms, mechanical edits, running commands) -> haiku. Read-only "
    "survey, search, sampling, summarising -> sonnet."
)

# The seven approval boundaries, quoted from the sdlc process chapter
# docs/process/operator-escalations.md.  Passed as policy text rather than
# paraphrased into each question, because a paraphrase of a governance boundary
# is a second, unversioned copy of it.
APPROVAL_BOUNDARY_POLICY = (
    "Seven categories mark where a run's authority ends and the sole human "
    "operator must decide: production changes; destructive operations; secrets "
    "or credential changes; identity and permission changes; billing or "
    "cost-impacting actions; external commitments; major team or process "
    "authority changes. Judge only whether the work DESCRIBED touches the "
    "category, not whether it is permitted -- nothing reading this answer "
    "grants or withholds an approval."
)

# The repository's own rule for what earns a durable journal entry, from its
# CLAUDE.md.  Generic criteria get the generic meaning, which in a repository of
# prose and skills classifies almost every commit as noteworthy.
JOURNAL_POLICY = (
    "A commit earns an engineering-journal entry when it fixed something whose "
    "cause was not obvious from the symptom, when it built a feature whose "
    "mechanism is not obvious from the diff, or when it settled a pattern, "
    "convention or tooling choice with alternatives worth recording. Routine "
    "work does not: renaming, reformatting, dependency bumps, straightforward "
    "test additions, prose edits, and fixes whose cause the diff states plainly."
)


@dataclass(frozen=True)
class Verb:
    """One named judgment point."""

    name: str
    summary: str
    state_help: str
    questions: dict[str, Any] = field(default_factory=dict)
    confidence_floor: float = 0.6

    def question_set(self) -> dict[str, Any]:
        return {key: dict(value) for key, value in self.questions.items()}


def _noul(instructions: str, policy: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "noul"}
    body["instructions"] = {"question": instructions, "policy": policy} if policy else instructions
    return body


def _choice(instructions: str, criteria: Mapping[str, str], policy: str | None = None) -> dict:
    body: dict[str, Any] = {"type": "choice", "criteria": dict(criteria)}
    body["instructions"] = {"question": instructions, "policy": policy} if policy else instructions
    return body


def _score(instructions: str, levels: Sequence[str]) -> dict[str, Any]:
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


VERBS: dict[str, Verb] = {
    "tier": Verb(
        name="tier",
        summary="Which model tier and effort should run a task",
        state_help='the task description, as {"task": "..."}',
        questions={
            "model": _choice(
                "Which model tier should run `task`?",
                {
                    "haiku": "cheapest; mechanical or deterministic work",
                    "sonnet": "mid; survey, search, summarising, moderate coding",
                    "opus": "most capable; judgment, design, adversarial review, root cause",
                },
                TIER_POLICY,
            ),
            "effort": _choice(
                "How much reasoning effort does `task` need?",
                {
                    "low": "obvious steps, little ambiguity",
                    "medium": "some judgment",
                    "high": "substantial ambiguity or many interacting constraints",
                    "max": "consequential architectural or strategic decision",
                },
            ),
        },
    ),
    "triage": Verb(
        name="triage",
        summary="What kind of issue a body describes",
        state_help='the issue body, as {"issue": "..."}',
        questions={
            "type": _choice(
                "Which issue type does `issue` describe?",
                {
                    "capability": "new user-facing capability that does not exist yet",
                    "enhancement": "improves something that already works",
                    "defect": "something is broken and must be repaired",
                    "exploration": "open question needing research before it can be planned",
                    "context-update": "documentation, prose, or instruction change",
                },
            ),
            "risk": _score("How risky is the change `issue` describes?", ["low", "medium", "high"]),
        },
    ),
    "lenses": Verb(
        name="lenses",
        summary="Which conditional review lenses a diff warrants",
        state_help='the diff and any guidance, as {"diff": "..."}',
        questions={
            "security": _noul("Does `diff` warrant a security review lens?"),
            "api_contract": _noul("Does `diff` change an API contract?"),
            "testing": _noul("Does `diff` warrant a test-coverage lens?"),
            "docs_clarity": _noul("Does `diff` warrant a documentation-clarity lens?"),
            "infra": _noul("Does `diff` touch infrastructure or deployment?"),
        },
    ),
    "bucket": Verb(
        name="bucket",
        summary="Which working bucket an item belongs in",
        state_help='the item, as {"item": "..."}',
        questions={
            "bucket": _choice(
                "Which bucket does `item` belong in?",
                {
                    "now": "actionable immediately",
                    "next": "actionable once something in flight lands",
                    "later": "worth keeping, not worth scheduling",
                    "drop": "no longer worth carrying",
                },
            )
        },
    ),
    "status": Verb(
        name="status",
        summary="What lifecycle status an item has reached",
        state_help='the item and its evidence, as {"item": "..."}',
        questions={
            "status": _choice(
                "What status has `item` reached?",
                {
                    "not-started": "no work has begun",
                    "in-progress": "work is underway",
                    "blocked": "work cannot proceed without something external",
                    "done": "the work is complete and evidenced",
                },
            )
        },
    ),
    "journal-route": Verb(
        name="journal-route",
        summary="Which engineering-journal file an entry belongs in",
        state_help='the candidate entry, as {"entry": "..."}',
        questions={
            "file": _choice(
                "Which journal file does `entry` belong in?",
                {
                    "LEARNINGS": "a non-obvious mechanism discovered by doing the work",
                    "DECISIONS": "a choice made, with alternatives rejected",
                    "QUEUED": "a follow-up not yet acted on",
                    "none": "not durable enough to record",
                },
            )
        },
    ),
    "preflight": Verb(
        name="preflight",
        summary="Whether a change is ready to run against a live system",
        state_help='the change and its checks, as {"change": "..."}',
        questions={
            "ready": _noul("Is `change` ready to run against a live system?"),
            "reversible": _noul("Can `change` be reversed without data loss?"),
        },
    ),
    "qa-strategies": Verb(
        name="qa-strategies",
        summary="Which prescribed testing strategies a change needs proof from",
        state_help=(
            'the change and the catalogue, as {"change": {"files": [...], "summary": "..."}, '
            '"strategies": {"<id>": "<what selects it>"}}'
        ),
        # One yes/no question per catalogue row in plugins/saga/references/qa-catalogue.yaml.
        # The KEYS are the contract: a test asserts this set equals the catalogue's strategy
        # identifiers in BOTH directions, so a row added to one and not the other fails rather
        # than silently going unasked.  The strategy DESCRIPTIONS stay in the catalogue and are
        # passed as state, so only the key set is duplicated here.
        #
        # This verb is advisory and additive only.  Its caller computes the required set from the
        # repository profile's file patterns FIRST and unions this answer with it, per the
        # widen-only rule: an existing pattern rule is a floor a model may raise and never lower.
        questions={
            "api-workflow": _noul(
                "Does `change` need proof of a deployed HTTP surface's workflow?"
            ),
            "contract-check": _noul(
                "Does `change` need proof that a published contract did not drift?"
            ),
            "app-ui": _noul("Does `change` need proof of application widget or screen behaviour?"),
            "hosted-surface": _noul("Does `change` need proof of a hosted page's behaviour?"),
            "cli-smoke": _noul(
                "Does `change` need proof that a command-line entry point still runs?"
            ),
            "deploy-boundary": _noul("Does `change` need proof that the deployed edge serves it?"),
            "data-check": _noul("Does `change` need proof about persisted data or a write path?"),
            "infrastructure-read-back": _noul(
                "Does `change` need proof read back from infrastructure or cluster configuration?"
            ),
            "installed-surface": _noul(
                "Does `change` need proof that an installed plugin surface resolves?"
            ),
            "manual-runbook": _noul(
                "Does `change` need proof that only a person running a runbook can give?"
            ),
        },
    ),
    "handoff-check": Verb(
        name="handoff-check",
        summary="Whether a handoff carries what its receiver needs",
        state_help='the handoff text, as {"handoff": "..."}',
        questions={
            "complete": _noul(
                "Does `handoff` carry everything its receiver needs to act without asking?"
            ),
            "names_evidence": _noul("Does `handoff` cite evidence rather than assert?"),
        },
    ),
    "roster-check": Verb(
        name="roster-check",
        summary="Whether a named agent or model still exists in the roster",
        state_help='the roster and the name, as {"roster": [...], "name": "..."}',
        questions={
            "present": _noul("Does `name` appear in `roster`?"),
        },
    ),
    "dedupe": Verb(
        name="dedupe",
        summary="Whether two findings or items are the same thing",
        state_help='the pair, as {"left": "...", "right": "..."}',
        questions={
            "same": _noul("Do `left` and `right` describe the same underlying thing?"),
        },
    ),
    "issue-flags": Verb(
        name="issue-flags",
        summary="Which review and approval categories an issue body touches",
        state_help='the issue body, as {"issue": "..."}',
        # 0.70 rather than the registry default: these five keys widen saga's
        # mandatory test gate, so an eager answer costs a whole extra lens.
        # Provisional until the harness has about thirty verdicts per key.
        confidence_floor=0.70,
        questions={
            "has_security": _noul(
                "Does `issue` involve authentication, authorisation, cryptography, key "
                "or credential handling, or any other security-sensitive behaviour?"
            ),
            "has_api": _noul(
                "Does `issue` change an interface other code depends on -- an endpoint, "
                "a command-line surface, a returned shape, or a module's public functions?"
            ),
            "has_infra": _noul(
                "Does `issue` touch infrastructure, deployment, or hosting configuration?"
            ),
            "has_privacy": _noul(
                "Does `issue` involve personal data, customer content, retention, or consent?"
            ),
            "has_refactor": _noul(
                "Is `issue` substantially a restructuring of existing code rather than "
                "new behaviour?"
            ),
            "production": _noul(
                "Does `issue` describe a change to a production system?",
                APPROVAL_BOUNDARY_POLICY,
            ),
            "destructive": _noul(
                "Does `issue` describe a destructive operation -- deleting, dropping, "
                "overwriting or otherwise discarding something not trivially recoverable?",
                APPROVAL_BOUNDARY_POLICY,
            ),
            "credentials": _noul(
                "Does `issue` describe creating, rotating, moving or changing a secret "
                "or a credential?",
                APPROVAL_BOUNDARY_POLICY,
            ),
            "permissions": _noul(
                "Does `issue` describe an identity or permission change -- a role, a "
                "policy, an access grant or a scope?",
                APPROVAL_BOUNDARY_POLICY,
            ),
            "billing": _noul(
                "Does `issue` describe an action that costs money or changes what is spent?",
                APPROVAL_BOUNDARY_POLICY,
            ),
            "external_commitments": _noul(
                "Does `issue` describe a commitment to someone outside this repository?",
                APPROVAL_BOUNDARY_POLICY,
            ),
            "process_authority": _noul(
                "Does `issue` describe a change to team structure, decision authority, "
                "or a process that governs how work is approved?",
                APPROVAL_BOUNDARY_POLICY,
            ),
        },
    ),
    "journal-nudge": Verb(
        name="journal-nudge",
        summary="Whether a commit earns an engineering-journal entry",
        state_help='the commit, as {"message": "...", "files": ["..."]}',
        # 0.60: the whole cost of an eager answer here is one advisory line on
        # standard error, so this decision can afford to be readier than the
        # issue flags above.  Provisional on the same terms.
        confidence_floor=0.60,
        questions={
            "earns_entry": _noul(
                "Does the commit described by `message` and `files` record a non-obvious "
                "mechanism or a pattern decision worth a durable journal entry?",
                JOURNAL_POLICY,
            ),
        },
    ),
    "readiness": Verb(
        name="readiness",
        summary="Whether an idea is ready to be planned",
        state_help='the idea, as {"idea": "..."}',
        questions={
            "ready": _noul("Is `idea` settled enough to plan without more discovery?"),
            "scope_clear": _noul("Is the scope of `idea` unambiguous?"),
        },
    ),
}


def verb_names() -> tuple[str, ...]:
    return tuple(sorted(VERBS))


__all__: Sequence[str] = (
    "APPROVAL_BOUNDARY_POLICY",
    "JOURNAL_POLICY",
    "TIER_POLICY",
    "VERBS",
    "Verb",
    "verb_names",
)
