"""Handoff maturity — frontmatter-aware inference (KTD7, issue 913 B1)."""

from __future__ import annotations

import importlib.util
import os
import shlex
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
HANDOFF_PATH = ROOT / "plugins/saga/scripts/handoff_envelope.py"


def _load() -> ModuleType:
    if str(HANDOFF_PATH.parent) not in sys.path:
        sys.path.insert(0, str(HANDOFF_PATH.parent))
    spec = importlib.util.spec_from_file_location("handoff_envelope_maturity", HANDOFF_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HE: ModuleType = _load()


@pytest.fixture(autouse=True)
def _isolated_git_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Envelope classification tests do not need repository metadata or subprocesses."""
    monkeypatch.setattr(HE, "current_git_state", lambda root: {"branch": "", "head": ""})


def _write_file(path: Path, maturity: str | None) -> None:
    if maturity is None:
        path.write_text("# No frontmatter\n\nBody.\n", encoding="utf-8")
        return
    path.write_text(
        f"---\ndate: 2026-08-30\ntopic: test-topic\nmaturity: {maturity}\n---\n\nBody.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Frontmatter wins — pending-confirmation declared in file.
# ---------------------------------------------------------------------------


def test_frontmatter_maturity_pending_confirmation_wins(tmp_path: Path) -> None:
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-test-topic-requirements.md"
    _write_file(target, "pending-confirmation")
    # Absolute path case (tmp_path file).
    assert HE.infer_maturity(str(target)) == "pending-confirmation"


def test_frontmatter_maturity_requirements_ready_wins(tmp_path: Path) -> None:
    # Relocated to a directory whose path rule disagrees (ideation -> idea-ready) so
    # removing the frontmatter reader flips the result.
    ideation = tmp_path / "docs" / "ideation"
    ideation.mkdir(parents=True)
    target = ideation / "2026-08-30-test-topic-requirements.md"
    target.write_text("---\nmaturity: requirements-ready\n---\n\nBody\n", encoding="utf-8")
    assert HE.infer_maturity(str(target)) == "requirements-ready"
    assert (
        HE.infer_maturity("docs/ideation/2026-08-30-test-topic-requirements.md", root=tmp_path)
        == "requirements-ready"
    )


# ---------------------------------------------------------------------------
# Path inference preserved — pre-existing return values unchanged when no
# declared maturity exists (file missing declaration or path not on disk).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("docs/brainstorms/2026-08-30-topic-requirements.md", "requirements-ready"),
        ("docs/ideation/2026-08-30-topic-ideation.md", "idea-ready"),
        ("docs/plans/2026-08-30-topic-plan.md", "plan-ready"),
        ("docs/specs/2026-08-30-topic-spec.md", "requirements-ready"),
        ("docs/work-sessions/2026-08-30-topic-session.md", "resume-ready"),
        ("branch:feature/foo", "resume-ready"),
    ],
)
def test_path_inference_preserved_when_no_declared_maturity(source: str, expected: str) -> None:
    # No file on disk for this source — falls through to path inference.
    assert HE.infer_maturity(source) == expected


def test_path_inference_preserved_for_brainstorms_file_without_maturity(tmp_path: Path) -> None:
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-topic-requirements.md"
    _write_file(target, None)
    # File exists but declares no maturity — path rule applies.
    assert HE.infer_maturity(str(target)) == "requirements-ready"


# ---------------------------------------------------------------------------
# Missing file — no raise, path rule fallback.
# ---------------------------------------------------------------------------


def test_missing_file_falls_back_to_path_rule_and_raises_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "docs" / "brainstorms" / "no-such-file.md"
    # Must not raise; must return path-based value.
    result = HE.infer_maturity(str(missing))
    assert result == "requirements-ready"
    # Non-brainstorms missing path.
    assert HE.infer_maturity("docs/plans/missing.md") == "plan-ready"
    assert HE.infer_maturity("branch:foo") == "resume-ready"


def test_out_of_domain_declared_value_falls_through(tmp_path: Path) -> None:
    ideation = tmp_path / "docs" / "ideation"
    ideation.mkdir(parents=True)
    target = ideation / "2026-06-19-plugin-grooming-next-steps.md"
    target.write_text("---\nmaturity: ready-to-execute\n---\n\nBody\n", encoding="utf-8")
    # Unrecognized non-empty declared maturity now fails closed (API-03), not fall-through
    assert HE.infer_maturity(str(target)) == "unknown:unrecognized:ready-to-execute"
    envelope = HE.build_handoff_envelope(
        "docs/ideation/2026-06-19-plugin-grooming-next-steps.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_inline_comment_stripped(tmp_path: Path) -> None:
    # Use a value that differs from the path default so broken comment-stripping is detectable:
    # ideation's path rule is idea-ready, but pending-confirmation with trailing comment should win.
    ideation = tmp_path / "docs" / "ideation"
    ideation.mkdir(parents=True)
    target = ideation / "2026-08-30-topic-requirements.md"
    target.write_text(
        "---\nmaturity: pending-confirmation   # some note\n---\n\nBody\n", encoding="utf-8"
    )
    assert HE.infer_maturity(str(target)) == "pending-confirmation"
    assert (
        HE.infer_maturity("docs/ideation/2026-08-30-topic-requirements.md", root=tmp_path)
        == "pending-confirmation"
    )


def test_shell_shaped_value_rejected(tmp_path: Path) -> None:
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-topic-requirements.md"
    target.write_text("---\nmaturity: ; rm -rf ~\n---\n\nBody\n", encoding="utf-8")
    assert HE.infer_maturity(str(target)) == "unknown:unrecognized:; rm -rf ~"
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_non_utf8_file_does_not_raise(tmp_path: Path) -> None:
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-topic-requirements.md"
    target.write_bytes(b"---\nmaturity: requirements-ready\n---\n\nBody \xe9\n")
    # Must not raise UnicodeDecodeError; must fall through to path rule
    assert HE.infer_maturity(str(target)) == "requirements-ready"


def test_root_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-topic-requirements.md"
    _write_file(target, "pending-confirmation")
    # Plant a decoy at the same relative path under the cwd that declares a different maturity
    # — root must win even when cwd has a colliding file.
    other = tmp_path / "other"
    other.mkdir()
    decoy_dir = other / "docs" / "brainstorms"
    decoy_dir.mkdir(parents=True)
    (decoy_dir / "2026-08-30-topic-requirements.md").write_text(
        "---\nmaturity: requirements-ready\n---\n\nBody\n", encoding="utf-8"
    )
    monkeypatch.chdir(other)
    assert (
        HE.infer_maturity("docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path)
        == "pending-confirmation"
    )
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    )
    assert envelope["handoff_maturity"] == "pending-confirmation"
    # The decoy file lives inside the declared root (tmp_path/"other"), so by SEC-01
    # resolution it IS a trusted root-subtree path and its own frontmatter wins.
    assert (
        HE.infer_maturity(str(decoy_dir / "2026-08-30-topic-requirements.md"), root=tmp_path)
        == "requirements-ready"
    )
    # The true cwd-decoy case (SEC-01): cwd OUTSIDE the declared root, absolute path under
    # that cwd, same relative subpath — the untrusted absolute must re-anchor to the ROOT's
    # artifact, and the root-relative value ("pending-confirmation") must win with no route.
    # The decoy cwd is created inside a SEPARATE TemporaryDirectory (deleted afterward), so
    # cwd is never a subtree of the declared root — a cwd under tmp_path would be a trusted
    # root-subtree path instead.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as outside_raw:
        outside = Path(outside_raw).resolve() / "cwd-root"
        (outside / "docs" / "brainstorms").mkdir(parents=True)
        (outside / "docs" / "brainstorms" / "2026-08-30-topic-requirements.md").write_text(
            "---\nmaturity: requirements-ready\n---\n\nBody\n", encoding="utf-8"
        )
        monkeypatch.chdir(outside)
        assert (
            HE.infer_maturity(
                str(outside / "docs/brainstorms/2026-08-30-topic-requirements.md"), root=tmp_path
            )
            == "pending-confirmation"
        )
        envelope_outside = HE.build_handoff_envelope(
            str(outside / "docs/brainstorms/2026-08-30-topic-requirements.md"), root=tmp_path
        )
        assert envelope_outside["handoff_maturity"] == "pending-confirmation"
        assert "/issue --prepare" not in envelope_outside["suggested_command"]
    monkeypatch.chdir(tmp_path)
    # Sanity: an absolute path INSIDE the declared root still reads its frontmatter.
    assert HE.infer_maturity(str(target), root=tmp_path) == "pending-confirmation"
    # Also direct check: infer with root vs without
    assert HE.infer_maturity(str(target)) == "pending-confirmation"


def test_non_routable_guard(tmp_path: Path) -> None:
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-topic-requirements.md"
    _write_file(target, "pending-confirmation")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    )
    assert envelope["handoff_maturity"] == "pending-confirmation"
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_unrecognized_maturity_fails_closed(tmp_path: Path) -> None:
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    # Empty maturity
    target = brainstorms / "2026-08-30-topic-requirements.md"
    target.write_text("---\nmaturity: \n---\n\nBody\n", encoding="utf-8")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]
    # Misspelled value
    target.write_text("---\nmaturity: requirments-ready\n---\n\nBody\n", encoding="utf-8")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]
    # A frontmatter whose whole body is uniformly indented IS a top-level YAML mapping — there is
    # nothing for it to be nested under — so the declaration is honoured and the document fails
    # closed. The previous line-scanner contract called this "nested, therefore ignored" and fell
    # through to the path rule, routing a declared pending-confirmation live. That was a fail-open,
    # and pinning it here is why it survived five review cycles.
    target.write_text("---\n  maturity: pending-confirmation\n---\n\nBody\n", encoding="utf-8")
    assert (
        HE.infer_maturity("docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path)
        == "pending-confirmation"
    )
    # A genuinely nested key — under another mapping key — does not declare, and fails closed as a
    # carrier rather than falling through to the path rule.
    target.write_text(
        "---\nmeta:\n  maturity: pending-confirmation\n---\n\nBody\n", encoding="utf-8"
    )
    assert HE.infer_maturity(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    ).startswith("unknown:carrier:")


def test_maturity_vocabularies_in_sync() -> None:
    # Drift guard: parse_issue vocabulary must EQUAL HANDOFF_MATURITIES, saga-spec prose must
    # carry every value, and mission-control's consumer vocabulary is checked against an
    # explicit exclusion map (API-07) — see the block below for the recorded exclusion.
    handoff_mats = set(HE.HANDOFF_MATURITIES)  # type: ignore[attr-defined]
    # parse_issue.py vocabulary
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "parse_issue_check", ROOT / "plugins/saga/scripts/parse_issue.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = mod  # type: ignore[attr-defined]
    spec.loader.exec_module(mod)
    parse_vals = set(mod.HANDOFF_MATURITY_VALUES)  # type: ignore[attr-defined]
    assert parse_vals == handoff_mats, f"parse_issue vocab {parse_vals} != handoff {handoff_mats}"
    # saga-spec.md HANDOFF_MATURITIES tuple must also match
    spec_text = (ROOT / "plugins/saga/references/saga-spec.md").read_text(encoding="utf-8")
    assert "pending-confirmation" in spec_text
    for val in handoff_mats:
        assert val in spec_text, f"saga-spec missing {val}"
    # #942: mission-control no longer carries its own maturity vocabulary — it
    # delegates to this module's readiness-owner API, so the third (consumer)
    # vocabulary copy and its exclusion map are retired with it.


def test_non_delimited_frontmatter_carrier_fails_closed(tmp_path: Path) -> None:
    """AU-09: a maturity declared OUTSIDE a delimited YAML block must fail closed.

    A bullet-carrier document under docs/brainstorms/ declaring pending-confirmation used to
    fall through to the path rule and return requirements-ready with a live route — the more
    dangerous input got the softer treatment than a mere typo.
    """
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-topic-requirements.md"
    target.write_text(
        "# Some doc\n\n- date: 2026-08-30\n- maturity: pending-confirmation\n\nBody\n",
        encoding="utf-8",
    )
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    )
    assert envelope["handoff_maturity"].startswith("unknown:")
    assert "/issue --prepare" not in envelope["suggested_command"]
    # A file with NO maturity mention anywhere keeps the legacy path-default behaviour.
    plain = brainstorms / "2026-08-30-plain-requirements.md"
    plain.write_text("# No maturity here\n\nJust prose.\n", encoding="utf-8")
    assert HE.infer_maturity(str(plain)) == "requirements-ready"


def test_bom_prefixed_frontmatter_still_fails_closed(tmp_path: Path) -> None:
    """API-09/CORR-09: a byte-order mark must not make a declared maturity invisible."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-topic-requirements.md"
    target.write_bytes(b"\xef\xbb\xbf---\nmaturity: pending-confirmation\n---\n\nBody\n")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-topic-requirements.md", root=tmp_path
    )
    assert envelope["handoff_maturity"] == "pending-confirmation"
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_quoted_declared_maturity_resolves(tmp_path: Path) -> None:
    """TEST-09: quote-stripping is load-bearing — a quoted valid value must still route."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    double = brainstorms / "2026-08-30-double-requirements.md"
    double.write_text('---\nmaturity: "pending-confirmation"\n---\n\nBody\n', encoding="utf-8")
    assert HE.infer_maturity(str(double)) == "pending-confirmation"
    single = brainstorms / "2026-08-30-single-requirements.md"
    single.write_text("---\nmaturity: 'pending-confirmation'\n---\n\nBody\n", encoding="utf-8")
    assert HE.infer_maturity(str(single)) == "pending-confirmation"


def test_envelope_schema_version_pinned(tmp_path: Path) -> None:
    """AM-11: envelope schema_version literal carries a drift guard."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-schema-requirements.md"
    target.write_text("---\nmaturity: requirements-ready\n---\n\nBody\n", encoding="utf-8")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-schema-requirements.md", root=tmp_path
    )
    assert envelope["schema_version"] == "1.1"
    spec_text = (ROOT / "plugins/saga/references/saga-spec.md").read_text(encoding="utf-8")
    # Spec half must be the envelope versioning rule, not just any heading containing the substring.
    import re

    # TEST-32: derive the searched version from the envelope and anchor to the "currently"
    # clause. The historical "1.0 -> 1.1 is the precedent" parenthetical later on the same line
    # satisfies a loose regex even when the current clause has drifted, so the guard must pin
    # the clause that actually states today's value.
    version = envelope["schema_version"]
    anchored = (
        r"handoff envelope built by `handoff_envelope\.py` carries its own "
        rf"`schema_version` \(currently `\"{re.escape(version)}\"`\)"
    )
    assert re.search(anchored, spec_text, re.IGNORECASE), (
        f"saga-spec.md section 9 must state the envelope's current schema_version as {version!r} "
        "in its currently clause, not only in a historical parenthetical"
    )


