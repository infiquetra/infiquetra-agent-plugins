"""#812 single-writer guard: saga does not compose board Stage/Status writes.

Step-1 inventory (launch pin 2026-08-25, live ``flow field-options`` / field list):

- Operations (#3), Asgard (#2), CAMPPS (#4): fields are Title, Assignees, Status,
  Labels, Linked pull requests, Milestone, Repository, Reviewers, Parent issue,
  Sub-issues progress, Created, Updated, Closed, Objective, Priority.
- ``Status`` is present on all three boards. ``Stage`` is present on none.
- Operations Status options: Idea, Shaping, Ready, Active, Verify, Done.
- Saga GraphQL mutations that write a project field: none. The only ``--field``
  Status/Stage argv is the mission-control submission in
  ``plugins/saga/scripts/board_progression.py:default_board_writer``.

The named in-scope failure: the single-writer policy exists by operator ruling
but nothing enforced it, so a future saga script could silently re-introduce
direct board composition. This guard is the smallest enforcement.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
SAGA_ROOT = ROOT / "plugins" / "saga"
SCRIPTS = SAGA_ROOT / "scripts"
SUBMISSION_PATH = (SCRIPTS / "board_progression.py").resolve()


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RC = _load("op_allowlist")

# The step-1 live receipt as DATA, not as a sentence in a docstring. Every single-select and
# built-in field the three boards carried on 2026-08-25. The tests below read the real
# certificate against this constant, so widening the correction allowlist or recording a newly
# created Stage field both trip the suite instead of passing silently.
LIVE_BOARD_FIELDS = frozenset(
    {
        "Title",
        "Assignees",
        "Status",
        "Labels",
        "Linked pull requests",
        "Milestone",
        "Repository",
        "Reviewers",
        "Parent issue",
        "Sub-issues progress",
        "Created",
        "Updated",
        "Closed",
        "Objective",
        "Priority",
    }
)

# Correction field names the certificate allows that the live boards do NOT yet carry. Every
# such name is dead until the field is created; keeping the set explicit is what makes a later
# Stage field a deliberate two-line edit rather than a silent drift.
ALLOWED_NOT_YET_LIVE = frozenset({"Stage"})

# Direct ProjectV2 field mutations — reserved to mission-control.
FORBIDDEN_MUTATIONS = (
    "updateProjectV2ItemFieldValue",
    "updateProjectV2ItemField",
    "clearProjectV2ItemFieldValue",
    "QUERY_SET_FIELD_VALUE",
)

# CLI shapes that write a project field without going through mission-control.
FORBIDDEN_CLI = (
    "project item-edit",
    "gh project item-edit",
)

_FIELD_ARGV_RE = re.compile(
    r"""["']--field["']\s*,\s*["'](Status|Stage)["']"""
    r"""|["']--field["']\s*,\s*(?:field_name|field)\b"""
)
_FLOW_SET_FIELD_RE = re.compile(r"""["']flow["']\s*,\s*["']set-field["']""")
_FLOW_SET_FIELD_CALL_RE = re.compile(r"\bflow_set_field\s*\(")


# This file, and the fleet-wide sibling, quote the forbidden tokens as the
# denylist. Scanning them reports the denylist as an offense.
_DENYLIST_SOURCES = frozenset(
    {
        Path(__file__).resolve(),
        (Path(__file__).resolve().parent / "test_saga_no_direct_write.py").resolve(),
    }
)


def _iter_saga_python(root: Path = SAGA_ROOT) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file() and path.resolve() not in _DENYLIST_SOURCES
    )


def _offenses_in_text(text: str) -> list[str]:
    found: list[str] = []
    for token in FORBIDDEN_MUTATIONS:
        if token in text:
            found.append(token)
    for token in FORBIDDEN_CLI:
        if token in text:
            found.append(token)
    if _FLOW_SET_FIELD_CALL_RE.search(text):
        found.append("flow_set_field(")
    return found


