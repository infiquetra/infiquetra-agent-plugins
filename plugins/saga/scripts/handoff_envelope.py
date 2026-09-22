#!/usr/bin/env python3
"""Document-maturity assessment: the readiness owner mission-control delegates to.

**Kept by issue 1030, which removed the `/handoff` command.** The name is historical. This module
is not that command's envelope machinery -- that went with the command. What it is, and has been
for some time, is the owner of the readiness vocabulary (`idea-ready`, `requirements-ready`,
`plan-ready`, `resume-ready`, `deferred-context`, `pending-confirmation`) and the parser that
classifies a source document's declared maturity.

`plugins/mission-control/scripts/sdlc_manager.py` resolves this file by path (its
`_SAGA_OWNER_MARKER`), gates it on `READINESS_CONTRACT_MAJOR`, and calls `assess_source` and
`assess_declared` at seven sites in its issue-prepare path. Deleting it with the command would have
broken a plugin this card does not otherwise touch, in order to remove a name rather than a
behaviour.

Original header: build a thin Infiquetra loop handoff envelope for mission-control.

Also exposes the versioned readiness-owner API (``assess_source`` /
``assess_declared``, issue #942) that the mission-control consumer gates on.
"""

import argparse
import codecs
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class _StrictMappingLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys.

    ``yaml.safe_load`` applies last-key-wins silently, so a frontmatter whose first visible
    ``maturity:`` says ``pending-confirmation`` and whose second says ``plan-ready`` parsed as
    ``plan-ready`` and routed live (SEC-4). Raising here routes the document into the same
    fail-closed path a malformed block already takes.
    """


def _no_duplicate_keys(loader: _StrictMappingLoader, node: Any) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=False)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate key {key!r} in frontmatter")
        mapping[key] = loader.construct_object(value_node, deep=False)
    return mapping


_StrictMappingLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)

STATE_DIR = Path(".claude/saga")
SOURCE_DIRS = (
    Path("docs/plans"),
    Path("docs/brainstorms"),
    Path("docs/specs"),
    Path("docs/ideation"),
    Path("docs/reviews"),
    Path("docs/work-sessions"),
)

HANDOFF_MATURITIES = (
    "idea-ready",
    "requirements-ready",
    "plan-ready",
    "resume-ready",
    "deferred-context",
    "pending-confirmation",
)

#: The subset whose `suggested_command` is runnable. `pending-confirmation` is a member of
#: HANDOFF_MATURITIES but carries no durable route, so offering it as a remediation target
#: sends the author straight back to the same diagnostic (API-25).
ROUTABLE_MATURITIES = tuple(m for m in HANDOFF_MATURITIES if m != "pending-confirmation")

# Derived from SOURCE_DIRS to avoid a second literal that must be kept in sync.
# Used for re-anchoring an absolute source outside the declared root to its
# marker-directory subpath.
MARKER_DIRS = tuple(p.name for p in SOURCE_DIRS)

# Bounded read size for frontmatter scan to avoid amplifying memory on large files.
_FRONTMATTER_READ_LIMIT = 8192


@dataclass(frozen=True)
class ResolvedSource:
    """One source decision shared by inference and envelope publication."""

    path_to_read: Path | None
    published: str
    reanchored: bool
    refused: bool


@dataclass(frozen=True)
class _ReadWindow:
    text: str
    has_more: bool


_DELIMITER = re.compile(r"^---\s*$", re.MULTILINE)


def _extract_declared_maturity_value(line: str) -> str | None:
    """Scan a visible declaration, including indented and bullet carrier forms.

    This scan detects malformed carriers; the YAML parser decides whether a key
    is top-level. Inline comments and quotes are stripped in every scanning arm.
    """
    cleaned = line.strip().lstrip("-*").strip()
    if not cleaned.startswith("maturity:"):
        return None
    value = cleaned[len("maturity:") :].strip()
    return value.split("#", 1)[0].strip().strip("\"'").strip()


def _scanned_maturity_line(text: str) -> str | None:
    for line in text.splitlines():
        extracted = _extract_declared_maturity_value(line)
        if extracted is not None:
            return extracted
    return None


def _carrier(value: str | None) -> str:
    return f"unknown:carrier:{value or ''}"


def _recover_utf16(raw: bytes) -> str | None:
    for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
        try:
            candidate = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        # A successful decode alone can be mojibake; require a real declaration.
        if "maturity:" in candidate and "\x00" not in candidate:
            return candidate
    return None


def _recover_text(raw: bytes) -> str | None:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
        recovered = _recover_utf16(raw)
        if recovered is not None:
            return recovered
    replacement = raw.decode("utf-8-sig", errors="replace")
    if "maturity:" in replacement and "\x00" not in replacement:
        return replacement
    return None


def _decode_window(raw: bytes, has_more: bool) -> str | None:
    try:
        # Incremental decoding leaves a trailing partial codepoint buffered only
        # when the file continues beyond this window (SEC-09).
        text = codecs.getincrementaldecoder("utf-8-sig")().decode(raw, final=not has_more)
    except UnicodeDecodeError:
        return _recover_text(raw)
    if "\x00" in text:
        return _recover_text(raw)
    return text


def _read_window(path: Path) -> _ReadWindow | None:
    """Read at most 8192 bytes plus a one-byte overflow probe; fail closed on I/O."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(_FRONTMATTER_READ_LIMIT)
            has_more = len(raw) == _FRONTMATTER_READ_LIMIT and bool(stream.read(1))
    except (OSError, ValueError):
        return None
    text = _decode_window(raw, has_more)
    return None if text is None else _ReadWindow(text, has_more)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Identify a non-delimited carrier, an opened block, or a closed YAML body."""
    opening = _DELIMITER.match(text)
    if opening is None:
        return "none", text
    closing = _DELIMITER.search(text, opening.end())
    if closing is None:
        return "unterminated", text[opening.end() :]
    return "closed", text[opening.end() : closing.start()]


def _nested_maturity_detail(node: object) -> str:
    # Track identities, including sequence context, so alias-shared containers are
    # visited at most twice. An iterative walk also handles deep parsed structures.
    pending = [(node, False)]
    seen: set[tuple[int, bool]] = set()
    while pending:
        current, in_sequence = pending.pop()
        identity = (id(current), in_sequence)
        if not isinstance(current, (dict, list)) or identity in seen:
            continue
        seen.add(identity)
        if isinstance(current, dict):
            if "maturity" in current:
                return "sequence item" if in_sequence else "nested under a key"
            pending.extend((value, in_sequence) for value in current.values())
        else:
            pending.extend((value, True) for value in current)
    return ""


def _has_nested_maturity(node: object) -> bool:
    return bool(_nested_maturity_detail(node))


def _parse_frontmatter(frontmatter: str) -> tuple[bool, object]:
    try:
        parsed = yaml.load(frontmatter, Loader=_StrictMappingLoader)  # noqa: S506 # nosec B506
    except (yaml.YAMLError, RecursionError):
        return False, None
    return True, parsed


def _classify_declared_value(raw: object) -> str:
    value = "" if raw is None else str(raw).strip()
    if not value or value in HANDOFF_MATURITIES:
        return value
    # Author-declared unknown: text cannot forge any reserved sentinel cause.
    return f"unknown:unrecognized:{value}"


def _classify_frontmatter(frontmatter: str, window_text: str) -> str | None:
    valid, parsed = _parse_frontmatter(frontmatter)
    if not valid:
        # A premature --- inside malformed YAML must not hide a later visible key.
        scanned = _scanned_maturity_line(window_text)
        return None if scanned is None else _carrier(scanned)
    if isinstance(parsed, dict) and "maturity" in parsed:
        return _classify_declared_value(parsed["maturity"])
    scanned = _scanned_maturity_line(frontmatter)
    if scanned is not None or _has_nested_maturity(parsed):
        return _carrier(scanned)
    return None


def _read_frontmatter_maturity(path: Path) -> str | None:
    window = _read_window(path)
    if window is None:
        return "unknown:unreadable"
    kind, body = _split_frontmatter(window.text)
    if kind == "none":
        # The non-delimited carrier contract scans the first thirty lines.
        scanned = _scanned_maturity_line("\n".join(body.splitlines()[:30]))
        return None if scanned is None else _carrier(scanned)
    if kind == "unterminated":
        scanned = _scanned_maturity_line(body)
        if scanned is not None or window.has_more:
            return f"unknown:unterminated:{scanned or ''}"
        return None
    return _classify_frontmatter(body, window.text)


def carrier_detail(path: Path) -> str:
    """Non-published cause for an unknown:carrier: diagnostic; no new sentinel."""
    window = _read_window(path)
    if window is None:
        return "carrier could not be re-read"
    kind, body = _split_frontmatter(window.text)
    if kind == "none":
        return "missing delimiters; declared outside a delimited YAML block"
    valid, parsed = _parse_frontmatter(body)
    if not valid:
        return "block will not parse as YAML"
    return _nested_maturity_detail(parsed) or "not a top-level key"


def _unterminated_detail(path: Path | None) -> str:
    window = _read_window(path) if path is not None else None
    if window is not None and window.has_more:
        return (
            f"closing --- not found within the first {_FRONTMATTER_READ_LIMIT} bytes; "
            "shorten the frontmatter or close the block"
        )
    return "closing --- missing; fix frontmatter to close the block"


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


def _is_within(candidate: Path, base: Path) -> bool:
    """Judge containment on resolved paths; an unresolvable path is outside."""
    try:
        return candidate.resolve().is_relative_to(base.resolve())
    except (OSError, ValueError):
        return False


def _reanchor_to_marker(normalized: str) -> str | None:
    """Return an absolute path's marker subpath, including its parent directory.

    Only resolve_source calls this helper. The test_resolve_source_is_the_single_owner
    spy pins both inference and the envelope's published source to that resolver.
    """
    parts = Path(normalized).parts
    for marker in MARKER_DIRS:
        if marker in parts:
            idx = parts.index(marker)
            return "/".join(parts[idx - 1 :])
    return None


def resolve_source(source: str, root: Path | None) -> ResolvedSource:
    """Resolve the file to read and the source to publish with one containment policy.

    A source that resolves outside the declared root is never read. Two outcomes:
    a contained, existing marker-directory twin is read instead and its declaration
    decides, or the source is refused. This applies whether the original exists and
    however its path is spelled. With no declared root the caller's named path is read.
    """
    normalized = source.replace("\\", "/")
    base = root or Path.cwd()
    candidate = base / normalized
    if root is None or _is_within(candidate, base):
        path_to_read = candidate if _is_file(candidate) else None
        return ResolvedSource(path_to_read, normalized, False, False)
    reanchored = _reanchor_to_marker(str(candidate.absolute()))
    if reanchored is not None:
        twin = base / reanchored
        if _is_within(twin, base) and _is_file(twin):
            return ResolvedSource(twin, reanchored, True, False)
    return ResolvedSource(None, normalized, False, True)


def _path_maturity(normalized: str) -> str:
    if "docs/ideation/" in normalized:
        return "idea-ready"
    if "docs/brainstorms/" in normalized or "docs/specs/" in normalized:
        return "requirements-ready"
    if "docs/plans/" in normalized or "docs/reviews/" in normalized:
        return "plan-ready"
    if "docs/work-sessions/" in normalized or normalized.startswith("branch:"):
        return "resume-ready"
    return "requirements-ready"


def _resolved_maturity(resolved: ResolvedSource) -> str:
    if resolved.refused:
        return f"unknown:out-of-root:{resolved.published}"
    if resolved.path_to_read is not None:
        declared = _read_frontmatter_maturity(resolved.path_to_read)
        if declared is not None:
            return declared
        if resolved.reanchored:
            # A twin that declares nothing cannot authorize the original source.
            return f"unknown:out-of-root:{resolved.published}"
    return _path_maturity(resolved.published)


def infer_maturity(source: str, root: Path | None = None) -> str:
    return _resolved_maturity(resolve_source(source, root))


def infer_lifecycle_phase(source: str) -> str:
    normalized = source.replace("\\", "/")
    if "docs/ideation/" in normalized:
        return "ideation"
    if "docs/brainstorms/" in normalized:
        return "brainstorm"
    if "docs/plans/" in normalized:
        return "plan"
    if "docs/reviews/" in normalized:
        return "review"
    if "docs/work-sessions/" in normalized or normalized.startswith("branch:"):
        return "work"
    # docs/specs/ is off-chain (/spec) — no lifecycle phase; maturity is set in infer_maturity.
    return "unknown"


def read_state(root: Path) -> dict[str, object]:
    state_path = root / STATE_DIR / "state.json"
    if not state_path.exists():
        return {}
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _state_source(state: dict[str, object]) -> str | None:
    current = state.get("current_work")
    if isinstance(current, dict):
        for key in ("plan_path", "work_session_path"):
            value = current.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _source_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for rel_dir in SOURCE_DIRS:
        directory = root / rel_dir
        # Use lstat to avoid following directory symlinks that could escape root (SEC-04).
        try:
            if not directory.exists() or directory.is_symlink():
                continue
        except OSError:
            continue
        # Collect candidates but skip file symlinks that escape containment.
        for path in directory.rglob("*.md"):
            if not _is_file(path) or path.is_symlink():
                continue
            try:
                if not path.resolve().is_relative_to(directory.resolve()):
                    continue
            except (OSError, ValueError):
                continue
            candidates.append(path)
    return candidates


def discover_active_source(root: Path) -> str | None:
    selected = _state_source(read_state(root))
    if selected:
        return selected
    candidates = _source_candidates(root)
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return latest.relative_to(root).as_posix()


def _git_output(args: list[str], root: Path) -> str:
    result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else ""


def current_git_state(root: Path) -> dict[str, str]:
    branch = _git_output(["git", "branch", "--show-current"], root)
    head = _git_output(["git", "rev-parse", "--short", "HEAD"], root)
    return {"branch": branch, "head": head}


def _escape_controls(value: str) -> str:
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
        for char in value
    )


def _display_source(source: str) -> str:
    escaped = _escape_controls(source)
    return escaped[:255] + "…" if len(escaped) > 256 else escaped


def _bounded_maturity(maturity: str) -> str:
    if maturity.startswith("unknown:"):
        # Both handoff_maturity and suggested_command carry this bounded text;
        # the full author-declared value appears in neither. Mark truncation.
        body = _escape_controls(maturity[len("unknown:") :])
        return "unknown:" + (body[:120] + "…" if len(body) > 120 else body)
    return maturity


def _diagnostic_source(source: str, resolved: ResolvedSource) -> str:
    displayed = _display_source(resolved.published)
    if resolved.reanchored:
        displayed += (
            f" (re-anchored from {_display_source(source)!r} "
            f"to {_display_source(resolved.published)!r})"
        )
    return displayed


def _maturity_remediation() -> str:
    return (
        f"fix frontmatter to one of {', '.join(ROUTABLE_MATURITIES)}, "
        "or pending-confirmation for a Brainstorm boundary that is not yet confirmed "
        "(no durable route until it is)"
    )


def _maturity_diagnostic(maturity: str, source: str, path: Path | None) -> str | None:
    if maturity == "pending-confirmation":
        return (
            f"Boundary recorded but unconfirmed for {source} — "
            "no durable route exists until the operator confirms in Brainstorm Phase 2.5"
        )
    elif maturity == "":
        return (
            f"Blank maturity for {source} — the key is declared but empty; "
            f"no durable route; {_maturity_remediation()}"
        )
    elif maturity.startswith("unknown:carrier:"):
        raw = maturity.removeprefix("unknown:carrier:")
        cause = carrier_detail(path) if path is not None else "not a top-level key"
        return (
            f"Frontmatter carrier for {source} — {cause}; maturity {raw!r}; "
            "no durable route; fix frontmatter to be delimited by literal --- lines "
            "with a top-level maturity: key"
        )
    elif maturity.startswith("unknown:unterminated:"):
        raw = maturity.removeprefix("unknown:unterminated:")
        return (
            f"Unterminated frontmatter block for {source} — maturity {raw!r}; "
            f"{_unterminated_detail(path)}; no durable route"
        )
    elif maturity.startswith("unknown:out-of-root:"):
        raw = maturity.removeprefix("unknown:out-of-root:")
        return (
            f"Source outside the declared root for {source} — "
            f"refused handoff ({raw!r}); no durable route; "
            "name a source inside the declared root"
        )
    elif maturity == "unknown:unreadable":
        return (
            f"Unreadable frontmatter for {source} — "
            "file could not be opened, or decoded into text carrying a maturity "
            "declaration; no durable route; re-save the file as UTF-8 with a closed "
            "--- block and a top-level maturity: key, then re-run"
        )
    elif maturity.startswith("unknown:unrecognized:"):
        raw = maturity.removeprefix("unknown:unrecognized:")
        return (
            f"Unrecognized maturity {raw!r} for {source} — "
            f"no durable route; {_maturity_remediation()}"
        )
    return None


def _suggested_command(
    source: str,
    resolved: ResolvedSource,
    maturity: str,
    target_team: str,
    target_repo: str,
) -> str:
    diagnostic = _maturity_diagnostic(
        maturity, _diagnostic_source(source, resolved), resolved.path_to_read
    )
    if diagnostic is not None:
        return diagnostic
    command = f"/issue --prepare --from {shlex.quote(resolved.published)} --maturity {maturity}"
    if target_team:
        command += f" for {target_team}"
    if target_repo:
        command += f" in {target_repo}"
    return command


def build_handoff_envelope(
    source: str | None = None,
    *,
    target_team: str = "",
    target_repo: str = "",
    issue_type: str = "",
    reason: str = "",
    blockers: str = "",
    open_questions: str = "",
    root: Path | None = None,
) -> dict[str, object]:
    root = root or Path.cwd()
    selected_source = source or discover_active_source(root)
    if not selected_source:
        raise RuntimeError("No handoff source found; provide --source or create a durable artifact")

    resolved = resolve_source(selected_source, root)
    maturity = _bounded_maturity(_resolved_maturity(resolved))
    suggested_command = _suggested_command(
        selected_source, resolved, maturity, target_team, target_repo
    )

    return {
        "schema_version": "1.1",
        "created_at": datetime.now(UTC).isoformat(),
        "source": resolved.published,
        "lifecycle_phase": infer_lifecycle_phase(resolved.published),
        "handoff_maturity": maturity,
        "handoff_reason": reason,
        "target_team": target_team,
        "target_repo": target_repo,
        "issue_type": issue_type,
        "blockers": blockers,
        "open_questions": open_questions,
        "suggested_command": suggested_command,
        "lifecycle_owner": "saga",
        "issue_artifact_owner": "mission-control",
        "body_template_owner": "mission-control",
        "git": current_git_state(root),
    }


def build_deploy_handoff_envelope(
    saga_id: str,
    *,
    payload: str = "gate",
    offered_by: str = "",
    pr_refs: list[str] | None = None,
    token: str | None = None,
    now: str | None = None,
) -> dict[str, object]:
    """Thin delegator to ``deploy_handoff.build_envelope`` (issue #395, KTD1).

    The saga -> deploy edge gets its own single-writer sidecar module
    (``deploy_handoff.py``); this builder is the only seam ``handoff_envelope.py`` exposes onto it,
    keeping the mission-control envelope (``build_handoff_envelope`` above) byte-untouched. The
    import is lazy so loading this module for the mission-control path never pulls the deploy edge
    in — and ``deploy_handoff`` is a sibling script resolved via a ``sys.path`` insert, not a
    cross-plugin import (R1).
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import deploy_handoff  # noqa: PLC0415

    return deploy_handoff.build_envelope(
        saga_id,
        payload=payload,
        offered_by=offered_by,
        pr_refs=pr_refs,
        token=token,
        now=now,
    )


# ---------------------------------------------------------------------------
# Readiness owner API (#942): explicit declarations where location cannot decide.
# ---------------------------------------------------------------------------

#: Contract major of the ``assess_source`` / ``assess_declared`` surface. The
#: mission-control consumer gates on this and refuses an incompatible owner.
READINESS_CONTRACT_MAJOR = 1

#: Every non-vocabulary cause is prefixed with this bounded sentinel family.
UNKNOWN_PREFIX = "unknown:"

#: The declared vocabulary subset that authorizes a live route. ``deferred-context``
#: and ``pending-confirmation`` are declared states but never carry a command.
_LIVE_MATURITIES = ("idea-ready", "requirements-ready", "plan-ready", "resume-ready")

# A saved issue draft and the Saga state file are ready only when an explicit
# declaration says so; their location alone must never decide (T942-02/03).
_DRAFT_DIR_MARKER = "docs/sdlc-issue-drafts/"
_STATE_SOURCE = (STATE_DIR / "state.json").as_posix()


@dataclass(frozen=True)
class ReadinessAssessment:
    """One owner-side readiness decision shared with the mission-control consumer."""

    maturity: str
    routable: bool
    diagnostic: str
    next_action: str
    path_read: str
    published_source: str
    reanchored: bool
    refused: bool
    declaration_required: bool
    contract_major: int


def _declaration_class(published: str) -> str:
    """'' , ``'draft'`` or ``'state'`` — the explicit-declaration classes."""
    normalized = published.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == _STATE_SOURCE or normalized.endswith("/" + _STATE_SOURCE):
        return "state"
    if _DRAFT_DIR_MARKER in normalized:
        return "draft"
    return ""


def _read_draft_declaration(path_to_read: Path) -> tuple[str, object]:
    """Strict sidecar read: only a sidecar ``handoff_maturity`` declares the draft."""
    sidecar = path_to_read.with_suffix(".json")
    if not _is_file(sidecar):
        return "absent", None
    try:
        loaded = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable", None
    if isinstance(loaded, dict) and "handoff_maturity" in loaded:
        return "value", loaded["handoff_maturity"]
    return "absent", None


def _read_state_declaration(path_to_read: Path) -> tuple[str, object]:
    """Strict read of the state file's top-level ``handoff_maturity``."""
    try:
        loaded = json.loads(path_to_read.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable", None
    if isinstance(loaded, dict) and "handoff_maturity" in loaded:
        return "value", loaded["handoff_maturity"]
    return "absent", None


def _assessment_diagnostic(
    maturity: str, published: str, display: str, path_read: Path | None
) -> str:
    """Diagnostics for the assessment surface only; the envelope prose is frozen.

    These strings can be rendered beside live route commands, so they name the
    declaration CLASS but never embed the source path — a path like
    ``docs/plans/x.md`` carries the literal ``/plan`` substring and would read
    as a live route to substring-based safety checks (T942-04). The path
    travels structurally on ``ReadinessAssessment.published_source``.
    """
    if maturity == "deferred-context":
        return (
            "Deferred context — parked, not routed; an operator resumes it "
            "explicitly before any command exists"
        )
    if maturity == "pending-confirmation":
        # Path-free twin of the frozen _maturity_diagnostic prose (same wording
        # minus the source interpolation) for the same substring reason as above.
        return (
            "Boundary recorded but unconfirmed — no durable route exists until "
            "the operator confirms in Brainstorm Phase 2.5"
        )
    if maturity.startswith(f"{UNKNOWN_PREFIX}undeclared:"):
        if _declaration_class(published) == "draft":
            return (
                "Undeclared draft — the sidecar carries no "
                "handoff_maturity; the drafts folder alone cannot make it ready"
            )
        return "Undeclared Saga state — no top-level handoff_maturity declares it ready"
    # Path-free twins of the remaining frozen _maturity_diagnostic arms
    # (review finding #10): same prose minus the source interpolation, and
    # minus any raw author-declared value — a declared value is author text
    # and could itself carry a route substring.
    if maturity == "":
        return (
            "Blank maturity — the key is declared but empty; no durable route; "
            + _maturity_remediation()
        )
    if maturity.startswith(f"{UNKNOWN_PREFIX}carrier:"):
        cause = carrier_detail(path_read) if path_read is not None else "not a top-level key"
        return (
            f"Frontmatter carrier — {cause}; no durable route; "
            "fix frontmatter to be delimited by literal --- lines with a top-level maturity: key"
        )
    if maturity.startswith(f"{UNKNOWN_PREFIX}unterminated:"):
        return (
            f"Unterminated frontmatter block — {_unterminated_detail(path_read)}; no durable route"
        )
    if maturity.startswith(f"{UNKNOWN_PREFIX}out-of-root:"):
        return (
            "Source outside the declared root — refused handoff; no durable route; "
            "name a source inside the declared root"
        )
    if maturity == f"{UNKNOWN_PREFIX}unreadable":
        return (
            "Unreadable frontmatter — the file could not be opened, or decoded into "
            "text carrying a maturity declaration; no durable route; re-save the file "
            "as UTF-8 with a closed --- block and a top-level maturity: key, then re-run"
        )
    if maturity.startswith(f"{UNKNOWN_PREFIX}unrecognized:"):
        return f"Unrecognized maturity value — no durable route; {_maturity_remediation()}"
    diagnostic = _maturity_diagnostic(maturity, display, path_read)
    return diagnostic or ""


def _build_assessment(
    maturity: str,
    *,
    published: str,
    display: str,
    path_read: Path | None,
    reanchored: bool,
    refused: bool,
    declaration_required: bool,
) -> ReadinessAssessment:
    routable = maturity in _LIVE_MATURITIES
    diagnostic = _assessment_diagnostic(maturity, published, display, path_read)
    if routable:
        command = "/plan" if maturity in ("idea-ready", "requirements-ready") else "/work"
        next_action = f"{command} {shlex.quote(published)}"
    elif diagnostic:
        next_action = diagnostic
    else:
        next_action = ""
    return ReadinessAssessment(
        maturity=maturity,
        routable=routable,
        diagnostic=diagnostic,
        next_action=next_action,
        path_read=str(path_read) if path_read is not None else "",
        published_source=published,
        reanchored=reanchored,
        refused=refused,
        declaration_required=declaration_required,
        contract_major=READINESS_CONTRACT_MAJOR,
    )


def assess_source(source: str, root: Path | None = None) -> ReadinessAssessment:
    """Assess one source's readiness: explicit declarations where location cannot decide."""
    resolved = resolve_source(source, root)
    declaration_required = bool(_declaration_class(resolved.published))
    if resolved.refused or not declaration_required:
        maturity = _resolved_maturity(resolved)
    elif resolved.path_to_read is None:
        # Fail closed (review finding #11): an in-root declaration-class path
        # with no file behind it carries no declaration. The bounded undeclared
        # sentinel replaces the former assert — a crash is not a verdict, and
        # ``python -O`` would strip the assert entirely.
        maturity = f"{UNKNOWN_PREFIX}undeclared:{resolved.published}"
    else:
        if _declaration_class(resolved.published) == "state":
            status, value = _read_state_declaration(resolved.path_to_read)
        else:
            status, value = _read_draft_declaration(resolved.path_to_read)
        if status == "value":
            maturity = _classify_declared_value(value)
        elif status == "unreadable":
            maturity = "unknown:unreadable"
        else:
            maturity = f"{UNKNOWN_PREFIX}undeclared:{resolved.published}"
    return _build_assessment(
        maturity,
        published=resolved.published,
        display=_diagnostic_source(source, resolved),
        path_read=resolved.path_to_read,
        reanchored=resolved.reanchored,
        refused=resolved.refused,
        declaration_required=declaration_required,
    )


def assess_declared(
    value: object, published_source: str, *, declaration_required: bool
) -> ReadinessAssessment:
    """Classify one explicit declaration against the shared vocabulary."""
    return _build_assessment(
        _classify_declared_value(value),
        published=published_source,
        display=_display_source(published_source),
        path_read=None,
        reanchored=False,
        refused=False,
        declaration_required=declaration_required,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None)
    parser.add_argument("--target-team", default="")
    parser.add_argument("--target-repo", default="")
    parser.add_argument("--issue-type", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--blockers", default="")
    parser.add_argument("--open-questions", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    envelope = build_handoff_envelope(
        args.source,
        target_team=args.target_team,
        target_repo=args.target_repo,
        issue_type=args.issue_type,
        reason=args.reason,
        blockers=args.blockers,
        open_questions=args.open_questions,
    )
    print(json.dumps(envelope, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