def test_carrier_diagnostic_names_delimiters_not_vocabulary(tmp_path: Path) -> None:
    """AM-12: carrier diagnostic must name the missing delimiters, not the vocabulary."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-carrier-requirements.md"
    # Valid vocabulary value but declared outside delimited block (bullet carrier)
    target.write_text(
        "- maturity: pending-confirmation\n\nBody\n",
        encoding="utf-8",
    )
    assert HE.infer_maturity(str(target)).startswith("unknown:carrier:")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-carrier-requirements.md", root=tmp_path
    )
    assert envelope["handoff_maturity"].startswith("unknown:carrier:")
    assert "/issue --prepare" not in envelope["suggested_command"]
    # Diagnostic must name delimiters, not claim unrecognized value
    assert "delimited" in envelope["suggested_command"].lower()
    assert (
        "carrier" in envelope["suggested_command"].lower()
        or "delimiters" in envelope["suggested_command"].lower()
    )


def test_unterminated_frontmatter_block_fails_closed(tmp_path: Path) -> None:
    """API-13/CORR-15: unterminated block (opening --- without closing ---) must fail closed."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-unterminated-requirements.md"
    target.write_text(
        "---\nmaturity: pending-confirmation\n\nBody without closing delimiter", encoding="utf-8"
    )
    assert HE.infer_maturity(str(target)).startswith("unknown:unterminated:")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-unterminated-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]
    # Also test with bullet carrier inside unterminated? No, just ensure no route
    # And test that missing closing delimiter with valid routable value also fails closed
    target2 = brainstorms / "2026-08-30-unterminated2-requirements.md"
    target2.write_text("---\nmaturity: requirements-ready\n\nBody", encoding="utf-8")
    assert HE.infer_maturity(str(target2)).startswith("unknown:unterminated:")
    envelope2 = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-unterminated2-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope2["suggested_command"]


