"""Plan-artifact conformance — issue #922 (unit U1), repaired per review F06t.

The conformance check itself ships as ``plugins/saga/scripts/plan_artifact_conformance.py``
(review F06t: the shipped contract must be callable, not only enforced when pytest runs).
This file IMPORTS that module and exercises it; it does not redefine any of it. The
definition pins (marker triple, required-field set) parse the markdown declarations and
bind the shipped constants to them.

None of these tests asserts a Plan question, its wording, or the order of the conversation
(R29): the rigidity guard is asserted as the absence of rigid prose shapes in the Phase 0
intake subsection, and the corpus assertions stay relational — exit and non-empty report,
never a count or a file name (R33, obligation 7): the nested-corpus guard derives its
instances from the corpus on disk instead of naming one.

Mutation wiring (issue 924's mutation proof, now against shipped code):

* removing the required-field rule from the shipped check fails the incomplete-plan
  assertions (the fixture is reported only by that rule);
* deleting the marker half of the shipped check fails the single-pass test;
* deleting the recursion fails the nested-report test;
* re-defining any check function in this file fails the imported-not-duplicated pin.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLANS_ROOT = REPO_ROOT / "docs" / "plans"
PLAN_SKILL_MD = REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md"
PLAN_SECTIONS_MD = (
    REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "references" / "plan-sections.md"
)
CONFORMANCE_SCRIPT = REPO_ROOT / "plugins" / "saga" / "scripts" / "plan_artifact_conformance.py"


def _load_conformance() -> ModuleType:
    """Load the SHIPPED conformance module — the check under test (review F06t).

    Registered in ``sys.modules`` under its bare name: it defines a frozen
    ``@dataclass`` and (on Python 3.12+) dataclass processing looks the class's
    ``__module__`` up in ``sys.modules`` while building it.
    """
    spec = importlib.util.spec_from_file_location("plan_artifact_conformance", CONFORMANCE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["plan_artifact_conformance"] = module
    spec.loader.exec_module(module)
    return module


CONFORMANCE = _load_conformance()

# The contract surface, bound from the shipped module — never redefined here (F06t).
MARKER_IMPLEMENTATION_UNITS = CONFORMANCE.MARKER_IMPLEMENTATION_UNITS
MARKER_KEY_TECHNICAL_DECISIONS = CONFORMANCE.MARKER_KEY_TECHNICAL_DECISIONS
MARKER_U1_PREFIX_LABEL = CONFORMANCE.MARKER_U1_PREFIX_LABEL
U1_PREFIX_RE = CONFORMANCE.U1_PREFIX_RE
BACKEND_ENUM = CONFORMANCE.BACKEND_ENUM
REQUIRED_FIELDS = CONFORMANCE.REQUIRED_FIELDS
KIND_LEGACY_NO_BACKEND = CONFORMANCE.KIND_LEGACY_NO_BACKEND
KIND_MISSING_REQUIRED_FIELD = CONFORMANCE.KIND_MISSING_REQUIRED_FIELD
KIND_BACKEND_NOT_IN_ENUM = CONFORMANCE.KIND_BACKEND_NOT_IN_ENUM
KIND_MARKER_MISSING = CONFORMANCE.KIND_MARKER_MISSING
Finding = CONFORMANCE.Finding
check_document = CONFORMANCE.check_document
check_plan_corpus = CONFORMANCE.check_plan_corpus
corpus_exit = CONFORMANCE.corpus_exit


# --- F06t: the check is imported, not duplicated, and runnable ------------------------


def test_the_conformance_check_is_imported_not_duplicated() -> None:
    # Review F06t: the plan's three mutation proofs must mutate shipped code, not the
    # test. Re-defining any check function here would let the test mutate itself again,
    # so this pin fails on any local re-definition.
    assert check_document.__module__ == "plan_artifact_conformance"
    assert check_plan_corpus.__module__ == "plan_artifact_conformance"
    assert corpus_exit.__module__ == "plan_artifact_conformance"
    source = Path(__file__).read_text(encoding="utf-8")
    # Probe strings assembled at runtime so the pin never matches its own literals.
    for name in ("check_document", "check_plan_corpus", "corpus_exit", "split_frontmatter"):
        probe = "def " + name
        assert probe not in source, f"{probe!r} redefined in the test — import it instead"


def test_the_shipped_conformance_module_runs_as_a_real_subprocess() -> None:
    # Review F06t: the operator can run the contract — a real subprocess, not an
    # in-process fixture. Exit matches the reported corpus_exit.
    proc = subprocess.run(
        [sys.executable, str(CONFORMANCE_SCRIPT), str(PLANS_ROOT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    payload = json.loads(proc.stdout)
    assert payload["findings"], "the corpus report must not be empty"
    assert proc.returncode == payload["exit"]
    assert proc.returncode == 0, "no new-contract document fails the contract today"


# --- fixture builders ---------------------------------------------------------------


def _frontmatter(**fields: object) -> str:
    lines = ["---", *[f"{name}: {value}" for name, value in fields.items()], "---"]
    return "\n".join(lines) + "\n"


# Body satisfying all three markers of the triple.
MARKER_BODY = """
# Fixture plan