def scan_saga_direct_writes(root: Path = SAGA_ROOT) -> list[tuple[Path, str]]:
    """Return (path, token) for every in-scope direct Stage/Status write in saga."""
    hits: list[tuple[Path, str]] = []
    for path in _iter_saga_python(root):
        text = path.read_text(encoding="utf-8")
        resolved = path.resolve()
        # Every saga file, submission path included, is forbidden the GraphQL/`gh project`
        # writes and the in-process `flow_set_field(` call. The ONLY exemption the submission
        # path earns is composing the `flow set-field` argv below — which is the whole point
        # of `default_board_writer`. Keeping one offense helper means that exemption lives in
        # exactly one place instead of drifting between two identical-bodied functions.
        tokens = _offenses_in_text(text)
        if resolved != SUBMISSION_PATH:
            if _FLOW_SET_FIELD_RE.search(text):
                tokens.append("flow,set-field")
            if _FIELD_ARGV_RE.search(text):
                tokens.append("--field Status|Stage")
        for token in tokens:
            hits.append((path, token))
    return hits


def test_no_direct_stage_or_status_write_remains_in_saga() -> None:
    """AC1: no saga call site composes a direct board Stage or Status write."""
    hits = scan_saga_direct_writes()
    assert hits == [], "direct Stage/Status writes in saga:\n" + "\n".join(
        f"  {path.relative_to(ROOT)}: {token}" for path, token in hits
    )


def test_surviving_set_field_reference_is_submission_path_only() -> None:
    """AC1: every surviving ``flow set-field`` argv is the board_progression writer."""
    owners: list[Path] = []
    for path in _iter_saga_python():
        text = path.read_text(encoding="utf-8")
        if _FLOW_SET_FIELD_RE.search(text) or _FIELD_ARGV_RE.search(text):
            owners.append(path.resolve())
    assert owners == [SUBMISSION_PATH], (
        "set-field argv must live only in default_board_writer, got: "
        + ", ".join(str(p.relative_to(ROOT)) for p in owners)
    )


def test_submission_path_passes_field_name_and_correction_flag() -> None:
    """The one legal writer submits ``--field <name>`` and ``--correction``."""
    text = SUBMISSION_PATH.read_text(encoding="utf-8")
    assert '"--field"' in text
    assert '"--correction"' in text
    assert "authorize_correction_field" in text
    assert "set-field-stage" not in text


def test_guard_fails_closed_on_a_direct_write_fixture(tmp_path: Path) -> None:
    """A guard never seen to fail is not known to work — seed a mutation and trip it."""
    fixture = tmp_path / "evil_direct_write.py"
    fixture.write_text(
        'QUERY = """mutation { updateProjectV2ItemFieldValue(input: {}) { ok } }"""\n',
        encoding="utf-8",
    )
    text = fixture.read_text(encoding="utf-8")
    assert "updateProjectV2ItemFieldValue" in _offenses_in_text(text)

    argv_fixture = tmp_path / "evil_argv.py"
    argv_fixture.write_text(
        'cmd = ["python3", "sdlc_manager.py", "flow", "set-field", "--field", "Status"]\n',
        encoding="utf-8",
    )
    argv_text = argv_fixture.read_text(encoding="utf-8")
    assert _FLOW_SET_FIELD_RE.search(argv_text)
    assert _FIELD_ARGV_RE.search(argv_text)


def test_certificate_retains_no_autonomous_lifecycle_write_authority() -> None:
    """W7 (SDLC R30/R32): the certificate keeps GATING a set-field-status submission, but Saga
    holds no AUTONOMOUS write authority over a lifecycle field. The concrete autonomy site is the
    reconcile controller's ``AUTO_CORRECT_OP_KINDS`` (plan KTD4) — post-W7 it is EMPTY, so no
    controller tick ever re-writes a drifted lifecycle field on its own authority, and no skill
    initiates the write either (the AE2 scan, ``tests/test_saga_no_direct_write.py``, pins the
    skill half)."""
    from importlib import import_module  # noqa: PLC0415 — sibling module, same scripts dir

    controller = import_module("reconcile_controller")
    assert frozenset() == controller.AUTO_CORRECT_OP_KINDS, (
        "the controller auto-correct allowlist must be empty — an autonomous lifecycle-field "
        "rewrite is a second routine writer (R30)"
    )
    # The gate the certificate still applies to a submission is field identity (GATE by field),
    # never autonomy: an authorized verdict exists ONLY for ops the operator routes.
    assert RC.authorize_write("set-field-status") == RC.AUTHORIZED