def test_sentinel_length_bound(tmp_path: Path) -> None:
    """TEST-14: sentinel truncation bounds unbounded author-controlled text."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-long-requirements.md"
    long_value = "x" * 300
    target.write_text(f"---\nmaturity: {long_value}\n---\n\nBody\n", encoding="utf-8")
    maturity = HE.infer_maturity(str(target))
    assert maturity.startswith("unknown:unrecognized:")
    # infer returns full raw; envelope truncates to 120 chars after prefix (API-12)
    assert len(maturity) == len("unknown:unrecognized:") + 300
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-long-requirements.md", root=tmp_path
    )
    # Truncation now marks the loss with an ellipsis (AU-28), so the bound is 120 + "…"
    assert len(envelope["handoff_maturity"]) == len("unknown:") + 121  # type: ignore[index]
    assert envelope["handoff_maturity"].endswith("…")  # type: ignore[index]
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_blank_carrier_fails_closed(tmp_path: Path) -> None:
    """TEST-15: blank-value non-delimited carrier must fail closed with bare sentinel."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-blank-carrier-requirements.md"
    target.write_text("- maturity: \n\nBody\n", encoding="utf-8")
    maturity = HE.infer_maturity(str(target))
    assert maturity == "unknown:carrier:"
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-blank-carrier-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_read_failure_fails_closed(tmp_path: Path) -> None:
    """API-15/CORR-15: read/decode failure must fail closed with distinct sentinel."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-unreadable-requirements.md"
    # Write bytes that are not valid UTF-8 and contain no recoverable frontmatter
    # (so the retry logic cannot extract a maturity and must return the unreadable sentinel)
    target.write_bytes(b"\xff\xfe\xfd\xfc\xfb")
    maturity = HE.infer_maturity(str(target))
    assert maturity == "unknown:unreadable"
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-unreadable-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]
    assert "unreadable" in envelope["suggested_command"].lower()
    # Valid frontmatter with invalid body byte should still be classified, not unreadable
    valid = brainstorms / "2026-08-30-valid-with-bad-body-requirements.md"
    valid.write_bytes(b"---\nmaturity: pending-confirmation\n---\n\nBody \xe9\n")
    assert HE.infer_maturity(str(valid)) == "pending-confirmation"


def test_reanchored_missing_twin_is_refused(tmp_path: Path) -> None:
    """SEC-1/TEST-10: a missing twin refuses even an unconfirmed original declaration."""
    # Root has no docs/brainstorms/b.md, but absolute file outside root declares pending-confirmation
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    (outside / "docs" / "brainstorms").mkdir(parents=True)
    abs_file = outside / "docs" / "brainstorms" / "2026-08-30-missing-reanchored-requirements.md"
    abs_file.write_text("---\nmaturity: pending-confirmation\n---\n\nBody\n", encoding="utf-8")
    # Ensure root has no such subpath
    assert not (
        root / "docs" / "brainstorms" / "2026-08-30-missing-reanchored-requirements.md"
    ).exists()
    maturity = HE.infer_maturity(str(abs_file), root=root)
    assert maturity.startswith("unknown:out-of-root:")
    envelope = HE.build_handoff_envelope(str(abs_file), root=root)
    assert envelope["handoff_maturity"].startswith("unknown:out-of-root:")
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_no_checked_in_artifact_declares_non_vocab_maturity() -> None:
    """CORR-17: repository check — no checked-in artifact declares a non-vocabulary maturity."""
    source_dirs = [
        ROOT / "docs" / d
        for d in ["ideation", "brainstorms", "specs", "plans", "reviews", "work-sessions"]
    ]
    bad: list[tuple[str, str]] = []
    for base in source_dirs:
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            # Use the shared helper so carrier and unterminated shapes are not skipped.
            declared = HE._read_frontmatter_maturity(path)  # type: ignore[attr-defined]
            if declared is None:
                continue
            # Empty string or any unknown:-prefixed sentinel means the checked-in file
            # declares a value outside the vocabulary (or a malformed block).
            # `_read_frontmatter_maturity` returns a vocabulary value, the empty string, or
            # an `unknown:`-prefixed sentinel, so these two cases cover everything outside
            # HANDOFF_MATURITIES without needing the vocabulary set itself.
            if declared == "" or declared.startswith("unknown:"):
                bad.append((str(path.relative_to(ROOT)), declared))
    assert not bad, (
        f"checked-in artifacts declare non-vocab maturity outside HANDOFF_MATURITIES: {bad}"
    )


def test_utf16_with_bom_pending_confirmation(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    target = plans / "2026-08-30-utf16-bom-requirements.md"
    target.write_bytes("---\nmaturity: pending-confirmation\n---\n\nbody\n".encode("utf-16"))
    assert HE.infer_maturity(str(target)) == "pending-confirmation"


def test_utf16_le_without_bom_pending_confirmation(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    target = plans / "2026-08-30-utf16-le-requirements.md"
    target.write_bytes("---\nmaturity: pending-confirmation\n---\n\nbody\n".encode("utf-16-le"))
    assert HE.infer_maturity(str(target)) == "pending-confirmation"


def test_utf16_be_without_bom_pending_confirmation(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    target = plans / "2026-08-30-utf16-be-requirements.md"
    target.write_bytes("---\nmaturity: pending-confirmation\n---\n\nbody\n".encode("utf-16-be"))
    assert HE.infer_maturity(str(target)) == "pending-confirmation"


def test_corrupt_nul_bearing_file_is_unreadable(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    target = plans / "2026-08-30-corrupt-requirements.md"
    target.write_bytes(b"\x00\x01\x02\xff\xfe\x99")
    assert HE.infer_maturity(str(target)) == "unknown:unreadable"


def test_unterminated_bulleted_declaration_fails_closed(tmp_path: Path) -> None:
    """TEST-28: an unterminated block with a bulleted declaration must not route."""
    b = tmp_path / "docs" / "brainstorms"
    b.mkdir(parents=True)
    target = b / "2026-08-31-bulleted-requirements.md"
    target.write_text("---\n- maturity: pending-confirmation\n", encoding="utf-8")
    assert HE.infer_maturity(str(target), root=tmp_path).startswith("unknown:unterminated:")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-31-bulleted-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_unterminated_indented_declaration_fails_closed(tmp_path: Path) -> None:
    """TEST-28: an unterminated block with an indented declaration must not route."""
    b = tmp_path / "docs" / "brainstorms"
    b.mkdir(parents=True)
    target = b / "2026-08-31-indented-requirements.md"
    target.write_text("---\n  maturity: pending-confirmation\n", encoding="utf-8")
    assert HE.infer_maturity(str(target), root=tmp_path).startswith("unknown:unterminated:")
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-31-indented-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_unterminated_empty_value_fails_closed(tmp_path: Path) -> None:
    """TEST-30: a bare maturity key inside an unterminated block must not route."""
    b = tmp_path / "docs" / "brainstorms"
    b.mkdir(parents=True)
    target = b / "2026-08-31-emptyval-requirements.md"
    target.write_text("---\nmaturity: \n", encoding="utf-8")
    assert HE.infer_maturity(str(target), root=tmp_path) == "unknown:unterminated:"
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/2026-08-31-emptyval-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_carrier_scan_last_line_inside_window_fails_closed(tmp_path: Path) -> None:
    """TEST-33: a carrier declaration on the last scanned line still fails closed."""
    b = tmp_path / "docs" / "brainstorms"
    b.mkdir(parents=True)
    target = b / "2026-08-31-cliff-in-requirements.md"
    body = "\n".join(f"filler {i}" for i in range(29)) + "\n- maturity: pending-confirmation\n"
    target.write_text(body, encoding="utf-8")
    assert HE.infer_maturity(str(target), root=tmp_path) == "unknown:carrier:pending-confirmation"


def test_carrier_scan_first_line_outside_window_falls_through(tmp_path: Path) -> None:
    """TEST-33: one line past the scan bound the declaration is not seen — the documented cliff."""
    b = tmp_path / "docs" / "brainstorms"
    b.mkdir(parents=True)
    target = b / "2026-08-31-cliff-out-requirements.md"
    body = "\n".join(f"filler {i}" for i in range(30)) + "\n- maturity: pending-confirmation\n"
    target.write_text(body, encoding="utf-8")
    assert HE.infer_maturity(str(target), root=tmp_path) == "requirements-ready"


def test_nul_bearing_valid_utf8_is_unreadable(tmp_path: Path) -> None:
    """TEST-29: the post-decode NUL guard — a stray NUL in an otherwise valid file fails closed."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    target = plans / "2026-08-31-nul-requirements.md"
    target.write_bytes(b"---\nmaturity: pending-confirmation\n---\n\nbody with \x00 nul\n")
    assert HE.infer_maturity(str(target), root=tmp_path) == "unknown:unreadable"
    envelope = HE.build_handoff_envelope("docs/plans/2026-08-31-nul-requirements.md", root=tmp_path)
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_frontmatter_read_limit_does_not_split_a_codepoint(tmp_path: Path) -> None:
    """TEST-35: a multi-byte codepoint straddling the read bound must not hide the declaration."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    target = plans / "2026-08-31-trim-requirements.md"
    head = b"---\nmaturity: pending-confirmation\n---\n"
    pad = b"x" * (HE._FRONTMATTER_READ_LIMIT - len(head) - 1)
    target.write_bytes(head + pad + "é".encode() + b"tail\n")
    assert HE.infer_maturity(str(target), root=tmp_path) == "pending-confirmation"


def test_relative_source_escaping_root_does_not_read_out_of_root_frontmatter(
    tmp_path: Path,
) -> None:
    """TEST-31: containment — a parent-segment escape must not honour the out-of-root declaration."""
    root = tmp_path / "root"
    (root / "docs" / "brainstorms").mkdir(parents=True)
    outside = tmp_path / "outside" / "docs" / "brainstorms"
    outside.mkdir(parents=True)
    escaped = outside / "2026-08-31-escape-requirements.md"
    escaped.write_text("---\nmaturity: pending-confirmation\n---\n\nx\n", encoding="utf-8")
    relative = os.path.relpath(escaped, root)
    result = HE.infer_maturity(relative, root=root)
    # The out-of-root declaration must not leak in, AND the escape must not route live.
    # This test previously asserted `requirements-ready` — the path rule's live route — and
    # its own comment conceded that was undesirable. SEC-15 is the P1 finding that a
    # containment refusal must fail closed, so the refusal is now the asserted behaviour.
    assert result != "pending-confirmation"
    assert result.startswith("unknown:out-of-root:")


def _infer(tmp_path: Path, body: str) -> str:
    """Write BODY as a brainstorm artifact under TMP_PATH and return its inferred maturity."""
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True, exist_ok=True)
    (brainstorms / "t-requirements.md").write_text(body, encoding="utf-8")
    return HE.infer_maturity(  # type: ignore[no-any-return]
        "docs/brainstorms/t-requirements.md", root=tmp_path
    )


def test_sequence_item_at_column_zero_is_not_a_declaration(tmp_path: Path) -> None:
    """AM-35: a column-0 sequence item is nested under the preceding key, not top-level."""
    got = _infer(tmp_path, "---\ntitle: x\nthings:\n- maturity: plan-ready\n---\n\nBody\n")
    assert got != "plan-ready"
    assert got.startswith("unknown:carrier:")


def test_bullet_without_space_is_not_a_declaration(tmp_path: Path) -> None:
    """CORR-29: `-maturity:` is not a YAML sequence item and must not declare."""
    got = _infer(tmp_path, "---\ntitle: x\n-maturity: plan-ready\n---\n\nBody\n")
    assert got != "plan-ready"
    assert got.startswith("unknown:carrier:")


def test_quoted_top_level_key_declares(tmp_path: Path) -> None:
    """CORR-28: `"maturity":` is a valid YAML spelling of the top-level key."""
    assert _infer(tmp_path, '---\n"maturity": pending-confirmation\n---\n\nBody\n') == (
        "pending-confirmation"
    )


def test_space_before_colon_declares(tmp_path: Path) -> None:
    """CORR-28: `maturity :` is a valid YAML spelling of the top-level key."""
    assert (
        _infer(tmp_path, "---\nmaturity : pending-confirmation\n---\n\nBody\n")
        == "pending-confirmation"
    )


def test_nested_under_another_mapping_key_fails_closed(tmp_path: Path) -> None:
    """A nested declaration is refused rather than routed live by the path rule."""
    got = _infer(tmp_path, "---\nmeta:\n  maturity: plan-ready\n---\n\nBody\n")
    assert got.startswith("unknown:carrier:")


def test_non_string_scalar_maturity_is_unrecognized(tmp_path: Path) -> None:
    """A YAML float must be classified, not crash the reader."""
    assert _infer(tmp_path, "---\nmaturity: 1.1\n---\n\nBody\n") == "unknown:unrecognized:1.1"


def test_malformed_yaml_carrying_maturity_fails_closed(tmp_path: Path) -> None:
    """A block that will not parse but visibly declares must never route live."""
    got = _infer(tmp_path, "---\nmaturity: pending-confirmation\n  bad: [unclosed\n---\n\nBody\n")
    assert got.startswith("unknown:")


def test_flow_style_nested_mapping_fails_closed(tmp_path: Path) -> None:
    """Flow-style nesting is invisible to a line scan: no line begins with `maturity:`.

    Without the structural check this falls through to the path rule and routes live.
    """
    got = _infer(tmp_path, "---\ntitle: x\nmeta: {maturity: plan-ready}\n---\n\nBody\n")
    assert got != "plan-ready"
    assert got.startswith("unknown:carrier:")


def test_flow_style_nested_sequence_fails_closed(tmp_path: Path) -> None:
    """Same blindness inside a flow sequence of mappings."""
    got = _infer(tmp_path, "---\ntitle: x\nthings: [{maturity: plan-ready}]\n---\n\nBody\n")
    assert got != "plan-ready"
    assert got.startswith("unknown:carrier:")


def test_relative_traversal_outside_root_fails_closed(tmp_path: Path) -> None:
    """SEC-15: a relative path escaping the declared root must not route live."""
    root = tmp_path / "root"
    (root / "docs" / "brainstorms").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x-requirements.md").write_text("---\nmaturity: plan-ready\n---\n\nB\n", "utf-8")
    got = HE.infer_maturity("docs/brainstorms/../../../outside/x-requirements.md", root=root)
    assert got.startswith("unknown:out-of-root:")
    assert got != "requirements-ready"


def test_same_file_two_spellings_agree(tmp_path: Path) -> None:
    """SEC-15: the gate decision must not depend on how a path is spelled."""
    root = tmp_path / "root"
    brainstorms = root / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    (brainstorms / "x-requirements.md").write_text(
        "---\nmaturity: pending-confirmation\n---\n\nB\n", "utf-8"
    )
    direct = HE.infer_maturity("docs/brainstorms/x-requirements.md", root=root)
    indirect = HE.infer_maturity("docs/brainstorms/./x-requirements.md", root=root)
    absolute = HE.infer_maturity(str(brainstorms / "x-requirements.md"), root=root)
    assert direct == indirect == absolute == "pending-confirmation"
    outside = tmp_path / "elsewhere/docs/brainstorms/outside.md"
    outside.parent.mkdir(parents=True)
    _write_file(outside, "plan-ready")
    absolute_outside = HE.infer_maturity(str(outside), root=root)
    relative_outside = HE.infer_maturity(os.path.relpath(outside, root), root=root)
    assert absolute_outside.split(":", 2)[:2] == relative_outside.split(":", 2)[:2]
    assert absolute_outside.startswith("unknown:out-of-root:")
    assert relative_outside.startswith("unknown:out-of-root:")


def test_out_of_root_sentinel_carries_a_diagnostic(tmp_path: Path) -> None:
    """The refusal must explain itself rather than emit a runnable command."""
    root = tmp_path / "root"
    (root / "docs" / "brainstorms").mkdir(parents=True)
    envelope = HE.build_handoff_envelope(
        "docs/brainstorms/../../../outside/x-requirements.md", root=root
    )
    assert "/issue --prepare" not in envelope["suggested_command"]
    assert "outside the declared root" in envelope["suggested_command"]


def test_out_of_root_absolute_with_no_declaration_is_refused(tmp_path: Path) -> None:
    """AM-28: classification and attribution must not come from different paths.

    Neither the re-anchored candidate nor the original exists, so nothing declares. Previously
    the maturity was derived from the re-anchored subpath while the envelope published the
    out-of-root original, and the result was a live route.
    """
    root = tmp_path / "root"
    (root / "docs" / "brainstorms").mkdir(parents=True)
    ghost = tmp_path / "elsewhere" / "docs" / "brainstorms" / "ghost.md"
    got = HE.infer_maturity(str(ghost), root=root)
    assert got != "requirements-ready"
    assert got.startswith("unknown:out-of-root:")
    envelope = HE.build_handoff_envelope(str(ghost), root=root)
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_reanchored_candidate_escaping_root_is_refused(tmp_path: Path) -> None:
    """TEST-37: the re-anchored candidate's containment check must be load-bearing.

    The marker slice carries `..` segments, so re-anchoring lands on a REAL file outside the
    declared root. Without the containment check that file is read and its declaration leaks
    in. The escape target is a sibling of the root, reached as root/../outside/.
    """
    root = tmp_path / "root"
    (root / "docs" / "brainstorms").mkdir(parents=True)
    victim = tmp_path / "outside"
    victim.mkdir()
    (victim / "x.md").write_text("---\nmaturity: plan-ready\n---\n\nB\n", "utf-8")
    (tmp_path / "elsewhere/docs/brainstorms").mkdir(parents=True)
    source = str(
        tmp_path / "elsewhere" / "docs" / "brainstorms" / ".." / ".." / ".." / "outside" / "x.md"
    )
    assert Path(source).is_file(), "the escape must reach a real declaration"
    result = HE.infer_maturity(source, root=root)
    assert result != "plan-ready", "an out-of-root declaration must not leak in"
    assert result.startswith("unknown:out-of-root:")


def test_alias_shared_frontmatter_does_not_blow_up(tmp_path: Path) -> None:
    """SEC-2: YAML anchors expand into SHARED objects; a naive walk is exponential.

    At eight anchor levels this took 39 seconds before memoisation, growing about 9x per
    level. A wall-clock bound is the only assertion that catches a re-introduction.
    """
    import time

    levels, fan = 8, 9
    rows = ["---", "l0: &l0 [" + ",".join(['"x"'] * fan) + "]"]
    for i in range(1, levels):
        rows.append(f"l{i}: &l{i} [" + ",".join([f"*l{i - 1}"] * fan) + "]")
    rows += ["top: [" + ",".join([f"*l{levels - 1}"] * fan) + "]", "---", "", "Body"]
    started = time.monotonic()
    got = _infer(tmp_path, "\n".join(rows) + "\n")
    elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"alias-shared frontmatter took {elapsed:.1f}s — the walk is unbounded"
    assert got == "requirements-ready"


def test_duplicate_top_level_maturity_fails_closed(tmp_path: Path) -> None:
    """SEC-4: YAML last-key-wins let the hidden second value route live."""
    got = _infer(
        tmp_path, "---\nmaturity: pending-confirmation\nmaturity: plan-ready\n---\n\nBody\n"
    )
    assert got != "plan-ready", "the hidden duplicate must not decide the route"
    assert got.startswith("unknown:")


def test_marker_less_out_of_root_declaration_is_never_read(tmp_path: Path) -> None:
    """The one out-of-root case the prose got wrong in both directions.

    Every other out-of-root test uses a marker-bearing path. A path carrying no marker
    directory never enters the re-anchor branch at all, so the containment check refuses it
    before anything is read — its declaration cannot be honoured however emphatic it is. The
    release note first claimed every out-of-root source is refused, then claimed a declaring
    one is honoured; both readings are wrong here, and nothing pinned which was true.
    """
    root = tmp_path / "root"
    (root / "docs" / "brainstorms").mkdir(parents=True)
    stray = tmp_path / "elsewhere" / "notes.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("---\nmaturity: plan-ready\n---\n\nBody\n", encoding="utf-8")
    got = HE.infer_maturity(str(stray), root=root)
    assert got != "plan-ready", "a marker-less out-of-root file must not be read"
    assert got.startswith("unknown:out-of-root:")


def test_out_of_root_declaring_file_is_refused_in_both_spellings(tmp_path: Path) -> None:
    """SEC-1: the absolute plan-ready spelling must not publish a runnable command."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere/docs/brainstorms/x.md"
    outside.parent.mkdir(parents=True)
    _write_file(outside, "plan-ready")
    for source in (str(outside), os.path.relpath(outside, root)):
        envelope = HE.build_handoff_envelope(source, root=root)
        assert "/issue --prepare" not in envelope["suggested_command"]
        assert envelope["handoff_maturity"].startswith("unknown:out-of-root:")
        assert HE.infer_maturity(source, root).startswith("unknown:out-of-root:")


