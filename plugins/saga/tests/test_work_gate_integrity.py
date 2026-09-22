"""U1 #928 — merge-gate integrity pins.

Validates that saga.py save refuses non-canonical gate verdicts via the existing
parse_gate_verdict, preserves colon-bearing refs, records change_kinds, and
splits the override flag so the audit trail names its gate.

Carried from infiquetra-claude-plugins@acc99fe7 (upstream 1.2.0). Only the module
bootstrap changed: this package's tests sit under ``plugins/saga/tests/`` rather
than at a repository root, so ``ROOT`` walks up four levels instead of two.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORK_SKILL = ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md"
CODE_REVIEW_SKILL = ROOT / "plugins" / "saga" / "skills" / "code-review" / "SKILL.md"
SAGA_PY = ROOT / "plugins" / "saga" / "scripts" / "saga.py"


# The single-sourcing clause section 4.1 must carry. Until issue #1027 this pinned the writeup's
# change_kinds value to the hard test gate's input. That gate was removed with the risk-gated test
# prose, so the clause now pins the writeup to the BUILD LOOP's recorded criterion -- the same
# property (one authority, rendered once, never re-derived) about the thing that replaced it.
_SINGLE_SOURCE_CLAUSE = re.compile(
    r"criterion\s+the\s+loop\s+ran\s+and\s+the\s+criterion\s+the\s+record\s+holds"
    r"\s+as\s+the\s+same\s+thing",
    re.IGNORECASE,
)


def _issue_progress():
    """Load `issue_progress` BY PATH, the way almost every module in this suite loads a plugin script.

    The package form `from plugins.saga.scripts import ...` resolves against whatever `plugins`
    package `find_spec` reaches first, which is the primary checkout when the worktree under test is
    nested beneath it -- so the module under test is not necessarily the module in this tree.
    """
    import importlib.util

    path = ROOT / "plugins" / "saga" / "scripts" / "issue_progress.py"
    spec = importlib.util.spec_from_file_location("_issue_progress_for_gate_integrity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    # Registered BEFORE exec: `dataclasses` resolves a string annotation through
    # `sys.modules[cls.__module__]`, so a frozen dataclass in the module under load fails to build
    # if its own name is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _saga_module():
    """Load `saga.py` by path, for the same reason `_issue_progress` does."""
    import importlib.util

    path = ROOT / "plugins" / "saga" / "scripts" / "saga.py"
    spec = importlib.util.spec_from_file_location("_saga_for_gate_integrity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    # Registered BEFORE exec: `dataclasses` resolves a string annotation through
    # `sys.modules[cls.__module__]`, so a frozen dataclass in the module under load fails to build
    # if its own name is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_skill() -> str:
    return WORK_SKILL.read_text(encoding="utf-8")


def _section(text: str, start_heading: str, end_heading: str) -> str:
    s = text.find(start_heading)
    e = text.find(end_heading, s + len(start_heading))
    assert s >= 0, f"missing heading {start_heading}"
    assert e >= 0, f"missing heading {end_heading}"
    return text[s:e]


def _run_save(tmp_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(SAGA_PY),
        "save",
        "--id",
        "999",
        *extra_args,
    ]
    return subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, timeout=10)


# ---------------------------------------------------------------------------
# Happy path — valid verdicts save byte-identical
# ---------------------------------------------------------------------------


def test_valid_verdict_saves_byte_identical(tmp_path: Path) -> None:
    verdict = "tests:done:abc123"
    result = _run_save(tmp_path, "--gate-verdict", verdict)
    assert result.returncode == 0, f"valid save failed: {result.stderr}"
    # Verify stored value is byte-identical via restore.
    restore = subprocess.run(
        [sys.executable, str(SAGA_PY), "restore", "--saga-id", "issue-999"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert restore.returncode == 0
    import json

    payload = json.loads(restore.stdout)
    assert payload["gate_verdicts"] == [verdict]


def test_valid_verdict_with_colon_ref_survives_intact(tmp_path: Path) -> None:
    verdict = "tests:done:https://github.com/o/r/pull/9"
    result = _run_save(tmp_path, "--gate-verdict", verdict)
    assert result.returncode == 0, f"colon-bearing ref save failed: {result.stderr}"
    import json

    restore = subprocess.run(
        [sys.executable, str(SAGA_PY), "restore", "--saga-id", "issue-999"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    payload = json.loads(restore.stdout)
    assert payload["gate_verdicts"] == [verdict]
    # Also direct parse preserves ref.
    saga_mod = _saga_module()

    g, s, ref = saga_mod.parse_gate_verdict(verdict)
    assert g == "tests" and s == "done" and ref == "https://github.com/o/r/pull/9"


# ---------------------------------------------------------------------------
# Error path — malformed verdicts are refused at save time with error at exit 2
# ---------------------------------------------------------------------------


def test_malformed_verdict_noncanonical_state_is_refused(tmp_path: Path) -> None:
    result = _run_save(tmp_path, "--gate-verdict", "tests:pass:abc123")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}: {result.stderr} / {result.stdout}"
    )
    assert "error:" in result.stderr.lower()
    # Parser message must name the six canonical states.
    assert "must be one of" in result.stderr.lower()
    for state in ("done", "in-progress", "blocked", "failed", "halted", "not-reached"):
        assert state in result.stderr
    # No envelope and no state.json entry written.
    sagas_dir = tmp_path / ".claude" / "saga" / "sagas" / "issue-999"
    if sagas_dir.exists():
        assert list(sagas_dir.glob("*.md")) == []
    state_path = tmp_path / ".claude" / "saga" / "state.json"
    if state_path.exists():
        import json

        state = json.loads(state_path.read_text(encoding="utf-8"))
        sagas = state.get("sagas", {})
        assert "issue-999" not in sagas


def test_malformed_verdict_no_colon_is_refused(tmp_path: Path) -> None:
    result = _run_save(tmp_path, "--gate-verdict", "garbage")
    assert result.returncode == 2
    assert "error:" in result.stderr.lower()
    assert "no colon" in result.stderr.lower() or "colon" in result.stderr.lower()
    sagas_dir = tmp_path / ".claude" / "saga" / "sagas" / "issue-999"
    if sagas_dir.exists():
        assert list(sagas_dir.glob("*.md")) == []
    # Also test only one colon.
    result2 = _run_save(tmp_path, "--gate-verdict", "tests:done")
    assert result2.returncode == 2
    assert "error:" in result2.stderr.lower()


# ---------------------------------------------------------------------------
# change_kinds — writeup records the derived value and single-sources the gate
# ---------------------------------------------------------------------------


def test_work_writeup_single_sources_the_build_loop_criterion() -> None:
    """The writeup and the run record must be ONE criterion, and the section must say so.

    `assert "same" in collapsed.lower()` was once the whole single-sourcing check, and the word
    "same" appears in ordinary prose for a hundred unrelated reasons -- it could not distinguish
    the contract from a sentence that happened to contain it. This asserts the clause itself, and
    the control below proves it discriminates.

    Issue #1027 moved what the clause pins. The hard test gate is gone, so there is no gate input
    to single-source any more; what a second derivation would now corrupt is the build loop's
    recorded result, and a writeup that re-derived a criterion of its own would reintroduce exactly
    the drift the written criterion was built to remove.
    """
    text = _read_skill()
    sec = _section(text, "### 4.1 ", "### 4.2 ")
    collapsed = " ".join(sec.split())
    assert "change_kinds" in sec, "the derived value is still recorded, it just gates nothing"
    assert "requires_hard_test_gate" not in collapsed, (
        "the hard test gate was removed in #1027; section 4.1 must not feed a gate that is gone"
    )
    assert "build_loop" in collapsed, "the writeup must name the block it renders"
    assert _SINGLE_SOURCE_CLAUSE.search(collapsed), (
        "section 4.1 must state that the criterion the loop ran and the criterion the record "
        "holds are the same thing, not two derivations"
    )
    assert "verbatim" in collapsed, "the recorded value must be required to be verbatim"


def _lifecycle_state():
    """Load `lifecycle_state` BY PATH, for the same reason `_issue_progress` does."""
    import importlib.util

    path = ROOT / "plugins" / "saga" / "scripts" / "lifecycle_state.py"
    spec = importlib.util.spec_from_file_location("_lifecycle_state_for_gate_integrity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_change_kinds_gate_is_driven_not_merely_described() -> None:
    """The clause was pinned by prose grep alone; the derivation it describes was never called.

    A prose test proves the section SAYS the writeup value and the gate input are one list. It
    cannot prove the function behind that claim behaves as described -- setting the risky set to
    empty left 1608 tests green, because nothing in the suite asked the derivation a question."""
    lifecycle = _lifecycle_state()
    # Every risky kind the section names must actually demand the hard gate, one at a time.
    for kind in ("behavior", "security", "infra", "api", "deployment", "data"):
        assert lifecycle.requires_hard_test_gate([kind]) is True, kind
        assert lifecycle.requires_hard_test_gate([kind.upper()]) is True, kind
    # Control: the gate must DISCRIMINATE, or "always True" would pass the loop above.
    assert lifecycle.requires_hard_test_gate([]) is False
    assert lifecycle.requires_hard_test_gate(["docs"]) is False
    assert lifecycle.requires_hard_test_gate(["docs", "chore"]) is False
    # One risky kind among safe ones still demands the gate -- the list is a union, not a vote.
    assert lifecycle.requires_hard_test_gate(["docs", "security"]) is True


def test_the_single_source_clause_pattern_discriminates() -> None:
    """Control: the pattern must reject prose that merely contains the word "same"."""
    assert _SINGLE_SOURCE_CLAUSE.search(
        "record the criterion the loop ran and the criterion the record holds as the same thing, "
        "not as two derivations"
    )
    assert not _SINGLE_SOURCE_CLAUSE.search(
        "run the tests in the same directory as the plan, then record the same day's date"
    )


# ---------------------------------------------------------------------------
# Override split — helper refuses unnamed waiver, comment distinguishes gates
# ---------------------------------------------------------------------------


def test_override_without_gate_is_refused() -> None:
    ip = _issue_progress()

    with pytest.raises(ValueError):
        ip._override_line(None, "some rationale")
    with pytest.raises(ValueError):
        ip._override_line("", "some rationale")
    with pytest.raises(ValueError):
        ip._override_line("unknown-gate", "rationale")
    # Absent rationale yields no line, not a raise.
    assert ip._override_line("doc-review", None) is None
    assert ip._override_line("doc-review", "") is None
    assert ip._override_line("review-gate", None) is None


def test_override_renders_distinguishable_labels() -> None:
    ip = _issue_progress()

    doc_comment = ip.render_issue_comment(
        event="phase",
        issue_ref="o/r#1",
        destination="pr",
        doc_review_override="doc rationale",
    )
    review_comment = ip.render_issue_comment(
        event="phase",
        issue_ref="o/r#1",
        destination="pr",
        review_gate_override="review rationale",
    )
    assert "doc review override" in doc_comment
    assert "review rationale" not in doc_comment
    assert "review gate override" in review_comment
    assert "doc rationale" not in review_comment
    # Both distinguishable when both present.
    both = ip.render_issue_comment(
        event="phase",
        issue_ref="o/r#1",
        destination="pr",
        doc_review_override="doc",
        review_gate_override="rev",
    )
    assert "doc review override" in both
    assert "review gate override" in both
    assert both.count("override") == 2


def test_issue_progress_cli_both_flags_render() -> None:
    cmd = [
        sys.executable,
        str(ROOT / "plugins" / "saga" / "scripts" / "issue_progress.py"),
        "--event",
        "phase",
        "--issue-ref",
        "o/r#1",
        "--destination",
        "pr",
        "--doc-review-override",
        "doc override text",
        "--review-gate-override",
        "review override text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert "doc review override" in result.stdout
    assert "review gate override" in result.stdout


# ---------------------------------------------------------------------------
# Anti-regression — merge confirmation, four outcomes, programmatic writes nothing
# ---------------------------------------------------------------------------


def test_merge_confirmation_still_present() -> None:
    """The confirmation must outlive the mechanism that used to carry it.

    This guard used to assert two literal ceremony invocations -- `run --operator-confirmed merge`
    and `run --operator-confirmed branch_delete`. That pinned the MECHANISM, so when issue #1027
    removed the ship ceremony the guard failed for a change it should have permitted, while a
    change that quietly dropped the confirmation and kept the strings would have passed it. It now
    asserts the property: issue #1029's preservation contract says the pull-request open, the
    review request and the merge each stay explicitly confirmed, whatever runs them.
    """
    text = _read_skill()
    collapsed = " ".join(text.split())
    assert "explicitly confirmed" in collapsed, (
        "the preservation contract from #1029 must be stated somewhere in the skill"
    )

    boundary = _section(text, "### 5.5 ", "\n---")
    boundary_collapsed = " ".join(boundary.split())
    # The exact phrase issue #938's anti-regression pin and this guard both hold. Keeping one
    # wording across both means a rewrite cannot satisfy one guard while breaking the other.
    assert "PR-open, review-request, and merge are each explicitly confirmed" in boundary_collapsed
    assert "silently mutate" in boundary_collapsed


def test_four_typed_review_outcomes_still_pinned() -> None:
    text = _read_skill()
    gate = _section(text, "### 5.3 ", "### 5.4 ")
    outcomes = tuple(re.findall(r"^- \*\*`([^`]+)`\*\* —", gate, flags=re.MULTILINE))
    assert outcomes == (
        "accepted",
        "repairs_requested",
        "cycle_cap_best_available",
        "review_incomplete",
    )


def test_skill_names_gate_verdict_validation_at_save() -> None:
    text = _read_skill()
    sec = _section(text, "### 4.2 ", "### 4.3 ")
    collapsed = " ".join(sec.split()).lower()
    assert "parse_gate_verdict" in collapsed
    assert "refuses" in collapsed or "refuse" in collapsed
    assert "error:" in collapsed
    assert "exit 2" in collapsed


def test_skill_override_flag_names_its_gate() -> None:
    text = _read_skill()
    # Phase 1.3 doc-review gate uses doc flag, 5.3 review gate uses review flag.
    assert "--doc-review-override" in text
    assert "--review-gate-override" in text
    # 4.3 explains the two flags map to distinct labels.
    sec43 = _section(text, "### 4.3 ", "### 4.4 ")
    assert "doc review override" in sec43
    assert "review gate override" in sec43