## Implementation Units

### U1. The only unit

Do the thing.

## Key Technical Decisions

**KTD1: Do the thing.** Because it is the thing.
"""

# Body satisfying the frontmatter-adjacent expectations but missing the
# `Key Technical Decisions` marker.
BODY_MISSING_KTD = """
# Fixture plan

## Implementation Units

### U1. The only unit

Do the thing.

## Design notes

No decisions section here.
"""

NEW_CONTRACT_FRONTMATTER = {
    "title": "Fixture plan",
    "type": "feat",
    "status": "active",
    "date": "2026-08-30",
    "backend": "inline",
}


# --- positive: the contract, and the single pass -------------------------------------


def test_new_contract_plan_conforms_with_no_findings(tmp_path: Path) -> None:
    corpus = tmp_path / "plans"
    corpus.mkdir()
    good = corpus / "good-plan.md"
    good.write_text(_frontmatter(**NEW_CONTRACT_FRONTMATTER) + MARKER_BODY, encoding="utf-8")
    # Mutation mate for the required-field rule: same corpus, one required field absent.
    # Deleting the required-field rule from the SHIPPED check would leave this document
    # unreported, so this assertion — not the clean pass above — fails on that mutation.
    incomplete = corpus / "incomplete-plan.md"
    missing_status = {k: v for k, v in NEW_CONTRACT_FRONTMATTER.items() if k != "status"}
    incomplete.write_text(_frontmatter(**missing_status) + MARKER_BODY, encoding="utf-8")

    findings = check_plan_corpus(corpus)

    assert [f for f in findings if f.path == good] == []
    reported = [f for f in findings if f.path == incomplete]
    assert any(f.kind == KIND_MISSING_REQUIRED_FIELD and "`status`" in f.detail for f in reported)
    assert corpus_exit(findings) == 1


def test_single_pass_reports_frontmatter_and_markers_together(tmp_path: Path) -> None:
    corpus = tmp_path / "plans"
    corpus.mkdir()
    doc = corpus / "frontmatter-ok-markers-bad.md"
    doc.write_text(_frontmatter(**NEW_CONTRACT_FRONTMATTER) + BODY_MISSING_KTD, encoding="utf-8")

    # The same call that validates the frontmatter also evaluates the marker half: the
    # document satisfies the frontmatter contract and fails the marker triple, and both
    # verdicts come out of one pass. Deleting the marker half of the SHIPPED check
    # removes the finding this test asserts on.
    findings = check_plan_corpus(corpus)

    assert not any(f.kind == KIND_MISSING_REQUIRED_FIELD for f in findings)
    assert not any(f.kind == KIND_BACKEND_NOT_IN_ENUM for f in findings)
    marker_findings = [f for f in findings if f.path == doc and f.kind == KIND_MARKER_MISSING]
    assert any(MARKER_KEY_TECHNICAL_DECISIONS in f.detail for f in marker_findings)
    assert corpus_exit(findings) == 1


# --- negative: the legacy rule (KTD3) -------------------------------------------------


def test_missing_backend_is_legacy_reported_and_never_fails(tmp_path: Path) -> None:
    corpus = tmp_path / "plans"
    corpus.mkdir()
    legacy_plan = corpus / "legacy-plan.md"
    legacy_fields = {k: v for k, v in NEW_CONTRACT_FRONTMATTER.items() if k != "backend"}
    legacy_plan.write_text(_frontmatter(**legacy_fields) + MARKER_BODY, encoding="utf-8")
    # Whatever else it contains: no frontmatter and no markers at all.
    odd = corpus / "odd.md"
    odd.write_text("# Not much of anything\n\nNo frontmatter, no markers.\n", encoding="utf-8")

    findings = check_plan_corpus(corpus)

    assert findings, "legacy documents are reported, not silently skipped"
    assert all(f.legacy for f in findings)
    assert {f.path for f in findings if f.kind == KIND_LEGACY_NO_BACKEND} == {
        legacy_plan,
        odd,
    }
    assert any(f.path == odd and f.kind == KIND_MARKER_MISSING for f in findings)
    assert corpus_exit(findings) == 0


def test_stripped_backend_field_is_reported_without_failing(tmp_path: Path) -> None:
    # The "new document, missing required field" case, distinct from the plain legacy
    # fixture above (review F26): it is authored as a new-contract document — carrying
    # every other required field and the new-contract markers — and then stripped of
    # `backend:`. KTD3 makes absence the legacy signal, and that class cannot exist in
    # the real corpus by construction, so the test asserts the report, never corpus
    # membership.
    corpus = tmp_path / "plans"
    corpus.mkdir()
    doc = corpus / "stripped-plan.md"
    authored = _frontmatter(**NEW_CONTRACT_FRONTMATTER) + MARKER_BODY
    stripped = "\n".join(line for line in authored.splitlines() if not line.startswith("backend:"))
    doc.write_text(stripped + "\n", encoding="utf-8")

    findings = check_plan_corpus(corpus)

    assert [f.kind for f in findings] == [KIND_LEGACY_NO_BACKEND]
    assert all(f.legacy and not f.failing for f in findings)
    assert corpus_exit(findings) == 0


# --- negative: recursion under the scanned root ---------------------------------------


def test_check_recurses_into_subdirectories(tmp_path: Path) -> None:
    corpus = tmp_path / "plans"
    nested_dir = corpus / "sub" / "nested"
    nested_dir.mkdir(parents=True)
    nested = nested_dir / "nested-report.md"
    nested.write_text("# Nested report\n\nNo frontmatter, no plan markers.\n", encoding="utf-8")

    # Deleting the recursion (rglob -> glob) from the SHIPPED check removes the nested
    # document from the pass, which is the mutation this test fails on.
    findings = check_plan_corpus(corpus)

    assert any(f.path == nested and f.kind == KIND_MARKER_MISSING for f in findings)
    assert corpus_exit(findings) == 0  # no backend -> legacy -> reported, non-failing


def test_real_corpus_report_reaches_nested_documents() -> None:
    # Obligation 7 / R33: no corpus file name and no count pinned — the corpus itself
    # supplies the instances. The single pass must reach documents below the top level
    # of docs/plans (recursion) and report the non-conforming ones there; deleting the
    # recursion from the SHIPPED check empties the nested report and fails this test.
    nested_in_corpus = [p for p in PLANS_ROOT.rglob("*.md") if p.parent != PLANS_ROOT]
    if not nested_in_corpus:
        pytest.skip("this catalog's docs/plans has no nested markdown for the corpus pass")

    findings = check_plan_corpus(PLANS_ROOT)

    nested_in_report = [f for f in findings if f.path.parent != PLANS_ROOT]
    assert nested_in_report, (
        "the corpus holds nested markdown, so the pass must reach it and report the "
        "non-conforming documents there — never accept one silently for its path"
    )
    assert any(f.kind == KIND_MARKER_MISSING for f in nested_in_report), (
        "the nested corpus documents are not plan artifacts; the pass must say so"
    )


def test_real_corpus_produces_a_report_and_zero_exit() -> None:
    findings = check_plan_corpus(PLANS_ROOT)

    # The assertion is on the exit and on the report being non-empty — never on a count
    # or on a file name (R33).
    assert findings
    assert corpus_exit(findings) == 0


# --- contract pin: the marker triple definition ---------------------------------------


def test_marker_triple_definition_is_pinned_unchanged() -> None:
    # Definition pin (R6), not a classification test: Document Review's recognition
    # prose lives in doc-review/SKILL.md, this unit does not own that file, and no
    # home-grown classifier stands in for it. Pin the tokens as declared in
    # plan/SKILL.md so a later edit cannot silently redefine what makes a document a
    # plan — on either side. Since F06t the constants bind to the SHIPPED module, so
    # these cross-checks are no longer tautologies (review F27): they fail if the
    # shipped constants and the declaration drift apart.
    text = PLAN_SKILL_MD.read_text(encoding="utf-8")
    declaration = next(
        (para for para in text.split("\n\n") if "recognize the document as a plan" in para),
        None,
    )
    assert declaration is not None, "plan recognition sentence disappeared from plan/SKILL.md"
    assert "Implementation Units" in declaration
    assert "Key Technical Decisions" in declaration
    assert "`U1` U-ID prefix" in declaration
    assert MARKER_IMPLEMENTATION_UNITS == "Implementation Units"
    assert MARKER_KEY_TECHNICAL_DECISIONS == "Key Technical Decisions"
    assert MARKER_IMPLEMENTATION_UNITS in declaration
    assert MARKER_KEY_TECHNICAL_DECISIONS in declaration


# --- contract pin: the required-field set (U1's required-backend change) --------------


def test_required_field_set_is_pinned_to_both_declarations() -> None:
    # Definition pin (review F01/F06), matching the marker-triple pin above. The
    # required-field contract is declared in two markdown surfaces; this pin parses
    # both and binds the SHIPPED check's REQUIRED_FIELDS constant to them, so reverting
    # the required-backend rule in either declaration fails here instead of passing
    # vacuously against a test-local tuple.
    sections_text = PLAN_SECTIONS_MD.read_text(encoding="utf-8")
    bullet = next(
        (
            line
            for line in sections_text.splitlines()
            if "are required on every newly created plan" in line
        ),
        None,
    )
    assert bullet is not None, "required-field bullet disappeared from plan-sections.md"
    declared = tuple(re.findall(r"`(\w+)`", bullet))
    assert "backend" in declared, "plan-sections.md no longer names backend as required"
    assert declared == REQUIRED_FIELDS, (
        f"plan-sections.md declares {declared}, the check enforces {REQUIRED_FIELDS}"
    )

    skill_collapsed = " ".join(PLAN_SKILL_MD.read_text(encoding="utf-8").split())
    assert "`backend:` is required on every newly created plan" in skill_collapsed, (
        "plan/SKILL.md lost its required-backend sentence"
    )