def test_in_root_symlink_to_out_of_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    link = root / "docs/plans/link.md"
    link.parent.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    _write_file(outside, "plan-ready")
    link.symlink_to(outside)
    for source in (str(link), "docs/plans/link.md"):
        envelope = HE.build_handoff_envelope(source, root=root)
        assert "/issue --prepare" not in envelope["suggested_command"]
        assert envelope["handoff_maturity"].startswith("unknown:out-of-root:")
        assert HE.infer_maturity(source, root).startswith("unknown:out-of-root:")


def test_reanchored_twin_declaring_nothing_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    twin = root / "docs/brainstorms/x.md"
    twin.parent.mkdir(parents=True)
    twin.write_text("---\ntitle: hello\n---\n", encoding="utf-8")
    source = str(tmp_path / "elsewhere/docs/brainstorms/x.md")
    assert HE.infer_maturity(source, root).startswith("unknown:out-of-root:")
    envelope = HE.build_handoff_envelope(source, root=root)
    assert envelope["handoff_maturity"].startswith("unknown:out-of-root:")
    assert "/issue --prepare" not in envelope["suggested_command"]
    assert "re-anchored from" in envelope["suggested_command"]
    # Refusal concerns the original; the diagnostic must not say the contained twin escapes.
    assert "resolves outside" not in envelope["suggested_command"]


def test_resolve_source_is_the_single_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    for relative in ("docs/brainstorms/x.md", "brainstorms/x.md"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_file(target, "plan-ready")
    source = str(tmp_path / "elsewhere/docs/brainstorms/x.md")
    forced = HE.ResolvedSource(
        path_to_read=None, published="FORCED-BY-TEST", reanchored=False, refused=True
    )
    monkeypatch.setattr(HE, "resolve_source", lambda source, root: forced)
    envelope = HE.build_handoff_envelope(source, root=root)
    assert envelope["source"] == "FORCED-BY-TEST"
    assert envelope["handoff_maturity"].startswith("unknown:out-of-root:")
    assert envelope["handoff_maturity"] == HE.infer_maturity(source, root)


@pytest.mark.parametrize("shape", ["ghost", "no-declaration", "backslash", "marker-less"])
def test_infer_and_envelope_agree_on_every_out_of_root_shape(shape: str) -> None:
    # Keep the fixture source below the separately tested 120-character sentinel bound,
    # so exact equality measures resolution rather than intentional publication truncation.
    with tempfile.TemporaryDirectory(prefix="912-", dir="/tmp") as fixture_dir:
        base = Path(fixture_dir).resolve()
        root = base / "root"
        root.mkdir()
        source_path = base / "elsewhere/docs/brainstorms/x.md"
        source_path.parent.mkdir(parents=True)
        _write_file(source_path, "plan-ready")
        if shape in {"no-declaration", "backslash"}:
            twin = root / "docs/brainstorms/x.md"
            twin.parent.mkdir(parents=True)
            _write_file(twin, None if shape == "no-declaration" else "pending-confirmation")
        if shape == "marker-less":
            source_path = base / "notes.md"
            _write_file(source_path, "plan-ready")
        source = str(source_path)
        if shape == "backslash":
            source = source.replace("/", "\\")
        expected = HE.infer_maturity(source, root)
        envelope = HE.build_handoff_envelope(source, root=root)
        assert envelope["handoff_maturity"] == expected
        if shape == "backslash":
            assert envelope["source"] == "docs/brainstorms/x.md"


_CARRIER_CASES = [
    ("---\nmeta:\n  maturity: requirements-ready\n---\n", "nested"),
    ("---\nkeys:\n- maturity: requirements-ready\n---\n", "sequence item"),
    ("maturity: requirements-ready\n", "missing delimiters"),
]


@pytest.mark.parametrize(("body", "cause"), _CARRIER_CASES)
def test_carrier_diagnostic_names_the_actual_cause(tmp_path: Path, body: str, cause: str) -> None:
    _infer(tmp_path, body)
    envelope = HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)
    assert envelope["handoff_maturity"].startswith("unknown:carrier:")
    diagnostic = envelope["suggested_command"]
    assert cause in diagnostic.lower()
    if cause != "missing delimiters":
        assert "missing delimiters" not in diagnostic.lower()


def test_carrier_diagnostics_are_pairwise_distinct(tmp_path: Path) -> None:
    diagnostics = []
    for body, _ in _CARRIER_CASES:
        _infer(tmp_path, body)
        diagnostics.append(
            HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)[
                "suggested_command"
            ]
        )
    assert len(set(diagnostics)) == 3


def test_blank_maturity_diagnostic_says_blank_not_unrecognized(tmp_path: Path) -> None:
    assert _infer(tmp_path, "---\nmaturity:\n---\n") == ""
    envelope = HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)
    assert "blank" in envelope["suggested_command"].lower()
    assert "Unrecognized" not in envelope["suggested_command"]


def test_unrecognized_remediation_names_pending_confirmation(tmp_path: Path) -> None:
    _infer(tmp_path, "---\nmaturity: pending confirmation\n---\n")
    envelope = HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)
    assert "pending-confirmation" in envelope["suggested_command"]


def test_maturity_past_the_read_window_fails_closed(tmp_path: Path) -> None:
    filler = "".join(f"k{i:03d}: text\n" for i in range(900))
    body = f"---\n{filler}maturity: pending-confirmation\n---\n# doc\n\n"
    assert len(body.encode()) == 9946
    got = _infer(tmp_path, body)
    assert got.startswith("unknown:unterminated:")
    envelope = HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_closing_delimiter_past_the_read_window_names_the_window(tmp_path: Path) -> None:
    filler = "".join(f"k{i:03d}: text\n" for i in range(900))
    _infer(tmp_path, f"---\nmaturity: plan-ready\n{filler}---\n# doc\n")
    envelope = HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)
    assert "8192" in envelope["suggested_command"]
    assert "closing --- missing" not in envelope["suggested_command"]


def test_early_dashes_inside_quoted_value_fail_closed(tmp_path: Path) -> None:
    got = _infer(tmp_path, '---\nnote: "line\n---\n"\nmaturity: pending-confirmation\n---\n# doc\n')
    assert got.startswith("unknown:carrier:")
    envelope = HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)
    assert "/issue --prepare" not in envelope["suggested_command"]


def test_deeply_nested_yaml_fails_closed_without_traceback(tmp_path: Path) -> None:
    body = "---\nmaturity: plan-ready\na: " + "[" * 4000 + "]" * 4000 + "\n---\n"
    got = _infer(tmp_path, body)
    assert got.startswith("unknown:carrier:")


@pytest.mark.parametrize(
    "source",
    [
        "docs/plans/a.md; rm -rf victim",
        "docs/plans/a.md --maturity resume-ready --target x",
        "docs/plans/a.md --force",
        "docs/plans/a.md\n/issue --prepare --from attacker",
    ],
)
def test_suggested_command_is_shell_safe_and_single_line(tmp_path: Path, source: str) -> None:
    target = tmp_path / source
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_file(target, "plan-ready")
    envelope = HE.build_handoff_envelope(source, root=tmp_path)
    assert shlex.split(envelope["suggested_command"]) == [
        "/issue",
        "--prepare",
        "--from",
        source,
        "--maturity",
        "plan-ready",
    ]
    if "\n" in source:
        _write_file(target, "pending-confirmation")
        refused = HE.build_handoff_envelope(source, root=tmp_path)
        assert "\n" not in refused["suggested_command"]


def test_plain_path_command_is_byte_identical(tmp_path: Path) -> None:
    envelope = HE.build_handoff_envelope("docs/plans/a.md", root=tmp_path)
    assert envelope["suggested_command"] == (
        "/issue --prepare --from docs/plans/a.md --maturity plan-ready"
    )


def test_overlong_path_component_returns_a_sentinel_not_oserror(tmp_path: Path) -> None:
    (tmp_path / "docs/plans").mkdir(parents=True)
    source = "docs/plans/" + "a" * 400 + ".md"
    got = HE.infer_maturity(source, root=tmp_path)
    assert isinstance(got, str)


def test_unrecognized_handoff_section_requires_clarification() -> None:
    spec = importlib.util.spec_from_file_location(
        "parse_issue_clarification", ROOT / "plugins/saga/scripts/parse_issue.py"
    )
    assert spec is not None and spec.loader is not None
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    got = parser.extract_handoff("### Handoff maturity\nunknown:carrier:requirements-ready\n")
    assert got["maturity"] == ""
    assert got["can_plan"] is False
    assert got["requires_clarification"] is True
    assert (
        parser.extract_handoff("### Objective\nNo handoff section.\n")["requires_clarification"]
        is False
    )


def test_top_level_flow_mapping_declares(tmp_path: Path) -> None:
    target = tmp_path / "docs/ideation/flow.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\n{maturity: requirements-ready, topic: x}\n---\n", encoding="utf-8")
    assert HE.infer_maturity(str(target), root=tmp_path) == "requirements-ready"


@pytest.mark.parametrize("value", ["unknown:out-of-root:x", "unknown:carrier:"])
def test_hand_written_unknown_prefix_is_wrapped_not_honoured(tmp_path: Path, value: str) -> None:
    assert _infer(tmp_path, f'---\nmaturity: "{value}"\n---\n') == (f"unknown:unrecognized:{value}")
    envelope = HE.build_handoff_envelope("docs/brainstorms/t-requirements.md", root=tmp_path)
    assert "/issue --prepare" not in envelope["suggested_command"]


@pytest.mark.parametrize("shape", ["missing", "directory", "nul"])
def test_frontmatter_io_failure_is_unreadable(tmp_path: Path, shape: str) -> None:
    target = tmp_path / "unreadable.md"
    if shape == "directory":
        target.mkdir()
    elif shape == "nul":
        target = tmp_path / "bad\x00name.md"
    assert HE._read_frontmatter_maturity(target) == "unknown:unreadable"
    assert HE.carrier_detail(target) == "carrier could not be re-read"


def test_small_open_block_without_maturity_keeps_the_path_rule(tmp_path: Path) -> None:
    assert _infer(tmp_path, "---\ntitle: hello\n") == "requirements-ready"


def test_dash_prefixed_yaml_key_does_not_close_frontmatter(tmp_path: Path) -> None:
    assert _infer(tmp_path, "---\n---note: hello\nmaturity: pending-confirmation\n---\n") == (
        "pending-confirmation"
    )


@pytest.mark.parametrize(
    "body",
    [
        b"---\nmaturity: pending-confirmation\n---\n",
        b"---\nmaturity:\n---\n",
        b"---\nmaturity: pending confirmation\n---\n",
        b"---\nmeta:\n  maturity: plan-ready\n---\n",
        b"---\nmaturity: plan-ready\n",
        b"\xff\xfe\xfd\xfc\xfb",
    ],
)
def test_every_file_diagnostic_escapes_and_bounds_the_source(tmp_path: Path, body: bytes) -> None:
    source = "docs/brainstorms/a\nb\rc\td/" + "/".join(["x" * 100] * 3) + "/x.md"
    target = tmp_path / source
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    envelope = HE.build_handoff_envelope(source, root=tmp_path)
    diagnostic = envelope["suggested_command"]
    assert all(char not in diagnostic for char in "\n\r\t\x00")
    displayed = HE._display_source(source)
    assert displayed in diagnostic
    assert len(displayed) == 256
    assert displayed.endswith("…")
    assert r"a\nb\rc\td" in diagnostic


def test_out_of_root_diagnostic_escapes_nul_and_other_controls(tmp_path: Path) -> None:
    source = "docs/plans/a\nb\rc\td\x00.md"
    envelope = HE.build_handoff_envelope(source, root=tmp_path)
    assert envelope["handoff_maturity"].startswith("unknown:out-of-root:")
    assert r"a\nb\rc\td\x00.md" in envelope["suggested_command"]
    assert all(char not in envelope["suggested_command"] for char in "\n\r\t\x00")
    assert all(char not in envelope["handoff_maturity"] for char in "\n\r\t\x00")


# ---------------------------------------------------------------------------
# #942 owner-side assess_source / assess_declared parity (MC-ALIGN-07-TEST-AUTHOR)
# ---------------------------------------------------------------------------


def _assess_source():
    fn = getattr(HE, "assess_source", None)
    assert callable(fn), "assess_source is not implemented"
    return fn


def _assess_declared():
    fn = getattr(HE, "assess_declared", None)
    assert callable(fn), "assess_declared is not implemented"
    return fn


def _maturity(assessment: object) -> str:
    if isinstance(assessment, str):
        return assessment
    maturity = getattr(assessment, "maturity", None)
    assert isinstance(maturity, str)
    return maturity


def _next_action(assessment: object) -> str:
    return str(getattr(assessment, "next_action", "") or "")


def _write_owner(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_readiness_contract_major_and_unknown_prefix_are_exported() -> None:
    major = getattr(HE, "READINESS_CONTRACT_MAJOR", None)
    assert major in {1, "1"}
    prefix = getattr(HE, "UNKNOWN_PREFIX", None)
    assert prefix == "unknown:"


def test_assess_source_pending_confirmation_brainstorm(tmp_path: Path) -> None:
    _write_owner(
        tmp_path,
        "docs/brainstorms/2026-09-13-alignment-boundary.md",
        "---\nmaturity: pending-confirmation\n---\n\n# Boundary\n",
    )
    assessment = _assess_source()("docs/brainstorms/2026-09-13-alignment-boundary.md", tmp_path)
    assert _maturity(assessment) == "pending-confirmation"
    assert assessment.routable is False
    assert "/plan" not in _next_action(assessment)
    assert "/work" not in _next_action(assessment)


def test_assess_source_undeclared_draft_and_state(tmp_path: Path) -> None:
    draft = _write_owner(
        tmp_path,
        "docs/sdlc-issue-drafts/2026-09-13-bare-draft.md",
        "# Bare draft\n",
    )
    draft.with_suffix(".json").write_text('{"title": "bare"}', encoding="utf-8")
    _write_owner(
        tmp_path,
        ".claude/saga/state.json",
        '{"current_work": {"plan_path": "docs/sdlc-issue-drafts/2026-09-13-bare-draft.md"}}',
    )
    assess = _assess_source()
    draft_assessment = assess("docs/sdlc-issue-drafts/2026-09-13-bare-draft.md", tmp_path)
    state_assessment = assess(".claude/saga/state.json", tmp_path)
    assert _maturity(draft_assessment).startswith("unknown:undeclared:")
    assert _maturity(state_assessment).startswith("unknown:undeclared:")
    assert draft_assessment.declaration_required is True
    assert state_assessment.declaration_required is True


@pytest.mark.parametrize(
    "state",
    (
        "idea-ready",
        "requirements-ready",
        "plan-ready",
        "resume-ready",
        "deferred-context",
        "pending-confirmation",
    ),
)
def test_assess_source_declared_state_overrides_brainstorm_folder(
    tmp_path: Path, state: str
) -> None:
    _write_owner(
        tmp_path,
        "docs/brainstorms/declared.md",
        f"---\nmaturity: {state}\n---\n\n# Declared\n",
    )
    assessment = _assess_source()("docs/brainstorms/declared.md", tmp_path)
    assert _maturity(assessment) == state
    live = state in {
        "idea-ready",
        "requirements-ready",
        "plan-ready",
        "resume-ready",
    }
    assert (("/plan" in _next_action(assessment)) or ("/work" in _next_action(assessment))) is live


def test_assess_source_out_of_root_and_selected_twin(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-owner-outside.md"
    outside.write_text("---\nmaturity: requirements-ready\n---\n\n# Out\n", encoding="utf-8")
    _write_owner(
        tmp_path,
        "docs/brainstorms/selected-twin.md",
        "---\nmaturity: plan-ready\n---\n\n# Twin\n",
    )
    _write_owner(tmp_path, "docs/brainstorms/ghost.md", "# No declaration\n")
    outside_twin = tmp_path.parent / "docs" / "brainstorms" / "ghost.md"
    outside_twin.parent.mkdir(parents=True, exist_ok=True)
    outside_twin.write_text(
        "---\nmaturity: requirements-ready\n---\n\n# Outside twin\n",
        encoding="utf-8",
    )
    assess = _assess_source()
    refused = assess(str(outside), tmp_path)
    assert _maturity(refused).startswith("unknown:out-of-root:")
    undeclared_twin = assess(str(outside_twin), tmp_path)
    assert _maturity(undeclared_twin).startswith("unknown:out-of-root:")
    twin = assess("docs/brainstorms/selected-twin.md", tmp_path)
    assert _maturity(twin) == "plan-ready"
    assert twin.published_source == "docs/brainstorms/selected-twin.md"


def test_assess_declared_classifies_vocabulary_and_unknown() -> None:
    assess = _assess_declared()
    ready = assess("requirements-ready", "docs/brainstorms/a.md", declaration_required=False)
    assert _maturity(ready) == "requirements-ready"
    blank = assess("", "docs/brainstorms/a.md", declaration_required=True)
    assert _maturity(blank) == "" or str(_maturity(blank)).startswith("unknown:")
    unknown = assess("bogus", "docs/brainstorms/a.md", declaration_required=False)
    assert str(_maturity(unknown)).startswith("unknown:unrecognized:")


@pytest.mark.parametrize(
    ("name", "text", "prefix"),
    (
        ("bogus.md", "---\nmaturity: bogus-value\n---\n\n# Bogus\n", "unknown:unrecognized:"),
        (
            "dup.md",
            "---\nmaturity: pending-confirmation\nmaturity: plan-ready\n---\n\n# Dup\n",
            "unknown:",
        ),
        ("carrier.md", "maturity: plan-ready\n\n# Carrier\n", "unknown:carrier:"),
        ("open.md", "---\nmaturity: plan-ready\n", "unknown:unterminated:"),
        ("blank.md", "---\nmaturity:\n---\n\n# Blank\n", ""),
    ),
)
def test_assess_source_malformed_declarations_fail_closed(
    tmp_path: Path, name: str, text: str, prefix: str
) -> None:
    rel = f"docs/brainstorms/{name}"
    _write_owner(tmp_path, rel, text)
    assessment = _assess_source()(rel, tmp_path)
    maturity = _maturity(assessment)
    if prefix:
        assert maturity.startswith(prefix)
    else:
        assert maturity == "" or maturity.startswith("unknown:")
    assert "/plan" not in _next_action(assessment)
    assert "/work" not in _next_action(assessment)


def test_assess_source_unreadable_bytes_are_unknown(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "brainstorms" / "binary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\xfd\xfc\xfb")
    assessment = _assess_source()("docs/brainstorms/binary.md", tmp_path)
    assert _maturity(assessment).startswith("unknown:")
    assert "/plan" not in _next_action(assessment)
